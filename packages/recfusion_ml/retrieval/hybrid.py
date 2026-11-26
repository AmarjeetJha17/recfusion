"""Deterministic hybrid retrieval over collaborative and content rankings."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from recfusion_core.contracts import Interaction
from recfusion_ml.evaluation.fusion import FusionDiagnostics, summarize_fusion
from recfusion_ml.ranking.rrf import RRFConfig, RRFResult, fuse_ranked_candidates
from recfusion_ml.retrieval.content import ContentIndex


class HybridCandidatePolicy(StrEnum):
    """Candidate-universe choices for warm and cold hybrid retrieval."""

    WARM_HYBRID = "warm_hybrid"
    CONTENT_ELIGIBLE_HYBRID = "content_eligible_hybrid"


@dataclass(frozen=True, slots=True)
class HybridUserContext:
    """Private per-query context; only its aggregates belong in reports."""

    user_key: str
    training_interactions: Sequence[Interaction]
    prediction_time_ms: int
    target_item_key: str | None = None


@dataclass(frozen=True, slots=True)
class HybridConfig:
    """Explicit RRF source weights/depths and the content source identity."""

    rrf: RRFConfig
    content_source_name: str = "tfidf_content"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.content_source_name, str)
            or not self.content_source_name.strip()
        ):
            raise ValueError("A non-empty content source name is required.")
        weights = self.rrf.source_weights
        depths = self.rrf.source_depths
        if weights is None or depths is None:
            raise ValueError(
                "Hybrid retrieval requires explicit source weights and depths."
            )
        if set(weights) != set(depths):
            raise ValueError(
                "Hybrid source weights and depths must name the same sources."
            )
        if self.content_source_name not in weights:
            raise ValueError(
                "The configured content source must have an explicit weight and depth."
            )
        if any(not isinstance(name, str) or not name.strip() for name in weights):
            raise ValueError("Hybrid source names must be non-empty strings.")
        if not any(
            not isinstance(weight, bool) and isfinite(weight) and weight > 0
            for weight in weights.values()
        ):
            raise ValueError("At least one hybrid source must have positive weight.")

    @property
    def source_weights(self) -> Mapping[str, float]:
        assert self.rrf.source_weights is not None
        return self.rrf.source_weights

    @property
    def source_depths(self) -> Mapping[str, int]:
        assert self.rrf.source_depths is not None
        return self.rrf.source_depths


@dataclass(frozen=True, slots=True)
class HybridRetrievalResult:
    """One query result with private rankings and audit counts in memory."""

    candidate_policy: HybridCandidatePolicy
    fusion: RRFResult
    candidate_item_keys: frozenset[str]
    warm_candidate_item_keys: frozenset[str]
    cold_candidate_item_keys: frozenset[str]
    content_warm_candidate_count: int
    content_cold_candidate_count: int
    profile_seen_item_count: int
    profile_positive_item_count: int
    profile_missing_content_item_count: int
    content_profile_empty: bool
    source_eligible_warm_counts: Mapping[str, int]
    source_eligible_cold_counts: Mapping[str, int]
    content_source_name: str

    @property
    def warm_candidate_count(self) -> int:
        return len(self.warm_candidate_item_keys)

    @property
    def cold_candidate_count(self) -> int:
        return len(self.cold_candidate_item_keys)


@dataclass(frozen=True, slots=True)
class HybridDiagnostics:
    """Aggregate-safe diagnostics; contains no user or item identifiers."""

    fusion: FusionDiagnostics
    candidate_policy: HybridCandidatePolicy
    candidate_pool_item_count: int
    warm_candidate_count: int
    cold_candidate_count: int
    content_warm_candidate_count: int
    content_cold_candidate_count: int
    source_candidate_excluded_counts: Mapping[str, int]
    source_eligible_warm_counts: Mapping[str, int]
    source_eligible_cold_counts: Mapping[str, int]
    by_k: Mapping[int, Mapping[str, object]]


def retrieve_hybrid(
    *,
    context: HybridUserContext,
    content_index: ContentIndex,
    collaborative_rankings: Mapping[str, Sequence[str]],
    content_ranking: Sequence[str] | None = None,
    train_known_item_keys: Set[str],
    candidate_policy: HybridCandidatePolicy,
    config: HybridConfig,
    k: int,
) -> HybridRetrievalResult:
    """Create the TF-IDF source and fuse it with train-known model rankings.

    Source-specific filtering happens inside the existing RRF implementation,
    after depth truncation, so disallowed candidates do not shift source ranks.
    """
    if not isinstance(candidate_policy, HybridCandidatePolicy):
        raise ValueError("An explicit hybrid candidate policy is required.")
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("K must be a positive integer.")
    if config.content_source_name in collaborative_rankings:
        raise ValueError("The content source name is reserved for the TF-IDF adapter.")

    weights = config.source_weights
    depths = config.source_depths
    collaborative_source_names = set(weights) - {config.content_source_name}
    unknown_sources = set(collaborative_rankings) - collaborative_source_names
    if unknown_sources:
        raise ValueError("Collaborative rankings contain an unconfigured source name.")

    train_known = frozenset(train_known_item_keys)
    if any(not isinstance(item, str) or not item.strip() for item in train_known):
        raise ValueError("Train-known item identifiers must be non-empty strings.")
    events = tuple(context.training_interactions)
    observed_train_items = frozenset(event.item_key for event in events)
    if train_known != observed_train_items:
        raise ValueError(
            "Train-known candidates must exactly match supplied training items."
        )

    content_candidates = frozenset(content_index.candidate_keys)
    warm_content_candidates = content_candidates & train_known
    cold_content_candidates = content_candidates - train_known
    warm_candidates = train_known
    if candidate_policy is HybridCandidatePolicy.WARM_HYBRID:
        candidate_items = warm_candidates
        eligible_content_candidates = warm_content_candidates
    else:
        candidate_items = train_known | cold_content_candidates
        eligible_content_candidates = warm_content_candidates | cold_content_candidates

    profile = content_index.profile_from_training_history(
        events,
        user_key=context.user_key,
        prediction_time_ms=context.prediction_time_ms,
        target_item_key=context.target_item_key,
    )
    if content_ranking is None:
        content_depth = depths[config.content_source_name]
        if content_depth > content_index.vectorizer.config.max_recommendations:
            raise ValueError(
                "Content source depth exceeds the configured retrieval limit."
            )
        generated_content = content_index.recommend_for_profile(
            profile,
            k=content_depth,
            eligible_item_keys=eligible_content_candidates,
        )
        content_items = tuple(match.item_key for match in generated_content.items)
    else:
        content_items = tuple(content_ranking)
    rankings: dict[str, Sequence[str]] = {
        name: tuple(collaborative_rankings.get(name, ()))
        for name in sorted(collaborative_source_names)
    }
    rankings[config.content_source_name] = content_items
    source_pools = {name: train_known for name in collaborative_source_names}
    source_pools[config.content_source_name] = eligible_content_candidates

    fusion = fuse_ranked_candidates(
        rankings,
        candidate_items=candidate_items,
        source_candidate_items=source_pools,
        seen_items=profile.seen_item_keys,
        k=k,
        config=config.rrf,
    )
    source_eligible_warm_counts: dict[str, int] = {}
    source_eligible_cold_counts: dict[str, int] = {}
    for source_name, source_ranking in rankings.items():
        allowed = source_pools[source_name]
        depth = depths[source_name]
        eligible = {
            item
            for item in tuple(source_ranking)[:depth]
            if item in candidate_items
            and item in allowed
            and item not in profile.seen_item_keys
        }
        source_eligible_warm_counts[source_name] = sum(
            item in warm_candidates for item in eligible
        )
        source_eligible_cold_counts[source_name] = sum(
            item in cold_content_candidates for item in eligible
        )

    return HybridRetrievalResult(
        candidate_policy=candidate_policy,
        fusion=fusion,
        candidate_item_keys=frozenset(candidate_items),
        warm_candidate_item_keys=frozenset(warm_candidates),
        cold_candidate_item_keys=frozenset(
            cold_content_candidates
            if candidate_policy is HybridCandidatePolicy.CONTENT_ELIGIBLE_HYBRID
            else ()
        ),
        content_warm_candidate_count=len(warm_content_candidates),
        content_cold_candidate_count=len(cold_content_candidates),
        profile_seen_item_count=len(profile.seen_item_keys),
        profile_positive_item_count=profile.prior_positive_item_count,
        profile_missing_content_item_count=profile.missing_content_item_count,
        content_profile_empty=not profile.vector,
        source_eligible_warm_counts=source_eligible_warm_counts,
        source_eligible_cold_counts=source_eligible_cold_counts,
        content_source_name=config.content_source_name,
    )


def summarize_hybrid(
    results: Sequence[HybridRetrievalResult],
    *,
    ks: tuple[int, ...] = (5, 10, 20),
) -> HybridDiagnostics:
    """Aggregate several query results without returning user/item identities."""
    if not results:
        raise ValueError("At least one hybrid result is required for diagnostics.")
    first = results[0]
    for result in results[1:]:
        if (
            result.candidate_policy is not first.candidate_policy
            or result.candidate_item_keys != first.candidate_item_keys
            or result.warm_candidate_item_keys != first.warm_candidate_item_keys
            or result.cold_candidate_item_keys != first.cold_candidate_item_keys
            or result.content_source_name != first.content_source_name
        ):
            raise ValueError(
                "Hybrid diagnostic results must share one candidate policy and pool."
            )

    fusion = summarize_fusion(
        {str(index): result.fusion for index, result in enumerate(results)},
        candidate_items=first.candidate_item_keys,
        ks=ks,
    )
    source_excluded: Counter[str] = Counter()
    source_warm: Counter[str] = Counter()
    source_cold: Counter[str] = Counter()
    for result in results:
        source_excluded.update(result.fusion.source_candidate_excluded_counts)
        source_warm.update(result.source_eligible_warm_counts)
        source_cold.update(result.source_eligible_cold_counts)

    by_k: dict[int, Mapping[str, object]] = {}
    for k in ks:
        recommendations = [result.fusion.recommended_items[:k] for result in results]
        flat_items = [item for ranked in recommendations for item in ranked]
        warm_recommendations = [
            item for item in flat_items if item in first.warm_candidate_item_keys
        ]
        cold_recommendations = [
            item for item in flat_items if item in first.cold_candidate_item_keys
        ]
        unique_warm = set(warm_recommendations)
        unique_cold = set(cold_recommendations)
        source_contribution_by_name: dict[str, float] = {}
        for result in results:
            selected = set(result.fusion.recommended_items[:k])
            for (
                source_name,
                contributions,
            ) in result.fusion.source_contributions.items():
                source_contribution_by_name[source_name] = (
                    source_contribution_by_name.get(source_name, 0.0)
                    + sum(contributions.get(item, 0.0) for item in selected)
                )
        content_contribution = source_contribution_by_name.get(
            first.content_source_name, 0.0
        )
        collaborative_contribution = sum(
            value
            for name, value in source_contribution_by_name.items()
            if name != first.content_source_name
        )
        by_k[k] = {
            "final_warm_recommendation_count": len(warm_recommendations),
            "final_cold_recommendation_count": len(cold_recommendations),
            "unique_warm_recommended_item_count": len(unique_warm),
            "unique_cold_recommended_item_count": len(unique_cold),
            "warm_catalog_coverage": (
                len(unique_warm) / len(first.warm_candidate_item_keys)
                if first.warm_candidate_item_keys
                else None
            ),
            "cold_catalog_coverage": (
                len(unique_cold) / len(first.cold_candidate_item_keys)
                if first.cold_candidate_item_keys
                else None
            ),
            "source_rank_contribution_by_name": dict(
                sorted(source_contribution_by_name.items())
            ),
            "source_rank_contribution_by_kind": {
                "collaborative": collaborative_contribution,
                "content": content_contribution,
            },
            "fusion": fusion.by_k[k],
        }

    return HybridDiagnostics(
        fusion=fusion,
        candidate_policy=first.candidate_policy,
        candidate_pool_item_count=len(first.candidate_item_keys),
        warm_candidate_count=len(first.warm_candidate_item_keys),
        cold_candidate_count=len(first.cold_candidate_item_keys),
        content_warm_candidate_count=first.content_warm_candidate_count,
        content_cold_candidate_count=first.content_cold_candidate_count,
        source_candidate_excluded_counts=dict(sorted(source_excluded.items())),
        source_eligible_warm_counts=dict(sorted(source_warm.items())),
        source_eligible_cold_counts=dict(sorted(source_cold.items())),
        by_k=by_k,
    )
