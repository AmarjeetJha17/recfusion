from __future__ import annotations

import math
from decimal import Decimal

import pytest

from recfusion_ml.evaluation.two_tower_diagnostics import (
    _audit_negative_exclusions,
    _cross_recommender_overlap,
    _frequency_summary,
    _gini,
    _pairwise_overlap,
    _pearson,
    _stable_sample,
)
from recfusion_ml.training.two_tower import TwoTowerExample
from recfusion_ml.types import RatingEvent


def test_stable_sample_is_seeded_bounded_and_input_order_independent() -> None:
    values = ("user-1", "user-2", "user-3", "user-4", "user-5")

    first = _stable_sample(values, limit=3, seed=71)
    reordered = _stable_sample(tuple(reversed(values)), limit=3, seed=71)

    assert first == reordered
    assert len(first) == 3
    assert _stable_sample(values, limit=3, seed=72) != first


def test_frequency_summary_counts_zero_items_and_duplicate_lists() -> None:
    rankings = {
        "u1": ("a", "b", "c"),
        "u2": ("a", "b", "d"),
        "u3": ("a", "c", "d"),
    }

    summary = _frequency_summary(rankings, {"a", "b", "c", "d", "e"}, k=2)

    assert summary["placement_count"] == 6
    assert summary["unique_recommended_items"] == 3
    assert summary["zero_frequency_candidate_count"] == 2
    assert summary["top_item_placement_shares"] == {
        "1": pytest.approx(0.5),
        "5": 1.0,
        "10": 1.0,
    }
    assert summary["users_in_duplicate_list_groups"] == 2
    assert summary["distinct_recommendation_lists"] == 2
    assert summary["normalized_entropy_over_full_candidate_pool"] == pytest.approx(
        -(0.5 * math.log(0.5) + (1 / 3) * math.log(1 / 3) + (1 / 6) * math.log(1 / 6))
        / math.log(5)
    )
    assert summary["gini_over_full_candidate_pool"] == pytest.approx(16 / 30)


def test_pairwise_overlap_uses_bounded_deterministic_users() -> None:
    rankings = {f"u{index}": ("a", f"item-{index}") for index in range(10)}
    rankings["u9"] = ("a", "item-0")

    first = _pairwise_overlap(rankings, k=2, seed=9, limit=4)
    second = _pairwise_overlap(rankings, k=2, seed=9, limit=4)

    assert first == second
    assert first["sampled_user_count"] == 4
    assert first["pair_count"] == 6
    assert first["mean"] is not None


def test_cross_recommender_overlap_requires_same_users_and_reports_aggregate_only() -> (
    None
):
    two_tower = {"u1": ("a", "b"), "u2": ("b", "c")}
    popularity = {"u1": ("a", "c"), "u2": ("a", "c")}

    result = _cross_recommender_overlap(two_tower, popularity, k=2)

    assert result["mean_user_list_overlap_fraction"] == pytest.approx(0.5)
    assert result["users_with_identical_ordered_lists"] == 0
    assert result["unique_item_intersection"] == 2
    with pytest.raises(ValueError, match="same evaluated users"):
        _cross_recommender_overlap(two_tower, {"u1": ("a",)}, k=1)


def test_negative_exclusion_audit_samples_rebuilt_train_examples() -> None:
    events = (
        RatingEvent("u1", "a", Decimal("5"), "train"),
        RatingEvent("u1", "b", Decimal("2"), "train"),
        RatingEvent("u2", "c", Decimal("5"), "train"),
        RatingEvent("u2", "d", Decimal("4"), "train"),
    )
    examples = (
        TwoTowerExample("u1", "a", 10, ()),
        TwoTowerExample("u2", "c", 10, ()),
    )

    audit = _audit_negative_exclusions(events, examples, seed=4, limit=2)

    assert audit["sampled_target_count"] == 2
    assert audit["targets_absent_from_sampled_negatives"] is True
    assert audit["negatives_absent_from_complete_train_seen_sets"] is True
    assert audit["negative_samples_distinct_per_target"] is True


def test_gini_and_pearson_handle_uniform_and_constant_inputs() -> None:
    assert _gini((0, 0, 0)) == 0
    assert _gini((2, 2, 2)) == 0
    assert _pearson((1, 2, 3), (2, 4, 6)) == pytest.approx(1.0)
    assert _pearson((1, 1, 1), (2, 3, 4)) is None
