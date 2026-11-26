"""Run the predeclared, aggregate-only Amazon Electronics RRF comparison."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import tracemalloc
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from recfusion_ml.baselines.item_cf import ItemBasedCollaborativeFilter
from recfusion_ml.baselines.popularity import PopularityRecommender
from recfusion_ml.evaluation.fusion import FusionDiagnostics, summarize_fusion
from recfusion_ml.evaluation.metrics import (
    ValidationCohort,
    build_validation_cohort,
)
from recfusion_ml.evaluation.model_comparison import (
    _assert_saved_metrics,
    _object,
    _read_report,
    _validate_shared_lineage,
    compare_rankings,
)
from recfusion_ml.evaluation.pilot import (
    _sha256_file,
    load_trusted_pilot_data,
)
from recfusion_ml.evaluation.two_tower_diagnostics import _validate_run
from recfusion_ml.evaluation.two_tower_pilot import (
    _memory_status,
    _peak_working_set_bytes,
)
from recfusion_ml.ranking.rrf import RRFConfig, RRFResult, fuse_ranked_candidates
from recfusion_ml.training.bpr import TrainingData, load_checkpoint

_K_VALUES = (5, 10, 20)
_SOURCE_DEPTH = 100
_BOOTSTRAP_RESAMPLES = 2000
_BOOTSTRAP_SEED = 33033
_PERSONALIZATION_SAMPLE = 128
_RRF_SOURCE_MODEL_KEYS = {
    "popularity": "popularity",
    "item-cf": "item_cf",
    "bpr": "bpr",
    "two-tower": "two_tower",
}
_SOURCE_REPORTS = {
    "popularity": Path("amazon-electronics-pilot-10000-popularity-v1")
    / "aggregate-report.json",
    "item_cf": Path("amazon-electronics-pilot-10000-itemcf-v1") / "item-cf-report.json",
    "bpr": Path("amazon-electronics-pilot-10000-bpr-v1") / "bpr-report.json",
    "two_tower": Path("amazon-electronics-pilot-10000-twotower-v1")
    / "two-tower-report.json",
}
_CONFIGURATIONS = {
    "equal-four-model-rrf": {
        "popularity": 1.0,
        "item-cf": 1.0,
        "bpr": 1.0,
        "two-tower": 1.0,
    },
    "two-tower-bpr-rrf": {"two-tower": 1.0, "bpr": 1.0},
}


def _check_source_inventory(root: Path, processed: Path) -> dict[str, object]:
    ingestion_dir = processed / "amazon-electronics-pilot-10000-v1"
    ingestion_manifest_path = ingestion_dir / "manifest.json"
    ingestion_manifest = json.loads(ingestion_manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(ingestion_manifest, dict)
        or ingestion_manifest.get("canonical_schema_version")
        != "recfusion.canonical.v1"
    ):
        raise ValueError("The existing 10,000-user ingestion manifest is invalid.")
    source = _object(ingestion_manifest.get("source"), "ingestion source")
    if (
        source.get("id") != "amazon-reviews-2023-electronics"
        or source.get("version") != "electronics-5core-timestamp-v1"
    ):
        raise ValueError("Ingestion source identity differs from the pilot.")
    raw_files = _object(source.get("files"), "source files")
    expected_splits = {
        "train": "Electronics.train.csv",
        "validation": "Electronics.valid.csv",
        "test": "Electronics.test.csv",
    }
    source_inventory: dict[str, dict[str, object]] = {}
    for split, file_name in expected_splits.items():
        item = _object(raw_files.get(split), f"{split} source file")
        path = root / file_name
        if (
            item.get("file") != file_name
            or not path.is_file()
            or path.stat().st_size != item.get("size_bytes")
        ):
            raise ValueError(f"The recorded {split} source inventory has changed.")
        source_inventory[split] = {
            "file": file_name,
            "size_bytes": item.get("size_bytes"),
            "sha256_recorded_by_ingestion": item.get("sha256"),
            "source_file_read_this_step": False,
        }

    outputs = ingestion_manifest.get("outputs")
    if not isinstance(outputs, list):
        raise ValueError("Ingestion manifest has no output inventory.")
    verified: dict[str, dict[str, object]] = {}
    for entry in outputs:
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            raise ValueError("Ingestion output inventory is malformed.")
        file_name = cast(str, entry["file"])
        if Path(file_name).name != file_name or file_name in verified:
            raise ValueError("Ingestion output filename is unsafe or repeated.")
        path = ingestion_dir / file_name
        if not path.is_file():
            raise ValueError(f"Ingestion output {file_name} is missing.")
        checksum, size = _sha256_file(path)
        if entry.get("sha256") != checksum:
            raise ValueError(f"Ingestion output checksum differs for {file_name}.")
        verified[file_name] = {"sha256": checksum, "size_bytes": size}

    pilot_report_path = (
        processed / "amazon-electronics-pilot-10000-report-v1" / "pilot-report.json"
    )
    pilot_report = _read_report(pilot_report_path)
    pilot_source = _object(pilot_report.get("source"), "pilot source")
    report_files = pilot_source.get("files")
    if not isinstance(report_files, list):
        raise ValueError("Pilot report is missing source checksum records.")
    report_by_split = {
        entry.get("split"): entry for entry in report_files if isinstance(entry, dict)
    }
    for split, file_name in expected_splits.items():
        report_record = report_by_split.get(split)
        manifest_record = source_inventory[split]
        if not isinstance(report_record, dict) or any(
            report_record.get(key) != value
            for key, value in (
                ("path", file_name),
                ("bytes", manifest_record["size_bytes"]),
                ("sha256", manifest_record["sha256_recorded_by_ingestion"]),
                ("expected_sha256", manifest_record["sha256_recorded_by_ingestion"]),
                ("matches_expected", True),
            )
        ):
            raise ValueError(f"Pilot source checksum record differs for {split}.")
    return {
        "dataset": source.get("id"),
        "source_version": source.get("version"),
        "source_files": source_inventory,
        "ingestion_manifest_sha256": _sha256_file(ingestion_manifest_path)[0],
        "ingestion_output_hashes": {
            name: record["sha256"] for name, record in sorted(verified.items())
        },
        "pilot_report_sha256": _sha256_file(pilot_report_path)[0],
    }


def _manifest_output_hashes(manifest: Mapping[str, object]) -> dict[str, str]:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise ValueError("Artifact manifest has no output inventory.")
    result: dict[str, str] = {}
    for output in outputs:
        if (
            not isinstance(output, dict)
            or not isinstance(output.get("file"), str)
            or not isinstance(output.get("sha256"), str)
        ):
            raise ValueError("Artifact output inventory is malformed.")
        result[cast(str, output["file"])] = cast(str, output["sha256"])
    return dict(sorted(result.items()))


def _validate_rankings(
    rankings: Mapping[str, Sequence[str]],
    *,
    users: Sequence[str],
    cohort: ValidationCohort,
    candidate_items: frozenset[str],
) -> None:
    if set(rankings) != set(users):
        raise ValueError("A source ranking is missing an evaluable validation user.")
    for user, items in rankings.items():
        if len(items) > _SOURCE_DEPTH or len(items) != len(set(items)):
            raise ValueError("A source list is over-depth or contains duplicate items.")
        if set(items) - candidate_items:
            raise ValueError("A source returned an item outside the train-known pool.")
        if set(items) & cohort.seen_items_by_user[user]:
            raise ValueError("A source returned a train-seen item.")


def _fuse_users(
    rankings: Mapping[str, Mapping[str, Sequence[str]]],
    *,
    users: Sequence[str],
    cohort: ValidationCohort,
    config: RRFConfig,
) -> dict[str, RRFResult]:
    results = {
        user: fuse_ranked_candidates(
            {
                source: rankings[_RRF_SOURCE_MODEL_KEYS[source]][user]
                for source in config.source_weights or {}
            },
            candidate_items=cohort.candidate_items,
            seen_items=cohort.seen_items_by_user[user],
            k=max(_K_VALUES),
            config=config,
        )
        for user in users
    }
    for result in results.values():
        for source in result.source_names:
            reconciled = sum(
                (
                    result.eligible_counts[source],
                    result.depth_truncated_counts[source],
                    result.outside_pool_counts[source],
                    result.seen_excluded_counts[source],
                )
            )
            if result.raw_generated_counts[source] != reconciled:
                raise ValueError("RRF source row counts do not reconcile.")
    return results


def _fusion_diagnostics_json(value: FusionDiagnostics) -> dict[str, object]:
    result = {
        "user_count": value.user_count,
        "candidate_pool_item_count": value.candidate_pool_item_count,
        "eligible_union_item_count": value.eligible_union_item_count,
        "eligible_union_coverage": value.eligible_union_coverage,
        "mean_eligible_union_size": value.mean_eligible_union_size,
        "source_raw_generated_counts": value.source_raw_generated_counts,
        "source_eligible_counts": value.source_eligible_counts,
        "source_depth_truncated_counts": value.source_depth_truncated_counts,
        "source_outside_pool_counts": value.source_outside_pool_counts,
        "source_seen_excluded_counts": value.source_seen_excluded_counts,
        "source_recommendation_attribution_counts": (
            value.source_recommendation_attribution_counts
        ),
        "source_pair_mean_jaccard": {
            f"{left}_vs_{right}": score
            for (left, right), score in value.source_pair_mean_jaccard.items()
        },
        "source_pair_mean_disagreement": {
            f"{left}_vs_{right}": score
            for (left, right), score in value.source_pair_mean_disagreement.items()
        },
        "by_k": value.by_k,
    }
    return cast(dict[str, object], result)


def _metric_differences(
    comparison: Mapping[str, object], *, names: Sequence[str]
) -> dict[str, object]:
    models = _object(comparison.get("models"), "comparison models")
    output: dict[str, object] = {}
    for fusion_name in names:
        fusion_metrics = _object(models.get(fusion_name), fusion_name)
        output[fusion_name] = {}
        fusion_output = cast(dict[str, object], output[fusion_name])
        for baseline in ("popularity", "item_cf", "bpr", "two_tower"):
            baseline_metrics = _object(models.get(baseline), baseline)
            by_k: dict[str, object] = {}
            for k in _K_VALUES:
                fused = _object(fusion_metrics.get(str(k)), f"{fusion_name} K={k}")
                base = _object(baseline_metrics.get(str(k)), f"{baseline} K={k}")
                fields: dict[str, object] = {}
                for metric in (
                    "recall",
                    "ndcg",
                    "hit_rate",
                    "mrr",
                    "candidate_coverage",
                ):
                    fused_value = cast(float, fused[metric])
                    baseline_value = cast(float, base[metric])
                    difference = fused_value - baseline_value
                    fields[metric] = {
                        "fusion": fused_value,
                        "baseline": baseline_value,
                        "absolute_difference": difference,
                        "relative_difference_percent": (
                            difference / baseline_value * 100
                            if baseline_value
                            else None
                        ),
                    }
                by_k[str(k)] = fields
            fusion_output[baseline] = by_k
    return output


def _orient_paired_statistic(
    statistic: Mapping[str, object], *, reverse: bool
) -> dict[str, object]:
    """Orient stored paired differences as requested_left minus requested_right."""
    result = dict(statistic)
    if reverse:
        result["mean_difference"] = -cast(float, result["mean_difference"])
        result["wins"], result["losses"] = result["losses"], result["wins"]
        result["win_rate"], result["loss_rate"] = (
            result["loss_rate"],
            result["win_rate"],
        )
        interval = cast(list[float], result["bootstrap_95_percentile_ci"])
        result["bootstrap_95_percentile_ci"] = [-interval[1], -interval[0]]
    return result


def _paired_fusion_baseline_results(
    comparison: Mapping[str, object], *, fusion_names: Sequence[str]
) -> dict[str, object]:
    all_pairs = _object(comparison.get("paired_comparisons"), "paired comparisons")
    result: dict[str, object] = {}
    for fusion_name in fusion_names:
        baselines: dict[str, object] = {}
        for baseline in ("popularity", "two_tower"):
            forward = f"{fusion_name}_minus_{baseline}"
            reverse = f"{baseline}_minus_{fusion_name}"
            pair = _object(
                all_pairs.get(forward, all_pairs.get(reverse)), "paired result"
            )
            reverse_order = forward not in all_pairs
            by_k: dict[str, object] = {}
            for k in _K_VALUES:
                metrics = _object(pair.get(str(k)), "paired K metrics")
                selected: dict[str, object] = {}
                for metric in ("ndcg", "recall"):
                    selected[metric] = _orient_paired_statistic(
                        _object(metrics.get(metric), "paired metric"),
                        reverse=reverse_order,
                    )
                by_k[str(k)] = selected
            baselines[baseline] = by_k
        result[fusion_name] = baselines
    return result


def _cohort_output_counts(
    rankings_by_model: Mapping[str, Mapping[str, Sequence[str]]],
    cohort: ValidationCohort,
) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, rankings in rankings_by_model.items():
        by_k: dict[str, object] = {}
        for k in _K_VALUES:
            lists = [rankings[user][:k] for user in sorted(cohort.targets_by_user)]
            placements = sum(map(len, lists))
            target_hit_users = sum(
                bool(set(ranked) & cohort.targets_by_user[user])
                for user, ranked in zip(
                    sorted(cohort.targets_by_user), lists, strict=True
                )
            )
            by_k[str(k)] = {
                "recommendation_count": placements,
                "mean_final_list_length": placements / len(lists) if lists else None,
                "users_receiving_any_recommendation": sum(
                    bool(items) for items in lists
                ),
                "users_with_at_least_one_relevant_item": target_hit_users,
                "users_short_of_k": sum(len(items) < k for items in lists),
            }
        result[name] = by_k
    return result


def _code_provenance(root: Path) -> dict[str, object]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source_names = (
        "packages/recfusion_ml/evaluation/fusion_pilot.py",
        "packages/recfusion_ml/evaluation/fusion.py",
        "packages/recfusion_ml/ranking/rrf.py",
        "packages/recfusion_ml/evaluation/model_comparison.py",
    )
    return {
        "git_commit": commit,
        "working_tree_dirty": bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        ),
        "working_tree_source_sha256": {
            name: _sha256_file(root / name)[0] for name in source_names
        },
    }


def run_fusion_pilot(
    *,
    preprocessing_dir: Path,
    temporal_dir: Path,
    output_dir: Path,
) -> dict[str, object]:
    """Rank top-100 source lists, evaluate two fixed RRF variants, save aggregates."""
    run_started = time.perf_counter()
    memory_at_start = _memory_status()
    tracemalloc.start()
    root = Path(__file__).resolve().parents[3]
    processed = (root / "data" / "processed").resolve()
    output_dir = output_dir.resolve()
    if processed not in output_dir.parents:
        raise ValueError("Fusion output must be inside ignored data/processed.")
    if output_dir.exists():
        raise ValueError("Fusion output directory exists; refusing to overwrite it.")

    source_inventory = _check_source_inventory(root, processed)
    data = load_trusted_pilot_data(preprocessing_dir, temporal_dir)
    cohort = build_validation_cohort(
        data.train_events, data.validation_events, data.candidate_items
    )
    if (
        len(data.train_events) != 81_688
        or len({event.user_key for event in data.train_events}) != 10_000
        or len(data.validation_events) != 6_760
        or len(data.candidate_items) != 45_331
        or cohort.users_with_evaluable_targets != 1_369
        or cohort.eligible_positive_target_count != 1_911
    ):
        raise ValueError("Trusted inputs differ from the frozen 10,000-user cohort.")
    users = sorted(cohort.targets_by_user)
    reports = {
        name: _read_report(processed / path) for name, path in _SOURCE_REPORTS.items()
    }
    lineage = _validate_shared_lineage(data, reports)
    source_report_hashes = {
        name: _sha256_file(processed / path)[0]
        for name, path in _SOURCE_REPORTS.items()
    }
    source_rankings: dict[str, dict[str, tuple[str, ...]]] = {}
    source_generation_seconds: dict[str, float] = {}

    started = time.perf_counter()
    popularity = PopularityRecommender.fit(data.train_events, data.candidate_items)
    source_rankings["popularity"] = {
        user: popularity.recommend(
            seen_items=cohort.seen_items_by_user[user], k=_SOURCE_DEPTH
        )
        for user in users
    }
    source_generation_seconds["popularity"] = time.perf_counter() - started
    _validate_rankings(
        source_rankings["popularity"],
        users=users,
        cohort=cohort,
        candidate_items=data.candidate_items,
    )
    _assert_saved_metrics(
        "popularity",
        source_rankings["popularity"],
        cohort,
        data.candidate_items,
        _object(reports["popularity"].get("metrics"), "popularity metrics"),
    )

    started = time.perf_counter()
    item_cf_report = reports["item_cf"]
    item_cf_config = _object(
        item_cf_report.get("similarity_configuration"), "item-CF configuration"
    )
    item_cf = ItemBasedCollaborativeFilter.fit(data.train_events, data.candidate_items)
    if any(
        item_cf_config.get(field) != expected
        for field, expected in (
            ("method", "cosine over binary user-item indicators"),
            ("minimum_shared_users", item_cf.config.min_shared_users),
            ("maximum_neighbors_per_item", item_cf.config.max_neighbors_per_item),
            (
                "maximum_positive_history_items",
                item_cf.config.max_positive_history_items,
            ),
        )
    ):
        raise ValueError("Saved item-CF configuration differs from implementation.")
    source_rankings["item_cf"] = {
        user: item_cf.recommend(user, k=_SOURCE_DEPTH).items for user in users
    }
    source_generation_seconds["item_cf"] = time.perf_counter() - started
    _validate_rankings(
        source_rankings["item_cf"],
        users=users,
        cohort=cohort,
        candidate_items=data.candidate_items,
    )
    item_cf_comparison = _object(item_cf_report.get("comparison"), "item-CF comparison")
    _assert_saved_metrics(
        "item-CF",
        source_rankings["item_cf"],
        cohort,
        data.candidate_items,
        {
            k: _object(item_cf_comparison.get(k), f"item-CF K={k}").get("item_cf")
            for k in map(str, _K_VALUES)
        },
    )

    started = time.perf_counter()
    bpr_report = reports["bpr"]
    bpr_checkpoint = processed / _SOURCE_REPORTS["bpr"].parent / "bpr-best.pt"
    bpr_selection = _object(bpr_report.get("selection"), "BPR selection")
    bpr_checkpoint_sha, bpr_checkpoint_size = _sha256_file(bpr_checkpoint)
    if (
        bpr_selection.get("checkpoint") != bpr_checkpoint.name
        or bpr_selection.get("epoch") != 13
        or bpr_selection.get("checkpoint_sha256") != bpr_checkpoint_sha
        or bpr_selection.get("checkpoint_size_bytes") != bpr_checkpoint_size
        or bpr_selection.get("checkpoint_reload_rankings_identical") is not True
    ):
        raise ValueError("BPR checkpoint does not match its saved report.")
    bpr = load_checkpoint(bpr_checkpoint, repository_root=root)
    bpr_config = _object(bpr_report.get("configuration"), "BPR configuration")
    if any(
        bpr_config.get(field) != getattr(bpr.config, field)
        for field in (
            "embedding_dim",
            "epochs",
            "batch_size",
            "learning_rate",
            "regularization",
            "seed",
            "negative_sampling_retries",
        )
    ):
        raise ValueError("BPR checkpoint configuration differs from its report.")
    expected_bpr = TrainingData.from_events(
        data.train_events, source_artifact_fingerprints=(lineage["train_sha256"],)
    )
    if (
        bpr.data.training_fingerprint != expected_bpr.training_fingerprint
        or bpr.data.user_ids != expected_bpr.user_ids
        or bpr.data.item_ids != expected_bpr.item_ids
        or bpr.data.seen_items_by_user != expected_bpr.seen_items_by_user
        or bpr.data.source_artifact_fingerprints != (lineage["train_sha256"],)
    ):
        raise ValueError("BPR train state differs from trusted training artifacts.")
    source_rankings["bpr"] = bpr.recommend_many(users, k=_SOURCE_DEPTH)
    source_generation_seconds["bpr"] = time.perf_counter() - started
    _validate_rankings(
        source_rankings["bpr"],
        users=users,
        cohort=cohort,
        candidate_items=data.candidate_items,
    )
    _assert_saved_metrics(
        "BPR",
        source_rankings["bpr"],
        cohort,
        data.candidate_items,
        _object(
            _object(bpr_report.get("metrics"), "BPR metrics").get("bpr"), "BPR metrics"
        ),
    )

    started = time.perf_counter()
    two_tower_report_path = processed / _SOURCE_REPORTS["two_tower"]
    two_tower_checkpoint = two_tower_report_path.parent / "two-tower-best.pt"
    two_tower, verified_report, two_tower_lineage = _validate_run(
        data, two_tower_checkpoint, two_tower_report_path
    )
    if verified_report != reports["two_tower"]:
        raise ValueError("Two-Tower report changed during validation.")
    two_tower_selection = _object(
        reports["two_tower"].get("selection"), "Two-Tower selection"
    )
    if two_tower_selection.get("epoch") != 2:
        raise ValueError(
            "Saved Two-Tower checkpoint is not the validation-selected epoch 2."
        )
    two_tower_architecture = _object(
        reports["two_tower"].get("architecture"), "Two-Tower architecture"
    )
    if any(
        two_tower_architecture.get(field) != expected
        for field, expected in (
            ("embedding_dim", two_tower.config.embedding_dim),
            ("hidden_dims", list(two_tower.config.hidden_dims)),
            ("history_length_limit", two_tower.config.max_history_items),
            ("retrieval_dim", two_tower.config.retrieval_dim),
        )
    ):
        raise ValueError("Two-Tower checkpoint configuration differs from its report.")
    source_rankings["two_tower"] = two_tower.recommend_many(users, k=_SOURCE_DEPTH)
    source_generation_seconds["two_tower"] = time.perf_counter() - started
    _validate_rankings(
        source_rankings["two_tower"],
        users=users,
        cohort=cohort,
        candidate_items=data.candidate_items,
    )
    _assert_saved_metrics(
        "Two-Tower",
        source_rankings["two_tower"],
        cohort,
        data.candidate_items,
        _object(
            _object(reports["two_tower"].get("metrics"), "Two-Tower metrics").get(
                "two_tower"
            ),
            "Two-Tower metrics",
        ),
    )

    configs = {
        name: RRFConfig(
            rank_constant=60,
            source_weights=weights,
            source_depths={source: _SOURCE_DEPTH for source in weights},
        )
        for name, weights in _CONFIGURATIONS.items()
    }
    fusion_started = time.perf_counter()
    fused_results = {
        name: _fuse_users(
            source_rankings,
            users=users,
            cohort=cohort,
            config=config,
        )
        for name, config in configs.items()
    }
    replay_results = {
        name: _fuse_users(
            source_rankings,
            users=users,
            cohort=cohort,
            config=config,
        )
        for name, config in configs.items()
    }
    deterministic_replay = fused_results == replay_results
    if not deterministic_replay:
        raise ValueError(
            "Repeated fusion of identical in-memory source lists differed."
        )
    fusion_seconds = time.perf_counter() - fusion_started
    fusion_rankings = {
        name: {user: result.recommended_items for user, result in results.items()}
        for name, results in fused_results.items()
    }

    ranking_sets: dict[str, Mapping[str, Sequence[str]]] = {
        **source_rankings,
        **fusion_rankings,
    }
    evaluation_started = time.perf_counter()
    comparison = compare_rankings(
        cohort,
        ranking_sets,
        candidate_items=data.candidate_items,
        ks=_K_VALUES,
        bootstrap_resamples=_BOOTSTRAP_RESAMPLES,
        bootstrap_seed=_BOOTSTRAP_SEED,
        personalization_users=_PERSONALIZATION_SAMPLE,
    )
    evaluation_seconds = time.perf_counter() - evaluation_started
    _comparison_models = _object(comparison.get("models"), "comparison models")
    fusion_summaries = {
        name: _fusion_diagnostics_json(
            summarize_fusion(
                results,
                candidate_items=data.candidate_items,
                ks=_K_VALUES,
            )
        )
        for name, results in fused_results.items()
    }
    cohort_outputs = _cohort_output_counts(ranking_sets, cohort)
    source_candidate_statistics: dict[str, object] = {}
    for source, source_lists in source_rankings.items():
        union: set[str] = set()
        lengths = [len(items) for items in source_lists.values()]
        for items in source_lists.values():
            union.update(items)
        source_candidate_statistics[source] = {
            "raw_generated_items": sum(lengths),
            "mean_raw_list_length": sum(lengths) / len(lengths) if lengths else None,
            "users_with_fewer_than_source_depth": sum(
                length < _SOURCE_DEPTH for length in lengths
            ),
            "distinct_eligible_source_items_union": len(union),
            "source_union_coverage": len(union) / len(data.candidate_items),
        }

    baseline_metric_validation_seconds = 0.0
    for name, saved_report in reports.items():
        started = time.perf_counter()
        if name == "item_cf":
            item_metrics = _object(saved_report.get("comparison"), "item-CF comparison")
            saved = {
                k: _object(item_metrics.get(k), f"item-CF K={k}").get("item_cf")
                for k in map(str, _K_VALUES)
            }
        elif name == "bpr":
            saved = _object(
                _object(saved_report.get("metrics"), "BPR metrics").get("bpr"),
                "BPR metrics",
            )
        elif name == "two_tower":
            saved = _object(
                _object(saved_report.get("metrics"), "Two-Tower metrics").get(
                    "two_tower"
                ),
                "Two-Tower metrics",
            )
        else:
            saved = _object(saved_report.get("metrics"), "popularity metrics")
        _assert_saved_metrics(
            name,
            source_rankings[name],
            cohort,
            data.candidate_items,
            saved,
        )
        baseline_metric_validation_seconds += time.perf_counter() - started
    standalone_reports = {
        name: _object(_comparison_models[name], f"{name} metrics")
        for name in _SOURCE_REPORTS
    }
    fusion_reports = {
        name: _object(_comparison_models[name], f"{name} metrics")
        for name in _CONFIGURATIONS
    }
    metrics_comparison = _metric_differences(comparison, names=tuple(_CONFIGURATIONS))
    paired_comparisons = _paired_fusion_baseline_results(
        comparison, fusion_names=tuple(_CONFIGURATIONS)
    )

    temporal_hash, _ = _sha256_file(data.temporal_dir / "manifest.json")
    preprocessing_hash, _ = _sha256_file(data.preprocessing_dir / "manifest.json")
    checkpoint_hashes = {
        "bpr": bpr_checkpoint_sha,
        "two_tower": two_tower_lineage["checkpoint_sha256"],
    }
    peak_traced_bytes = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    comparison_uncertainty = _object(comparison.get("uncertainty"), "uncertainty")
    report: dict[str, object] = {
        "report_schema_version": "recfusion.amazon-electronics-fusion-pilot.v1",
        "experiment": "amazon-electronics-pilot-10000-rank-fusion-v1",
        "status": "complete",
        "protocol": {
            "evaluation_split": "validation only",
            "test_rows_parsed_or_evaluated": False,
            "positive_min_rating": "4",
            "cohort_users": 1_369,
            "eligible_positive_target_pairs": 1_911,
            "candidate_pool": "exact train-known Step 2.5 item pool",
            "candidate_pool_item_count": len(data.candidate_items),
            "seen_item_policy": "exclude every train-observed user-item pair",
            "vocabulary_and_model_fitting": "train split only; no fitting performed",
            "metadata": "unavailable; no product metadata joined",
            "final_k": list(_K_VALUES),
            "source_depth": _SOURCE_DEPTH,
            "source_score_normalization": "none; ranks only",
            "per_user_rankings_persisted": False,
            "source_csvs_opened_this_step": False,
            "test_rows_hash_checked_without_parsing": True,
        },
        "dataset": {
            "train_interactions": len(data.train_events),
            "train_users": len({event.user_key for event in data.train_events}),
            "train_known_items": len(data.candidate_items),
            "validation_interactions": len(data.validation_events),
            "source_inventory": source_inventory,
            "artifact_hashes": {
                "preprocessing_manifest_sha256": preprocessing_hash,
                "temporal_manifest_sha256": temporal_hash,
                "preprocessing_output_sha256": _manifest_output_hashes(
                    data.preprocessing
                ),
                "temporal_output_sha256": {
                    name: cast(str, record["sha256"])
                    for name, record in sorted(data.temporal_outputs.items())
                },
                "train_sha256": lineage["train_sha256"],
                "validation_sha256": lineage["validation_sha256"],
                "test_sha256_verified_without_parsing": lineage[
                    "test_sha256_verified_without_parsing"
                ],
            },
        },
        "checkpoints": {
            "bpr": {
                "sha256": checkpoint_hashes["bpr"],
                "size_bytes": bpr_checkpoint_size,
                "selected_epoch": bpr_selection["epoch"],
                "configuration": bpr_config,
                "train_fingerprint_verified": True,
            },
            "two_tower": {
                "sha256": checkpoint_hashes["two_tower"],
                "size_bytes": _sha256_file(two_tower_checkpoint)[1],
                "selected_epoch": two_tower_selection["epoch"],
                "configuration": two_tower_architecture,
                "train_history_rebuilt_and_verified": True,
            },
        },
        "source_reports_sha256": source_report_hashes,
        "selection_caveat": (
            "BPR epoch 13 and Two-Tower epoch 2 were selected using this "
            "validation cohort; comparisons are exploratory and conditional "
            "on those checkpoints."
        ),
        "configurations": {
            name: {
                "weights": weights,
                "rank_constant": 60,
                "source_depth": _SOURCE_DEPTH,
                "active_models": list(weights),
                "metrics_by_k": fusion_reports[name],
                "candidate_union_and_attribution": fusion_summaries[name],
            }
            for name, weights in _CONFIGURATIONS.items()
        },
        "standalone_models": standalone_reports,
        "cohort_output_counts": cohort_outputs,
        "source_candidate_statistics": source_candidate_statistics,
        "fusion_vs_standalone_metric_differences": metrics_comparison,
        "paired_fusion_vs_popularity_and_two_tower": paired_comparisons,
        "paired_analysis": {
            "method": comparison_uncertainty["method"],
            "resamples": _BOOTSTRAP_RESAMPLES,
            "seed": _BOOTSTRAP_SEED,
            "confidence_level": comparison_uncertainty["confidence_level"],
            "limitations": (
                "Exploratory paired user bootstrap intervals are conditional on "
                "validation-selected checkpoints and do not remove model-selection "
                "optimism or account for broader hypothesis multiplicity."
            ),
        },
        "verification": {
            "all_four_baseline_metrics_reproduced": True,
            "source_lists_unique_pool_valid_and_train_seen_free": True,
            "all_source_row_counts_reconciled": True,
            "fusion_replay_from_identical_source_lists_equal": deterministic_replay,
            "fusion_semantics_changed": False,
            "fallback_added": False,
            "test_rows_parsed_or_evaluated": False,
        },
        "resources": {
            "source_ranking_generation_seconds_by_model": source_generation_seconds,
            "fusion_seconds_including_deterministic_replay": fusion_seconds,
            "offline_evaluation_and_bootstrap_seconds": evaluation_seconds,
            "baseline_metric_revalidation_seconds": baseline_metric_validation_seconds,
            "total_wall_time_seconds": time.perf_counter() - run_started,
            "peak_process_working_set_bytes": _peak_working_set_bytes(),
            "peak_traced_python_allocation_bytes": peak_traced_bytes,
            "memory_status_at_startup_bytes": memory_at_start,
        },
        "provenance": {
            **lineage,
            **source_inventory,
            "source_reports_sha256": source_report_hashes,
            "bpr_checkpoint_sha256": checkpoint_hashes["bpr"],
            "two_tower_checkpoint_sha256": checkpoint_hashes["two_tower"],
            "code": _code_provenance(root),
            "comparison_code_commit": _object(
                reports["bpr"].get("configuration"), "BPR configuration"
            ).get("code_commit"),
        },
        "output_privacy": {
            "contains_user_ids": False,
            "contains_item_ids": False,
            "contains_reviews": False,
            "contains_row_level_metrics_or_rankings": False,
            "aggregate_only": True,
        },
    }
    output_dir.mkdir(parents=True)
    report_path = output_dir / "fusion-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    report_hash, report_size = _sha256_file(report_path)
    return {
        **report,
        "report_path": str(report_path.relative_to(root)),
        "report_sha256": report_hash,
        "report_size_bytes": report_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
        "--output-dir",
        type=Path,
        default=Path("data/processed/amazon-electronics-pilot-10000-fusion-v1"),
    )
    args = parser.parse_args()
    report = run_fusion_pilot(
        preprocessing_dir=args.preprocessing_dir,
        temporal_dir=args.temporal_dir,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "report": report["report_path"],
                "report_sha256": report["report_sha256"],
                "cohort": {"users": 1_369, "targets": 1_911, "items": 45_331},
                "configurations": list(_CONFIGURATIONS),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
