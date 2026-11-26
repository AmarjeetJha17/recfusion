"""Train and select a CPU Two-Tower model on the trusted 10K pilot."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import cast

import torch

from recfusion_ml.evaluation.metrics import (
    RankingMetrics,
    ValidationCohort,
    build_validation_cohort,
    evaluate_rankings,
)
from recfusion_ml.evaluation.pilot import TrustedPilotData, load_trusted_pilot_data
from recfusion_ml.training.two_tower import (
    TwoTowerConfig,
    TwoTowerEvent,
    TwoTowerRecommender,
    build_two_tower_data,
    fit_two_tower,
)
from recfusion_ml.training.two_tower_checkpoint import (
    load_two_tower_checkpoint,
    save_two_tower_checkpoint,
)

_EXPECTED = {
    "train_users": 10_000,
    "train_items": 45_331,
    "train_records": 81_688,
    "validation_records": 6_760,
    "validation_users": 1_369,
    "validation_targets": 1_911,
    "positive_train_pairs": 65_842,
}
_K_VALUES = (5, 10, 20)
_PROCESSED_DIR = "data/processed"
_REPORT_SCHEMA = "recfusion.two-tower-pilot-report.v1"


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} is malformed.")
    return cast(Mapping[str, object], value)


def _read_report(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} is malformed.")
    return value


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _memory_status() -> dict[str, int | None]:
    if os.name != "nt":
        return {"total_bytes": None, "available_bytes": None}
    buffer = ctypes.create_string_buffer(64)
    ctypes.c_uint32.from_buffer(buffer).value = 64
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(buffer):
        return {"total_bytes": None, "available_bytes": None}
    return {
        "total_bytes": ctypes.c_uint64.from_buffer(buffer, 8).value,
        "available_bytes": ctypes.c_uint64.from_buffer(buffer, 16).value,
    }


def _peak_working_set_bytes() -> int | None:
    if os.name != "nt":
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    try:
        psapi = ctypes.WinDLL("Psapi.dll", use_last_error=True)
        kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        success = psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        return int(counters.PeakWorkingSetSize) if success else None
    except (AttributeError, OSError):
        return None


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _code_provenance(root: Path) -> dict[str, object]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    files = (
        "packages/recfusion_ml/models/two_tower.py",
        "packages/recfusion_ml/training/two_tower.py",
        "packages/recfusion_ml/training/two_tower_checkpoint.py",
        "packages/recfusion_ml/evaluation/two_tower_pilot.py",
    )
    return {
        "git_commit": commit,
        "working_tree_changes_present": bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        ),
        "source_file_sha256": {name: _sha256_file(root / name)[0] for name in files},
    }


def _validated_events(data: TrustedPilotData) -> tuple[TwoTowerEvent, ...]:
    configuration = _object(data.temporal.get("configuration"), "temporal config")
    cutoffs = _object(configuration.get("cutoffs"), "temporal cutoffs")
    train_end_ms = cutoffs.get("train_end_ms_exclusive")
    if not isinstance(train_end_ms, int) or isinstance(train_end_ms, bool):
        raise ValueError("Trusted train timestamp boundary is malformed.")
    events: list[TwoTowerEvent] = []
    for record, rating_event in zip(data.train_records, data.train_events, strict=True):
        interaction = _object(record.get("interaction"), "train interaction")
        timestamp = interaction.get("event_time_ms")
        timestamp_text = interaction.get("event_time_utc")
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, int)
            or not 0 <= timestamp < train_end_ms
            or not isinstance(timestamp_text, str)
        ):
            raise ValueError("Train timestamp schema is invalid.")
        expected_utc = (
            time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(timestamp // 1000))
            + f".{timestamp % 1000:03d}Z"
        )
        if timestamp_text != expected_utc:
            raise ValueError("Train timestamp milliseconds and UTC text disagree.")
        events.append(
            TwoTowerEvent(
                user_key=rating_event.user_key,
                item_key=rating_event.item_key,
                rating=rating_event.rating,
                event_time_ms=timestamp,
                split="train",
            )
        )
    return tuple(events)


def _validate_dimensions(
    data: TrustedPilotData,
) -> tuple[ValidationCohort, dict[str, object]]:
    train_users = {event.user_key for event in data.train_events}
    train_items = {event.item_key for event in data.train_events}
    if (
        len(train_users) != _EXPECTED["train_users"]
        or len(train_items) != _EXPECTED["train_items"]
        or len(data.train_events) != _EXPECTED["train_records"]
        or len(data.validation_events) != _EXPECTED["validation_records"]
        or frozenset(train_items) != data.candidate_items
    ):
        raise ValueError(
            "Trusted train/validation dimensions or candidate pool differ."
        )
    cohort = build_validation_cohort(
        data.train_events, data.validation_events, data.candidate_items
    )
    if (
        cohort.users_with_evaluable_targets != _EXPECTED["validation_users"]
        or cohort.eligible_positive_target_count != _EXPECTED["validation_targets"]
    ):
        raise ValueError("Validation cohort differs from the approved pilot cohort.")
    return cohort, {
        "validation_users": cohort.validation_user_count,
        "validation_users_with_observed_positives": (
            cohort.users_with_observed_positives
        ),
        "validation_users_with_warm_positive_targets": (
            cohort.users_with_warm_positive_targets
        ),
        "train_users": len(train_users),
        "train_known_items": len(train_items),
        "train_interactions": len(data.train_events),
        "validation_interactions": len(data.validation_events),
        "validation_evaluable_users": cohort.users_with_evaluable_targets,
        "validation_warm_positive_target_pairs": (
            cohort.eligible_positive_target_count
        ),
        "validation_cold_item_positive_observations": (
            cohort.cold_item_positive_observation_count
        ),
        "validation_cold_user_positive_observations": (
            cohort.cold_user_positive_observation_count
        ),
        "validation_seen_positive_observations": cohort.seen_positive_observation_count,
        "validation_duplicate_positive_observations": (
            cohort.duplicate_positive_observation_count
        ),
        "validation_non_positive_observations": cohort.non_positive_observation_count,
        "validation_excluded_positive_target_counts": dict(
            cohort.excluded_target_counts
        ),
    }


def _history_audit(
    events: Sequence[TwoTowerEvent],
    *,
    max_history_items: int,
) -> dict[str, int]:
    tower_data = build_two_tower_data(
        events,
        max_history_items=max_history_items,
        source_artifact_fingerprints=(),
    )
    histories_by_user: dict[str, dict[str, list[int]]] = {}
    for event in events:
        histories_by_user.setdefault(event.user_key, {}).setdefault(
            event.item_key, []
        ).append(event.event_time_ms)
    empty_histories = 0
    max_history = 0
    for example in tower_data.examples:
        if example.item_key in example.history_item_ids:
            raise ValueError("A positive target occurs in its own training history.")
        user_items = histories_by_user[example.user_key]
        if any(
            item not in user_items or max(user_items[item]) >= example.event_time_ms
            for item in example.history_item_ids
        ):
            raise ValueError("Training history contains a future/equal-time event.")
        if len(set(example.history_item_ids)) != len(example.history_item_ids):
            raise ValueError("Training history contains repeated item IDs.")
        expected_history = tuple(
            item
            for item, _ in sorted(
                (
                    (
                        item,
                        max(
                            timestamp
                            for timestamp in timestamps
                            if timestamp < example.event_time_ms
                        ),
                    )
                    for item, timestamps in user_items.items()
                    if item != example.item_key
                    and any(
                        timestamp < example.event_time_ms for timestamp in timestamps
                    )
                ),
                key=lambda pair: (-pair[1], pair[0]),
            )[:max_history_items]
        )
        if example.history_item_ids != expected_history:
            raise ValueError("Training history ordering or truncation is not stable.")
        empty_histories += not example.history_item_ids
        max_history = max(max_history, len(example.history_item_ids))
    for user_key, history in tower_data.inference_history_by_user.items():
        expected_inference_history = tuple(
            item
            for item, _ in sorted(
                (
                    (item, max(timestamps))
                    for item, timestamps in histories_by_user[user_key].items()
                ),
                key=lambda pair: (-pair[1], pair[0]),
            )[:max_history_items]
        )
        if history != expected_inference_history:
            raise ValueError("Inference history is not derived from train-only events.")
    if len(tower_data.examples) != _EXPECTED["positive_train_pairs"]:
        raise ValueError("Training positive target count differs from the pilot.")
    return {
        "training_positive_targets": len(tower_data.examples),
        "empty_history_targets": empty_histories,
        "maximum_history_length": max_history,
        "duplicate_positive_observations_collapsed": (
            tower_data.collapsed_positive_observations
        ),
        "history_targets_audited": len(tower_data.examples),
        "train_users_with_inference_histories": len(
            tower_data.inference_history_by_user
        ),
    }


def _validate_validation_timestamps(data: TrustedPilotData) -> None:
    configuration = _object(data.temporal.get("configuration"), "temporal config")
    cutoffs = _object(configuration.get("cutoffs"), "temporal cutoffs")
    train_end_ms = cutoffs.get("train_end_ms_exclusive")
    test_start_ms = cutoffs.get("test_start_ms_inclusive")
    if (
        not isinstance(train_end_ms, int)
        or isinstance(train_end_ms, bool)
        or not isinstance(test_start_ms, int)
        or isinstance(test_start_ms, bool)
    ):
        raise ValueError("Trusted split timestamp boundaries are malformed.")
    for record in data.validation_records:
        interaction = _object(record.get("interaction"), "validation interaction")
        timestamp = interaction.get("event_time_ms")
        timestamp_text = interaction.get("event_time_utc")
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, int)
            or not train_end_ms <= timestamp < test_start_ms
            or not isinstance(timestamp_text, str)
        ):
            raise ValueError("Validation timestamp violates the official interval.")
        expected_utc = (
            time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(timestamp // 1000))
            + f".{timestamp % 1000:03d}Z"
        )
        if timestamp_text != expected_utc:
            raise ValueError("Validation timestamp milliseconds and UTC text disagree.")


def _metrics_json(metrics: Mapping[int, RankingMetrics]) -> dict[str, object]:
    return {
        str(k): {
            "recall": metrics[k].recall,
            "ndcg": metrics[k].ndcg,
            "hit_rate": metrics[k].hit_rate,
            "mrr": metrics[k].mrr,
            "candidate_coverage": metrics[k].candidate_coverage,
            "unique_recommended_items": metrics[k].unique_recommended_items,
            "recommendation_count": metrics[k].recommendation_count,
        }
        for k in _K_VALUES
    }


def _validate_baseline_reports(
    *,
    data: TrustedPilotData,
    cohort_counts: Mapping[str, object],
    popularity_path: Path,
    item_cf_path: Path,
    bpr_path: Path,
) -> tuple[dict[str, object], dict[str, str]]:
    root = _repository_root()
    processed = (root / _PROCESSED_DIR).resolve()
    paths = (popularity_path.resolve(), item_cf_path.resolve(), bpr_path.resolve())
    if any(processed not in path.parents or not path.is_file() for path in paths):
        raise ValueError("Baseline reports must be existing local processed reports.")
    popularity, item_cf, bpr = (_read_report(path) for path in paths)
    train_sha = cast(str, data.temporal_outputs["interactions.train.jsonl"]["sha256"])
    validation_sha = cast(
        str, data.temporal_outputs["interactions.validation.jsonl"]["sha256"]
    )
    test_sha = cast(str, data.temporal_outputs["interactions.test.jsonl"]["sha256"])
    temporal_sha = _sha256_file(data.temporal_dir / "manifest.json")[0]
    preprocessing_sha = _sha256_file(data.preprocessing_dir / "manifest.json")[0]
    pop_sha, item_sha = _sha256_file(paths[0])[0], _sha256_file(paths[1])[0]

    if bpr.get("status") != "complete":
        raise ValueError("Existing BPR baseline report is incomplete.")
    provenance = _object(bpr.get("provenance"), "BPR baseline provenance")
    protocol = _object(bpr.get("protocol"), "BPR baseline protocol")
    counts = _object(bpr.get("counts"), "BPR baseline counts")
    expected_provenance = {
        "train_sha256": train_sha,
        "validation_sha256": validation_sha,
        "test_sha256_verified_without_parsing": test_sha,
        "temporal_manifest_sha256": temporal_sha,
        "preprocessing_manifest_sha256": preprocessing_sha,
        "popularity_report_sha256": pop_sha,
        "item_cf_report_sha256": item_sha,
    }
    if any(provenance.get(key) != value for key, value in expected_provenance.items()):
        raise ValueError("Baseline report fingerprints do not match this pilot.")
    if (
        protocol.get("evaluation_split") != "validation only"
        or protocol.get("test_rows_parsed_or_evaluated") is not False
        or protocol.get("candidate_pool") != "exact train-known Step 2.5 item pool"
        or protocol.get("seen_item_policy")
        != "exclude every train-observed user-item pair"
        or protocol.get("ks") != list(_K_VALUES)
        or counts.get("train_records") != _EXPECTED["train_records"]
        or counts.get("validation_records") != _EXPECTED["validation_records"]
        or counts.get("validation_evaluable_users")
        != cohort_counts["validation_evaluable_users"]
        or counts.get("validation_eligible_positive_targets")
        != cohort_counts["validation_warm_positive_target_pairs"]
    ):
        raise ValueError("Baseline protocol or cohort differs from this pilot.")
    bpr_metrics = _object(bpr.get("metrics"), "BPR metrics")
    saved_baselines = _object(bpr_metrics.get("baselines"), "BPR baselines")
    result: dict[str, object] = {}
    for k in _K_VALUES:
        key = str(k)
        result[key] = {
            "popularity": _object(saved_baselines.get(key), f"baseline @{k}").get(
                "popularity"
            ),
            "item_cf": _object(saved_baselines.get(key), f"baseline @{k}").get(
                "item_cf"
            ),
            "bpr": _object(bpr_metrics.get("bpr"), "BPR metric group").get(key),
        }
        for baseline, report, metric_key in (
            ("popularity", popularity, "metrics"),
            ("item_cf", item_cf, "comparison"),
        ):
            top = _object(report.get(metric_key), f"{baseline} metric group")
            at_k = _object(top.get(key), f"{baseline} @{k}")
            if baseline == "item_cf":
                at_k = _object(at_k.get("item_cf"), f"item-CF @{k}")
            at_k_saved = _object(result[key], f"saved baseline @{k}")
            saved = _object(at_k_saved.get(baseline), f"saved {baseline} @{k}")
            if any(
                saved.get(field) != at_k.get(field)
                for field in ("recall", "ndcg", "hit_rate", "mrr")
            ):
                raise ValueError(f"Saved {baseline} results do not match its report.")
    return result, {
        "popularity_report_sha256": pop_sha,
        "item_cf_report_sha256": item_sha,
        "bpr_report_sha256": _sha256_file(paths[2])[0],
        "temporal_manifest_sha256": temporal_sha,
        "preprocessing_manifest_sha256": preprocessing_sha,
        "train_sha256": train_sha,
        "validation_sha256": validation_sha,
    }


def _recommend_and_evaluate(
    recommender: TwoTowerRecommender,
    cohort: ValidationCohort,
    candidate_items: frozenset[str],
) -> tuple[dict[str, tuple[str, ...]], dict[int, RankingMetrics], float]:
    started = time.perf_counter()
    rankings = recommender.recommend_many(
        cohort.targets_by_user, k=max(_K_VALUES), chunk_size=4096
    )
    evaluation = evaluate_rankings(
        cohort, rankings, candidate_items=set(candidate_items), ks=_K_VALUES
    )
    return rankings, dict(evaluation.metrics_by_k), time.perf_counter() - started


def _configuration() -> TwoTowerConfig:
    return TwoTowerConfig(epochs=20, batch_size=256, seed=42)


def _serialized_config(config: TwoTowerConfig) -> dict[str, object]:
    return {**asdict(config), "hidden_dims": list(config.hidden_dims)}


def _preflight_record(
    *,
    data: TrustedPilotData,
    train_events: tuple[TwoTowerEvent, ...],
    cohort: ValidationCohort,
    cohort_counts: Mapping[str, object],
    history_counts: Mapping[str, int],
    config: TwoTowerConfig,
) -> dict[str, object]:
    before_memory = _memory_status()
    before_disk = shutil.disk_usage(_repository_root().drive + "\\").free
    full_validation_seconds: list[float] = []
    validation_counts: list[int] = []

    benchmark_metrics: list[dict[str, object]] = []

    def benchmark_validation(recommender: TwoTowerRecommender) -> None:
        rankings, metrics, elapsed = _recommend_and_evaluate(
            recommender, cohort, data.candidate_items
        )
        full_validation_seconds.append(elapsed)
        validation_counts.append(len(rankings))
        benchmark_metrics.append(_metrics_json(metrics))
        if len(rankings) != _EXPECTED["validation_users"]:
            raise ValueError("Preflight did not rank the complete validation cohort.")
        if not math.isfinite(metrics[10].ndcg or math.nan):
            raise ValueError("Preflight validation NDCG@10 is non-finite.")

    benchmark_started = time.perf_counter()
    benchmark = fit_two_tower(
        train_events,
        config=replace(config, epochs=1),
        source_artifact_fingerprints=(
            cast(str, data.temporal_outputs["interactions.train.jsonl"]["sha256"]),
        ),
        epoch_callback=benchmark_validation,
    )
    parameter_count = sum(
        parameter.numel() for parameter in benchmark.model.parameters()
    )
    elapsed = time.perf_counter() - benchmark_started
    after_memory = _memory_status()
    after_disk = shutil.disk_usage(_repository_root().drive + "\\").free
    return {
        "schema_version": "recfusion.two-tower-preflight.v1",
        "source": data.temporal.get("source"),
        "provenance": {
            "train_sha256": data.temporal_outputs["interactions.train.jsonl"]["sha256"],
            "validation_sha256": data.temporal_outputs["interactions.validation.jsonl"][
                "sha256"
            ],
            "temporal_manifest_sha256": _sha256_file(
                data.temporal_dir / "manifest.json"
            )[0],
            "preprocessing_manifest_sha256": _sha256_file(
                data.preprocessing_dir / "manifest.json"
            )[0],
        },
        "configuration": _serialized_config(config),
        "counts": {
            **dict(cohort_counts),
            **dict(history_counts),
            "benchmark_training_epochs": len(benchmark.epoch_statistics),
            "benchmark_training_examples": benchmark.summary.training_examples,
        },
        "benchmark": {
            "training_seconds": benchmark.epoch_statistics[0].duration_seconds,
            "validation_pass_seconds": full_validation_seconds[0],
            "validation_users_ranked": validation_counts[0],
            "validation_metrics_for_resource_benchmark_only": benchmark_metrics[0],
            "end_to_end_seconds": elapsed,
            "device": "cpu",
            "parameter_count": parameter_count,
            "model_vector_cache_bytes": (
                len(data.candidate_items) * config.retrieval_dim * 4
            ),
            "available_memory_before_bytes": before_memory["available_bytes"],
            "available_memory_after_bytes": after_memory["available_bytes"],
            "peak_process_working_set_bytes": _peak_working_set_bytes(),
            "free_disk_before_bytes": before_disk,
            "free_disk_after_bytes": after_disk,
            "full_catalog_validation_completed": True,
        },
        "history_audit": dict(history_counts),
    }


def run_two_tower_preflight(
    *,
    preprocessing_dir: Path,
    temporal_dir: Path,
    output_dir: Path,
    temp_dir: Path,
) -> dict[str, object]:
    root = _repository_root()
    processed = (root / _PROCESSED_DIR).resolve()
    output_dir, temp_dir = output_dir.resolve(), temp_dir.resolve()
    if processed not in output_dir.parents or processed not in temp_dir.parents:
        raise ValueError(
            "Output and temporary directories must be under data/processed."
        )
    if (
        output_dir == temp_dir
        or output_dir in temp_dir.parents
        or temp_dir in output_dir.parents
    ):
        raise ValueError("Output and temporary directories must be separate.")
    if output_dir.exists():
        raise ValueError("Output directory already exists; refusing to overwrite it.")
    temp_dir.mkdir(parents=True, exist_ok=True)
    preflight_path = temp_dir / "preflight.json"
    if preflight_path.exists():
        raise ValueError("Preflight report already exists; refusing to overwrite it.")
    data = load_trusted_pilot_data(preprocessing_dir, temporal_dir)
    cohort, counts = _validate_dimensions(data)
    train_events = _validated_events(data)
    _validate_validation_timestamps(data)
    config = _configuration()
    history_counts = _history_audit(
        train_events, max_history_items=config.max_history_items
    )
    result = _preflight_record(
        data=data,
        train_events=train_events,
        cohort=cohort,
        cohort_counts=counts,
        history_counts=history_counts,
        config=config,
    )
    _atomic_json(preflight_path, result)
    return result


def run_two_tower_pilot(
    *,
    preprocessing_dir: Path,
    temporal_dir: Path,
    popularity_report_path: Path,
    item_cf_report_path: Path,
    bpr_report_path: Path,
    output_dir: Path,
    temp_dir: Path,
) -> dict[str, object]:
    started = time.perf_counter()
    root = _repository_root()
    processed = (root / _PROCESSED_DIR).resolve()
    output_dir, temp_dir = output_dir.resolve(), temp_dir.resolve()
    if processed not in output_dir.parents or processed not in temp_dir.parents:
        raise ValueError(
            "Output and temporary directories must be under data/processed."
        )
    if (
        output_dir == temp_dir
        or output_dir in temp_dir.parents
        or temp_dir in output_dir.parents
    ):
        raise ValueError("Output and temporary directories must be separate.")
    for input_dir in (preprocessing_dir.resolve(), temporal_dir.resolve()):
        if input_dir == output_dir or input_dir in output_dir.parents:
            raise ValueError("Output directory cannot overwrite or contain an input.")
    if output_dir.exists():
        raise ValueError("Output directory already exists; refusing to overwrite it.")
    preflight_path = temp_dir / "preflight.json"
    if not preflight_path.is_file():
        raise ValueError("A completed matching resource preflight is required.")

    data = load_trusted_pilot_data(preprocessing_dir, temporal_dir)
    cohort, counts = _validate_dimensions(data)
    train_events = _validated_events(data)
    _validate_validation_timestamps(data)
    config = _configuration()
    history_counts = _history_audit(
        train_events, max_history_items=config.max_history_items
    )
    baselines, baseline_provenance = _validate_baseline_reports(
        data=data,
        cohort_counts=counts,
        popularity_path=popularity_report_path,
        item_cf_path=item_cf_report_path,
        bpr_path=bpr_report_path,
    )
    preflight = _read_report(preflight_path)
    preflight_provenance = _object(preflight.get("provenance"), "preflight provenance")
    matching = {
        "train_sha256": data.temporal_outputs["interactions.train.jsonl"]["sha256"],
        "validation_sha256": data.temporal_outputs["interactions.validation.jsonl"][
            "sha256"
        ],
        "temporal_manifest_sha256": baseline_provenance["temporal_manifest_sha256"],
        "preprocessing_manifest_sha256": baseline_provenance[
            "preprocessing_manifest_sha256"
        ],
    }
    if (
        preflight.get("schema_version") != "recfusion.two-tower-preflight.v1"
        or preflight.get("configuration") != _serialized_config(config)
        or any(
            preflight_provenance.get(key) != value for key, value in matching.items()
        )
        or _object(preflight.get("benchmark"), "preflight benchmark").get(
            "full_catalog_validation_completed"
        )
        is not True
    ):
        raise ValueError("Preflight does not match this data and configuration.")

    output_dir.mkdir(parents=True)
    checkpoint_path = output_dir / "two-tower-best.pt"
    progress_path = output_dir / "progress.jsonl"
    epoch_results: list[dict[str, object]] = []
    best_ndcg = -math.inf
    best_epoch = 0
    best_rankings: dict[str, tuple[str, ...]] = {}
    best_validation_seconds = 0.0

    def validate_epoch(recommender: TwoTowerRecommender) -> None:
        nonlocal best_ndcg, best_epoch, best_rankings, best_validation_seconds
        epoch = recommender.epoch_statistics[-1]
        rankings, metrics, validation_seconds = _recommend_and_evaluate(
            recommender, cohort, data.candidate_items
        )
        ndcg = metrics[10].ndcg
        if ndcg is None or not math.isfinite(ndcg):
            raise ValueError("Validation NDCG@10 is not finite.")
        result: dict[str, object] = {
            "epoch": epoch.epoch,
            "retrieval_loss": epoch.retrieval_loss,
            "regularization_loss": epoch.regularization_loss,
            "total_loss": epoch.total_loss,
            "training_examples": epoch.training_example_count,
            "sampled_negatives": epoch.sampled_negative_count,
            "training_seconds": epoch.duration_seconds,
            "validation_seconds": validation_seconds,
            "validation_ndcg_at_10": ndcg,
            "peak_process_working_set_bytes": _peak_working_set_bytes(),
            "available_memory_after_epoch_bytes": _memory_status()["available_bytes"],
        }
        epoch_results.append(result)
        with progress_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(result, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if best_epoch == 0 or ndcg > best_ndcg:
            temporary_checkpoint = output_dir / f"two-tower-candidate-{epoch.epoch}.pt"
            save_two_tower_checkpoint(
                recommender,
                temporary_checkpoint,
                repository_root=root,
            )
            temporary_checkpoint.replace(checkpoint_path)
            best_ndcg = ndcg
            best_epoch = epoch.epoch
            best_rankings = rankings
            best_validation_seconds = validation_seconds

    before_memory = _memory_status()
    before_disk = shutil.disk_usage(root.drive + "\\").free
    recommender = fit_two_tower(
        train_events,
        config=config,
        source_artifact_fingerprints=(
            cast(str, data.temporal_outputs["interactions.train.jsonl"]["sha256"]),
        ),
        epoch_callback=validate_epoch,
    )
    training_and_validation_seconds = time.perf_counter() - started
    loaded = load_two_tower_checkpoint(checkpoint_path, repository_root=root)
    reload_started = time.perf_counter()
    final_rankings, final_metrics, reload_validation_seconds = _recommend_and_evaluate(
        loaded, cohort, data.candidate_items
    )
    reload_seconds = time.perf_counter() - reload_started
    reload_identical = final_rankings == best_rankings
    if not reload_identical:
        raise ValueError("Checkpoint reload changed validation recommendations.")

    baseline_metric = baselines
    final_json = _metrics_json(final_metrics)
    comparison: dict[str, object] = {}
    for key in map(str, _K_VALUES):
        references = _object(baseline_metric[key], f"baseline metrics @{key}")
        final_at_k = _object(final_json.get(key), f"Two-Tower metrics @{key}")
        deltas: dict[str, object] = {}
        for name in ("popularity", "item_cf", "bpr"):
            reference = _object(references.get(name), name)
            deltas[name] = {}
            for metric in ("recall", "ndcg", "hit_rate", "mrr"):
                current_value, baseline_value = (
                    final_at_k.get(metric),
                    reference.get(metric),
                )
                cast(dict[str, object], deltas[name])[metric] = (
                    float(current_value) - float(baseline_value)
                    if isinstance(current_value, (int, float))
                    and isinstance(baseline_value, (int, float))
                    else None
                )
        comparison[key] = deltas

    checkpoint_sha, checkpoint_size = _sha256_file(checkpoint_path)
    after_memory = _memory_status()
    after_disk = shutil.disk_usage(root.drive + "\\").free
    resource_report = {
        "preflight_benchmark": preflight["benchmark"],
        "training_and_validation_wall_seconds": training_and_validation_seconds,
        "checkpoint_reload_full_validation_seconds": reload_validation_seconds,
        "checkpoint_reload_wall_seconds": reload_seconds,
        "peak_process_working_set_bytes": _peak_working_set_bytes(),
        "available_memory_before_training_bytes": before_memory["available_bytes"],
        "available_memory_after_training_bytes": after_memory["available_bytes"],
        "free_disk_before_training_bytes": before_disk,
        "free_disk_after_training_bytes": after_disk,
        "checkpoint_size_bytes": checkpoint_size,
        "output_artifact_bytes_excluding_final_report": sum(
            path.stat().st_size for path in output_dir.rglob("*") if path.is_file()
        ),
    }
    temporal_counts = _object(data.temporal.get("counts"), "temporal counts")
    split_counts = _object(temporal_counts.get("split_counts"), "split counts")
    rejected_by_input = _object(
        temporal_counts.get("rejected_by_input"), "split rejection counts"
    )
    source_reconciliation: dict[str, object] = {}
    for split, row_count in (
        ("train", len(data.train_events)),
        ("validation", len(data.validation_events)),
    ):
        reasons = _object(rejected_by_input.get(split), f"{split} rejections")
        source_reconciliation[split] = {
            "input_rows": row_count,
            "accepted_rows": row_count,
            "rejected_rows": sum(
                value for value in reasons.values() if isinstance(value, int)
            ),
            "rejection_reasons": dict(reasons),
        }
    report: dict[str, object] = {
        "report_schema_version": _REPORT_SCHEMA,
        "experiment": "phase-3.3B-real-amazon-electronics-history-aware-two-tower",
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
        "provenance": baseline_provenance,
        "code_provenance": _code_provenance(root),
        "protocol": {
            "training_split": "train only",
            "evaluation_split": "validation only",
            "test_rows_parsed_or_evaluated": False,
            "candidate_pool": "exact train-known Step 2.5 item pool",
            "seen_item_policy": "exclude every train-observed user-item pair",
            "positive_min_rating": "4",
            "unobserved_items": "unknown; sampled negatives are not verified dislikes",
            "selection_metric": "macro NDCG@10",
            "selection_tie_policy": "earliest epoch",
            "ks": list(_K_VALUES),
            "metadata_features": "unavailable; no product metadata joined",
            "confidence_intervals": "not computed; no significance claim",
        },
        "configuration": {
            **asdict(config),
            "model": "history-aware two-tower sampled-softmax retrieval",
            "optimizer": "Adam",
            "device": "cpu",
            "selection_metric": "macro NDCG@10",
            "dataset_sampling_seed": _dataset_seed(data),
            "training_seed": config.seed,
            "torch_version": str(torch.__version__),
            "cpu_threads": torch.get_num_threads(),
        },
        "counts": {
            **counts,
            **history_counts,
            "source_reconciliation": source_reconciliation,
            "sampled_negatives_per_epoch": (
                recommender.summary.sampled_negative_count_per_epoch
            ),
            "positive_targets_skipped_without_negative": (
                recommender.summary.skipped_examples_without_negative
            ),
            "ranking_users": len(final_rankings),
            "users_receiving_fewer_than_k": {
                str(k): sum(len(items) < k for items in final_rankings.values())
                for k in _K_VALUES
            },
        },
        "training_and_validation_source_quality": {
            split: {
                "rating_label_distribution": _object(
                    split_counts.get(split), f"{split} split"
                ).get("rating_label_distribution"),
                "timestamp_range_ms": _object(
                    split_counts.get(split), f"{split} split"
                ).get("timestamp_range_ms"),
                "rejected_records": _object(
                    _object(temporal_counts.get("rejected_by_input"), "rejections").get(
                        split
                    ),
                    f"{split} rejections",
                ),
            }
            for split in ("train", "validation")
        },
        "architecture": {
            "embedding_dim": config.embedding_dim,
            "hidden_dims": list(config.hidden_dims),
            "retrieval_dim": config.retrieval_dim,
            "history_length_limit": config.max_history_items,
            "parameter_count": sum(
                parameter.numel() for parameter in loaded.model.parameters()
            ),
            "dropout": "not implemented by the Phase 3.3A model",
            "metadata": "not used; item tower is ID-only",
        },
        "history_policy": {
            "training": (
                "strictly earlier train observations; equal timestamps excluded; "
                "target item masked; unique most-recent items"
            ),
            "validation_inference": (
                "train-only user history; validation targets and ratings are not "
                "tower inputs"
            ),
            "empty_history_supported": True,
        },
        "training_summary": {
            "train_events": recommender.summary.train_event_count,
            "positive_observations": recommender.summary.positive_observation_count,
            "distinct_positive_pairs": recommender.summary.unique_positive_pairs,
            "collapsed_positive_observations": (
                recommender.summary.collapsed_positive_observations
            ),
            "training_examples": recommender.summary.training_examples,
            "negative_policy": "up to four distinct train-unobserved items per target",
        },
        "epochs": epoch_results,
        "selection": {
            "epoch": best_epoch,
            "metric": "macro NDCG@10",
            "validation_ndcg_at_10": best_ndcg,
            "tie_policy": "earliest epoch",
            "checkpoint": checkpoint_path.name,
            "checkpoint_sha256": checkpoint_sha,
            "checkpoint_size_bytes": checkpoint_size,
            "checkpoint_reload_rankings_identical": reload_identical,
            "checkpoint_reload_seconds": reload_seconds,
        },
        "metrics": {"two_tower": final_json, "baselines": baselines},
        "metric_deltas_vs_baselines": comparison,
        "candidate_coverage": {
            "candidate_pool_size": len(data.candidate_items),
            "evaluated_users": len(final_rankings),
            "eligible_warm_positive_targets": counts[
                "validation_warm_positive_target_pairs"
            ],
            "metrics_by_k": final_json,
        },
        "resources": resource_report,
        "limitations": [
            (
                "This is one local validation-selected experiment, not statistical "
                "evidence of generalization."
            ),
            "The item tower uses IDs only and cannot retrieve cold items.",
            "No product metadata was joined or evaluated.",
            "Amazon ratings are observed review ratings, not purchases or impressions.",
            (
                "Validation uses the warm-positive subset; cold-item positives are "
                "excluded by the frozen cohort protocol."
            ),
        ],
    }
    _atomic_json(output_dir / "two-tower-report.json", report)
    return report


def _dataset_seed(data: TrustedPilotData) -> object:
    manifest_path = (
        _repository_root()
        / _PROCESSED_DIR
        / "amazon-electronics-pilot-10000-v1"
        / "manifest.json"
    )
    manifest = _read_report(manifest_path)
    sampling = manifest.get("sampling")
    if not isinstance(sampling, dict):
        return None
    return sampling.get("seed")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preflight or train the validation-only 10K Two-Tower pilot."
    )
    parser.add_argument("--phase", choices=("preflight", "run"), required=True)
    parser.add_argument(
        "--preprocessing-dir",
        type=Path,
        default=Path("data/processed/amazon-electronics-pilot-10000-preprocessed-v1"),
    )
    parser.add_argument(
        "--temporal-dir",
        type=Path,
        default=Path("data/processed/amazon-electronics-pilot-10000-temporal-v1"),
    )
    parser.add_argument(
        "--popularity-report",
        type=Path,
        default=Path(
            "data/processed/amazon-electronics-pilot-10000-popularity-v1/aggregate-report.json"
        ),
    )
    parser.add_argument(
        "--item-cf-report",
        type=Path,
        default=Path(
            "data/processed/amazon-electronics-pilot-10000-itemcf-v1/item-cf-report.json"
        ),
    )
    parser.add_argument(
        "--bpr-report",
        type=Path,
        default=Path(
            "data/processed/amazon-electronics-pilot-10000-bpr-v1/bpr-report.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed/amazon-electronics-pilot-10000-twotower-v1"),
    )
    parser.add_argument(
        "--temp-dir",
        type=Path,
        default=Path("data/processed/amazon-electronics-pilot-10000-twotower-temp-v1"),
    )
    arguments = parser.parse_args(argv)
    if arguments.phase == "preflight":
        result = run_two_tower_preflight(
            preprocessing_dir=arguments.preprocessing_dir,
            temporal_dir=arguments.temporal_dir,
            output_dir=arguments.output_dir,
            temp_dir=arguments.temp_dir,
        )
    else:
        result = run_two_tower_pilot(
            preprocessing_dir=arguments.preprocessing_dir,
            temporal_dir=arguments.temporal_dir,
            popularity_report_path=arguments.popularity_report,
            item_cf_report_path=arguments.item_cf_report,
            bpr_report_path=arguments.bpr_report,
            output_dir=arguments.output_dir,
            temp_dir=arguments.temp_dir,
        )
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
