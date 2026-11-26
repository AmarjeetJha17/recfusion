"""Deterministic reciprocal-rank fusion for ranked candidate sources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class RRFConfig:
    rank_constant: float = 60
    source_weights: Mapping[str, float] | None = None
    source_depths: Mapping[str, int] | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.rank_constant, bool)
            or not isfinite(self.rank_constant)
            or self.rank_constant <= 0
        ):
            raise ValueError("RRF rank constant must be finite and positive.")
        if self.source_weights is not None:
            for name, weight in self.source_weights.items():
                if not name.strip():
                    raise ValueError("Source names must be non-empty.")
                if isinstance(weight, bool) or not isfinite(weight) or weight < 0:
                    raise ValueError("Source weights must be finite and non-negative.")
        if self.source_depths is not None:
            for name, depth in self.source_depths.items():
                if not name.strip():
                    raise ValueError("Source names must be non-empty.")
                if isinstance(depth, bool) or not isinstance(depth, int) or depth <= 0:
                    raise ValueError("Source depths must be positive integers.")


@dataclass(frozen=True, slots=True)
class RRFResult:
    recommended_items: tuple[str, ...]
    scores: Mapping[str, float]
    source_provenance: Mapping[str, tuple[str, ...]]
    source_contributions: Mapping[str, Mapping[str, float]]
    source_names: tuple[str, ...]
    raw_generated_counts: Mapping[str, int]
    eligible_counts: Mapping[str, int]
    depth_truncated_counts: Mapping[str, int]
    outside_pool_counts: Mapping[str, int]
    source_candidate_excluded_counts: Mapping[str, int]
    seen_excluded_counts: Mapping[str, int]
    eligible_union_size: int
    source_jaccard: Mapping[tuple[str, str], float]


def fuse_ranked_candidates(
    source_rankings: Mapping[str, Sequence[str]],
    *,
    candidate_items: Set[str],
    k: int,
    config: RRFConfig = RRFConfig(),
    seen_items: Set[str] = frozenset(),
    source_candidate_items: Mapping[str, Set[str]] | None = None,
) -> RRFResult:
    """Fuse one-based ranks with global, source-specific, and seen filters."""
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("K must be a positive integer.")
    if any(not isinstance(item, str) or not item.strip() for item in candidate_items):
        raise ValueError("Candidate item identifiers must be non-empty strings.")
    if any(not isinstance(item, str) or not item.strip() for item in seen_items):
        raise ValueError("Seen item identifiers must be non-empty strings.")

    weights = config.source_weights
    depths = config.source_depths or {}
    if weights is not None and set(source_rankings) - set(weights):
        raise ValueError("Every ranked source must have a configured weight.")
    source_pools = source_candidate_items or {}
    names = tuple(
        sorted(
            set(source_rankings) | set(weights or {}) | set(depths) | set(source_pools)
        )
    )
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise ValueError("Source names must be non-empty strings.")
    effective_weights = {
        name: 1.0 if weights is None else weights.get(name, 0.0) for name in names
    }
    if not any(weight > 0 for weight in effective_weights.values()):
        raise ValueError("At least one positive effective source weight is required.")

    pool = set(candidate_items)
    seen = set(seen_items)
    for _, allowed_items in source_pools.items():
        if any(not isinstance(item, str) or not item.strip() for item in allowed_items):
            raise ValueError(
                "Source candidate pool identifiers must be non-empty strings."
            )
        if set(allowed_items) - pool:
            raise ValueError(
                "Each source candidate pool must be a subset of the global pool."
            )
    scores: dict[str, float] = {}
    provenance: dict[str, list[str]] = {}
    contributions: dict[str, dict[str, float]] = {}
    raw_counts: dict[str, int] = {}
    eligible_counts: dict[str, int] = {}
    truncated_counts: dict[str, int] = {}
    outside_counts: dict[str, int] = {}
    source_excluded_counts: dict[str, int] = {}
    seen_counts: dict[str, int] = {}
    eligible_by_source: dict[str, set[str]] = {}

    for name in names:
        ranked = tuple(source_rankings.get(name, ()))
        if any(not isinstance(item, str) or not item.strip() for item in ranked):
            raise ValueError("Ranked item identifiers must be non-empty strings.")
        if len(set(ranked)) != len(ranked):
            raise ValueError(f"Source {name!r} contains duplicate item identifiers.")
        raw_counts[name] = len(ranked)
        depth = depths.get(name)
        truncated_counts[name] = max(0, len(ranked) - depth) if depth else 0
        source_eligible: set[str] = set()
        source_contributions: dict[str, float] = {}
        outside = 0
        source_excluded = 0
        seen_excluded = 0
        weight = effective_weights[name]
        source_pool = source_pools.get(name)
        for rank, item in enumerate(ranked[:depth], start=1):
            if item not in pool:
                outside += 1
                continue
            if source_pool is not None and item not in source_pool:
                source_excluded += 1
                continue
            if item in seen:
                seen_excluded += 1
                continue
            source_eligible.add(item)
            if weight <= 0:
                continue
            contribution = weight / (config.rank_constant + rank)
            source_contributions[item] = contribution
            scores[item] = scores.get(item, 0.0) + contribution
            provenance.setdefault(item, []).append(name)
        eligible_by_source[name] = source_eligible
        contributions[name] = source_contributions
        eligible_counts[name] = len(source_eligible)
        outside_counts[name] = outside
        source_excluded_counts[name] = source_excluded
        seen_counts[name] = seen_excluded

    ordered = tuple(sorted(scores, key=lambda item: (-scores[item], item))[:k])
    overlaps: dict[tuple[str, str], float] = {}
    for left_index, left in enumerate(names):
        for right in names[left_index + 1 :]:
            union = eligible_by_source[left] | eligible_by_source[right]
            intersection = eligible_by_source[left] & eligible_by_source[right]
            overlaps[(left, right)] = len(intersection) / len(union) if union else 0.0

    return RRFResult(
        recommended_items=ordered,
        scores=dict(sorted(scores.items())),
        source_provenance={
            item: tuple(provenance[item]) for item in sorted(provenance)
        },
        source_contributions=contributions,
        source_names=names,
        raw_generated_counts=raw_counts,
        eligible_counts=eligible_counts,
        depth_truncated_counts=truncated_counts,
        outside_pool_counts=outside_counts,
        source_candidate_excluded_counts=source_excluded_counts,
        seen_excluded_counts=seen_counts,
        eligible_union_size=len(scores),
        source_jaccard=overlaps,
    )
