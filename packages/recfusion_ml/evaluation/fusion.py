"""Aggregate-only diagnostics for deterministic rank-fusion outputs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Set
from dataclasses import dataclass

from recfusion_ml.ranking.rrf import RRFResult


@dataclass(frozen=True, slots=True)
class FusionDiagnostics:
    user_count: int
    candidate_pool_item_count: int
    eligible_union_item_count: int
    eligible_union_coverage: float | None
    mean_eligible_union_size: float | None
    source_raw_generated_counts: Mapping[str, int]
    source_eligible_counts: Mapping[str, int]
    source_depth_truncated_counts: Mapping[str, int]
    source_outside_pool_counts: Mapping[str, int]
    source_seen_excluded_counts: Mapping[str, int]
    source_recommendation_attribution_counts: Mapping[str, int]
    source_pair_mean_jaccard: Mapping[tuple[str, str], float]
    source_pair_mean_disagreement: Mapping[tuple[str, str], float]
    by_k: Mapping[int, Mapping[str, object]]


def summarize_fusion(
    results: Mapping[str, RRFResult],
    *,
    candidate_items: Set[str],
    ks: tuple[int, ...] = (5, 10, 20),
) -> FusionDiagnostics:
    """Summarize recommendation quality without retaining identifiers."""
    if not ks or any(isinstance(k, bool) or k <= 0 for k in ks):
        raise ValueError("K values must be positive integers.")
    if len(set(ks)) != len(ks):
        raise ValueError("K values must be unique.")
    pool = set(candidate_items)
    user_count = len(results)
    union_items = set().union(*(set(result.scores) for result in results.values()))
    all_sources = (
        sorted(set().union(*(set(result.source_names) for result in results.values())))
        if results
        else []
    )
    raw_counts = Counter({name: 0 for name in all_sources})
    eligible_counts = Counter({name: 0 for name in all_sources})
    depth_counts = Counter({name: 0 for name in all_sources})
    outside_counts = Counter({name: 0 for name in all_sources})
    seen_counts = Counter({name: 0 for name in all_sources})
    attribution_counts = Counter({name: 0 for name in all_sources})
    pair_values: dict[tuple[str, str], list[float]] = {}
    for result in results.values():
        raw_counts.update(result.raw_generated_counts)
        eligible_counts.update(result.eligible_counts)
        depth_counts.update(result.depth_truncated_counts)
        outside_counts.update(result.outside_pool_counts)
        seen_counts.update(result.seen_excluded_counts)
        for item in result.recommended_items:
            attribution_counts.update(result.source_provenance[item])
        for pair, jaccard in result.source_jaccard.items():
            pair_values.setdefault(pair, []).append(jaccard)

    by_k: dict[int, Mapping[str, object]] = {}
    for k in ks:
        recommendations = [result.recommended_items[:k] for result in results.values()]
        item_counts = Counter(item for items in recommendations for item in items)
        recommendation_count = sum(item_counts.values())
        attributed = Counter({name: 0 for name in all_sources})
        exclusive = Counter({name: 0 for name in all_sources})
        for result in results.values():
            for item in result.recommended_items[:k]:
                sources = result.source_provenance[item]
                attributed.update(sources)
                if len(sources) == 1:
                    exclusive.update(sources)
        top_shares = {
            str(n): (
                sum(count for _, count in item_counts.most_common(n))
                / recommendation_count
                if recommendation_count
                else 0.0
            )
            for n in (1, 5, 10)
        }
        histogram = Counter(
            "0"
            if count == 0
            else "1"
            if count == 1
            else "2-5"
            if count <= 5
            else "6-10"
            if count <= 10
            else ">10"
            for count in (item_counts.get(item, 0) for item in pool)
        )
        by_k[k] = {
            "recommendation_count": recommendation_count,
            "unique_recommended_item_count": len(item_counts),
            "final_catalog_coverage": len(item_counts) / len(pool) if pool else None,
            "mean_final_list_length": (
                recommendation_count / user_count if user_count else None
            ),
            "users_short_of_k": sum(len(items) < k for items in recommendations),
            "frequency_histogram": {
                bucket: histogram[bucket] for bucket in ("0", "1", "2-5", "6-10", ">10")
            },
            "top_item_placement_shares": top_shares,
            "source_attribution_counts": dict(sorted(attributed.items())),
            "source_attribution_shares": {
                name: count / recommendation_count if recommendation_count else 0.0
                for name, count in sorted(attributed.items())
            },
            "source_exclusive_attribution_counts": dict(sorted(exclusive.items())),
            "source_exclusive_attribution_shares": {
                name: count / recommendation_count if recommendation_count else 0.0
                for name, count in sorted(exclusive.items())
            },
        }

    return FusionDiagnostics(
        user_count=user_count,
        candidate_pool_item_count=len(pool),
        eligible_union_item_count=len(union_items),
        eligible_union_coverage=len(union_items) / len(pool) if pool else None,
        mean_eligible_union_size=(
            sum(result.eligible_union_size for result in results.values()) / user_count
            if user_count
            else None
        ),
        source_raw_generated_counts=dict(sorted(raw_counts.items())),
        source_eligible_counts=dict(sorted(eligible_counts.items())),
        source_depth_truncated_counts=dict(sorted(depth_counts.items())),
        source_outside_pool_counts=dict(sorted(outside_counts.items())),
        source_seen_excluded_counts=dict(sorted(seen_counts.items())),
        source_recommendation_attribution_counts=dict(
            sorted(attribution_counts.items())
        ),
        source_pair_mean_jaccard={
            pair: sum(values) / len(values)
            for pair, values in sorted(pair_values.items())
        },
        source_pair_mean_disagreement={
            pair: 1 - sum(values) / len(values)
            for pair, values in sorted(pair_values.items())
        },
        by_k=by_k,
    )
