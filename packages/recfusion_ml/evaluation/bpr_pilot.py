"""Train BPR and select an epoch on the trusted warm validation cohort."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import math
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import cast

import torch

from recfusion_ml.evaluation.metrics import (
    RankingMetrics,
    build_validation_cohort,
    evaluate_rankings,
)
from recfusion_ml.evaluation.pilot import TrustedPilotData, load_trusted_pilot_data
from recfusion_ml.training.bpr import (
    BPRConfig,
    BPRRecommender,
    TrainingEpoch,
    fit_bpr,
    load_checkpoint,
    save_checkpoint,
)
from recfusion_ml.types import RatingEvent

_K_VALUES = (5, 10, 20)
_EXPECTED = {
    "train_records": 81_688,
    "train_users": 10_000,
    "train_items": 45_331,
    "validation_records": 6_760,
    "evaluated_users": 1_369,
    "eligible_targets": 1_911,
    "triplets_per_epoch": 65_842,
}
_METRIC_FIELDS = (
    "recall",
    "ndcg",
    "hit_rate",
    "mrr",
    "candidate_coverage",
    "unique_recommended_items",
    "recommendation_count",
)


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _code_fingerprint(repository_root: Path) -> dict[str, object]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source_files = (
        "packages/recfusion_ml/models/implicit_mf.py",
        "packages/recfusion_ml/training/bpr.py",
        "packages/recfusion_ml/evaluation/bpr_pilot.py",
    )
    return {
        "git_commit": commit,
        "working_tree_source_sha256": {
            name: _sha256_file(repository_root / name)[0] for name in source_files
        },
    }


def _json_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read aggregate report {path.name}.") from error
    if not isinstance(value, dict):
        raise ValueError(f"Aggregate report {path.name} is malformed.")
    return cast(dict[str, object], value)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} is malformed.")
    return cast(Mapping[str, object], value)


def _temporal_audit_counts(manifest: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(manifest.get("counts"), "temporal counts")


def _validate_baseline_reports(
    *,
    data: TrustedPilotData,
    cohort_users: int,
    eligible_targets: int,
    popularity_report_path: Path,
    item_cf_report_path: Path,
    repository_root: Path | None = None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    repository_root = repository_root or Path(__file__).resolve().parents[3]
    processed_root = (repository_root / "data" / "processed").resolve()
    reports = []
    for path in (popularity_report_path, item_cf_report_path):
        resolved = path.resolve()
        if processed_root not in resolved.parents or not resolved.is_file():
            raise ValueError(
                "Baseline reports must be existing local processed reports."
            )
        reports.append(_json_object(resolved))
    popularity, item_cf = reports
    popularity_hash, _ = _sha256_file(popularity_report_path.resolve())
    temporal_hash, _ = _sha256_file(data.temporal_dir / "manifest.json")
    preprocessing_hash, _ = _sha256_file(data.preprocessing_dir / "manifest.json")
    train_hash = cast(str, data.temporal_outputs["interactions.train.jsonl"]["sha256"])
    validation_hash = cast(
        str, data.temporal_outputs["interactions.validation.jsonl"]["sha256"]
    )
    test_hash = cast(str, data.temporal_outputs["interactions.test.jsonl"]["sha256"])
    expected_source = data.temporal.get("source")

    for report, kind in ((popularity, "popularity"), (item_cf, "item-CF")):
        provenance = _mapping(report.get("provenance"), f"{kind} provenance")
        counts = _mapping(report.get("counts"), f"{kind} counts")
        protocol = _mapping(report.get("protocol"), f"{kind} protocol")
        if report.get("source") != expected_source:
            raise ValueError(f"{kind} report source identity does not match the pilot.")
        if (
            provenance.get("temporal_manifest_sha256") != temporal_hash
            or provenance.get("train_sha256") != train_hash
            or provenance.get("validation_sha256") != validation_hash
            or provenance.get("test_sha256_verified_without_parsing") != test_hash
        ):
            raise ValueError(
                f"{kind} report input fingerprints do not match the pilot."
            )
        if (
            protocol.get("evaluation_split") != "validation only"
            or protocol.get("test_rows_parsed_or_evaluated") is not False
            or protocol.get("positive_min_rating") != "4"
            or protocol.get("ks") != list(_K_VALUES)
            or counts.get("candidate_pool_items") != len(data.candidate_items)
            or counts.get("evaluated_users") != cohort_users
            or counts.get("eligible_positive_target_pairs") != eligible_targets
            or counts.get("parsed_records")
            != {
                "train": len(data.train_events),
                "validation": len(data.validation_events),
            }
        ):
            raise ValueError(f"{kind} report protocol or evaluation cohort differs.")
    item_protocol = _mapping(item_cf.get("protocol"), "item-CF protocol")
    if (
        item_protocol.get("candidate_pool") != "exact Step 2.5 train-known item pool"
        or item_protocol.get("seen_item_policy")
        != "exclude every train-observed user-item pair"
    ):
        raise ValueError(
            "Item-CF report has a different candidate or seen-item policy."
        )
    item_provenance = _mapping(item_cf.get("provenance"), "item-CF provenance")
    if item_provenance.get("popularity_report_sha256") != popularity_hash:
        raise ValueError(
            "Item-CF report was not computed against this popularity report."
        )
    popularity_metrics = _mapping(popularity.get("metrics"), "popularity metrics")
    item_comparison = _mapping(item_cf.get("comparison"), "item-CF comparison")
    baseline_metrics: dict[str, object] = {}
    for k in _K_VALUES:
        key = str(k)
        popularity_at_k = _mapping(popularity_metrics.get(key), f"popularity @{k}")
        comparison_at_k = _mapping(item_comparison.get(key), f"item-CF @{k}")
        item_at_k = _mapping(comparison_at_k.get("item_cf"), f"item-CF metrics @{k}")
        embedded_popularity = _mapping(
            comparison_at_k.get("popularity"), f"embedded popularity @{k}"
        )
        if any(
            popularity_at_k.get(field) != embedded_popularity.get(field)
            for field in _METRIC_FIELDS
        ):
            raise ValueError(
                "Item-CF report's popularity results differ from the frozen report."
            )
        baseline_metrics[key] = {
            "popularity": dict(popularity_at_k),
            "item_cf": dict(item_at_k),
        }
    provenance = {
        "preprocessing_manifest_sha256": preprocessing_hash,
        "temporal_manifest_sha256": temporal_hash,
        "train_sha256": train_hash,
        "validation_sha256": validation_hash,
        "test_sha256_verified_without_parsing": test_hash,
        "popularity_report_sha256": popularity_hash,
        "item_cf_report_sha256": _sha256_file(item_cf_report_path.resolve())[0],
    }
    return baseline_metrics, provenance, {"popularity": popularity, "item_cf": item_cf}


def _timestamp_conversion_errors(records: Sequence[dict[str, object]]) -> int:
    from datetime import UTC, datetime

    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    errors = 0
    for record in records:
        interaction = record.get("interaction")
        if not isinstance(interaction, dict):
            errors += 1
            continue
        timestamp_ms = interaction.get("event_time_ms")
        timestamp_utc = interaction.get("event_time_utc")
        try:
            parsed = datetime.fromisoformat(
                cast(str, timestamp_utc).replace("Z", "+00:00")
            )
            delta = parsed - epoch
            parsed_ms = (
                delta.days * 86_400_000
                + delta.seconds * 1_000
                + delta.microseconds // 1_000
            )
            offset = parsed.utcoffset()
            if (
                isinstance(timestamp_ms, bool)
                or not isinstance(timestamp_ms, int)
                or parsed_ms != timestamp_ms
                or offset is None
                or offset.total_seconds() != 0
            ):
                errors += 1
        except (AttributeError, TypeError, ValueError):
            errors += 1
    return errors


def _rating_distribution(events: Sequence[RatingEvent]) -> dict[str, int]:
    counts: Counter[str] = Counter(
        format(event.rating.normalize(), "f") for event in events
    )
    return dict(sorted(counts.items()))


def _metric_values(metric: RankingMetrics) -> dict[str, float | int | None]:
    return {field: getattr(metric, field) for field in _METRIC_FIELDS}


def _peak_working_set_bytes() -> int | None:
    if sys.platform != "win32":
        return None

    class MemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("page_fault_count", ctypes.c_ulong),
            ("peak_working_set_size", ctypes.c_size_t),
            ("working_set_size", ctypes.c_size_t),
            ("quota_peak_paged_pool_usage", ctypes.c_size_t),
            ("quota_paged_pool_usage", ctypes.c_size_t),
            ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
            ("quota_non_paged_pool_usage", ctypes.c_size_t),
            ("pagefile_usage", ctypes.c_size_t),
            ("peak_pagefile_usage", ctypes.c_size_t),
        ]

    try:
        psapi = ctypes.WinDLL("Psapi.dll", use_last_error=True)
        kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(MemoryCounters),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        counters = MemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        success = psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        return int(counters.peak_working_set_size) if success else None
    except (AttributeError, OSError):
        return None


def _counts_in_training(data: TrustedPilotData) -> dict[str, object]:
    train_users = {event.user_key for event in data.train_events}
    train_items = {event.item_key for event in data.train_events}
    seen: dict[str, set[str]] = {}
    positive_pairs: set[tuple[str, str]] = set()
    for event in data.train_events:
        seen.setdefault(event.user_key, set()).add(event.item_key)
        if event.rating >= 4:
            positive_pairs.add((event.user_key, event.item_key))
    positive_users = {user for user, _ in positive_pairs}
    eligible_negative_users = sum(
        bool(train_items - seen[user]) for user in positive_users
    )
    return {
        "train_records": len(data.train_events),
        "train_users": len(train_users),
        "train_items": len(train_items),
        "positive_observations": sum(event.rating >= 4 for event in data.train_events),
        "unique_positive_pairs": len(positive_pairs),
        "positive_users": len(positive_users),
        "positive_users_with_negative_candidates": eligible_negative_users,
        "positive_users_without_negative_candidates": len(positive_users)
        - eligible_negative_users,
        "rating_distribution": _rating_distribution(data.train_events),
    }


def evaluate_bpr_pilot(
    *,
    preprocessing_dir: Path,
    temporal_dir: Path,
    popularity_report_path: Path,
    item_cf_report_path: Path,
    output_dir: Path,
    resume_existing: bool = False,
) -> dict[str, object]:
    """Train or finalize a completed run using validation NDCG@10."""
    started = time.perf_counter()
    repository_root = Path(__file__).resolve().parents[3]
    processed_root = (repository_root / "data" / "processed").resolve()
    output_dir = output_dir.resolve()
    if processed_root not in output_dir.parents:
        raise ValueError("Output directory must be under ignored data/processed.")
    if output_dir.exists() and not resume_existing:
        raise ValueError("Output directory already exists; refusing to overwrite it.")
    if resume_existing and (
        not output_dir.is_dir()
        or not (output_dir / "bpr-best.pt").is_file()
        or not (output_dir / "progress.jsonl").is_file()
        or (output_dir / "bpr-report.json").exists()
    ):
        raise ValueError(
            "Existing run is not in a recoverable report-finalization state."
        )

    data = load_trusted_pilot_data(preprocessing_dir, temporal_dir)
    train_users = {event.user_key for event in data.train_events}
    train_items = {event.item_key for event in data.train_events}
    if (
        len(data.train_events) != _EXPECTED["train_records"]
        or len(train_users) != _EXPECTED["train_users"]
        or len(train_items) != _EXPECTED["train_items"]
        or len(data.validation_events) != _EXPECTED["validation_records"]
        or frozenset(train_items) != data.candidate_items
    ):
        raise ValueError(
            "Trusted train/validation dimensions differ from the approved pilot."
        )
    if _timestamp_conversion_errors(data.train_records) + _timestamp_conversion_errors(
        data.validation_records
    ):
        raise ValueError("Canonical UTC timestamps do not match Unix milliseconds.")
    cohort = build_validation_cohort(
        data.train_events, data.validation_events, data.candidate_items
    )
    if (
        cohort.users_with_evaluable_targets != _EXPECTED["evaluated_users"]
        or cohort.eligible_positive_target_count != _EXPECTED["eligible_targets"]
    ):
        raise ValueError("Validation cohort differs from the approved baseline cohort.")
    baseline_metrics, provenance, _ = _validate_baseline_reports(
        data=data,
        cohort_users=cohort.users_with_evaluable_targets,
        eligible_targets=cohort.eligible_positive_target_count,
        popularity_report_path=popularity_report_path,
        item_cf_report_path=item_cf_report_path,
    )
    progress_path = output_dir / "progress.jsonl"
    config = BPRConfig()
    epoch_results: list[dict[str, object]] = []
    checkpoint_by_epoch: dict[int, Path] = {}
    best_ndcg: float | None = None
    best_epoch = 0
    best_rankings: dict[str, tuple[str, ...]] = {}
    best_validation_seconds = 0.0

    if resume_existing:
        progress_lines = progress_path.read_text(encoding="utf-8").splitlines()
        try:
            progress_records = [json.loads(line) for line in progress_lines]
        except json.JSONDecodeError as error:
            raise ValueError("Existing epoch progress log is malformed.") from error
        if len(progress_records) != config.epochs:
            raise ValueError("Existing epoch progress log is incomplete.")
        for expected_epoch, record in enumerate(progress_records, start=1):
            if (
                not isinstance(record, dict)
                or record.get("epoch") != expected_epoch
                or not all(
                    isinstance(record.get(key), (int, float))
                    and math.isfinite(record[key])
                    for key in (
                        "train_bpr_loss",
                        "regularization_loss",
                        "validation_ndcg_at_10",
                        "training_seconds",
                        "validation_seconds",
                    )
                )
                or record.get("triplets") != _EXPECTED["triplets_per_epoch"]
            ):
                raise ValueError("Existing epoch progress log is malformed.")
            bpr_loss = float(record["train_bpr_loss"])
            regularization_loss = float(record["regularization_loss"])
            epoch_results.append(
                {
                    "epoch": expected_epoch,
                    "bpr_loss": bpr_loss,
                    "regularization_loss": regularization_loss,
                    "total_loss": bpr_loss + regularization_loss,
                    "triplet_count": int(record["triplets"]),
                    "duration_seconds": float(record["training_seconds"]),
                    "validation_ndcg_at_10": float(record["validation_ndcg_at_10"]),
                    "validation_duration_seconds": float(record["validation_seconds"]),
                }
            )
        best_epoch = max(
            range(1, config.epochs + 1),
            key=lambda epoch: (
                cast(float, epoch_results[epoch - 1]["validation_ndcg_at_10"]),
                -epoch,
            ),
        )
        best_ndcg = cast(float, epoch_results[best_epoch - 1]["validation_ndcg_at_10"])
        best_validation_seconds = cast(
            float, epoch_results[best_epoch - 1]["validation_duration_seconds"]
        )
        final_checkpoint = output_dir / "bpr-best.pt"
        recovered = load_checkpoint(final_checkpoint, repository_root=repository_root)
        if (
            recovered.config != config
            or recovered.data.source_artifact_fingerprints
            != (
                cast(
                    str,
                    data.temporal_outputs["interactions.train.jsonl"]["sha256"],
                ),
            )
            or len(recovered.epoch_statistics) != best_epoch
        ):
            raise ValueError("Existing checkpoint does not match this run history.")
        for saved, reported in zip(
            recovered.epoch_statistics, epoch_results[:best_epoch], strict=True
        ):
            if (
                saved.epoch != reported["epoch"]
                or saved.bpr_loss != reported["bpr_loss"]
                or saved.regularization_loss != reported["regularization_loss"]
                or saved.duration_seconds != reported["duration_seconds"]
                or saved.triplet_count != reported["triplet_count"]
            ):
                raise ValueError("Existing checkpoint differs from epoch history.")
        best_rankings = recovered.recommend_many(
            cohort.targets_by_user, k=max(_K_VALUES), chunk_size=4096
        )
        fit_and_validation_wall_seconds = sum(
            cast(float, epoch["duration_seconds"])
            + cast(float, epoch["validation_duration_seconds"])
            for epoch in epoch_results
        )
    else:
        output_dir.mkdir(parents=True)
        checkpoint_dir = output_dir / "checkpoints"
        checkpoint_dir.mkdir()

    def evaluate_epoch(recommender: BPRRecommender, epoch: TrainingEpoch) -> None:
        nonlocal best_ndcg, best_epoch, best_rankings, best_validation_seconds
        validation_started = time.perf_counter()
        rankings = recommender.recommend_many(
            cohort.targets_by_user, k=max(_K_VALUES), chunk_size=4096
        )
        evaluation = evaluate_rankings(
            cohort, rankings, candidate_items=data.candidate_items, ks=(10,)
        )
        metric = evaluation.metrics_by_k[10]
        if metric.ndcg is None or not math.isfinite(metric.ndcg):
            raise ValueError("Validation NDCG@10 is unavailable or non-finite.")
        validation_seconds = time.perf_counter() - validation_started
        epoch_results.append(
            {
                **asdict(epoch),
                "validation_ndcg_at_10": metric.ndcg,
                "validation_duration_seconds": validation_seconds,
            }
        )
        progress = json.dumps(
            {
                "epoch": epoch.epoch,
                "train_bpr_loss": epoch.bpr_loss,
                "regularization_loss": epoch.regularization_loss,
                "triplets": epoch.triplet_count,
                "validation_ndcg_at_10": metric.ndcg,
                "training_seconds": epoch.duration_seconds,
                "validation_seconds": validation_seconds,
            },
            sort_keys=True,
        )
        with progress_path.open("a", encoding="utf-8") as stream:
            stream.write(progress + "\n")
            stream.flush()
        with contextlib.suppress(BrokenPipeError):
            print(progress, flush=True)
        if best_ndcg is None or metric.ndcg > best_ndcg:
            best_ndcg = metric.ndcg
            best_epoch = epoch.epoch
            best_rankings = rankings
            best_validation_seconds = validation_seconds
            checkpoint_path = checkpoint_dir / f"epoch-{epoch.epoch:02d}.pt"
            save_checkpoint(
                recommender,
                checkpoint_path,
                repository_root=repository_root,
            )
            checkpoint_by_epoch[epoch.epoch] = checkpoint_path

    if not resume_existing:
        fit_started = time.perf_counter()
        fit_bpr(
            data.train_events,
            config=config,
            source_artifact_fingerprints=(
                cast(str, data.temporal_outputs["interactions.train.jsonl"]["sha256"]),
            ),
            on_epoch_end=evaluate_epoch,
        )
        fit_and_validation_wall_seconds = time.perf_counter() - fit_started
        if not best_epoch or best_ndcg is None:
            raise RuntimeError(
                "BPR training produced no validation-selected checkpoint."
            )
        selected_checkpoint = checkpoint_by_epoch[best_epoch]
        final_checkpoint = output_dir / "bpr-best.pt"
        selected_checkpoint.replace(final_checkpoint)
        for stale_checkpoint in checkpoint_by_epoch.values():
            stale_checkpoint.unlink(missing_ok=True)
        checkpoint_dir.rmdir()

    checkpoint_sha256, checkpoint_size = _sha256_file(final_checkpoint)
    reload_started = time.perf_counter()
    loaded = load_checkpoint(final_checkpoint, repository_root=repository_root)
    final_rankings = loaded.recommend_many(
        cohort.targets_by_user, k=max(_K_VALUES), chunk_size=4096
    )
    final_evaluation = evaluate_rankings(
        cohort, final_rankings, candidate_items=data.candidate_items, ks=_K_VALUES
    )
    reload_seconds = time.perf_counter() - reload_started
    reload_rankings_match = final_rankings == {
        user: tuple(items[: max(_K_VALUES)]) for user, items in best_rankings.items()
    }
    if not reload_rankings_match:
        raise ValueError("Selected checkpoint reload changed validation rankings.")
    if final_evaluation.metrics_by_k[10].ndcg != best_ndcg:
        raise ValueError("Selected checkpoint reload changed selection NDCG@10.")

    final_metrics = {
        str(k): _metric_values(final_evaluation.metrics_by_k[k]) for k in _K_VALUES
    }
    comparison: dict[str, object] = {}
    for key in map(str, _K_VALUES):
        baseline_at_k = _mapping(baseline_metrics[key], f"baseline metrics @{key}")
        deltas: dict[str, object] = {}
        for baseline in ("popularity", "item_cf"):
            reference = _mapping(baseline_at_k.get(baseline), f"{baseline} @{key}")
            deltas[baseline] = {
                field: (
                    cast(float, final_metrics[key][field])
                    - cast(float, reference[field])
                    if final_metrics[key][field] is not None
                    else None
                )
                for field in ("recall", "ndcg", "hit_rate", "mrr")
            }
        comparison[key] = deltas
    training_counts = _counts_in_training(data)
    temporal_audit_counts = _temporal_audit_counts(data.temporal)
    temporal_counts = _mapping(
        temporal_audit_counts.get("split_counts"), "temporal split counts"
    )
    timestamp_ranges = {
        split: _mapping(
            _mapping(temporal_counts.get(split), split).get("timestamp_range_ms"),
            f"{split} timestamp range",
        )
        for split in ("train", "validation", "test")
    }
    rating_counts = _mapping(
        temporal_counts.get("validation"), "validation counts"
    ).get("rating_label_distribution")
    integrity_counts = _mapping(
        temporal_audit_counts.get("integrity"), "temporal integrity counts"
    )
    parameter_count = sum(parameter.numel() for parameter in loaded.model.parameters())
    code_fingerprint = _code_fingerprint(repository_root)
    report_peak_working_set_bytes = _peak_working_set_bytes()
    report: dict[str, object] = {
        "report_schema_version": "recfusion.bpr-pilot-report.v1",
        "experiment": "phase-3.2B.2-real-amazon-electronics-bpr",
        "status": "complete",
        "source": data.temporal.get("source"),
        "research_use": {
            "scope": "local non-commercial MCA academic coursework",
            "decision_status": "limited academic research-use assessment documented",
            "legal_clearance": False,
            "publication_boundary": (
                "no raw reviews, source user IDs, CSVs, row-level outputs, or images"
            ),
        },
        "provenance": provenance,
        "code_provenance": code_fingerprint,
        "verified_temporal_artifacts": {
            name: {
                "sha256": metadata.get("sha256"),
                "size_bytes": metadata.get("size_bytes"),
                "records": metadata.get("records"),
            }
            for name, metadata in data.temporal_outputs.items()
            if name
            in {
                "interactions.train.jsonl",
                "interactions.validation.jsonl",
                "interactions.test.jsonl",
            }
        },
        "protocol": {
            "training_split": "train only",
            "evaluation_split": "validation only",
            "test_rows_parsed_or_evaluated": False,
            "candidate_pool": "exact train-known Step 2.5 item pool",
            "seen_item_policy": "exclude every train-observed user-item pair",
            "positive_min_rating": "4",
            "sampled_unobserved_items": (
                "BPR training assumption; not verified dislikes"
            ),
            "selection_metric": "validation_ndcg_at_10",
            "tie_policy": "earliest epoch",
            "ks": list(_K_VALUES),
            "confidence_intervals": "not computed; no significance claim",
            "metadata_features": "unavailable; no product metadata joined",
        },
        "configuration": {
            **asdict(config),
            "model": "implicit-mf-bpr",
            "optimizer": "Adam",
            "device": "cpu",
            "max_epochs": 20,
            "selection_metric": "validation_ndcg_at_10",
            "negative_sampling_strategy": "uniform rejection; seeded scan fallback",
            "code_commit": code_fingerprint["git_commit"],
            "torch_version": torch.__version__.__str__(),
        },
        "counts": {
            **training_counts,
            "collapsed_positive_observations": (
                loaded.data.collapsed_positive_observations
            ),
            "triplets_per_epoch": loaded.summary.sampled_triplet_count_per_epoch,
            "positive_pairs_skipped_without_negative": (
                loaded.summary.skipped_pairs_without_negative
            ),
            "validation_records": len(data.validation_events),
            "validation_evaluable_users": cohort.users_with_evaluable_targets,
            "validation_eligible_positive_targets": (
                cohort.eligible_positive_target_count
            ),
            "cold_item_positive_observations": (
                cohort.cold_item_positive_observation_count
            ),
            "cold_user_positive_observations": (
                cohort.cold_user_positive_observation_count
            ),
            "seen_positive_observations": cohort.seen_positive_observation_count,
            "non_positive_validation_observations": (
                cohort.non_positive_observation_count
            ),
            "duplicate_positive_observations": (
                cohort.duplicate_positive_observation_count
            ),
            "excluded_positive_target_counts": dict(cohort.excluded_target_counts),
            "validation_rating_labels": rating_counts,
            "validation_cohort": {
                "validation_users": cohort.validation_user_count,
                "users_with_observed_positives": (cohort.users_with_observed_positives),
                "users_with_warm_positive_targets": (
                    cohort.users_with_warm_positive_targets
                ),
                "users_with_evaluable_targets": cohort.users_with_evaluable_targets,
                "positive_observations": cohort.positive_observation_count,
                "positive_target_pairs": cohort.positive_target_pair_count,
                "warm_positive_observations": cohort.warm_positive_observation_count,
                "warm_positive_targets": cohort.warm_positive_target_count,
                "cold_item_positive_observations": (
                    cohort.cold_item_positive_observation_count
                ),
                "cold_user_positive_observations": (
                    cohort.cold_user_positive_observation_count
                ),
                "seen_positive_observations": cohort.seen_positive_observation_count,
                "non_positive_observations": cohort.non_positive_observation_count,
                "duplicate_positive_observations": (
                    cohort.duplicate_positive_observation_count
                ),
                "excluded_positive_target_counts": dict(cohort.excluded_target_counts),
            },
            "temporal_integrity_audit": dict(integrity_counts),
            "rejected_by_input": temporal_audit_counts.get("rejected_by_input"),
        },
        "timestamp_ranges_ms_and_utc_from_trusted_manifest": timestamp_ranges,
        "model": {
            "parameter_count": parameter_count,
            "initial_parameters_and_score_finite": True,
            "device": "cpu",
        },
        "epochs": epoch_results,
        "selection": {
            "epoch": best_epoch,
            "validation_ndcg_at_10": best_ndcg,
            "checkpoint": final_checkpoint.name,
            "checkpoint_sha256": checkpoint_sha256,
            "checkpoint_size_bytes": checkpoint_size,
            "checkpoint_reload_rankings_identical": reload_rankings_match,
            "checkpoint_reload_time_seconds": reload_seconds,
        },
        "metrics": {"bpr": final_metrics, "baselines": baseline_metrics},
        "metric_deltas_vs_baselines": comparison,
        "ranking_completeness": {
            "expected_users": cohort.users_with_evaluable_targets,
            "ranked_users": len(final_rankings),
            "all_users_returned": len(final_rankings)
            == cohort.users_with_evaluable_targets,
            "recommendations_per_user_at_most": max(_K_VALUES),
            "recommendation_count_by_k": {
                str(k): final_evaluation.metrics_by_k[k].recommendation_count
                for k in _K_VALUES
            },
        },
        "resources": {
            "fit_and_validation_wall_seconds": (
                None if resume_existing else fit_and_validation_wall_seconds
            ),
            "sum_recorded_epoch_durations_seconds": fit_and_validation_wall_seconds,
            "training_wall_seconds": sum(
                cast(float, epoch["duration_seconds"]) for epoch in epoch_results
            ),
            "sum_epoch_training_seconds": sum(
                cast(float, epoch["duration_seconds"]) for epoch in epoch_results
            ),
            "validation_seconds_across_epochs": sum(
                cast(float, epoch["validation_duration_seconds"])
                for epoch in epoch_results
            ),
            "selected_epoch_validation_seconds": best_validation_seconds,
            "peak_working_set_bytes": (
                None if resume_existing else report_peak_working_set_bytes
            ),
            "report_finalization_peak_working_set_bytes": (
                report_peak_working_set_bytes if resume_existing else None
            ),
            "temporary_sqlite_size_bytes": 0,
            "checkpoint_size_bytes": checkpoint_size,
        },
    }
    report_path = output_dir / "bpr-report.json"
    temporary_path = output_dir / "bpr-report.json.tmp"
    resources = cast(dict[str, object], report["resources"])
    resources["total_wall_seconds"] = (
        None if resume_existing else time.perf_counter() - started
    )
    resources["report_finalization_wall_seconds"] = (
        time.perf_counter() - started if resume_existing else None
    )
    resources["reload_and_final_inference_seconds"] = reload_seconds
    resources["output_artifact_bytes_excluding_report"] = sum(
        path.stat().st_size
        for path in output_dir.iterdir()
        if path.is_file() and path != report_path
    )
    for _ in range(3):
        temporary_path.write_text(
            json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(report_path)
        report_size = report_path.stat().st_size
        if resources.get("report_file_size_bytes") == report_size:
            break
        resources["report_file_size_bytes"] = report_size
        resources["output_directory_bytes_including_report"] = sum(
            path.stat().st_size for path in output_dir.iterdir() if path.is_file()
        )
    return report


def _arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Train the fixed CPU BPR configuration and evaluate on the trusted "
            "Step 2.5 validation cohort only."
        )
    )
    parser.add_argument("--preprocessing-dir", type=Path, required=True)
    parser.add_argument("--temporal-dir", type=Path, required=True)
    parser.add_argument("--popularity-report", type=Path, required=True)
    parser.add_argument("--item-cf-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--resume-existing",
        action="store_true",
        help="Finalize an existing completed checkpoint and 20-epoch progress log.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments().parse_args(argv)
    try:
        report = evaluate_bpr_pilot(
            preprocessing_dir=args.preprocessing_dir,
            temporal_dir=args.temporal_dir,
            popularity_report_path=args.popularity_report,
            item_cf_report_path=args.item_cf_report,
            output_dir=args.output_dir,
            resume_existing=args.resume_existing,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"BPR pilot failed: {error}", file=sys.stderr)
        return 2
    counts = cast(dict[str, object], report["counts"])
    selection = cast(dict[str, object], report["selection"])
    with contextlib.suppress(BrokenPipeError):
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "evaluated_users": counts["validation_evaluable_users"],
                    "selected_epoch": selection["epoch"],
                    "validation_ndcg_at_10": selection["validation_ndcg_at_10"],
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
