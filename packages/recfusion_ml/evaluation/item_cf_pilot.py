"""Compare item-CF with the saved popularity baseline on one trusted cohort."""

from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from recfusion_ml.baselines.item_cf import ItemBasedCollaborativeFilter
from recfusion_ml.baselines.popularity import PopularityRecommender
from recfusion_ml.evaluation.metrics import (
    RankingMetrics,
    build_validation_cohort,
    evaluate_rankings,
)
from recfusion_ml.evaluation.pilot import (
    _repository_root,
    _sha256_file,
    load_trusted_pilot_data,
)

_POPULARITY_REPORT_SCHEMA = "recfusion.popularity-evaluation-report.v1"
_METRIC_FIELDS = ("recall", "ndcg", "hit_rate", "mrr", "candidate_coverage")
_SAVED_METRIC_FIELDS = (
    *_METRIC_FIELDS,
    "unique_recommended_items",
    "recommendation_count",
)


def _read_popularity_report(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Cannot read the aggregate popularity report.") from error
    if (
        not isinstance(value, dict)
        or value.get("report_schema_version") != _POPULARITY_REPORT_SCHEMA
    ):
        raise ValueError("Unsupported or malformed popularity report.")
    return cast(dict[str, object], value)


def _validate_popularity_reference(
    report: Mapping[str, object],
    *,
    source: object,
    temporal_manifest_sha256: str,
    train_sha256: object,
    validation_sha256: object,
    candidate_count: int,
    evaluated_users: int,
    eligible_targets: int,
    ks: Sequence[int],
) -> Mapping[str, object]:
    protocol = report.get("protocol")
    provenance = report.get("provenance")
    counts = report.get("counts")
    metrics = report.get("metrics")
    if not all(
        isinstance(value, dict) for value in (protocol, provenance, counts, metrics)
    ):
        raise ValueError(
            "Popularity report is missing protocol, provenance, or metrics."
        )
    protocol = cast(dict[str, object], protocol)
    provenance = cast(dict[str, object], provenance)
    counts = cast(dict[str, object], counts)
    metrics = cast(dict[str, object], metrics)
    if (
        report.get("source") != source
        or protocol.get("evaluation_split") != "validation only"
        or protocol.get("test_rows_parsed_or_evaluated") is not False
        or protocol.get("catalog_size") != candidate_count
        or protocol.get("positive_min_rating") != "4"
        or protocol.get("seen_train_items_excluded") is not True
        or protocol.get("ks") != list(ks)
        or provenance.get("temporal_manifest_sha256") != temporal_manifest_sha256
        or provenance.get("train_sha256") != train_sha256
        or provenance.get("validation_sha256") != validation_sha256
        or counts.get("evaluated_users") != evaluated_users
        or counts.get("eligible_positive_target_pairs") != eligible_targets
    ):
        raise ValueError(
            "Popularity report does not match the validated validation cohort."
        )
    if set(metrics) != {str(k) for k in ks}:
        raise ValueError("Popularity report metric K values do not match this run.")
    return metrics


def _metric_values(metric: RankingMetrics) -> dict[str, float | int | None]:
    values = {field: getattr(metric, field) for field in _METRIC_FIELDS}
    values["unique_recommended_items"] = metric.unique_recommended_items
    values["recommendation_count"] = metric.recommendation_count
    return values


def evaluate_item_cf_pilot(
    *,
    preprocessing_dir: Path,
    temporal_dir: Path,
    popularity_report_path: Path,
    output_dir: Path,
    ks: Sequence[int] = (5, 10, 20),
) -> dict[str, object]:
    """Run pure item-CF and compare it against a matching saved B0 report."""
    if not ks or any(
        isinstance(k, bool) or not isinstance(k, int) or k <= 0 for k in ks
    ):
        raise ValueError("K values must be positive integers.")
    if len(set(ks)) != len(ks):
        raise ValueError("K values must be unique.")

    started = time.perf_counter()
    tracemalloc.start()
    repository_root = _repository_root()
    processed_root = (repository_root / "data" / "processed").resolve()
    output_dir = output_dir.resolve()
    popularity_report_path = popularity_report_path.resolve()
    if processed_root not in output_dir.parents:
        raise ValueError("Output directory must be under ignored data/processed.")
    if output_dir.exists():
        raise ValueError("Output directory already exists; refusing to overwrite it.")
    if processed_root not in popularity_report_path.parents:
        raise ValueError("Popularity reference must be a local data/processed report.")
    if not popularity_report_path.is_file():
        raise ValueError("Popularity reference report is missing.")

    data = load_trusted_pilot_data(preprocessing_dir, temporal_dir)
    temporal_manifest_sha256, _ = _sha256_file(data.temporal_dir / "manifest.json")
    popularity_report = _read_popularity_report(popularity_report_path)
    cohort = build_validation_cohort(
        data.train_events, data.validation_events, data.candidate_items
    )
    reference_metrics = _validate_popularity_reference(
        popularity_report,
        source=data.temporal.get("source"),
        temporal_manifest_sha256=temporal_manifest_sha256,
        train_sha256=data.temporal_outputs["interactions.train.jsonl"].get("sha256"),
        validation_sha256=data.temporal_outputs["interactions.validation.jsonl"].get(
            "sha256"
        ),
        candidate_count=len(data.candidate_items),
        evaluated_users=cohort.users_with_evaluable_targets,
        eligible_targets=cohort.eligible_positive_target_count,
        ks=ks,
    )

    popularity = PopularityRecommender.fit(data.train_events, data.candidate_items)
    popularity_recommendations = {
        user: popularity.recommend(
            seen_items=cohort.seen_items_by_user[user], k=max(ks)
        )
        for user in sorted(cohort.targets_by_user)
    }
    popularity_evaluation = evaluate_rankings(
        cohort,
        popularity_recommendations,
        candidate_items=data.candidate_items,
        ks=ks,
    )
    for k, metric in popularity_evaluation.metrics_by_k.items():
        saved = reference_metrics[str(k)]
        if not isinstance(saved, dict) or any(
            saved.get(field) != getattr(metric, field) for field in _SAVED_METRIC_FIELDS
        ):
            raise ValueError(
                "Recomputed popularity metrics differ from the saved report."
            )

    item_cf = ItemBasedCollaborativeFilter.fit(data.train_events, data.candidate_items)
    item_cf_recommendations = {
        user: item_cf.recommend(user, k=max(ks))
        for user in sorted(cohort.targets_by_user)
    }
    item_cf_evaluation = evaluate_rankings(
        cohort,
        {user: result.items for user, result in item_cf_recommendations.items()},
        candidate_items=data.candidate_items,
        ks=ks,
    )
    users_with_candidates = sum(
        result.candidate_count > 0 for result in item_cf_recommendations.values()
    )
    recommendation_counts_by_k = {
        str(k): {
            baseline: sum(len(rows[user]) < k for user in cohort.targets_by_user)
            for baseline, rows in (
                ("popularity", popularity_recommendations),
                (
                    "item_cf",
                    {
                        user: result.items
                        for user, result in item_cf_recommendations.items()
                    },
                ),
            )
        }
        for k in ks
    }
    comparison: dict[str, object] = {}
    for k in ks:
        popularity_metric = popularity_evaluation.metrics_by_k[k]
        item_cf_metric = item_cf_evaluation.metrics_by_k[k]
        comparison[str(k)] = {
            "popularity": _metric_values(popularity_metric),
            "item_cf": _metric_values(item_cf_metric),
            "item_cf_minus_popularity": {
                field: (
                    getattr(item_cf_metric, field) - getattr(popularity_metric, field)
                    if getattr(item_cf_metric, field) is not None
                    and getattr(popularity_metric, field) is not None
                    else None
                )
                for field in _METRIC_FIELDS
            },
        }

    peak_allocated_bytes = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    report: dict[str, object] = {
        "report_schema_version": "recfusion.item-cf-evaluation-report.v1",
        "experiment": "amazon-electronics-10k-validation-item-cf-v1",
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": data.temporal.get("source"),
        "protocol": {
            "evaluation_split": "validation only",
            "test_rows_parsed_or_evaluated": False,
            "positive_min_rating": "4",
            "interaction_signal": "binary per unique train user-item positive pair",
            "unobserved_items": "unknown; not treated as negatives",
            "candidate_pool": "exact Step 2.5 train-known item pool",
            "seen_item_policy": "exclude every train-observed user-item pair",
            "scoring": "sum of binary cosine similarities from positive train history",
            "ks": list(ks),
        },
        "similarity_configuration": {
            "method": "cosine over binary user-item indicators",
            "minimum_shared_users": item_cf.config.min_shared_users,
            "maximum_neighbors_per_item": item_cf.config.max_neighbors_per_item,
            "maximum_positive_history_items": (
                item_cf.config.max_positive_history_items
            ),
            "history_cap_order": (
                "train positive-user-count descending, then item key ascending"
            ),
            "single_shared_user_pairs": "discarded by minimum-support rule",
            "popularity_fallback": "none; pure item-CF results only",
        },
        "provenance": {
            "temporal_manifest_sha256": temporal_manifest_sha256,
            "popularity_report_sha256": _sha256_file(popularity_report_path)[0],
            "train_sha256": data.temporal_outputs["interactions.train.jsonl"]["sha256"],
            "validation_sha256": data.temporal_outputs["interactions.validation.jsonl"][
                "sha256"
            ],
            "test_sha256_verified_without_parsing": data.temporal_outputs[
                "interactions.test.jsonl"
            ]["sha256"],
        },
        "integrity": {
            "evaluation_eligible": True,
            "blocking_violations": {},
            "source_split_membership_changed": 0,
        },
        "counts": {
            "source_split_records": {
                split: data.temporal_outputs[f"interactions.{split}.jsonl"]["records"]
                for split in ("train", "validation", "test")
            },
            "parsed_records": {
                "train": len(data.train_events),
                "validation": len(data.validation_events),
            },
            "candidate_pool_items": len(data.candidate_items),
            "validation_users": cohort.validation_user_count,
            "evaluated_users": cohort.users_with_evaluable_targets,
            "eligible_positive_target_pairs": cohort.eligible_positive_target_count,
            "training_users_with_positive_history": (
                item_cf.fit_summary.users_with_positive_history
            ),
            "training_users_without_positive_history": (
                len({event.user_key for event in data.train_events})
                - item_cf.fit_summary.users_with_positive_history
            ),
            "positive_observations": item_cf.fit_summary.positive_observation_count,
            "unique_positive_user_item_pairs": (
                item_cf.fit_summary.unique_positive_user_item_pairs
            ),
            "repeated_positive_observations_collapsed_to_binary": (
                item_cf.fit_summary.repeated_positive_observations_collapsed
            ),
            "users_truncated_by_history_cap": item_cf.fit_summary.truncated_user_count,
            "positive_items_excluded_by_history_cap": (
                item_cf.fit_summary.truncated_positive_item_count
            ),
            "sparse_cooccurrence_pairs": item_cf.fit_summary.cooccurrence_pair_count,
            "pairs_meeting_minimum_support": (
                item_cf.fit_summary.supported_similarity_pair_count
            ),
            "retained_directed_neighbor_edges": (
                item_cf.fit_summary.retained_neighbor_edges
            ),
            "users_with_generated_candidates": users_with_candidates,
            "users_without_generated_candidates": (
                cohort.users_with_evaluable_targets - users_with_candidates
            ),
            "candidate_generation_user_coverage": (
                users_with_candidates / cohort.users_with_evaluable_targets
                if cohort.users_with_evaluable_targets
                else None
            ),
            "generated_candidate_count_sum": sum(
                result.candidate_count for result in item_cf_recommendations.values()
            ),
            "fallback_users": 0,
            "users_receiving_fewer_than_k_results": recommendation_counts_by_k,
        },
        "comparison": comparison,
        "resources": {
            "wall_time_seconds": round(time.perf_counter() - started, 3),
            "peak_tracemalloc_bytes": peak_allocated_bytes,
            "process_peak_rss": "not measured by this runner",
        },
    }
    output_dir.mkdir(parents=True)
    report_path = output_dir / "item-cf-report.json"
    try:
        report_path.write_text(
            json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except OSError:
        report_path.unlink(missing_ok=True)
        output_dir.rmdir()
        raise
    return report


def _arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare sparse item-CF with a matching saved popularity report on "
            "trusted Step 2.5 validation artifacts."
        )
    )
    parser.add_argument("--preprocessing-dir", type=Path, required=True)
    parser.add_argument("--temporal-dir", type=Path, required=True)
    parser.add_argument("--popularity-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ks", type=int, nargs="+", default=(5, 10, 20))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments().parse_args(argv)
    try:
        report = evaluate_item_cf_pilot(
            preprocessing_dir=args.preprocessing_dir,
            temporal_dir=args.temporal_dir,
            popularity_report_path=args.popularity_report,
            output_dir=args.output_dir,
            ks=args.ks,
        )
    except (OSError, ValueError) as error:
        print(f"Item-CF evaluation failed: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir.resolve()),
                "evaluated_users": cast(dict[str, object], report["counts"])[
                    "evaluated_users"
                ],
                "comparison": report["comparison"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
