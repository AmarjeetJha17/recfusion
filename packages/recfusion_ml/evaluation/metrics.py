"""Warm-start ranking protocol and macro-averaged ranking metrics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass
from decimal import Decimal
from math import log2

from recfusion_ml.types import RatingEvent


@dataclass(frozen=True, slots=True)
class ValidationCohort:
    validation_user_count: int
    users_with_observed_positives: int
    users_with_warm_positive_targets: int
    users_with_evaluable_targets: int
    positive_observation_count: int
    positive_target_pair_count: int
    warm_positive_observation_count: int
    warm_positive_target_count: int
    eligible_positive_target_count: int
    cold_item_positive_observation_count: int
    cold_user_positive_observation_count: int
    seen_positive_observation_count: int
    non_positive_observation_count: int
    duplicate_positive_observation_count: int
    excluded_target_counts: Mapping[str, int]
    targets_by_user: Mapping[str, frozenset[str]]
    seen_items_by_user: Mapping[str, frozenset[str]]
    candidate_items: frozenset[str]


@dataclass(frozen=True, slots=True)
class RankingMetrics:
    recall: float | None
    ndcg: float | None
    hit_rate: float | None
    mrr: float | None
    candidate_coverage: float | None
    unique_recommended_items: int
    recommendation_count: int


@dataclass(frozen=True, slots=True)
class RankingEvaluation:
    evaluated_user_count: int
    eligible_positive_target_count: int
    candidate_pool_item_count: int
    metrics_by_k: Mapping[int, RankingMetrics]


def build_validation_cohort(
    training_events: Iterable[RatingEvent],
    validation_events: Iterable[RatingEvent],
    candidate_items: Set[str],
    *,
    positive_min_rating: Decimal = Decimal("4"),
) -> ValidationCohort:
    training_events = tuple(training_events)
    validation_events = tuple(validation_events)
    if any(event.split != "train" for event in training_events):
        raise ValueError("Training events must all belong to the train split.")
    if any(event.split != "validation" for event in validation_events):
        raise ValueError("Evaluation events must all belong to validation.")

    train_users = {event.user_key for event in training_events}
    train_items = {event.item_key for event in training_events}
    pool = frozenset(candidate_items)
    if pool != train_items:
        raise ValueError("Candidate pool must exactly match train-known items.")

    seen: dict[str, set[str]] = {}
    for event in training_events:
        seen.setdefault(event.user_key, set()).add(event.item_key)

    all_validation_users = {event.user_key for event in validation_events}
    positive_rows = [
        event for event in validation_events if event.rating >= positive_min_rating
    ]
    positive_pair_counts: Counter[tuple[str, str]] = Counter(
        (event.user_key, event.item_key) for event in positive_rows
    )
    positive_pairs = set(positive_pair_counts)
    warm_pairs = {
        pair for pair in positive_pairs if pair[0] in train_users and pair[1] in pool
    }
    eligible_pairs: set[tuple[str, str]] = set()
    exclusions: Counter[str] = Counter()
    for user_key, item_key in positive_pairs:
        if user_key not in train_users:
            exclusions["cold_user"] += 1
        elif item_key not in pool:
            exclusions["cold_item"] += 1
        elif item_key in seen.get(user_key, set()):
            exclusions["seen_in_train_history"] += 1
        else:
            eligible_pairs.add((user_key, item_key))

    positive_by_user: dict[str, set[str]] = {}
    warm_by_user: dict[str, set[str]] = {}
    eligible_by_user: dict[str, set[str]] = {}
    for user_key, item_key in positive_pairs:
        positive_by_user.setdefault(user_key, set()).add(item_key)
    for user_key, item_key in warm_pairs:
        warm_by_user.setdefault(user_key, set()).add(item_key)
    for user_key, item_key in eligible_pairs:
        eligible_by_user.setdefault(user_key, set()).add(item_key)

    return ValidationCohort(
        validation_user_count=len(all_validation_users),
        users_with_observed_positives=len(positive_by_user),
        users_with_warm_positive_targets=len(warm_by_user),
        users_with_evaluable_targets=len(eligible_by_user),
        positive_observation_count=len(positive_rows),
        positive_target_pair_count=len(positive_pairs),
        warm_positive_observation_count=sum(
            1
            for event in positive_rows
            if event.user_key in train_users and event.item_key in pool
        ),
        warm_positive_target_count=len(warm_pairs),
        eligible_positive_target_count=len(eligible_pairs),
        cold_item_positive_observation_count=sum(
            1 for event in positive_rows if event.item_key not in pool
        ),
        cold_user_positive_observation_count=sum(
            1 for event in positive_rows if event.user_key not in train_users
        ),
        seen_positive_observation_count=sum(
            1
            for event in positive_rows
            if event.user_key in train_users
            and event.item_key in pool
            and event.item_key in seen.get(event.user_key, set())
        ),
        non_positive_observation_count=len(validation_events) - len(positive_rows),
        duplicate_positive_observation_count=len(positive_rows) - len(positive_pairs),
        excluded_target_counts=dict(sorted(exclusions.items())),
        targets_by_user={
            user: frozenset(items) for user, items in eligible_by_user.items()
        },
        seen_items_by_user={user: frozenset(items) for user, items in seen.items()},
        candidate_items=pool,
    )


def evaluate_rankings(
    cohort: ValidationCohort,
    recommendations: Mapping[str, Sequence[str]],
    *,
    candidate_items: Set[str],
    ks: Sequence[int] = (5, 10, 20),
) -> RankingEvaluation:
    pool = frozenset(candidate_items)
    if pool != cohort.candidate_items:
        raise ValueError("Metric candidate pool differs from the validated train pool.")
    k_values = tuple(ks)
    if not k_values or any(isinstance(k, bool) or k <= 0 for k in k_values):
        raise ValueError("K values must be positive integers.")
    if len(set(k_values)) != len(k_values):
        raise ValueError("K values must be unique.")

    eligible_users = set(cohort.targets_by_user)
    if set(recommendations) != eligible_users:
        raise ValueError("Recommendations must be supplied for every evaluable user.")
    for user, ranked_items in recommendations.items():
        if len(set(ranked_items)) != len(ranked_items):
            raise ValueError("Recommendation lists must contain unique items.")
        if set(ranked_items) - pool:
            raise ValueError("Recommendations must use items from the candidate pool.")
        if set(ranked_items) & cohort.seen_items_by_user.get(user, frozenset()):
            raise ValueError("Recommendations must exclude train-seen items.")

    metrics: dict[int, RankingMetrics] = {}
    for k in k_values:
        recalls: list[float] = []
        ndcgs: list[float] = []
        hits: list[float] = []
        reciprocal_ranks: list[float] = []
        recommended: set[str] = set()
        recommendation_count = 0
        for user in sorted(eligible_users):
            relevant = cohort.targets_by_user[user]
            ranked = tuple(recommendations[user])[:k]
            recommended.update(ranked)
            recommendation_count += len(ranked)
            hits_at_k = [item in relevant for item in ranked]
            recalls.append(sum(hits_at_k) / len(relevant))
            dcg = sum(
                1.0 / log2(rank + 2)
                for rank, is_relevant in enumerate(hits_at_k)
                if is_relevant
            )
            ideal_count = min(len(relevant), k)
            idcg = sum(1.0 / log2(rank + 2) for rank in range(ideal_count))
            ndcgs.append(dcg / idcg)
            hits.append(float(any(hits_at_k)))
            first_hit = next(
                (rank for rank, hit in enumerate(hits_at_k, start=1) if hit), None
            )
            reciprocal_ranks.append(1 / first_hit if first_hit is not None else 0.0)

        if eligible_users:
            metrics[k] = RankingMetrics(
                recall=sum(recalls) / len(recalls),
                ndcg=sum(ndcgs) / len(ndcgs),
                hit_rate=sum(hits) / len(hits),
                mrr=sum(reciprocal_ranks) / len(reciprocal_ranks),
                candidate_coverage=(len(recommended) / len(pool) if pool else None),
                unique_recommended_items=len(recommended),
                recommendation_count=recommendation_count,
            )
        else:
            metrics[k] = RankingMetrics(
                recall=None,
                ndcg=None,
                hit_rate=None,
                mrr=None,
                candidate_coverage=None,
                unique_recommended_items=0,
                recommendation_count=0,
            )

    return RankingEvaluation(
        evaluated_user_count=len(eligible_users),
        eligible_positive_target_count=cohort.eligible_positive_target_count,
        candidate_pool_item_count=len(pool),
        metrics_by_k=metrics,
    )
