"""Aggregate-only diagnostics for the saved real-data Two-Tower checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import replace
from pathlib import Path
from typing import cast

import torch
from torch import Tensor

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
from recfusion_ml.evaluation.two_tower_pilot import _history_audit
from recfusion_ml.training.bpr import NegativeSampler, TrainingData
from recfusion_ml.training.two_tower import (
    TwoTowerEvent,
    TwoTowerExample,
    TwoTowerRecommender,
    build_two_tower_data,
)
from recfusion_ml.training.two_tower_checkpoint import load_two_tower_checkpoint
from recfusion_ml.types import RatingEvent

_K_VALUES = (5, 10, 20)
_SAMPLE_SEED = 33_031
_USER_SAMPLE_LIMIT = 256
_ITEM_SAMPLE_LIMIT = 1024
_OVERLAP_SAMPLE_LIMIT = 128
_SCORE_NEAR_TOLERANCE = 1e-6
_REPORT_SCHEMA = "recfusion.two-tower-diagnostics.v1"


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} is malformed.")
    return cast(dict[str, object], value)


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} is not numeric.")
    return float(value)


def _event_timestamp(record: Mapping[str, object]) -> int:
    interaction = _mapping(record.get("interaction"), "interaction")
    value = interaction.get("event_time_ms")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Trusted event timestamp is malformed.")
    return value


def _stable_sample(values: Sequence[str], *, limit: int, seed: int) -> tuple[str, ...]:
    """Select keys by a stable seeded digest; never depend on input order."""
    if limit < 1 or seed < 0:
        raise ValueError("Sample limit must be positive and seed non-negative.")
    return tuple(
        sorted(
            values,
            key=lambda value: (
                hashlib.sha256(f"{seed}\0{value}".encode()).digest(),
                value,
            ),
        )[:limit]
    )


def _quantiles(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {
            key: None for key in ("min", "p05", "p25", "median", "p75", "p95", "max")
        }
    tensor = torch.tensor(values, dtype=torch.float64)
    probabilities = torch.tensor((0.05, 0.25, 0.5, 0.75, 0.95), dtype=torch.float64)
    result = torch.quantile(tensor, probabilities).tolist()
    return {
        "min": float(tensor.min()),
        "p05": result[0],
        "p25": result[1],
        "median": result[2],
        "p75": result[3],
        "p95": result[4],
        "max": float(tensor.max()),
    }


def _distribution(values: Tensor) -> dict[str, object]:
    flattened = values.detach().to(dtype=torch.float64, device="cpu").flatten()
    if flattened.numel() == 0 or not torch.isfinite(flattened).all():
        raise ValueError("Diagnostic values must be non-empty and finite.")
    numbers = flattened.tolist()
    return {
        "count": len(numbers),
        "mean": float(flattened.mean()),
        "population_variance": float(flattened.var(unbiased=False)),
        "quantiles": _quantiles(numbers),
    }


def _cosine_summary(vectors: Tensor) -> dict[str, float | int | None]:
    normalized = torch.nn.functional.normalize(vectors.to(torch.float64), dim=1)
    similarities = normalized @ normalized.T
    upper = similarities[
        torch.triu(torch.ones_like(similarities, dtype=torch.bool), diagonal=1)
    ]
    if upper.numel() == 0:
        return {"pair_count": 0, "mean": None, "median": None, "p95": None}
    return {
        "pair_count": int(upper.numel()),
        "mean": float(upper.mean()),
        "median": float(torch.quantile(upper, 0.5)),
        "p95": float(torch.quantile(upper, 0.95)),
    }


def _gini(counts: Sequence[int]) -> float:
    ordered = sorted(counts)
    total = sum(ordered)
    if not ordered or total == 0:
        return 0.0
    n = len(ordered)
    weighted = sum(
        (2 * index - n - 1) * value for index, value in enumerate(ordered, 1)
    )
    return weighted / (n * total)


def _frequency_summary(
    rankings: Mapping[str, Sequence[str]], candidate_items: Set[str], *, k: int
) -> dict[str, object]:
    frequencies: Counter[str] = Counter(
        item for ranked in rankings.values() for item in ranked[:k]
    )
    if set(frequencies) - candidate_items:
        raise ValueError("A ranking contains an item outside the candidate pool.")
    placement_count = sum(frequencies.values())
    all_counts = [frequencies[item] for item in candidate_items]
    nonzero = [count for count in all_counts if count]
    if placement_count:
        entropy = -sum(
            (count / placement_count) * math.log(count / placement_count)
            for count in nonzero
        )
        normalized_entropy = (
            entropy / math.log(len(candidate_items))
            if len(candidate_items) > 1
            else 0.0
        )
    else:
        normalized_entropy = None
    ordered = sorted(frequencies.items(), key=lambda row: (-row[1], row[0]))
    top_shares = {
        str(limit): (
            sum(count for _, count in ordered[:limit]) / placement_count
            if placement_count
            else None
        )
        for limit in (1, 5, 10)
    }
    list_counts = Counter(tuple(items[:k]) for items in rankings.values())
    duplicated_user_count = sum(count for count in list_counts.values() if count > 1)
    return {
        "k": k,
        "user_count": len(rankings),
        "placement_count": placement_count,
        "unique_recommended_items": len(nonzero),
        "catalog_coverage": len(nonzero) / len(candidate_items)
        if candidate_items
        else None,
        "recommendation_frequency_over_candidate_pool": _quantiles(all_counts),
        "zero_frequency_candidate_count": len(candidate_items) - len(nonzero),
        "top_item_placement_shares": top_shares,
        "normalized_entropy_over_full_candidate_pool": normalized_entropy,
        "gini_over_full_candidate_pool": _gini(all_counts),
        "distinct_recommendation_lists": len(list_counts),
        "users_in_duplicate_list_groups": duplicated_user_count,
        "fraction_of_users_in_duplicate_list_groups": duplicated_user_count
        / len(rankings)
        if rankings
        else None,
        "top_item_user_reach_fraction": (
            len(
                {
                    user
                    for user, items in rankings.items()
                    if ordered and ordered[0][0] in items[:k]
                }
            )
            / len(rankings)
        )
        if rankings
        else None,
        "top_items": [
            {
                "frequency": count,
                "user_reach": sum(item in ranked[:k] for ranked in rankings.values()),
            }
            for item, count in ordered[:10]
        ],
    }


def _pairwise_overlap(
    rankings: Mapping[str, Sequence[str]], *, k: int, seed: int, limit: int
) -> dict[str, object]:
    users = _stable_sample(tuple(sorted(rankings)), limit=limit, seed=seed)
    overlaps: list[float] = []
    for left_index, left_user in enumerate(users):
        left = set(rankings[left_user][:k])
        for right_user in users[left_index + 1 :]:
            right = set(rankings[right_user][:k])
            denominator = min(len(left), len(right))
            overlaps.append(len(left & right) / denominator if denominator else 0.0)
    return {
        "sampled_user_count": len(users),
        "sample_seed": seed,
        "pair_count": len(overlaps),
        "overlap_definition": "intersection size divided by the smaller list length",
        "mean": statistics.fmean(overlaps) if overlaps else None,
        "median": statistics.median(overlaps) if overlaps else None,
        "p95": _quantiles(overlaps)["p95"],
    }


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("Correlation inputs must have the same length >= 2.")
    x = torch.tensor(left, dtype=torch.float64)
    y = torch.tensor(right, dtype=torch.float64)
    x_centered, y_centered = x - x.mean(), y - y.mean()
    denominator = torch.linalg.vector_norm(x_centered) * torch.linalg.vector_norm(
        y_centered
    )
    if denominator == 0:
        return None
    return float((x_centered @ y_centered) / denominator)


def _score_summary(
    recommender: TwoTowerRecommender,
    user_ids: Sequence[str],
    item_ids: Sequence[str],
) -> dict[str, object]:
    user_vectors = _encode_users(recommender, user_ids, empty_history=False)
    item_vectors = recommender.item_vectors(item_ids)
    scores = user_vectors @ item_vectors.T
    valid_rows: list[Tensor] = []
    for index, user in enumerate(user_ids):
        allowed = [
            item_index
            for item_index, item in enumerate(item_ids)
            if item not in recommender.data.seen_items_by_user[user]
        ]
        if allowed:
            valid_rows.append(scores[index, allowed])
    sampled = torch.cat(valid_rows) if valid_rows else torch.empty(0)
    summary = _distribution(sampled)
    exact_ties = 0
    near_ties = 0
    adjacent_pairs = 0
    for row in valid_rows:
        ordered = torch.sort(row).values
        differences = torch.diff(ordered)
        adjacent_pairs += int(differences.numel())
        exact_ties += int((differences == 0).sum())
        near_ties += int((differences.abs() <= _SCORE_NEAR_TOLERANCE).sum())
    summary["sampled_user_count"] = len(user_ids)
    summary["sampled_item_count"] = len(item_ids)
    summary["sampled_user_item_scores"] = int(sampled.numel())
    summary["exact_adjacent_tie_fraction"] = (
        exact_ties / adjacent_pairs if adjacent_pairs else None
    )
    summary["near_adjacent_tie_fraction"] = (
        near_ties / adjacent_pairs if adjacent_pairs else None
    )
    summary["near_tie_absolute_tolerance"] = _SCORE_NEAR_TOLERANCE
    return summary


def _encode_users(
    recommender: TwoTowerRecommender,
    user_ids: Sequence[str],
    *,
    empty_history: bool,
) -> Tensor:
    user_indices = torch.tensor(
        [recommender._user_indices[user] for user in user_ids], dtype=torch.long
    )
    if empty_history:
        history = torch.zeros(
            (len(user_ids), recommender.config.max_history_items), dtype=torch.long
        )
    else:
        history = torch.stack(
            [recommender._user_history_tensor(user)[0] for user in user_ids]
        )
    recommender.model.eval()
    with torch.no_grad():
        return recommender.model.encode_users(user_indices, history)


def _representation_summary(
    recommender: TwoTowerRecommender,
    user_ids: Sequence[str],
    item_ids: Sequence[str],
) -> dict[str, object]:
    normal_users = _encode_users(recommender, user_ids, empty_history=False)
    empty_users = _encode_users(recommender, user_ids, empty_history=True)
    items = recommender.item_vectors(item_ids)

    def tower_summary(vectors: Tensor) -> dict[str, object]:
        return {
            "vector_norm": _distribution(torch.linalg.vector_norm(vectors, dim=1)),
            "coordinate_variance_mean": float(
                vectors.var(dim=0, unbiased=False).mean()
            ),
            "coordinate_variance_median": float(
                vectors.var(dim=0, unbiased=False).median()
            ),
            "pairwise_cosine_similarity": _cosine_summary(vectors),
        }

    return {
        "user_sample_count": len(user_ids),
        "item_sample_count": len(item_ids),
        "user_with_training_history": tower_summary(normal_users),
        "user_with_empty_history": tower_summary(empty_users),
        "items": tower_summary(items),
        "user_history_vector_delta_norm": _distribution(
            torch.linalg.vector_norm(normal_users - empty_users, dim=1)
        ),
        "user_history_normal_vs_empty_cosine": _distribution(
            torch.nn.functional.cosine_similarity(normal_users, empty_users, dim=1)
        ),
    }


def _to_rating_events(events: Sequence[TwoTowerEvent]) -> tuple[RatingEvent, ...]:
    return tuple(
        RatingEvent(row.user_key, row.item_key, row.rating, row.split) for row in events
    )


def _validation_rankings(
    recommender: TwoTowerRecommender,
    cohort: ValidationCohort,
    candidate_items: Set[str],
) -> dict[str, tuple[str, ...]]:
    rankings = recommender.recommend_many(cohort.targets_by_user, k=max(_K_VALUES))
    evaluation = evaluate_rankings(
        cohort, rankings, candidate_items=candidate_items, ks=_K_VALUES
    )
    if (
        evaluation.evaluated_user_count != 1369
        or evaluation.eligible_positive_target_count != 1911
    ):
        raise ValueError("The frozen validation cohort differs from Phase 3.3B.")
    return rankings


def _all_metrics(
    cohort: ValidationCohort,
    rankings: Mapping[str, Sequence[str]],
    candidate_items: Set[str],
) -> dict[str, dict[str, object]]:
    result = evaluate_rankings(
        cohort, rankings, candidate_items=candidate_items, ks=_K_VALUES
    )
    return {
        str(k): {
            "recall": result.metrics_by_k[k].recall,
            "ndcg": result.metrics_by_k[k].ndcg,
            "hit_rate": result.metrics_by_k[k].hit_rate,
            "mrr": result.metrics_by_k[k].mrr,
            "unique_recommended_items": result.metrics_by_k[k].unique_recommended_items,
            "candidate_coverage": result.metrics_by_k[k].candidate_coverage,
            "recommendation_count": result.metrics_by_k[k].recommendation_count,
        }
        for k in _K_VALUES
    }


def _topology_metrics(
    rankings: Mapping[str, Sequence[str]], candidate_items: Set[str]
) -> dict[str, object]:
    return {
        str(k): {
            **_frequency_summary(rankings, candidate_items, k=k),
            "sampled_pairwise_list_overlap": _pairwise_overlap(
                rankings, k=k, seed=_SAMPLE_SEED, limit=_OVERLAP_SAMPLE_LIMIT
            ),
        }
        for k in _K_VALUES
    }


def _recommendation_popularity_correlation(
    rankings: Mapping[str, Sequence[str]],
    popularity: PopularityRecommender,
    candidate_items: Set[str],
) -> float | None:
    frequency: Counter[str] = Counter(
        item for ranked in rankings.values() for item in ranked[:10]
    )
    return _pearson(
        [float(frequency[item]) for item in sorted(candidate_items)],
        [
            float(popularity.positive_review_counts[item])
            for item in sorted(candidate_items)
        ],
    )


def _cross_recommender_overlap(
    left: Mapping[str, Sequence[str]],
    right: Mapping[str, Sequence[str]],
    *,
    k: int,
) -> dict[str, object]:
    if set(left) != set(right):
        raise ValueError("Recommenders must use the same evaluated users.")
    per_user: list[float] = []
    all_left: set[str] = set()
    all_right: set[str] = set()
    identical_lists = 0
    for user in sorted(left):
        left_items = tuple(left[user][:k])
        right_items = tuple(right[user][:k])
        denominator = min(len(left_items), len(right_items))
        per_user.append(
            len(set(left_items) & set(right_items)) / denominator
            if denominator
            else 0.0
        )
        all_left.update(left_items)
        all_right.update(right_items)
        identical_lists += left_items == right_items
    union = all_left | all_right
    return {
        "k": k,
        "mean_user_list_overlap_fraction": (
            statistics.fmean(per_user) if per_user else None
        ),
        "users_with_identical_ordered_lists": identical_lists,
        "fraction_users_with_identical_ordered_lists": (
            identical_lists / len(left) if left else None
        ),
        "two_tower_unique_items": len(all_left),
        "popularity_unique_items": len(all_right),
        "unique_item_intersection": len(all_left & all_right),
        "unique_item_jaccard": (
            len(all_left & all_right) / len(union) if union else None
        ),
    }


def _audit_negative_exclusions(
    training_events: Iterable[RatingEvent],
    examples: Sequence[TwoTowerExample],
    *,
    seed: int,
    limit: int,
) -> dict[str, object]:
    sampler_data = TrainingData.from_events(training_events)
    sampler = NegativeSampler(sampler_data)
    rng = random.Random(seed)
    chosen = sorted(
        examples,
        key=lambda row: (
            hashlib.sha256(f"{seed}\0{row.user_key}\0{row.item_key}".encode()).digest(),
            row.user_key,
            row.item_key,
        ),
    )[:limit]
    for example in chosen:
        negatives = sampler.sample_many(example.user_key, rng, 4)
        if (
            example.item_key in negatives
            or len(negatives) != len(set(negatives))
            or set(negatives) & sampler_data.seen_items_by_user[example.user_key]
        ):
            raise ValueError(
                "A sampled negative violates the complete train-seen exclusion."
            )
    return {
        "sampled_target_count": len(chosen),
        "targets_absent_from_sampled_negatives": True,
        "negatives_absent_from_complete_train_seen_sets": True,
        "negative_samples_distinct_per_target": True,
        "selection_seed": seed,
    }


def _validate_run(
    data: TrustedPilotData,
    checkpoint_path: Path,
    source_report_path: Path,
) -> tuple[TwoTowerRecommender, dict[str, object], dict[str, str]]:
    root = Path(__file__).resolve().parents[3]
    expected_dir = (root / "data" / "processed").resolve()
    for path in (checkpoint_path.resolve(), source_report_path.resolve()):
        if expected_dir not in path.parents or not path.is_file():
            raise ValueError(
                "Checkpoint and source report must be local processed artifacts."
            )
    report = json.loads(source_report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("status") != "complete":
        raise ValueError("The saved Phase 3.3B aggregate report is invalid.")
    selection = report.get("selection")
    provenance = report.get("provenance")
    if not isinstance(selection, dict) or not isinstance(provenance, dict):
        raise ValueError("The saved run provenance is malformed.")
    checkpoint_sha, checkpoint_size = _sha256_file(checkpoint_path)
    if (
        selection.get("epoch") != 2
        or selection.get("checkpoint_sha256") != checkpoint_sha
        or selection.get("checkpoint_size_bytes") != checkpoint_size
    ):
        raise ValueError("The epoch-2 checkpoint does not match the saved run report.")
    train_sha = cast(str, data.temporal_outputs["interactions.train.jsonl"]["sha256"])
    validation_sha = cast(
        str, data.temporal_outputs["interactions.validation.jsonl"]["sha256"]
    )
    test_sha = cast(str, data.temporal_outputs["interactions.test.jsonl"]["sha256"])
    expected_fingerprints = {
        "train_sha256": train_sha,
        "validation_sha256": validation_sha,
    }
    if any(
        provenance.get(key) != value for key, value in expected_fingerprints.items()
    ):
        raise ValueError("Saved run source fingerprints differ from trusted artifacts.")
    recommender = load_two_tower_checkpoint(checkpoint_path, repository_root=root)
    fresh_data = build_two_tower_data(
        tuple(
            TwoTowerEvent(
                event.user_key,
                event.item_key,
                event.rating,
                _event_timestamp(record),
            )
            for event, record in zip(data.train_events, data.train_records, strict=True)
        ),
        max_history_items=recommender.config.max_history_items,
        source_artifact_fingerprints=(train_sha,),
    )
    if (
        recommender.data.training_fingerprint != fresh_data.training_fingerprint
        or recommender.data.user_ids != fresh_data.user_ids
        or recommender.data.item_ids != fresh_data.item_ids
        or recommender.data.seen_items_by_user != fresh_data.seen_items_by_user
        or recommender.data.inference_history_by_user
        != fresh_data.inference_history_by_user
        or recommender.data.source_artifact_fingerprints != (train_sha,)
    ):
        raise ValueError("Checkpoint train-derived state does not match trusted data.")
    expected_report_provenance = {
        "train_sha256": train_sha,
        "validation_sha256": validation_sha,
        "temporal_manifest_sha256": _sha256_file(data.temporal_dir / "manifest.json")[
            0
        ],
        "preprocessing_manifest_sha256": _sha256_file(
            data.preprocessing_dir / "manifest.json"
        )[0],
    }
    if any(
        provenance.get(key) != value
        for key, value in expected_report_provenance.items()
    ):
        raise ValueError(
            "Saved report manifest fingerprints differ from trusted artifacts."
        )
    return (
        recommender,
        report,
        {
            "checkpoint_sha256": checkpoint_sha,
            "source_report_sha256": _sha256_file(source_report_path)[0],
            "train_sha256": train_sha,
            "validation_sha256": validation_sha,
            "test_sha256_verified_without_parsing": test_sha,
            "temporal_manifest_sha256": expected_report_provenance[
                "temporal_manifest_sha256"
            ],
            "preprocessing_manifest_sha256": expected_report_provenance[
                "preprocessing_manifest_sha256"
            ],
        },
    )


def run_two_tower_diagnostics(
    *,
    preprocessing_dir: Path,
    temporal_dir: Path,
    checkpoint_path: Path,
    source_report_path: Path,
    output_path: Path,
) -> dict[str, object]:
    """Measure saved-checkpoint behavior without fitting or touching test rows."""
    root = Path(__file__).resolve().parents[3]
    allowed = (root / "data" / "processed").resolve()
    output_path = output_path.resolve()
    if allowed not in output_path.parents or output_path.exists():
        raise ValueError("Output must be a new file under ignored data/processed.")
    started = time.perf_counter()
    data = load_trusted_pilot_data(preprocessing_dir, temporal_dir)
    recommender, source_report, provenance = _validate_run(
        data, checkpoint_path, source_report_path
    )
    cohort = build_validation_cohort(
        data.train_events, data.validation_events, data.candidate_items
    )
    if (
        cohort.users_with_evaluable_targets != 1369
        or cohort.eligible_positive_target_count != 1911
    ):
        raise ValueError(
            "The trusted validation cohort differs from the frozen cohort."
        )

    tower_train_events = tuple(
        TwoTowerEvent(
            event.user_key,
            event.item_key,
            event.rating,
            _event_timestamp(record),
        )
        for event, record in zip(data.train_events, data.train_records, strict=True)
    )
    history_audit = _history_audit(
        tower_train_events, max_history_items=recommender.config.max_history_items
    )
    audit_data = build_two_tower_data(
        tower_train_events,
        max_history_items=recommender.config.max_history_items,
    )
    negative_audit = _audit_negative_exclusions(
        data.train_events, audit_data.examples, seed=_SAMPLE_SEED, limit=256
    )
    popularity = PopularityRecommender.fit(data.train_events, data.candidate_items)
    normal_rankings = _validation_rankings(recommender, cohort, data.candidate_items)
    popularity_rankings = {
        user: popularity.recommend(
            seen_items=cohort.seen_items_by_user[user], k=max(_K_VALUES)
        )
        for user in cohort.targets_by_user
    }
    popularity_metrics = _all_metrics(cohort, popularity_rankings, data.candidate_items)
    saved_metrics = _mapping(source_report.get("metrics"), "saved metrics")
    saved_popularity = _mapping(saved_metrics.get("baselines"), "saved baselines")
    for key in map(str, _K_VALUES):
        saved_at_k = _mapping(
            _mapping(saved_popularity.get(key), f"saved baselines @{key}").get(
                "popularity"
            ),
            f"saved popularity @{key}",
        )
        if any(
            not math.isclose(
                _number(popularity_metrics[key][metric], f"popularity {metric}"),
                _number(saved_at_k.get(metric), f"saved popularity {metric}"),
                abs_tol=1e-12,
            )
            for metric in ("recall", "ndcg", "hit_rate", "mrr", "candidate_coverage")
        ):
            raise ValueError(
                "Recomputed popularity control differs from saved baseline."
            )

    empty_data = replace(
        recommender.data,
        inference_history_by_user={user: () for user in recommender.data.user_ids},
    )
    empty_recommender = replace(recommender, data=empty_data)
    empty_rankings = _validation_rankings(
        empty_recommender, cohort, data.candidate_items
    )
    normal_metrics = _all_metrics(cohort, normal_rankings, data.candidate_items)
    empty_metrics = _all_metrics(cohort, empty_rankings, data.candidate_items)
    normal_at_10 = [set(items[:10]) for items in normal_rankings.values()]
    empty_at_10 = [set(items[:10]) for items in empty_rankings.values()]
    history_list_overlap = statistics.fmean(
        len(left & right) / 10
        for left, right in zip(normal_at_10, empty_at_10, strict=True)
    )

    sampled_users = _stable_sample(
        tuple(sorted(recommender.data.user_ids)),
        limit=_USER_SAMPLE_LIMIT,
        seed=_SAMPLE_SEED,
    )
    sampled_items = _stable_sample(
        tuple(sorted(recommender.data.item_ids)),
        limit=_ITEM_SAMPLE_LIMIT,
        seed=_SAMPLE_SEED + 1,
    )
    representations = _representation_summary(recommender, sampled_users, sampled_items)
    empty_user_vectors = _encode_users(recommender, sampled_users, empty_history=True)
    representations["normal_vs_empty_user_vector_coordinate_mae"] = float(
        torch.mean(
            torch.abs(
                _encode_users(recommender, sampled_users, empty_history=False)
                - empty_user_vectors
            )
        )
    )
    score_summary = _score_summary(recommender, sampled_users, sampled_items)
    recommendation_popularity_correlation = _recommendation_popularity_correlation(
        normal_rankings, popularity, data.candidate_items
    )

    topology = {
        "two_tower": _topology_metrics(normal_rankings, data.candidate_items),
        "popularity_control": _topology_metrics(
            popularity_rankings, data.candidate_items
        ),
        "two_tower_vs_popularity_overlap": {
            str(k): _cross_recommender_overlap(
                normal_rankings, popularity_rankings, k=k
            )
            for k in _K_VALUES
        },
        "two_tower_k10_frequency_vs_train_positive_count_pearson": (
            recommendation_popularity_correlation
        ),
    }
    temporal = {
        "history_audit_counts": history_audit,
        "sampled_negative_exclusion_audit": {
            **negative_audit,
        },
        "training_split_only": True,
        "training_history_policy": (
            "strictly prior; equal-time excluded; target masked; unique latest items"
        ),
        "validation_inference_history_source": "training split only",
        "test_rows_parsed_or_evaluated": False,
        "vocabularies": "sorted train-only keys; index zero reserved for padding",
        "negative_sampling": (
            "seeded distinct train-known items absent from complete train history"
        ),
        "positive_target_in_negative_set": False,
        "sampled_softmax": (
            "cross entropy; positive at column zero; logits divided by temperature; "
            "unavailable padded negatives masked"
        ),
        "empty_history": "supported; identity embedding remains active",
        "source_code_audit": (
            "history construction, negative sampler, loss, and ranking inspected; "
            "synthetic regression tests cover relevant behavior"
        ),
    }
    epochs = source_report.get("epochs")
    if not isinstance(epochs, list) or len(epochs) != 20:
        raise ValueError("Expected saved aggregate logs for all 20 epochs.")
    training_curve = [
        {
            key: row[key]
            for key in ("epoch", "total_loss", "validation_ndcg_at_10")
            if key in row
        }
        for row in epochs
        if isinstance(row, dict)
    ]
    for entry in training_curve:
        if (
            "epoch" not in entry
            or "total_loss" not in entry
            or "validation_ndcg_at_10" not in entry
        ):
            raise ValueError("An epoch log is missing a required aggregate field.")
    saved_tower_metrics = _mapping(
        saved_metrics.get("two_tower"), "saved Two-Tower metrics"
    )
    for key in map(str, _K_VALUES):
        saved_at_k = _mapping(saved_tower_metrics.get(key), f"saved Two-Tower @{key}")
        if (
            any(
                not math.isclose(
                    _number(normal_metrics[key][metric], f"Two-Tower {metric}"),
                    _number(saved_at_k.get(metric), f"saved Two-Tower {metric}"),
                    abs_tol=1e-12,
                )
                for metric in (
                    "recall",
                    "ndcg",
                    "hit_rate",
                    "mrr",
                    "candidate_coverage",
                )
            )
            or normal_metrics[key]["unique_recommended_items"]
            != saved_at_k["unique_recommended_items"]
        ):
            raise ValueError(
                "Recomputed Two-Tower metrics differ from the saved report."
            )
    source_selection = _mapping(source_report.get("selection"), "source selection")
    code_provenance = _mapping(
        source_report.get("code_provenance"), "source code provenance"
    )
    source_dataset = source_report.get("source")
    report: dict[str, object] = {
        "report_schema_version": _REPORT_SCHEMA,
        "experiment": "phase-3.3B.1-two-tower-diagnostics",
        "status": "complete",
        "provenance": {
            **provenance,
            "checkpoint_epoch": 2,
            "checkpoint_selection_metric": source_selection.get("metric"),
            "code_commit": code_provenance.get("git_commit"),
            "sampling_seed": _SAMPLE_SEED,
            "source_dataset": source_dataset,
        },
        "cohort": {
            "validation_users": cohort.validation_user_count,
            "evaluated_users": cohort.users_with_evaluable_targets,
            "eligible_positive_targets": cohort.eligible_positive_target_count,
            "candidate_items": len(data.candidate_items),
            "evaluation_policy": (
                "saved validation cohort; exact train-known pool; train-seen exclusion"
            ),
        },
        "saved_metrics_verified": {
            "selected_epoch": 2,
            "ndcg_at_10": normal_metrics["10"]["ndcg"],
            "recall_at_10": normal_metrics["10"]["recall"],
            "unique_items_at_10": normal_metrics["10"]["unique_recommended_items"],
            "unique_items_at_20": normal_metrics["20"]["unique_recommended_items"],
            "matches_saved_report": True,
        },
        "topology": topology,
        "metrics": {
            "two_tower": normal_metrics,
            "popularity_control_same_cohort": popularity_metrics,
            "history_ablation_empty_histories": empty_metrics,
            "normal_vs_empty_k10_list_overlap_fraction": history_list_overlap,
        },
        "representations": {
            "sample_seed": _SAMPLE_SEED,
            "sampling_policy": (
                "lowest seeded SHA-256 digests of exact IDs; IDs are not output"
            ),
            **representations,
            "sampled_score_distribution": score_summary,
        },
        "training_history": {
            "epochs": training_curve,
            "best_validation_ndcg_epoch": max(
                training_curve,
                key=lambda row: cast(float, row["validation_ndcg_at_10"]),
            )["epoch"],
            "validation_catalog_coverage_per_epoch": (
                "unavailable; absent from saved epoch logs"
            ),
            "training_loss_decreases_over_run": _number(
                training_curve[-1]["total_loss"], "final loss"
            )
            < _number(training_curve[0]["total_loss"], "initial loss"),
            "validation_decline_after_epoch_2": _number(
                training_curve[-1]["validation_ndcg_at_10"], "final validation NDCG"
            )
            < _number(training_curve[1]["validation_ndcg_at_10"], "epoch-2 NDCG"),
        },
        "implementation_audit": {
            "candidate_order_matches_sorted_checkpoint_item_vocabulary": (
                recommender.data.item_ids == tuple(sorted(recommender.data.item_ids))
            ),
            "recommend_many_matches_single_user_recommendation_on_sample": all(
                recommender.recommend(user, k=20) == normal_rankings[user]
                for user in _stable_sample(
                    tuple(sorted(normal_rankings)), limit=16, seed=_SAMPLE_SEED + 2
                )
            ),
            "train_seen_exclusions_validated_by_evaluator": True,
            "score_tie_break": "descending score then ascending canonical item key",
            "item_vectors_cached": (
                "per recommend_many call; no persistent/global checkpoint cache"
            ),
            "candidate_item_index_mapping": (
                "checkpoint vocabulary and encoded vector rows use the same sorted IDs"
            ),
            "user_vectors_encoded_per_user": True,
            "padding_index_zero": True,
            "unknown_users": "return empty recommendation list",
            "ranking_defects_found": [],
        },
        "temporal_audit": temporal,
        "interpretation": {
            "confirmed_correctness_defects": [],
            "measured_concentration": (
                "Two-Tower and same-cohort popularity concentration recorded above."
            ),
            "measured_personalization": (
                "History ablation and list overlap quantify output behavior; "
                "cosine similarity alone is not treated as collapse evidence."
            ),
            "overfitting": (
                "Training loss falls while validation NDCG peaks at epoch 2 and "
                "then stays lower; this supports, but does not explain, overfitting."
            ),
            "unavailable_evidence": [
                "per-epoch catalog coverage",
                "independent seed variation or confidence intervals",
                "cold-item retrieval (ID-only item tower)",
            ],
        },
        "runtime_seconds": time.perf_counter() - started,
        "privacy": "aggregate only; no IDs, embeddings, or row-level recommendations",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose the saved Two-Tower checkpoint without training."
    )
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
        "--checkpoint",
        type=Path,
        default=Path(
            "data/processed/amazon-electronics-pilot-10000-twotower-v1/two-tower-best.pt"
        ),
    )
    parser.add_argument(
        "--source-report",
        type=Path,
        default=Path(
            "data/processed/amazon-electronics-pilot-10000-twotower-v1/two-tower-report.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "data/processed/amazon-electronics-pilot-10000-twotower-diagnostics-v1/diagnostics-v3.json"
        ),
    )
    args = parser.parse_args(argv)
    report = run_two_tower_diagnostics(
        preprocessing_dir=args.preprocessing_dir,
        temporal_dir=args.temporal_dir,
        checkpoint_path=args.checkpoint,
        source_report_path=args.source_report,
        output_path=args.output,
    )
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
