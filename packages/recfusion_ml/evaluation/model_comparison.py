"""Paired, aggregate-only comparison of saved validation recommendations."""

from __future__ import annotations

import hashlib
import json
import random
import time
from collections import Counter
from collections.abc import Mapping, Sequence, Set
from itertools import combinations
from math import log2
from pathlib import Path
from typing import cast

from recfusion_ml.baselines.item_cf import ItemBasedCollaborativeFilter
from recfusion_ml.baselines.popularity import PopularityRecommender
from recfusion_ml.evaluation.metrics import (
    ValidationCohort,
    build_validation_cohort,
    evaluate_rankings,
)
from recfusion_ml.evaluation.pilot import (
    TrustedPilotData,
    _sha256_file,
    load_trusted_pilot_data,
)
from recfusion_ml.evaluation.two_tower_diagnostics import _validate_run
from recfusion_ml.training.bpr import TrainingData, load_checkpoint

_METRICS = ("recall", "ndcg", "hit_rate", "mrr")
_K_VALUES = (5, 10, 20)


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"Saved {label} is malformed.")
    return cast(dict[str, object], value)


def _read_report(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return _object(value, "model report")


def _validate_shared_lineage(
    data: TrustedPilotData, reports: Mapping[str, dict[str, object]]
) -> dict[str, str]:
    temporal_manifest_sha, _ = _sha256_file(data.temporal_dir / "manifest.json")
    preprocessing_manifest_sha, _ = _sha256_file(
        data.preprocessing_dir / "manifest.json"
    )
    expected = {
        "train_sha256": cast(
            str, data.temporal_outputs["interactions.train.jsonl"]["sha256"]
        ),
        "validation_sha256": cast(
            str, data.temporal_outputs["interactions.validation.jsonl"]["sha256"]
        ),
        "temporal_manifest_sha256": temporal_manifest_sha,
    }
    for name, report in reports.items():
        provenance = _object(report.get("provenance"), f"{name} provenance")
        if any(provenance.get(key) != value for key, value in expected.items()):
            raise ValueError(f"Saved {name} report does not match trusted inputs.")
        reported_test_sha = provenance.get("test_sha256_verified_without_parsing")
        if (
            reported_test_sha is not None
            and reported_test_sha
            != data.temporal_outputs["interactions.test.jsonl"]["sha256"]
        ):
            raise ValueError(f"Saved {name} report test fingerprint differs.")
        protocol = _object(report.get("protocol"), f"{name} protocol")
        candidate_policy = protocol.get(
            "candidate_pool", protocol.get("candidate_universe")
        )
        seen_policy = protocol.get("seen_item_policy")
        seen_policy_matches = (
            seen_policy == "exclude every train-observed user-item pair"
            or (
                seen_policy is None
                and protocol.get("seen_train_items_excluded") is True
            )
        )
        if (
            protocol.get("evaluation_split") != "validation only"
            or protocol.get("test_rows_parsed_or_evaluated") is not False
            or candidate_policy
            not in {
                "exact Step 2.5 train-known item pool",
                "exact train-known Step 2.5 item pool",
                "train-known items from Step 2.5 candidate pool",
            }
            or not seen_policy_matches
            or protocol.get("positive_min_rating") != "4"
            or protocol.get("ks") != list(_K_VALUES)
        ):
            raise ValueError(f"Saved {name} evaluation protocol differs.")
    return {
        **expected,
        "preprocessing_manifest_sha256": preprocessing_manifest_sha,
        "test_sha256_verified_without_parsing": cast(
            str, data.temporal_outputs["interactions.test.jsonl"]["sha256"]
        ),
    }


def _assert_saved_metrics(
    name: str,
    rankings: Mapping[str, Sequence[str]],
    cohort: ValidationCohort,
    candidate_items: Set[str],
    saved: Mapping[str, object],
) -> None:
    measured = evaluate_rankings(
        cohort, rankings, candidate_items=candidate_items, ks=_K_VALUES
    )
    for k in _K_VALUES:
        expected = _object(saved.get(str(k)), f"{name} K={k} metrics")
        result = measured.metrics_by_k[k]
        for metric in (
            *_METRICS,
            "candidate_coverage",
            "unique_recommended_items",
            "recommendation_count",
        ):
            if expected.get(metric) != getattr(result, metric):
                raise ValueError(
                    f"Recomputed {name} {metric}@{k} differs from saved report."
                )


def run_four_model_comparison(
    *,
    preprocessing_dir: Path,
    temporal_dir: Path,
    output_dir: Path,
) -> dict[str, object]:
    """Reproduce four saved model rankings and write an aggregate-only report."""
    run_started = time.perf_counter()
    root = Path(__file__).resolve().parents[3]
    processed_root = (root / "data" / "processed").resolve()
    output_dir = output_dir.resolve()
    if processed_root not in output_dir.parents:
        raise ValueError("Output directory must be under ignored data/processed.")
    if output_dir.exists():
        raise ValueError("Output directory exists; refusing to overwrite it.")

    data = load_trusted_pilot_data(preprocessing_dir, temporal_dir)
    report_paths = {
        "popularity": processed_root
        / "amazon-electronics-pilot-10000-popularity-v1"
        / "aggregate-report.json",
        "item_cf": processed_root
        / "amazon-electronics-pilot-10000-itemcf-v1"
        / "item-cf-report.json",
        "bpr": processed_root
        / "amazon-electronics-pilot-10000-bpr-v1"
        / "bpr-report.json",
        "two_tower": processed_root
        / "amazon-electronics-pilot-10000-twotower-v1"
        / "two-tower-report.json",
    }
    reports = {name: _read_report(path) for name, path in report_paths.items()}
    lineage = _validate_shared_lineage(data, reports)
    cohort = build_validation_cohort(
        data.train_events, data.validation_events, data.candidate_items
    )
    if (
        cohort.users_with_evaluable_targets != 1369
        or cohort.eligible_positive_target_count != 1911
    ):
        raise ValueError("Trusted validation cohort differs from the frozen pilot.")
    users = sorted(cohort.targets_by_user)

    popularity = PopularityRecommender.fit(data.train_events, data.candidate_items)
    popularity_rankings = {
        user: popularity.recommend(
            seen_items=cohort.seen_items_by_user[user], k=max(_K_VALUES)
        )
        for user in users
    }
    popularity_report = reports["popularity"]
    _assert_saved_metrics(
        "popularity",
        popularity_rankings,
        cohort,
        data.candidate_items,
        _object(popularity_report.get("metrics"), "popularity metrics"),
    )

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
    item_cf_rankings = {
        user: item_cf.recommend(user, k=max(_K_VALUES)).items for user in users
    }
    item_cf_comparison = _object(item_cf_report.get("comparison"), "item-CF comparison")
    _assert_saved_metrics(
        "item-CF",
        item_cf_rankings,
        cohort,
        data.candidate_items,
        {
            k: _object(item_cf_comparison.get(k), f"item-CF K={k}").get("item_cf")
            for k in map(str, _K_VALUES)
        },
    )

    bpr_report = reports["bpr"]
    bpr_dir = report_paths["bpr"].parent
    bpr_checkpoint = bpr_dir / "bpr-best.pt"
    bpr_selection = _object(bpr_report.get("selection"), "BPR selection")
    bpr_checkpoint_sha, bpr_checkpoint_size = _sha256_file(bpr_checkpoint)
    if (
        bpr_selection.get("checkpoint") != bpr_checkpoint.name
        or bpr_selection.get("checkpoint_sha256") != bpr_checkpoint_sha
        or bpr_selection.get("checkpoint_size_bytes") != bpr_checkpoint_size
        or bpr_selection.get("checkpoint_reload_rankings_identical") is not True
    ):
        raise ValueError("Saved BPR checkpoint does not match its report.")
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
    expected_bpr_data = TrainingData.from_events(
        data.train_events, source_artifact_fingerprints=(lineage["train_sha256"],)
    )
    if (
        bpr.data.training_fingerprint != expected_bpr_data.training_fingerprint
        or bpr.data.user_ids != expected_bpr_data.user_ids
        or bpr.data.item_ids != expected_bpr_data.item_ids
        or bpr.data.seen_items_by_user != expected_bpr_data.seen_items_by_user
        or bpr.data.source_artifact_fingerprints != (lineage["train_sha256"],)
    ):
        raise ValueError("BPR checkpoint train state differs from trusted train data.")
    bpr_rankings = bpr.recommend_many(users, k=max(_K_VALUES))
    bpr_metrics = _object(
        _object(bpr_report.get("metrics"), "BPR metrics").get("bpr"),
        "BPR ranking metrics",
    )
    _assert_saved_metrics(
        "BPR", bpr_rankings, cohort, data.candidate_items, bpr_metrics
    )

    two_tower_report_path = report_paths["two_tower"]
    two_tower_checkpoint = two_tower_report_path.parent / "two-tower-best.pt"
    two_tower, verified_report, two_tower_lineage = _validate_run(
        data, two_tower_checkpoint, two_tower_report_path
    )
    if verified_report != reports["two_tower"]:
        raise ValueError("Two-Tower report changed during comparison.")
    two_tower_rankings = two_tower.recommend_many(users, k=max(_K_VALUES))
    two_tower_metrics = _object(
        _object(reports["two_tower"].get("metrics"), "Two-Tower metrics").get(
            "two_tower"
        ),
        "Two-Tower ranking metrics",
    )
    _assert_saved_metrics(
        "Two-Tower", two_tower_rankings, cohort, data.candidate_items, two_tower_metrics
    )

    started = time.perf_counter()
    result = compare_rankings(
        cohort,
        {
            "popularity": popularity_rankings,
            "item_cf": item_cf_rankings,
            "bpr": bpr_rankings,
            "two_tower": two_tower_rankings,
        },
        candidate_items=data.candidate_items,
        ks=_K_VALUES,
    )
    result.update(
        {
            "report_schema_version": "recfusion.four-model-validation-comparison.v1",
            "experiment": "amazon-electronics-10k-four-model-validation-comparison-v1",
            "protocol": {
                "evaluation_split": "validation only",
                "test_rows_parsed_or_evaluated": False,
                "positive_min_rating": "4",
                "candidate_pool": "exact train-known Step 2.5 item pool",
                "seen_item_policy": "exclude every train-observed user-item pair",
                "vocabulary_and_model_fitting": (
                    "train split only; no fitting performed"
                ),
                "per_user_records_persisted": False,
                "metadata": "unavailable; no product metadata joined",
            },
            "provenance": {
                **lineage,
                "source_reports_sha256": {
                    name: _sha256_file(path)[0] for name, path in report_paths.items()
                },
                "bpr_checkpoint_sha256": bpr_checkpoint_sha,
                "two_tower_checkpoint_sha256": two_tower_lineage["checkpoint_sha256"],
            },
            "model_selection": {
                "bpr_epoch": bpr_selection.get("epoch"),
                "two_tower_epoch": _object(
                    reports["two_tower"].get("selection"), "Two-Tower selection"
                ).get("epoch"),
                "warning": (
                    "Both neural checkpoints were selected on this validation "
                    "cohort; paired intervals are conditional on these selected "
                    "checkpoints and do not remove selection optimism."
                ),
            },
            "resources": {
                "analysis_wall_time_seconds": time.perf_counter() - run_started,
                "statistics_wall_time_seconds": time.perf_counter() - started,
            },
        }
    )
    output_dir.mkdir(parents=True)
    (output_dir / "four-model-comparison.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    """Run the frozen local four-model validation comparison."""
    import argparse

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
        default=Path("data/processed/amazon-electronics-pilot-10000-comparison-v1"),
    )
    args = parser.parse_args()
    result = run_four_model_comparison(
        preprocessing_dir=args.preprocessing_dir,
        temporal_dir=args.temporal_dir,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "report": str(args.output_dir / "four-model-comparison.json"),
                "cohort": result["cohort"],
                "resamples": _object(result.get("uncertainty"), "uncertainty")[
                    "resamples"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


def _user_metrics(
    cohort: ValidationCohort,
    rankings: Mapping[str, Sequence[str]],
    *,
    k: int,
) -> dict[str, dict[str, float]]:
    results: dict[str, dict[str, float]] = {}
    for user, targets in cohort.targets_by_user.items():
        hits = [item in targets for item in rankings[user][:k]]
        dcg = sum(1 / log2(rank + 2) for rank, relevant in enumerate(hits) if relevant)
        idcg = sum(1 / log2(rank + 2) for rank in range(min(k, len(targets))))
        first_hit = next(
            (rank for rank, relevant in enumerate(hits, start=1) if relevant), None
        )
        results[user] = {
            "recall": sum(hits) / len(targets),
            "ndcg": dcg / idcg,
            "hit_rate": float(any(hits)),
            "mrr": 1 / first_hit if first_hit is not None else 0.0,
        }
    return results


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    position = probability * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def _paired_statistics(
    differences: Sequence[float], *, bootstrap_resamples: int, bootstrap_seed: int
) -> dict[str, float | int | list[float]]:
    if not differences:
        raise ValueError("Paired comparison requires at least one evaluated user.")
    mean = sum(differences) / len(differences)
    wins = sum(value > 0 for value in differences)
    losses = sum(value < 0 for value in differences)
    ties = len(differences) - wins - losses
    rng = random.Random(bootstrap_seed)
    bootstrap_means = sorted(
        sum(differences[rng.randrange(len(differences))] for _ in differences)
        / len(differences)
        for _ in range(bootstrap_resamples)
    )
    return {
        "mean_difference": mean,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "win_rate": wins / len(differences),
        "loss_rate": losses / len(differences),
        "tie_rate": ties / len(differences),
        "bootstrap_95_percentile_ci": [
            _percentile(bootstrap_means, 0.025),
            _percentile(bootstrap_means, 0.975),
        ],
    }


def _concentration(
    rankings: Mapping[str, Sequence[str]],
    candidates: Set[str],
    *,
    k: int,
) -> dict[str, object]:
    counts: Counter[str] = Counter(
        item for rows in rankings.values() for item in rows[:k]
    )
    frequency = [counts[item] for item in candidates]
    placement_count = sum(frequency)
    unique_count = sum(count > 0 for count in frequency)
    entropy = (
        -sum(
            count / placement_count * log2(count / placement_count)
            for count in frequency
            if count
        )
        if placement_count
        else 0.0
    )
    normalized_entropy = entropy / log2(len(frequency)) if len(frequency) > 1 else 0.0
    ascending = sorted(frequency)
    descending = ascending[::-1]
    n = len(ascending)
    weighted_sum = sum((index + 1) * value for index, value in enumerate(ascending))
    total = sum(ascending)
    gini = (2 * weighted_sum / (n * total) - (n + 1) / n) if n and total else 0.0
    return {
        "unique_recommended_items": unique_count,
        "catalog_coverage": unique_count / len(candidates) if candidates else None,
        "recommendation_placements": placement_count,
        "normalized_shannon_entropy": normalized_entropy,
        "gini": gini,
        "top_item_placement_shares": {
            str(top): sum(descending[:top]) / placement_count
            if placement_count
            else 0.0
            for top in (1, 5, 10)
        },
    }


def _personalization_overlap(
    rankings: Mapping[str, Sequence[str]], *, k: int, seed: int, sample_size: int
) -> dict[str, float | int]:
    users = sorted(
        rankings,
        key=lambda user: (hashlib.sha256(f"{seed}:{user}".encode()).digest(), user),
    )[:sample_size]
    overlaps: list[float] = []
    for left, right in combinations(users, 2):
        left_items = set(rankings[left][:k])
        right_items = set(rankings[right][:k])
        denominator = min(len(left_items), len(right_items))
        overlaps.append(
            len(left_items & right_items) / denominator if denominator else 0.0
        )
    return {
        "sampled_users": len(users),
        "user_pairs": len(overlaps),
        "mean_overlap_of_shorter_list": sum(overlaps) / len(overlaps)
        if overlaps
        else 0.0,
    }


def compare_rankings(
    cohort: ValidationCohort,
    rankings_by_model: Mapping[str, Mapping[str, Sequence[str]]],
    *,
    candidate_items: Set[str] | None = None,
    ks: Sequence[int] = (5, 10, 20),
    bootstrap_resamples: int = 2000,
    bootstrap_seed: int = 33033,
    personalization_users: int = 128,
) -> dict[str, object]:
    """Compare models on exactly paired users, retaining no user-level output."""
    if len(rankings_by_model) < 2:
        raise ValueError("At least two model rankings are required.")
    if bootstrap_resamples < 1 or personalization_users < 1:
        raise ValueError("Resample and personalization counts must be positive.")
    pool = (
        cohort.candidate_items
        if candidate_items is None
        else frozenset(candidate_items)
    )
    users = set(cohort.targets_by_user)
    model_names = sorted(rankings_by_model)
    per_model: dict[str, dict[str, object]] = {}
    per_user_by_model: dict[str, dict[int, dict[str, dict[str, float]]]] = {}

    for model in model_names:
        rankings = rankings_by_model[model]
        if set(rankings) != users:
            raise ValueError(
                "Recommendations must be supplied for every evaluable user."
            )
        evaluations = evaluate_rankings(cohort, rankings, candidate_items=pool, ks=ks)
        per_user_by_model[model] = {k: _user_metrics(cohort, rankings, k=k) for k in ks}
        per_model[model] = {
            str(k): {
                **{
                    name: getattr(evaluations.metrics_by_k[k], name)
                    for name in _METRICS
                },
                "unique_recommended_items": evaluations.metrics_by_k[
                    k
                ].unique_recommended_items,
                "candidate_coverage": evaluations.metrics_by_k[k].candidate_coverage,
                "concentration": _concentration(rankings, pool, k=k),
                "personalization": _personalization_overlap(
                    rankings,
                    k=k,
                    seed=bootstrap_seed,
                    sample_size=personalization_users,
                ),
            }
            for k in ks
        }

    paired: dict[str, object] = {}
    for left, right in combinations(model_names, 2):
        key = f"{left}_minus_{right}"
        paired[key] = {
            str(k): {
                metric: _paired_statistics(
                    [
                        per_user_by_model[left][k][user][metric]
                        - per_user_by_model[right][k][user][metric]
                        for user in sorted(users)
                    ],
                    bootstrap_resamples=bootstrap_resamples,
                    bootstrap_seed=bootstrap_seed,
                )
                for metric in _METRICS
            }
            for k in ks
        }

    return {
        "models": per_model,
        "paired_comparisons": paired,
        "cohort": {
            "evaluated_users": len(users),
            "eligible_positive_target_pairs": cohort.eligible_positive_target_count,
            "candidate_items": len(pool),
        },
        "uncertainty": {
            "method": "paired user bootstrap percentile interval",
            "resamples": bootstrap_resamples,
            "seed": bootstrap_seed,
            "confidence_level": 0.95,
            "percentile_interpolation": "linear",
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
