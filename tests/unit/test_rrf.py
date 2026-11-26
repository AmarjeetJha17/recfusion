from decimal import Decimal

import pytest

from recfusion_ml.evaluation.fusion import summarize_fusion
from recfusion_ml.evaluation.fusion_pilot import _orient_paired_statistic
from recfusion_ml.evaluation.metrics import build_validation_cohort, evaluate_rankings
from recfusion_ml.ranking.rrf import RRFConfig, fuse_ranked_candidates
from recfusion_ml.types import RatingEvent


def test_rrf_uses_one_based_ranks_and_sums_weighted_contributions() -> None:
    result = fuse_ranked_candidates(
        {"alpha": ["a", "b"], "beta": ["b", "c"]},
        candidate_items={"a", "b", "c"},
        k=3,
        config=RRFConfig(rank_constant=1, source_weights={"alpha": 2, "beta": 1}),
    )

    assert result.recommended_items == ("b", "a", "c")
    assert result.scores == pytest.approx({"a": 1.0, "b": 7 / 6, "c": 1 / 3})
    assert result.source_provenance["b"] == ("alpha", "beta")
    assert result.source_contributions["alpha"]["a"] == 1.0
    assert result.source_contributions["beta"]["b"] == pytest.approx(1 / 2)


def test_rrf_applies_source_depth_before_pool_and_seen_filters() -> None:
    result = fuse_ranked_candidates(
        {"model": ["seen", "outside", "a", "b"]},
        candidate_items={"seen", "a", "b"},
        seen_items={"seen"},
        k=5,
        config=RRFConfig(source_depths={"model": 3}),
    )

    assert result.recommended_items == ("a",)
    assert result.depth_truncated_counts["model"] == 1
    assert result.outside_pool_counts["model"] == 1
    assert result.seen_excluded_counts["model"] == 1
    assert result.eligible_union_size == 1
    assert result.raw_generated_counts["model"] == sum(
        (
            result.depth_truncated_counts["model"],
            result.outside_pool_counts["model"],
            result.source_candidate_excluded_counts["model"],
            result.seen_excluded_counts["model"],
            result.eligible_counts["model"],
        )
    )


def test_rrf_applies_source_candidate_pool_without_rank_compression() -> None:
    result = fuse_ranked_candidates(
        {"collaborative": ["cold", "warm"]},
        candidate_items={"cold", "warm"},
        source_candidate_items={"collaborative": {"warm"}},
        k=2,
        config=RRFConfig(rank_constant=1),
    )

    assert result.recommended_items == ("warm",)
    assert result.scores == {"warm": pytest.approx(1 / 3)}
    assert result.source_candidate_excluded_counts == {"collaborative": 1}
    assert result.raw_generated_counts["collaborative"] == 2
    assert result.eligible_counts["collaborative"] == 1


def test_source_pool_filter_keeps_original_rank_three_contribution() -> None:
    result = fuse_ranked_candidates(
        {"content": ("first", "excluded", "third")},
        candidate_items={"first", "excluded", "third"},
        source_candidate_items={"content": {"first", "third"}},
        k=3,
        config=RRFConfig(
            rank_constant=60,
            source_weights={"content": 1.0},
            source_depths={"content": 20},
        ),
    )

    assert result.recommended_items == ("first", "third")
    assert result.source_contributions["content"]["third"] == 1 / 63


def test_rrf_source_candidate_pools_must_be_subsets_of_global_pool() -> None:
    with pytest.raises(ValueError, match="source candidate pool"):
        fuse_ranked_candidates(
            {"model": ["a"]},
            candidate_items={"a"},
            source_candidate_items={"model": {"outside"}},
            k=1,
        )


def test_rrf_accepts_missing_and_empty_sources_without_fallback() -> None:
    result = fuse_ranked_candidates(
        {"two_tower": [], "bpr": ["outside"]},
        candidate_items={"catalog_item"},
        k=5,
        config=RRFConfig(source_weights={"two_tower": 1, "bpr": 1, "item_cf": 1}),
    )

    assert result.recommended_items == ()
    assert result.source_names == ("bpr", "item_cf", "two_tower")
    assert result.raw_generated_counts == {"bpr": 1, "item_cf": 0, "two_tower": 0}


def test_zero_weight_source_is_audited_but_cannot_add_candidates() -> None:
    result = fuse_ranked_candidates(
        {"active": ["a"], "disabled": ["b"]},
        candidate_items={"a", "b"},
        k=2,
        config=RRFConfig(source_weights={"active": 1, "disabled": 0}),
    )

    assert result.recommended_items == ("a",)
    assert result.eligible_counts == {"active": 1, "disabled": 1}
    assert result.eligible_union_size == 1


def test_rrf_uses_lexical_tie_break_and_is_input_order_independent() -> None:
    config = RRFConfig(rank_constant=10)
    first = fuse_ranked_candidates(
        {"z": ["b", "a"], "a": ["a", "b"]},
        candidate_items={"a", "b"},
        k=2,
        config=config,
    )
    reordered = fuse_ranked_candidates(
        {"a": ["a", "b"], "z": ["b", "a"]},
        candidate_items={"b", "a"},
        k=2,
        config=config,
    )

    assert first.recommended_items == ("a", "b")
    assert first == reordered


def test_fusion_diagnostics_distinguish_union_from_final_catalog_coverage() -> None:
    first = fuse_ranked_candidates(
        {"alpha": ["a", "b"], "beta": ["b", "c"]},
        candidate_items={"a", "b", "c", "d"},
        k=3,
        config=RRFConfig(rank_constant=1),
    )
    diagnostics = summarize_fusion(
        {"u1": first}, candidate_items={"a", "b", "c", "d"}, ks=(1, 5)
    )

    assert diagnostics.eligible_union_coverage == 3 / 4
    assert diagnostics.by_k[1]["final_catalog_coverage"] == 1 / 4
    assert diagnostics.by_k[1]["unique_recommended_item_count"] == 1
    assert diagnostics.by_k[5]["users_short_of_k"] == 1
    assert diagnostics.by_k[5]["frequency_histogram"] == {
        "0": 1,
        "1": 3,
        "2-5": 0,
        "6-10": 0,
        ">10": 0,
    }
    assert diagnostics.source_recommendation_attribution_counts == {
        "alpha": 2,
        "beta": 2,
    }
    assert diagnostics.by_k[5]["source_attribution_counts"] == {
        "alpha": 2,
        "beta": 2,
    }
    assert diagnostics.by_k[5]["source_exclusive_attribution_counts"] == {
        "alpha": 1,
        "beta": 1,
    }
    assert diagnostics.by_k[5]["source_attribution_shares"] == {
        "alpha": pytest.approx(2 / 3),
        "beta": pytest.approx(2 / 3),
    }
    assert diagnostics.source_pair_mean_jaccard[("alpha", "beta")] == 1 / 3
    assert diagnostics.source_pair_mean_disagreement[
        ("alpha", "beta")
    ] == pytest.approx(2 / 3)


@pytest.mark.parametrize(
    ("kind", "match"),
    [
        ("duplicate", "duplicate"),
        ("empty_id", "non-empty"),
        ("rank_constant", "positive"),
        ("negative_weight", "non-negative"),
        ("zero_weight", "positive effective"),
    ],
)
def test_rrf_rejects_invalid_source_data_and_configuration(kind, match) -> None:
    with pytest.raises(ValueError, match=match):
        _raise_for_invalid_case(kind)


def _raise_for_invalid_case(kind: str) -> None:
    if kind == "duplicate":
        fuse_ranked_candidates({"m": ["a", "a"]}, candidate_items={"a"}, k=1)
    elif kind == "empty_id":
        fuse_ranked_candidates({"m": [""]}, candidate_items={"a"}, k=1)
    elif kind == "rank_constant":
        RRFConfig(rank_constant=0)
    elif kind == "negative_weight":
        RRFConfig(source_weights={"m": -1})
    else:
        fuse_ranked_candidates(
            {"m": ["a"]},
            candidate_items={"a"},
            k=1,
            config=RRFConfig(source_weights={"m": 0}),
        )


def test_fused_lists_remain_compatible_with_frozen_validation_evaluator() -> None:
    train = [
        RatingEvent("u1", "seen", Decimal("5"), "train"),
        RatingEvent("u2", "a", Decimal("4"), "train"),
        RatingEvent("u3", "b", Decimal("4"), "train"),
    ]
    validation = [RatingEvent("u1", "b", Decimal("5"), "validation")]
    cohort = build_validation_cohort(train, validation, {"seen", "a", "b"})
    fused = fuse_ranked_candidates(
        {"tower": ["seen", "b"], "bpr": ["a", "b"]},
        candidate_items=cohort.candidate_items,
        seen_items=cohort.seen_items_by_user["u1"],
        k=5,
        config=RRFConfig(),
    )

    result = evaluate_rankings(
        cohort,
        {"u1": fused.recommended_items},
        candidate_items=cohort.candidate_items,
        ks=(1, 5),
    )

    assert result.evaluated_user_count == 1
    assert result.eligible_positive_target_count == 1
    assert result.metrics_by_k[1].recall == 1
    assert result.metrics_by_k[5].candidate_coverage == 2 / 3


def test_paired_statistics_reverse_orientation_and_confidence_interval() -> None:
    oriented = _orient_paired_statistic(
        {
            "mean_difference": -0.2,
            "wins": 2,
            "losses": 6,
            "ties": 1,
            "win_rate": 2 / 9,
            "loss_rate": 6 / 9,
            "tie_rate": 1 / 9,
            "bootstrap_95_percentile_ci": [-0.3, -0.1],
        },
        reverse=True,
    )

    assert oriented["mean_difference"] == 0.2
    assert oriented["wins"] == 6
    assert oriented["losses"] == 2
    assert oriented["ties"] == 1
    assert oriented["bootstrap_95_percentile_ci"] == [0.1, 0.3]
