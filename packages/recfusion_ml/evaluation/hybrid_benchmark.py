"""Frozen, aggregate-only synthetic hybrid retrieval benchmark."""

from __future__ import annotations

import hashlib
import json
import time
import tracemalloc
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from recfusion_ml.evaluation.content_benchmark import (
    DEFAULT_SEED,
    POSITIVE_MIN_RATING,
    SyntheticContentBenchmark,
    _profile_targets,
    _ranked_by_policy,
    evaluate_macro_rankings,
)
from recfusion_ml.ranking.rrf import RRFConfig
from recfusion_ml.retrieval.content import ContentIndex
from recfusion_ml.retrieval.hybrid import (
    HybridCandidatePolicy,
    HybridConfig,
    HybridRetrievalResult,
    HybridUserContext,
    retrieve_hybrid,
)

HYBRID_BENCHMARK_SCHEMA = "recfusion.hybrid-benchmark.v1"
HYBRID_BENCHMARK_VERSION = "4.4B"
EVALUATION_KS = (5, 10, 20)
_CONTENT_SOURCE = "tfidf_content"
_POPULARITY_SOURCE = "popularity"
_SOURCE_DEPTH = 20
_RANK_CONSTANT = 60

_METHOD_CONFIGS: Mapping[str, Mapping[str, float]] = {
    "content_only": {_CONTENT_SOURCE: 1.0, _POPULARITY_SOURCE: 0.0},
    "popularity_only": {_CONTENT_SOURCE: 0.0, _POPULARITY_SOURCE: 1.0},
    "hybrid_a": {_CONTENT_SOURCE: 1.0, _POPULARITY_SOURCE: 1.0},
    "hybrid_b": {_CONTENT_SOURCE: 2.0, _POPULARITY_SOURCE: 1.0},
}


@dataclass(frozen=True, slots=True)
class HybridBenchmarkRun:
    """Aggregate report bytes plus non-deterministic local resource measures."""

    aggregate: Mapping[str, Any]
    manifest_bytes: bytes
    manifest_sha256: str
    runtime_seconds: float
    peak_traced_bytes: int


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _concentration(rankings: Mapping[str, Sequence[str]], k: int) -> dict[str, Any]:
    counts: Counter[str] = Counter(
        item for ranking in rankings.values() for item in ranking[:k]
    )
    total = sum(counts.values())
    shares = [count / total for count in counts.values()] if total else []
    return {
        "unique_recommended_item_count": len(counts),
        "recommendation_count": total,
        "maximum_item_exposure_share": max(shares, default=0.0),
        "herfindahl_hirschman_index": sum(share**2 for share in shares),
    }


def _cold_metrics(
    benchmark: SyntheticContentBenchmark,
    candidate_keys: frozenset[str],
    targets: Mapping[str, frozenset[str]],
    rankings: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    cold_targets = {
        user: frozenset(items & benchmark.cold_item_keys)
        for user, items in targets.items()
    }
    eligible_users = tuple(user for user in sorted(cold_targets) if cold_targets[user])
    target_count = sum(len(cold_targets[user]) for user in eligible_users)
    by_k: dict[str, object] = {}
    for k in EVALUATION_KS:
        hits = {
            user: len(set(rankings[user][:k]) & set(cold_targets[user]))
            for user in eligible_users
        }
        recall_values = [
            hits[user] / len(cold_targets[user]) for user in eligible_users
        ]
        unique_cold = {
            item
            for user in rankings
            for item in rankings[user][:k]
            if item in benchmark.cold_item_keys
        }
        by_k[str(k)] = {
            "cold_positive_hits": sum(hits.values()),
            "macro_cold_recall": (
                sum(recall_values) / len(recall_values) if recall_values else None
            ),
            "unique_cold_items_recommended": len(unique_cold),
            "cold_catalog_coverage": (
                len(unique_cold)
                / sum(item in candidate_keys for item in benchmark.cold_item_keys)
                if any(item in candidate_keys for item in benchmark.cold_item_keys)
                else None
            ),
        }
    return {
        "averaging": "macro over users with at least one eligible cold positive",
        "eligible_user_denominator": len(eligible_users),
        "eligible_target_denominator": target_count,
        "eligible_cold_candidate_count": sum(
            item in candidate_keys for item in benchmark.cold_item_keys
        ),
        "ineligible_cold_positive_count": len(
            {
                (event.user_key, event.item_key)
                for event in benchmark.evaluation_events
                if event.rating >= POSITIVE_MIN_RATING
                and event.item_key in benchmark.cold_item_keys
                and event.item_key not in candidate_keys
            }
        ),
        "metrics_by_k": by_k,
    }


def _method_report(
    *,
    benchmark: SyntheticContentBenchmark,
    candidate_keys: frozenset[str],
    targets: Mapping[str, frozenset[str]],
    results: Mapping[str, HybridRetrievalResult],
) -> dict[str, Any]:
    rankings = {
        user: result.fusion.recommended_items for user, result in results.items()
    }
    metrics = evaluate_macro_rankings(
        relevant_by_user=targets,
        rankings_by_user=rankings,
        eligible_candidate_count=len(candidate_keys),
        ks=EVALUATION_KS,
    )
    metrics_by_k = metrics["metrics_by_k"]
    assert isinstance(metrics_by_k, dict)
    for k in EVALUATION_KS:
        row = metrics_by_k[str(k)]
        assert isinstance(row, dict)
        row["final_catalog_coverage"] = (
            row["unique_recommended_products"] / len(candidate_keys)
            if candidate_keys
            else None
        )
        row["warm_item_coverage_count"] = len(
            {
                item
                for user in rankings
                for item in rankings[user][:k]
                if item in benchmark.warm_item_keys
            }
        )
        row["cold_item_coverage_count"] = len(
            {
                item
                for user in rankings
                for item in rankings[user][:k]
                if item in benchmark.cold_item_keys
            }
        )
        eligible_cold_catalog_size = sum(
            item in candidate_keys for item in benchmark.cold_item_keys
        )
        row["cold_catalog_coverage"] = (
            row["cold_item_coverage_count"] / eligible_cold_catalog_size
            if eligible_cold_catalog_size
            else None
        )
        row["recommendation_concentration"] = _concentration(rankings, k)

    source_contributions: dict[str, Any] = {}
    source_overlap: dict[str, list[float]] = {}
    source_eligible_warm: Counter[str] = Counter()
    source_eligible_cold: Counter[str] = Counter()
    candidate_union_sizes: list[int] = []
    for k in EVALUATION_KS:
        totals: dict[str, float] = {
            _CONTENT_SOURCE: 0.0,
            _POPULARITY_SOURCE: 0.0,
        }
        for result in results.values():
            selected = set(result.fusion.recommended_items[:k])
            for name, values in result.fusion.source_contributions.items():
                totals[name] = totals.get(name, 0.0) + sum(
                    values.get(item, 0.0) for item in selected
                )
        source_contributions[str(k)] = dict(sorted(totals.items()))
    for result in results.values():
        candidate_union_sizes.append(result.fusion.eligible_union_size)
        source_eligible_warm.update(result.source_eligible_warm_counts)
        source_eligible_cold.update(result.source_eligible_cold_counts)
        for pair, score in result.fusion.source_jaccard.items():
            key = "/".join(pair)
            source_overlap.setdefault(key, []).append(score)
    overlap_summary = {
        key: (sum(scores) / len(scores) if scores else 0.0)
        for key, scores in sorted(source_overlap.items())
    }
    return {
        "evaluated_user_count": len(targets),
        "eligible_target_count": sum(len(items) for items in targets.values()),
        "warm_target_count": sum(
            item in benchmark.warm_item_keys
            for items in targets.values()
            for item in items
        ),
        "eligible_cold_target_count": sum(
            item in benchmark.cold_item_keys
            for items in targets.values()
            for item in items
        ),
        "candidate_catalog_size": len(candidate_keys),
        "users_with_no_recommendations": sum(
            not ranking for ranking in rankings.values()
        ),
        "source_contribution_by_k": source_contributions,
        "source_eligible_candidate_occurrences": {
            "warm": dict(sorted(source_eligible_warm.items())),
            "cold": dict(sorted(source_eligible_cold.items())),
        },
        "mean_source_candidate_union_size": (
            sum(candidate_union_sizes) / len(candidate_union_sizes)
            if candidate_union_sizes
            else 0.0
        ),
        "mean_source_jaccard": overlap_summary,
        "metrics_by_k": metrics_by_k,
        "cold_item_metrics": _cold_metrics(
            benchmark, candidate_keys, targets, rankings
        ),
    }


def _pairwise_jaccard(
    left: Mapping[str, Sequence[str]],
    right: Mapping[str, Sequence[str]],
    k: int,
) -> float:
    values: list[float] = []
    for user in sorted(left):
        left_set = set(left[user][:k])
        right_set = set(right[user][:k])
        union = left_set | right_set
        values.append(len(left_set & right_set) / len(union) if union else 1.0)
    return sum(values) / len(values) if values else 0.0


def run_hybrid_benchmark(
    benchmark: SyntheticContentBenchmark,
    *,
    code_revision: str,
    working_tree_dirty: bool = False,
) -> HybridBenchmarkRun:
    """Run exactly four frozen methods for two policies; persist aggregates only."""
    if not isinstance(code_revision, str) or not code_revision.strip():
        raise ValueError("A source code revision is required for reproducibility.")
    if benchmark.seed != DEFAULT_SEED:
        raise ValueError("Phase 4.4B requires the frozen seed-43031 benchmark.")
    if not isinstance(working_tree_dirty, bool):
        raise ValueError("Working-tree dirty state must be a boolean.")

    started = time.perf_counter()
    tracemalloc.start()
    items = benchmark.products_by_key
    references = tuple(items[key] for key in sorted(benchmark.reference_item_keys))
    index = ContentIndex.fit(
        references,
        benchmark.products,
        code_revision=code_revision,
    )
    train_known = frozenset(event.item_key for event in benchmark.training_interactions)
    content_candidates = frozenset(index.candidate_keys)
    warm_candidates = train_known & content_candidates
    policies = {
        HybridCandidatePolicy.WARM_HYBRID: warm_candidates,
        HybridCandidatePolicy.CONTENT_ELIGIBLE_HYBRID: content_candidates,
    }
    policy_reports: dict[str, Any] = {}
    method_rankings: dict[str, dict[str, dict[str, tuple[str, ...]]]] = {}
    method_results: dict[str, dict[str, dict[str, HybridRetrievalResult]]] = {}

    for policy, candidate_keys in policies.items():
        targets = _profile_targets(benchmark, candidate_keys)
        content_rankings = _ranked_by_policy(
            index, benchmark, candidate_keys, "tfidf_user_profile"
        )
        popularity_rankings = _ranked_by_policy(
            index, benchmark, candidate_keys, "popularity"
        )
        method_results[policy.value] = {}
        method_rankings[policy.value] = {}
        for method, weights in _METHOD_CONFIGS.items():
            config = HybridConfig(
                rrf=RRFConfig(
                    rank_constant=_RANK_CONSTANT,
                    source_weights=weights,
                    source_depths={
                        _CONTENT_SOURCE: _SOURCE_DEPTH,
                        _POPULARITY_SOURCE: _SOURCE_DEPTH,
                    },
                ),
                content_source_name=_CONTENT_SOURCE,
            )
            results: dict[str, HybridRetrievalResult] = {}
            rankings: dict[str, tuple[str, ...]] = {}
            for user in benchmark.evaluation_users:
                context = HybridUserContext(
                    user_key=user,
                    training_interactions=benchmark.training_interactions,
                    prediction_time_ms=10_000,
                )
                result = retrieve_hybrid(
                    context=context,
                    content_index=index,
                    collaborative_rankings={
                        _POPULARITY_SOURCE: popularity_rankings[user]
                    },
                    content_ranking=content_rankings[user],
                    train_known_item_keys=set(train_known),
                    candidate_policy=policy,
                    config=config,
                    k=_SOURCE_DEPTH,
                )
                results[user] = result
                rankings[user] = result.fusion.recommended_items
            method_results[policy.value][method] = results
            method_rankings[policy.value][method] = rankings
        report_methods = {
            method: _method_report(
                benchmark=benchmark,
                candidate_keys=candidate_keys,
                targets=targets,
                results=method_results[policy.value][method],
            )
            for method in _METHOD_CONFIGS
        }
        warm_target_count = sum(
            item in benchmark.warm_item_keys
            for values in targets.values()
            for item in values
        )
        eligible_cold_target_count = sum(
            item in benchmark.cold_item_keys
            for values in targets.values()
            for item in values
        )
        eligible_cold_user_denominator = sum(
            any(item in benchmark.cold_item_keys for item in values)
            for values in targets.values()
        )
        policy_reports[policy.value] = {
            "candidate_catalog_size": len(candidate_keys),
            "warm_candidate_count": len(candidate_keys & benchmark.warm_item_keys),
            "cold_candidate_count": len(candidate_keys & benchmark.cold_item_keys),
            "evaluated_user_count": len(targets),
            "warm_target_count": warm_target_count,
            "eligible_cold_target_count": eligible_cold_target_count,
            "eligible_cold_user_denominator": eligible_cold_user_denominator,
            "methods": report_methods,
        }

    comparisons: dict[str, Any] = {}
    comparison_pairs = (
        ("hybrid_a", "content_only"),
        ("hybrid_a", "popularity_only"),
        ("hybrid_b", "content_only"),
        ("hybrid_b", "popularity_only"),
        ("hybrid_a", "hybrid_b"),
    )
    for policy_name, methods in method_rankings.items():
        pairs: dict[str, Any] = {}
        report_methods = policy_reports[policy_name]["methods"]
        for left, right in comparison_pairs:
            by_k: dict[str, Any] = {}
            for k in EVALUATION_KS:
                key = str(k)
                left_report = report_methods[left]
                right_report = report_methods[right]
                left_metrics = left_report["metrics_by_k"][key]
                right_metrics = right_report["metrics_by_k"][key]
                left_cold = left_report["cold_item_metrics"]["metrics_by_k"][key]
                right_cold = right_report["cold_item_metrics"]["metrics_by_k"][key]
                by_k[key] = {
                    metric: left_metrics[metric] - right_metrics[metric]
                    for metric in ("recall", "ndcg", "hit_rate", "mrr")
                }
                by_k[key]["final_catalog_coverage_delta"] = (
                    left_metrics["final_catalog_coverage"]
                    - right_metrics["final_catalog_coverage"]
                )
                by_k[key]["cold_recall_delta"] = (
                    None
                    if left_cold["macro_cold_recall"] is None
                    or right_cold["macro_cold_recall"] is None
                    else left_cold["macro_cold_recall"]
                    - right_cold["macro_cold_recall"]
                )
                by_k[key]["exposure_hhi_delta"] = (
                    left_metrics["recommendation_concentration"][
                        "herfindahl_hirschman_index"
                    ]
                    - right_metrics["recommendation_concentration"][
                        "herfindahl_hirschman_index"
                    ]
                )
                by_k[key]["mean_per_user_list_jaccard"] = _pairwise_jaccard(
                    methods[left], methods[right], k
                )
            pairs[f"{left}_minus_{right}"] = {"by_k": by_k}
        comparisons[policy_name] = pairs

    users_with_prior_history = {
        event.user_key
        for event in benchmark.training_interactions
        if event.event_time_ms < 10_000
    }
    empty_history_count = sum(
        user not in users_with_prior_history for user in benchmark.evaluation_users
    )
    cold_textless_count = sum(
        not items[item_key].fields for item_key in benchmark.cold_item_keys
    )
    cold_zero_vector_count = sum(
        bool(items[item_key].fields)
        and items[item_key].catalog_eligible
        and item_key not in content_candidates
        for item_key in benchmark.cold_item_keys
    )
    content_eligible_popularity = _ranked_by_policy(
        index,
        benchmark,
        policies[HybridCandidatePolicy.CONTENT_ELIGIBLE_HYBRID],
        "popularity",
    )
    short_popularity_users = sum(
        len(content_eligible_popularity[user]) < _SOURCE_DEPTH
        for user in benchmark.evaluation_users
    )
    aggregate: dict[str, Any] = {
        "schema": HYBRID_BENCHMARK_SCHEMA,
        "benchmark_version": HYBRID_BENCHMARK_VERSION,
        "seed": benchmark.seed,
        "source_benchmark": {
            "schema": benchmark.generator_schema,
            "source_manifest_sha256": _sha256(benchmark.manifest_bytes),
            "source_checksums": dict(sorted(benchmark.source_checksums.items())),
            "synthetic_catalog_sha256": index.catalog_manifest_sha256,
            "tfidf_vocabulary_sha256": index.vocabulary_sha256,
        },
        "configuration": {
            "methods": {
                name: dict(weights) for name, weights in _METHOD_CONFIGS.items()
            },
            "rank_constant": _RANK_CONSTANT,
            "source_depth": _SOURCE_DEPTH,
            "final_k": list(EVALUATION_KS),
            "content_source": _CONTENT_SOURCE,
            "popularity_source": _POPULARITY_SOURCE,
            "positive_rating_threshold": int(POSITIVE_MIN_RATING),
            "popularity_counting": "distinct positive training user/item pairs",
            "popularity_tie_break": "canonical synthetic item key ascending",
        },
        "candidate_policies": policy_reports,
        "comparisons": comparisons,
        "robustness_scenarios": {
            "strong_content_relevance": {
                "fixed_fixture_warm_positive_target_count": policy_reports[
                    HybridCandidatePolicy.WARM_HYBRID.value
                ]["warm_target_count"]
            },
            "training_popularity_alignment_mismatch": {
                "popularity_is_train_only": True,
                "content_vs_popularity_comparison_reported": True,
            },
            "content_bearing_cold_positives": {
                "eligible_cold_target_count": policy_reports[
                    HybridCandidatePolicy.CONTENT_ELIGIBLE_HYBRID.value
                ]["eligible_cold_target_count"]
            },
            "unseen_vocabulary_cold_items": {
                "cold_candidate_excluded_for_zero_vector_count": cold_zero_vector_count
            },
            "missing_metadata_cold_items": {"count": cold_textless_count},
            "conflicted_metadata_cold_items": {
                "count": sum(
                    not item.catalog_eligible
                    for item in benchmark.products
                    if item.item_key in benchmark.cold_item_keys
                )
            },
            "empty_user_histories": empty_history_count,
            "source_overlap_and_disagreement": {
                "source_jaccard_is_reported_per_method_and_policy": True,
                "source_jaccard_uses_both_source_lists": True,
            },
            "short_popularity_source_lists": {
                "user_count_shorter_than_source_depth": short_popularity_users,
                "source_depth": _SOURCE_DEPTH,
            },
        },
        "reproducibility": {
            "code_revision": code_revision,
            "working_tree_dirty": working_tree_dirty,
            "aggregate_only": True,
            "per_user_rankings_persisted": False,
            "runtime_and_memory_excluded_from_manifest": True,
        },
        "limitations": [
            "All users, products, interactions, and labels are invented "
            "fixture records.",
            "Synthetic runtime and metrics do not estimate production performance.",
            "No statistical significance or real-world gain is inferred.",
            "Popularity is a source control, not a trained collaborative model.",
        ],
        "phase_boundary": "Phase 4.2C remains ON HOLD.",
    }
    manifest_bytes = _canonical_bytes(aggregate) + b"\n"
    manifest_sha256 = _sha256(manifest_bytes)
    _, peak_traced_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return HybridBenchmarkRun(
        aggregate=aggregate,
        manifest_bytes=manifest_bytes,
        manifest_sha256=manifest_sha256,
        runtime_seconds=time.perf_counter() - started,
        peak_traced_bytes=peak_traced_bytes,
    )
