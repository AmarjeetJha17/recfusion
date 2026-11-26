"""End-to-end synthetic hybrid retrieval smoke test."""

from __future__ import annotations

import pytest

from recfusion_ml.evaluation.content_benchmark import generate_synthetic_benchmark
from recfusion_ml.ranking.rrf import RRFConfig
from recfusion_ml.retrieval.content import ContentIndex
from recfusion_ml.retrieval.hybrid import (
    HybridCandidatePolicy,
    HybridConfig,
    HybridUserContext,
    retrieve_hybrid,
    summarize_hybrid,
)

pytestmark = pytest.mark.integration


def test_synthetic_catalog_user_profiles_and_ranked_sources_fuse_end_to_end() -> None:
    benchmark = generate_synthetic_benchmark(seed=44041)
    items = benchmark.products_by_key
    reference_items = tuple(items[key] for key in sorted(benchmark.reference_item_keys))
    index = ContentIndex.fit(
        reference_items,
        benchmark.products,
        code_revision="synthetic-hybrid-integration-test",
    )
    vocabulary_sha256 = index.vocabulary_sha256
    train_items = frozenset(event.item_key for event in benchmark.training_interactions)
    ordered_train_items = tuple(sorted(train_items))
    config = HybridConfig(
        rrf=RRFConfig(
            rank_constant=60,
            source_weights={
                "item_cf": 1.0,
                "bpr": 1.0,
                "two_tower": 0.0,
                "tfidf_content": 1.0,
            },
            source_depths={
                "item_cf": 20,
                "bpr": 20,
                "two_tower": 20,
                "tfidf_content": 20,
            },
        )
    )
    results = []
    for user_key in benchmark.evaluation_users:
        context = HybridUserContext(
            user_key=user_key,
            training_interactions=benchmark.training_interactions,
            prediction_time_ms=10_000,
        )
        results.append(
            retrieve_hybrid(
                context=context,
                content_index=index,
                collaborative_rankings={
                    "item_cf": ordered_train_items[:2],
                    "bpr": tuple(reversed(ordered_train_items[2:5])),
                },
                train_known_item_keys=train_items,
                candidate_policy=HybridCandidatePolicy.CONTENT_ELIGIBLE_HYBRID,
                config=config,
                k=20,
            )
        )

    diagnostics = summarize_hybrid(results, ks=(5, 10, 20))
    assert len(results) == 16
    assert diagnostics.candidate_pool_item_count == 32
    assert diagnostics.warm_candidate_count == 24
    assert diagnostics.cold_candidate_count == 8
    assert diagnostics.fusion.source_raw_generated_counts["two_tower"] == 0
    assert diagnostics.source_candidate_excluded_counts["item_cf"] == 0
    assert diagnostics.by_k[20]["final_cold_recommendation_count"] > 0
    assert diagnostics.by_k[20]["source_rank_contribution_by_kind"]["content"] > 0
    assert index.vocabulary_sha256 == vocabulary_sha256
    for result in results:
        assert set(result.fusion.recommended_items) <= result.candidate_item_keys
        assert result.fusion.source_candidate_excluded_counts["two_tower"] == 0
