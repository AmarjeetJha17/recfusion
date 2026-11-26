import tracemalloc
from decimal import Decimal

import pytest

from recfusion_ml.baselines.item_cf import (
    ItemBasedCollaborativeFilter,
    ItemCFConfig,
)
from recfusion_ml.types import RatingEvent


def event(user: str, item: str, rating: str, split: str = "train") -> RatingEvent:
    return RatingEvent(user, item, Decimal(rating), split)


def test_binary_cosine_uses_distinct_positive_users_and_minimum_support() -> None:
    training = [
        event("u1", "a", "5"),
        event("u1", "a", "4"),
        event("u1", "b", "5"),
        event("u2", "a", "4"),
        event("u2", "b", "4"),
        event("u3", "a", "5"),
        event("u3", "c", "5"),
    ]

    model = ItemBasedCollaborativeFilter.fit(training, {"a", "b", "c"})

    assert model.positive_user_counts == {"a": 3, "b": 2, "c": 1}
    assert dict(model.neighbors_by_item["a"]) == {"b": pytest.approx(2 / (6**0.5))}
    assert dict(model.neighbors_by_item["b"]) == {"a": pytest.approx(2 / (6**0.5))}


def test_non_overlapping_positive_histories_have_no_similarity() -> None:
    model = ItemBasedCollaborativeFilter.fit(
        [event("u1", "a", "5"), event("u2", "b", "5")], {"a", "b"}
    )

    assert model.neighbors_by_item == {}
    assert model.recommend("u1", k=5).items == ()


def test_neighbor_ties_are_sorted_by_item_key() -> None:
    training = [
        event("u1", "center", "5"),
        event("u1", "left", "5"),
        event("u2", "center", "4"),
        event("u2", "left", "4"),
        event("u3", "center", "4"),
        event("u3", "right", "4"),
        event("u4", "center", "4"),
        event("u4", "right", "4"),
    ]

    model = ItemBasedCollaborativeFilter.fit(training, {"center", "left", "right"})

    assert tuple(item for item, _ in model.neighbors_by_item["center"]) == (
        "left",
        "right",
    )


def test_recommendations_exclude_all_train_observed_items() -> None:
    training = [
        event("u1", "positive-history", "5"),
        event("u1", "low-rated-seen", "2"),
        event("u1", "candidate", "5"),
        event("u2", "positive-history", "5"),
        event("u2", "candidate", "5"),
    ]

    model = ItemBasedCollaborativeFilter.fit(
        training, {"positive-history", "low-rated-seen", "candidate"}
    )
    recommendation = model.recommend("u1", k=5)

    assert recommendation.items == ()
    assert recommendation.candidate_count == 0
    assert recommendation.fallback_used is False


def test_empty_and_single_positive_histories_return_no_fabricated_results() -> None:
    training = [
        event("empty", "only-low", "3"),
        event("sparse", "only-positive", "5"),
        event("neighbor1", "shared", "5"),
        event("neighbor1", "only-positive", "5"),
        event("neighbor2", "shared", "5"),
        event("neighbor2", "only-positive", "5"),
    ]
    model = ItemBasedCollaborativeFilter.fit(
        training, {"only-low", "only-positive", "shared"}
    )

    assert model.recommend("empty", k=5).items == ()
    assert model.recommend("sparse", k=5).items == ("shared",)
    assert model.recommend("unknown-user", k=5).items == ()


def test_candidate_pool_must_match_train_known_items() -> None:
    with pytest.raises(ValueError, match="train-known"):
        ItemBasedCollaborativeFilter.fit(
            [event("u1", "item", "5")], {"item", "unseen-candidate"}
        )


def test_heldout_rows_are_rejected_and_do_not_change_train_similarity() -> None:
    training = [
        event("u1", "a", "5"),
        event("u1", "b", "5"),
        event("u2", "a", "5"),
        event("u2", "b", "5"),
    ]
    original = ItemBasedCollaborativeFilter.fit(training, {"a", "b"})
    reordered = ItemBasedCollaborativeFilter.fit(reversed(training), {"a", "b"})

    assert original.neighbors_by_item == reordered.neighbors_by_item
    with pytest.raises(ValueError, match="training split"):
        ItemBasedCollaborativeFilter.fit(
            [*training, event("u3", "a", "5", "validation")], {"a", "b"}
        )


def test_long_positive_histories_are_capped_deterministically() -> None:
    training = [event("u1", item, "5") for item in ("a", "b", "c", "d")] + [
        event("u2", "a", "5"),
        event("u2", "b", "5"),
        event("u3", "a", "5"),
        event("u3", "b", "5"),
    ]
    model = ItemBasedCollaborativeFilter.fit(
        training,
        {"a", "b", "c", "d"},
        config=ItemCFConfig(max_positive_history_items=2),
    )

    assert model.fit_summary.truncated_user_count == 1
    assert model.fit_summary.truncated_positive_item_count == 2
    assert model.positive_history_by_user["u1"] == frozenset({"a", "b"})


def test_neighbor_limit_is_enforced() -> None:
    training = [event("u1", "center", "5")]
    for index in range(3):
        item = f"neighbor-{index}"
        training.extend(
            [
                event(f"u{index + 2}", "center", "5"),
                event(f"u{index + 2}", item, "5"),
                event(f"u{index + 5}", "center", "5"),
                event(f"u{index + 5}", item, "5"),
            ]
        )
    items = {record.item_key for record in training}
    model = ItemBasedCollaborativeFilter.fit(
        training,
        items,
        config=ItemCFConfig(max_neighbors_per_item=2),
    )

    assert len(model.neighbors_by_item["center"]) == 2


def test_sparse_fit_scales_to_45331_items_without_dense_similarity_matrix() -> None:
    items = [f"item-{index:05d}" for index in range(45_331)]
    training = [
        event("u1", items[0], "5"),
        event("u1", items[1], "5"),
        event("u2", items[0], "5"),
        event("u2", items[1], "5"),
    ]
    training.extend(event("low-user", item, "1") for item in items[2:])
    tracemalloc.start()

    model = ItemBasedCollaborativeFilter.fit(training, set(items))
    peak_bytes = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    assert len(model.candidate_items) == 45_331
    assert len(model.neighbors_by_item) == 2
    assert peak_bytes < 32 * 1024 * 1024
