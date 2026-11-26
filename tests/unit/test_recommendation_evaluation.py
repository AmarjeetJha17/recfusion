from decimal import Decimal

import pytest

from recfusion_ml.baselines.popularity import PopularityRecommender
from recfusion_ml.evaluation.metrics import (
    build_validation_cohort,
    evaluate_rankings,
)
from recfusion_ml.types import RatingEvent


def event(user: str, item: str, rating: str, split: str = "train") -> RatingEvent:
    return RatingEvent(
        user_key=user,
        item_key=item,
        rating=Decimal(rating),
        split=split,
    )


def test_perfect_recommendations_score_one_for_all_requested_k_values() -> None:
    cohort = build_validation_cohort(
        [event("u1", "history", "3"), event("u2", "i1", "5"), event("u3", "i2", "4")],
        [event("u1", "i1", "5", "validation"), event("u1", "i2", "4", "validation")],
        {"history", "i1", "i2"},
    )

    result = evaluate_rankings(
        cohort,
        {"u1": ["i1", "i2"]},
        candidate_items={"history", "i1", "i2"},
        ks=(5, 10, 20),
    )

    assert result.evaluated_user_count == 1
    assert result.eligible_positive_target_count == 2
    assert all(metric.recall == 1 for metric in result.metrics_by_k.values())
    assert all(metric.ndcg == 1 for metric in result.metrics_by_k.values())
    assert all(metric.hit_rate == 1 for metric in result.metrics_by_k.values())
    assert all(metric.mrr == 1 for metric in result.metrics_by_k.values())


def test_zero_hit_is_zero_for_an_eligible_user() -> None:
    cohort = build_validation_cohort(
        [event("u1", "history", "5"), event("u2", "i1", "5"), event("u3", "i2", "5")],
        [event("u1", "i1", "5", "validation")],
        {"history", "i1", "i2"},
    )

    result = evaluate_rankings(
        cohort, {"u1": ["i2"]}, candidate_items={"history", "i1", "i2"}, ks=(5,)
    )

    assert result.metrics_by_k[5].recall == 0
    assert result.metrics_by_k[5].ndcg == 0
    assert result.metrics_by_k[5].hit_rate == 0
    assert result.metrics_by_k[5].mrr == 0


def test_ndcg_and_recall_use_distinct_target_set_denominators() -> None:
    cohort = build_validation_cohort(
        [
            event("u1", "history", "5"),
            event("u2", "i1", "5"),
            event("u3", "i2", "5"),
            event("u4", "i3", "5"),
        ],
        [
            event("u1", "i1", "5", "validation"),
            event("u1", "i2", "5", "validation"),
        ],
        {"history", "i1", "i2", "i3"},
    )

    result = evaluate_rankings(
        cohort,
        {"u1": ["i3", "i2"]},
        candidate_items={"history", "i1", "i2", "i3"},
        ks=(2,),
    )

    assert result.eligible_positive_target_count == 2
    assert result.metrics_by_k[2].recall == Decimal("0.5")
    assert result.metrics_by_k[2].ndcg == pytest.approx(0.38685280723454163)
    assert result.metrics_by_k[2].hit_rate == 1


def test_ineligible_users_are_counted_and_not_averaged_as_zero() -> None:
    cohort = build_validation_cohort(
        [event("u1", "history", "5"), event("u2", "i2", "5")],
        [
            event("u1", "i1", "3", "validation"),
            event("u2", "cold", "5", "validation"),
        ],
        {"history", "i2"},
    )

    result = evaluate_rankings(cohort, {}, candidate_items={"history", "i2"}, ks=(5,))

    assert cohort.validation_user_count == 2
    assert cohort.users_with_observed_positives == 1
    assert cohort.users_with_warm_positive_targets == 0
    assert cohort.users_with_evaluable_targets == 0
    assert result.evaluated_user_count == 0
    assert result.metrics_by_k[5].recall is None


def test_seen_and_cold_item_positive_targets_are_explicit_exclusions() -> None:
    training = [
        event("u1", "seen", "5"),
        event("u1", "history", "3"),
        event("u2", "other", "4"),
        event("u3", "warm", "4"),
    ]
    validation = [
        event("u1", "seen", "5", "validation"),
        event("u1", "cold", "5", "validation"),
        event("u1", "warm", "5", "validation"),
        event("u4", "other", "5", "validation"),
    ]

    cohort = build_validation_cohort(
        training, validation, {"seen", "warm", "other", "history"}
    )

    assert cohort.users_with_observed_positives == 2
    assert cohort.users_with_warm_positive_targets == 1
    assert cohort.users_with_evaluable_targets == 1
    assert cohort.eligible_positive_target_count == 1
    assert cohort.cold_item_positive_observation_count == 1
    assert cohort.cold_user_positive_observation_count == 1
    assert cohort.excluded_target_counts == {
        "cold_item": 1,
        "cold_user": 1,
        "seen_in_train_history": 1,
    }


def test_repeated_user_item_targets_count_once_in_metric_denominator() -> None:
    cohort = build_validation_cohort(
        [event("u1", "history", "5"), event("u2", "i1", "5")],
        [
            event("u1", "i1", "5", "validation"),
            event("u1", "i1", "4", "validation"),
        ],
        {"history", "i1"},
    )

    result = evaluate_rankings(
        cohort, {"u1": ["i1"]}, candidate_items={"history", "i1"}, ks=(5,)
    )

    assert cohort.positive_observation_count == 2
    assert cohort.duplicate_positive_observation_count == 1
    assert cohort.eligible_positive_target_count == 1
    assert result.metrics_by_k[5].recall == 1


def test_variable_recommendation_lengths_and_k_larger_than_candidates() -> None:
    cohort = build_validation_cohort(
        [
            event("u1", "history1", "5"),
            event("u2", "history2", "5"),
            event("u3", "a", "5"),
            event("u4", "b", "5"),
            event("u5", "c", "5"),
        ],
        [event("u1", "a", "5", "validation"), event("u2", "c", "5", "validation")],
        {"a", "b", "c", "history1", "history2"},
    )

    result = evaluate_rankings(
        cohort,
        {"u1": ["a", "b"], "u2": ["c"]},
        candidate_items={"a", "b", "c", "history1", "history2"},
        ks=(1, 20),
    )

    assert result.metrics_by_k[20].recall == 1
    assert result.metrics_by_k[20].candidate_coverage == pytest.approx(0.6)


def test_unknown_recommendation_ids_and_missing_eligible_users_are_rejected() -> None:
    cohort = build_validation_cohort(
        [event("u1", "history", "5"), event("u2", "i1", "5")],
        [event("u1", "i1", "5", "validation")],
        {"history", "i1"},
    )

    with pytest.raises(ValueError, match="candidate pool"):
        evaluate_rankings(
            cohort, {"u1": ["unknown"]}, candidate_items={"history", "i1"}, ks=(5,)
        )
    with pytest.raises(ValueError, match="every evaluable user"):
        evaluate_rankings(cohort, {}, candidate_items={"history", "i1"}, ks=(5,))


def test_popularity_uses_positive_training_reviews_and_stable_item_ties() -> None:
    training = [
        event("u1", "z", "5"),
        event("u2", "a", "4"),
        event("u3", "z", "2"),
        event("u4", "b", "3"),
    ]
    model = PopularityRecommender.fit(training, {"a", "b", "z"})

    assert model.recommend(seen_items=set(), k=3) == ("a", "z", "b")
    assert model.recommend(seen_items={"a"}, k=5) == ("z", "b")


def test_popularity_fit_rejects_heldout_rows_and_non_train_candidate_items() -> None:
    with pytest.raises(ValueError, match="training split"):
        PopularityRecommender.fit([event("u1", "i1", "5", "validation")], {"i1"})
    with pytest.raises(ValueError, match="train-known"):
        PopularityRecommender.fit([event("u1", "i1", "5")], {"i1", "heldout"})


def test_popularity_and_metrics_are_independent_of_input_row_order() -> None:
    training = [
        event("u1", "history", "5"),
        event("u2", "a", "5"),
        event("u3", "b", "4"),
    ]
    validation = [event("u1", "a", "5", "validation")]
    pool = {"history", "a", "b"}
    first = PopularityRecommender.fit(training, pool)
    second = PopularityRecommender.fit(reversed(training), pool)
    first_cohort = build_validation_cohort(training, validation, pool)
    second_cohort = build_validation_cohort(
        reversed(training), reversed(validation), pool
    )

    assert first.recommend(seen_items=set(), k=2) == second.recommend(
        seen_items=set(), k=2
    )
    assert first_cohort == second_cohort
