"""Frozen synthetic-only Phase 4.4B benchmark contracts."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from recfusion_ml.evaluation.content_benchmark import (
    _ranked_by_policy,
    generate_synthetic_benchmark,
)
from recfusion_ml.evaluation.hybrid_benchmark import (
    _concentration,
    run_hybrid_benchmark,
)
from recfusion_ml.retrieval.content import ContentIndex

pytestmark = pytest.mark.unit


def test_recommendation_concentration_matches_hand_calculated_placements() -> None:
    concentration = _concentration(
        {"u1": ("a", "b"), "u2": ("a", "c")},
        k=2,
    )

    # Four placements: a has 2/4 and b/c each have 1/4.
    assert concentration == {
        "unique_recommended_item_count": 3,
        "recommendation_count": 4,
        "maximum_item_exposure_share": 0.5,
        "herfindahl_hirschman_index": 0.375,
    }


def test_recommendation_concentration_is_zero_for_empty_rankings() -> None:
    assert _concentration({"u1": (), "u2": ()}, k=5) == {
        "unique_recommended_item_count": 0,
        "recommendation_count": 0,
        "maximum_item_exposure_share": 0.0,
        "herfindahl_hirschman_index": 0.0,
    }


def test_hybrid_benchmark_is_fixed_aggregate_only_and_reproducible() -> None:
    benchmark = generate_synthetic_benchmark(seed=43031)

    first = run_hybrid_benchmark(
        benchmark, code_revision="synthetic-hybrid-benchmark-test"
    )
    second = run_hybrid_benchmark(
        benchmark, code_revision="synthetic-hybrid-benchmark-test"
    )

    assert first.manifest_bytes == second.manifest_bytes
    assert first.manifest_sha256 == second.manifest_sha256
    assert set(first.aggregate["candidate_policies"]) == {
        "warm_hybrid",
        "content_eligible_hybrid",
    }
    for policy in first.aggregate["candidate_policies"].values():
        assert set(policy["methods"]) == {
            "content_only",
            "popularity_only",
            "hybrid_a",
            "hybrid_b",
        }
        for method in policy["methods"].values():
            assert set(method["metrics_by_k"]) == {"5", "10", "20"}
            assert method["evaluated_user_count"] == len(benchmark.evaluation_users)
    serialized = json.loads(first.manifest_bytes)
    assert serialized["reproducibility"]["aggregate_only"] is True
    assert serialized["reproducibility"]["per_user_rankings_persisted"] is False
    assert "user_key" not in serialized


def test_hybrid_benchmark_uses_fixed_popularity_and_cold_denominators() -> None:
    benchmark = generate_synthetic_benchmark(seed=43031)
    result = run_hybrid_benchmark(
        benchmark, code_revision="synthetic-hybrid-benchmark-test"
    )
    aggregate = result.aggregate

    assert aggregate["configuration"]["rank_constant"] == 60
    assert aggregate["configuration"]["source_depth"] == 20
    assert aggregate["configuration"]["positive_rating_threshold"] == 4
    assert aggregate["configuration"]["popularity_counting"] == (
        "distinct positive training user/item pairs"
    )
    warm = aggregate["candidate_policies"]["warm_hybrid"]
    assert warm["candidate_catalog_size"] == 24
    assert warm["methods"]["content_only"]["metrics_by_k"]["5"]["recall"] == 0.875
    assert warm["methods"]["popularity_only"]["metrics_by_k"]["10"]["recall"] == 0
    assert warm["methods"]["popularity_only"]["metrics_by_k"]["20"]["recall"] == 0.75
    eligible = aggregate["candidate_policies"]["content_eligible_hybrid"]
    assert eligible["candidate_catalog_size"] == 32
    assert eligible["eligible_cold_target_count"] == 8
    assert eligible["eligible_cold_user_denominator"] == 8
    assert (
        eligible["methods"]["hybrid_a"]["cold_item_metrics"][
            "eligible_target_denominator"
        ]
        == 8
    )
    for method in eligible["methods"].values():
        assert (
            method["source_eligible_candidate_occurrences"]["cold"]["popularity"] == 0
        )
    assert aggregate["phase_boundary"] == "Phase 4.2C remains ON HOLD."


def test_popularity_ranking_is_independent_of_held_out_labels() -> None:
    benchmark = generate_synthetic_benchmark(seed=43031)
    items = benchmark.products_by_key
    index = ContentIndex.fit(
        tuple(items[key] for key in sorted(benchmark.reference_item_keys)),
        benchmark.products,
        code_revision="synthetic-hybrid-benchmark-test",
    )
    changed_labels = replace(
        benchmark,
        evaluation_events=tuple(
            replace(event, rating=Decimal("1")) for event in benchmark.evaluation_events
        ),
    )
    candidates = frozenset(index.candidate_keys)

    original = _ranked_by_policy(index, benchmark, candidates, "popularity")
    changed = _ranked_by_policy(index, changed_labels, candidates, "popularity")

    assert original == changed
