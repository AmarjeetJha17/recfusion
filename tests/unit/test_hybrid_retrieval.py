"""Synthetic-only contracts for collaborative/content hybrid retrieval."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from recfusion_core.contracts import DataSplit
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

pytestmark = pytest.mark.unit

_SEED = 44041
_REVISION = "synthetic-hybrid-retrieval-test"
_CONTENT_SOURCE = "tfidf_content"
_COLLAB_SOURCE = "item_cf"


def _scenario():
    benchmark = generate_synthetic_benchmark(seed=_SEED)
    items = benchmark.products_by_key
    references = tuple(items[key] for key in sorted(benchmark.reference_item_keys))
    index = ContentIndex.fit(
        references,
        benchmark.products,
        code_revision=_REVISION,
    )
    train_items = frozenset(event.item_key for event in benchmark.training_interactions)
    return benchmark, index, train_items


def _config(
    *,
    content_weight: float = 1.0,
    collaborative_weight: float = 1.0,
    depth: int = 20,
    rank_constant: float = 60,
) -> HybridConfig:
    return HybridConfig(
        rrf=RRFConfig(
            rank_constant=rank_constant,
            source_weights={
                _COLLAB_SOURCE: collaborative_weight,
                _CONTENT_SOURCE: content_weight,
            },
            source_depths={_COLLAB_SOURCE: depth, _CONTENT_SOURCE: depth},
        ),
        content_source_name=_CONTENT_SOURCE,
    )


def _context(benchmark, user_key: str) -> HybridUserContext:
    return HybridUserContext(
        user_key=user_key,
        training_interactions=benchmark.training_interactions,
        prediction_time_ms=10_000,
    )


def test_warm_policy_restricts_candidate_union_to_train_known_items() -> None:
    benchmark, index, train_items = _scenario()
    cold_item = next(key for key in index.candidate_keys if key not in train_items)
    user = benchmark.evaluation_users[0]

    result = retrieve_hybrid(
        context=_context(benchmark, user),
        content_index=index,
        collaborative_rankings={_COLLAB_SOURCE: (cold_item,)},
        train_known_item_keys=train_items,
        candidate_policy=HybridCandidatePolicy.WARM_HYBRID,
        config=_config(),
        k=10,
    )

    assert result.candidate_item_keys == train_items
    assert cold_item not in result.fusion.scores
    assert result.fusion.outside_pool_counts[_COLLAB_SOURCE] == 1
    assert result.cold_candidate_count == 0


def test_content_eligible_policy_adds_cold_content_but_not_to_collaborative_pool() -> (
    None
):
    benchmark, index, train_items = _scenario()
    cold_item = next(key for key in index.candidate_keys if key not in train_items)

    result = retrieve_hybrid(
        context=_context(benchmark, benchmark.evaluation_users[0]),
        content_index=index,
        collaborative_rankings={_COLLAB_SOURCE: (cold_item,)},
        train_known_item_keys=train_items,
        candidate_policy=HybridCandidatePolicy.CONTENT_ELIGIBLE_HYBRID,
        config=_config(content_weight=0.0),
        k=10,
    )

    assert result.fusion.outside_pool_counts[_COLLAB_SOURCE] == 0
    assert result.fusion.source_candidate_excluded_counts[_COLLAB_SOURCE] == 1

    assert cold_item in result.candidate_item_keys
    assert cold_item not in result.fusion.scores
    assert result.fusion.source_candidate_excluded_counts[_COLLAB_SOURCE] == 1
    assert result.cold_candidate_count > 0


def test_precomputed_content_ranking_uses_the_content_source_pool() -> None:
    benchmark, index, train_items = _scenario()
    warm_content_item = next(key for key in index.candidate_keys if key in train_items)
    restricted_index = replace(
        index,
        candidate_keys=tuple(
            key for key in index.candidate_keys if key != warm_content_item
        ),
        candidate_vectors={
            key: value
            for key, value in index.candidate_vectors.items()
            if key != warm_content_item
        },
        eligible_candidate_count=index.eligible_candidate_count - 1,
    )

    result = retrieve_hybrid(
        context=_context(benchmark, benchmark.evaluation_users[0]),
        content_index=restricted_index,
        collaborative_rankings={},
        content_ranking=(warm_content_item,),
        train_known_item_keys=train_items,
        candidate_policy=HybridCandidatePolicy.WARM_HYBRID,
        config=_config(),
        k=5,
    )

    assert warm_content_item not in result.fusion.scores
    assert result.fusion.source_candidate_excluded_counts[_CONTENT_SOURCE] == 1


def test_content_source_can_rank_an_eligible_cold_item_in_final_top_k() -> None:
    benchmark, index, train_items = _scenario()
    cold_items = set(index.candidate_keys) - set(train_items)
    target_context = None
    target_item = None
    for event in benchmark.evaluation_events:
        if event.item_key in cold_items:
            context = _context(benchmark, event.user_key)
            profile = index.profile_from_training_history(
                context.training_interactions,
                user_key=context.user_key,
                prediction_time_ms=context.prediction_time_ms,
            )
            content = index.recommend_for_profile(
                profile,
                k=5,
                eligible_item_keys=cold_items,
            )
            if any(match.item_key == event.item_key for match in content.items):
                target_context = context
                target_item = event.item_key
                break
    assert target_context is not None
    assert target_item is not None

    result = retrieve_hybrid(
        context=target_context,
        content_index=index,
        collaborative_rankings={_COLLAB_SOURCE: ()},
        train_known_item_keys=train_items,
        candidate_policy=HybridCandidatePolicy.CONTENT_ELIGIBLE_HYBRID,
        config=_config(depth=20),
        k=10,
    )

    assert target_item in result.fusion.recommended_items
    assert target_item in result.fusion.source_provenance
    assert _CONTENT_SOURCE in result.fusion.source_provenance[target_item]


def test_seen_items_are_filtered_from_collaborative_and_content_sources() -> None:
    benchmark, index, train_items = _scenario()
    user = next(
        event.user_key
        for event in benchmark.training_interactions
        if event.item_key in train_items
    )
    seen = next(
        event.item_key
        for event in benchmark.training_interactions
        if event.user_key == user and event.event_time_ms < 10_000
    )

    result = retrieve_hybrid(
        context=_context(benchmark, user),
        content_index=index,
        collaborative_rankings={_COLLAB_SOURCE: (seen,)},
        train_known_item_keys=train_items,
        candidate_policy=HybridCandidatePolicy.CONTENT_ELIGIBLE_HYBRID,
        config=_config(),
        k=20,
    )

    assert seen not in result.fusion.recommended_items
    assert result.fusion.seen_excluded_counts[_COLLAB_SOURCE] == 1


def test_missing_conflicted_and_zero_vector_products_are_not_content_candidates() -> (
    None
):
    benchmark, index, train_items = _scenario()
    ineligible = {
        "synthetic_cold_missing_metadata",
        "synthetic_cold_conflicted_metadata",
        "synthetic_cold_laptop_gaming_unseen",
    }

    assert ineligible.isdisjoint(index.candidate_keys)
    result = retrieve_hybrid(
        context=_context(benchmark, benchmark.evaluation_users[0]),
        content_index=index,
        collaborative_rankings={_COLLAB_SOURCE: tuple(sorted(ineligible))},
        train_known_item_keys=train_items,
        candidate_policy=HybridCandidatePolicy.CONTENT_ELIGIBLE_HYBRID,
        config=_config(content_weight=0.0),
        k=20,
    )
    assert ineligible.isdisjoint(result.candidate_item_keys)
    assert result.fusion.outside_pool_counts[_COLLAB_SOURCE] == len(ineligible)


def test_foreign_and_source_ineligible_candidates_have_audited_counts() -> None:
    benchmark, index, train_items = _scenario()
    cold_item = next(key for key in index.candidate_keys if key not in train_items)

    result = retrieve_hybrid(
        context=_context(benchmark, benchmark.evaluation_users[0]),
        content_index=index,
        collaborative_rankings={_COLLAB_SOURCE: ("foreign_item", cold_item)},
        train_known_item_keys=train_items,
        candidate_policy=HybridCandidatePolicy.CONTENT_ELIGIBLE_HYBRID,
        config=_config(content_weight=0.0),
        k=10,
    )
    assert result.fusion.outside_pool_counts[_COLLAB_SOURCE] == 1
    assert result.fusion.source_candidate_excluded_counts[_COLLAB_SOURCE] == 1
    assert result.fusion.raw_generated_counts[_COLLAB_SOURCE] == 2
    assert result.fusion.raw_generated_counts[_COLLAB_SOURCE] == (
        result.fusion.depth_truncated_counts[_COLLAB_SOURCE]
        + result.fusion.outside_pool_counts[_COLLAB_SOURCE]
        + result.fusion.source_candidate_excluded_counts[_COLLAB_SOURCE]
        + result.fusion.seen_excluded_counts[_COLLAB_SOURCE]
        + result.fusion.eligible_counts[_COLLAB_SOURCE]
    )


def test_source_depth_is_independent_of_the_final_k_cutoff() -> None:
    benchmark, index, train_items = _scenario()
    ranking = tuple(sorted(train_items))[:3]
    config = HybridConfig(
        rrf=RRFConfig(
            rank_constant=1,
            source_weights={_COLLAB_SOURCE: 1.0, _CONTENT_SOURCE: 0.0},
            source_depths={_COLLAB_SOURCE: 2, _CONTENT_SOURCE: 2},
        ),
        content_source_name=_CONTENT_SOURCE,
    )

    result = retrieve_hybrid(
        context=_context(benchmark, "synthetic_user_without_history"),
        content_index=index,
        collaborative_rankings={_COLLAB_SOURCE: ranking},
        train_known_item_keys=train_items,
        candidate_policy=HybridCandidatePolicy.WARM_HYBRID,
        config=config,
        k=1,
    )

    assert result.fusion.recommended_items == ranking[:1]
    assert result.fusion.scores[ranking[0]] == pytest.approx(1 / 2)
    assert result.fusion.depth_truncated_counts[_COLLAB_SOURCE] == 1


def test_empty_history_has_empty_content_source_but_no_fabricated_fallback() -> None:
    benchmark, index, train_items = _scenario()
    user = "synthetic_user_without_history"

    result = retrieve_hybrid(
        context=_context(benchmark, user),
        content_index=index,
        collaborative_rankings={},
        train_known_item_keys=train_items,
        candidate_policy=HybridCandidatePolicy.CONTENT_ELIGIBLE_HYBRID,
        config=_config(),
        k=10,
    )

    assert result.content_profile_empty is True
    assert result.fusion.recommended_items == ()
    assert result.fusion.raw_generated_counts == {
        _COLLAB_SOURCE: 0,
        _CONTENT_SOURCE: 0,
    }


def test_future_or_nontraining_history_rows_are_rejected_or_excluded() -> None:
    benchmark, index, train_items = _scenario()
    user = benchmark.evaluation_users[0]
    base = next(
        event for event in benchmark.training_interactions if event.user_key == user
    )
    future = replace(base, event_time_ms=10_000)
    future_context = replace(
        _context(benchmark, user),
        training_interactions=(*benchmark.training_interactions, future),
    )
    result = retrieve_hybrid(
        context=future_context,
        content_index=index,
        collaborative_rankings={},
        train_known_item_keys=train_items,
        candidate_policy=HybridCandidatePolicy.WARM_HYBRID,
        config=_config(),
        k=5,
    )
    expected_seen = {
        event.item_key
        for event in benchmark.training_interactions
        if event.user_key == user and event.event_time_ms < 10_000
    }
    assert result.profile_seen_item_count == len(expected_seen)

    heldout = replace(base, split=DataSplit.VALIDATION)
    invalid_context = replace(
        _context(benchmark, user),
        training_interactions=(*benchmark.training_interactions, heldout),
    )
    with pytest.raises(ValueError, match="training-only"):
        retrieve_hybrid(
            context=invalid_context,
            content_index=index,
            collaborative_rankings={},
            train_known_item_keys=train_items,
            candidate_policy=HybridCandidatePolicy.WARM_HYBRID,
            config=_config(),
            k=5,
        )


def test_source_identity_and_depth_configuration_are_explicit() -> None:
    with pytest.raises(ValueError, match="content source"):
        HybridConfig(
            rrf=RRFConfig(
                source_weights={_COLLAB_SOURCE: 1}, source_depths={_COLLAB_SOURCE: 5}
            ),
            content_source_name=_CONTENT_SOURCE,
        )

    with pytest.raises(ValueError, match="Source names"):
        HybridConfig(
            rrf=RRFConfig(
                source_weights={_COLLAB_SOURCE: 1, _CONTENT_SOURCE: 1, "": 1},
                source_depths={_COLLAB_SOURCE: 5, _CONTENT_SOURCE: 5, "": 5},
            ),
            content_source_name=_CONTENT_SOURCE,
        )


def test_aggregate_diagnostics_separate_union_final_warm_cold_and_attribution() -> None:
    benchmark, index, train_items = _scenario()
    cold_items = set(index.candidate_keys) - set(train_items)
    user = benchmark.evaluation_users[0]
    warm_item = next(iter(sorted(train_items)))
    result = retrieve_hybrid(
        context=_context(benchmark, user),
        content_index=index,
        collaborative_rankings={_COLLAB_SOURCE: (warm_item,)},
        train_known_item_keys=train_items,
        candidate_policy=HybridCandidatePolicy.CONTENT_ELIGIBLE_HYBRID,
        config=_config(),
        k=5,
    )
    diagnostics = summarize_hybrid((result,), ks=(1, 5))

    assert diagnostics.fusion.user_count == 1
    assert diagnostics.warm_candidate_count == len(train_items)
    assert diagnostics.cold_candidate_count == len(cold_items)
    assert (
        diagnostics.fusion.eligible_union_item_count
        == result.fusion.eligible_union_size
    )
    assert diagnostics.by_k[5]["final_warm_recommendation_count"] > 0
    assert diagnostics.by_k[5]["source_rank_contribution_by_kind"]["content"] >= 0
    assert diagnostics.source_candidate_excluded_counts[_COLLAB_SOURCE] == 0


def test_repeated_hybrid_execution_is_deterministic_and_keeps_canonical_ids() -> None:
    benchmark, index, train_items = _scenario()
    kwargs = {
        "context": _context(benchmark, benchmark.evaluation_users[0]),
        "content_index": index,
        "collaborative_rankings": {_COLLAB_SOURCE: tuple(sorted(train_items))[:10]},
        "train_known_item_keys": train_items,
        "candidate_policy": HybridCandidatePolicy.CONTENT_ELIGIBLE_HYBRID,
        "config": _config(),
        "k": 10,
    }

    first = retrieve_hybrid(**kwargs)
    second = retrieve_hybrid(**kwargs)

    assert first == second
    assert set(first.fusion.recommended_items) <= first.candidate_item_keys
    seen = {
        event.item_key
        for event in kwargs["context"].training_interactions
        if event.user_key == kwargs["context"].user_key
        and event.event_time_ms < kwargs["context"].prediction_time_ms
    }
    assert set(first.fusion.recommended_items).isdisjoint(seen)


def test_target_mask_and_equal_timestamp_events_remain_out_of_content_history() -> None:
    benchmark, index, train_items = _scenario()
    user = next(
        event.user_key
        for event in benchmark.training_interactions
        if event.rating >= Decimal("4")
    )
    positive = next(
        event
        for event in benchmark.training_interactions
        if event.user_key == user and event.rating >= Decimal("4")
    )
    equal_time = replace(positive, event_time_ms=10_000, item_key="equal_time_item")
    target_context = replace(
        _context(benchmark, user),
        training_interactions=(*benchmark.training_interactions, equal_time),
        target_item_key=positive.item_key,
    )
    result = retrieve_hybrid(
        context=target_context,
        content_index=index,
        collaborative_rankings={},
        train_known_item_keys=train_items | {"equal_time_item"},
        candidate_policy=HybridCandidatePolicy.WARM_HYBRID,
        config=_config(),
        k=5,
    )

    expected_positive_count = len(
        {
            event.item_key
            for event in benchmark.training_interactions
            if event.user_key == user
            and event.event_time_ms < 10_000
            and event.rating >= Decimal("4")
            and event.item_key != positive.item_key
        }
    )
    assert result.profile_positive_item_count == expected_positive_count
    expected_seen_count = len(
        {
            event.item_key
            for event in benchmark.training_interactions
            if event.user_key == user and event.event_time_ms < 10_000
        }
    )
    assert result.profile_seen_item_count == expected_seen_count
