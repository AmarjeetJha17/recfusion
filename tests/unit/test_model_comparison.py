from dataclasses import replace

import pytest

from recfusion_ml.evaluation.metrics import ValidationCohort
from recfusion_ml.evaluation.model_comparison import compare_rankings


def _cohort() -> ValidationCohort:
    return ValidationCohort(
        validation_user_count=3,
        users_with_observed_positives=3,
        users_with_warm_positive_targets=3,
        users_with_evaluable_targets=3,
        positive_observation_count=3,
        positive_target_pair_count=3,
        warm_positive_observation_count=3,
        warm_positive_target_count=3,
        eligible_positive_target_count=3,
        cold_item_positive_observation_count=0,
        cold_user_positive_observation_count=0,
        seen_positive_observation_count=0,
        non_positive_observation_count=0,
        duplicate_positive_observation_count=0,
        excluded_target_counts={},
        targets_by_user={
            "u1": frozenset({"a"}),
            "u2": frozenset({"b"}),
            "u3": frozenset({"c"}),
        },
        seen_items_by_user={"u1": frozenset(), "u2": frozenset(), "u3": frozenset()},
        candidate_items=frozenset({"a", "b", "c", "d"}),
    )


def test_comparison_uses_paired_users_and_deterministic_bootstrap() -> None:
    cohort = _cohort()
    rankings = {
        "alpha": {"u1": ("a", "b"), "u2": ("d",), "u3": ("d",)},
        "beta": {"u1": ("d",), "u2": ("b",), "u3": ("d",)},
    }

    result = compare_rankings(
        cohort,
        rankings,
        ks=(1,),
        bootstrap_resamples=101,
        bootstrap_seed=7,
        personalization_users=3,
    )
    repeated = compare_rankings(
        cohort,
        rankings,
        ks=(1,),
        bootstrap_resamples=101,
        bootstrap_seed=7,
        personalization_users=3,
    )

    assert result == repeated
    assert result["models"]["alpha"]["1"]["ndcg"] == 1 / 3
    pair = result["paired_comparisons"]["alpha_minus_beta"]["1"]["ndcg"]
    assert pair["mean_difference"] == 0
    assert pair["wins"] == 1
    assert pair["losses"] == 1
    assert pair["ties"] == 1
    assert pair["bootstrap_95_percentile_ci"] == [-1.0, 1.0]
    assert 0 <= result["models"]["alpha"]["1"]["concentration"]["gini"] <= 1


def test_comparison_rejects_misaligned_users() -> None:
    cohort = _cohort()
    rankings = {
        "alpha": {"u1": ("a",), "u2": ("b",), "u3": ("c",)},
        "beta": {"u1": ("a",), "u2": ("b",)},
    }
    with pytest.raises(ValueError, match="every evaluable user"):
        compare_rankings(cohort, rankings, ks=(1,))


def test_comparison_rejects_seen_item_recommendations() -> None:
    cohort = replace(
        _cohort(),
        seen_items_by_user={
            "u1": frozenset({"a"}),
            "u2": frozenset(),
            "u3": frozenset(),
        },
    )
    rankings = {
        "alpha": {"u1": ("a",), "u2": ("b",), "u3": ("c",)},
        "beta": {"u1": ("d",), "u2": ("d",), "u3": ("d",)},
    }
    with pytest.raises(ValueError, match="train-seen"):
        compare_rankings(cohort, rankings, ks=(1,))
