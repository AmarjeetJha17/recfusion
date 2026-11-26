from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from recfusion_ml.evaluation.metrics import build_validation_cohort, evaluate_rankings
from recfusion_ml.evaluation.synthetic_workload import (
    _measure,
    build_synthetic_workload,
    get_workload_config,
    publish_report,
    run_synthetic_evaluation,
)
from recfusion_ml.types import RatingEvent


def _event(user: str, item: str, split: str) -> RatingEvent:
    return RatingEvent(
        user_key=user,
        item_key=item,
        rating=Decimal("5"),
        split=split,  # type: ignore[arg-type]
    )


def test_ranking_metrics_match_independent_hand_calculated_oracle() -> None:
    training = [
        _event("u1", "seen", "train"),
        _event("u2", "seen", "train"),
        _event("catalog", "a", "train"),
        _event("catalog", "b", "train"),
        _event("catalog", "c", "train"),
    ]
    validation = [
        _event("u1", "a", "validation"),
        _event("u1", "b", "validation"),
        _event("u2", "c", "validation"),
    ]
    cohort = build_validation_cohort(training, validation, {"seen", "a", "b", "c"})

    result = evaluate_rankings(
        cohort,
        {"u1": ["c", "a"], "u2": ["c"]},
        candidate_items={"seen", "a", "b", "c"},
        ks=(2,),
    )

    # u1 recall=1/2, NDCG=1/log2(3)/(1+1/log2(3)); u2 scores 1.
    # Macro averaging then gives recall=.75, NDCG=(.38685+1)/2,
    # hit rate=1, MRR=(1/2+1)/2=.75. Recommended unique items={a,c}.
    metrics = result.metrics_by_k[2]
    assert metrics.recall == pytest.approx(0.75)
    ndcg_for_u1 = (1 / 1.584962500721156) / (1 + 1 / 1.584962500721156)
    assert metrics.ndcg == pytest.approx((ndcg_for_u1 + 1) / 2)
    assert metrics.hit_rate == 1
    assert metrics.mrr == pytest.approx(0.75)
    assert metrics.candidate_coverage == pytest.approx(0.5)
    assert metrics.unique_recommended_items == 2
    assert metrics.recommendation_count == 3


def test_workload_profiles_are_bounded_and_large_is_opt_in() -> None:
    small = get_workload_config("small", seed=17)
    assert (small.user_count, small.candidate_count) == (20, 100)
    with pytest.raises(ValueError, match="opt-in"):
        get_workload_config("large", seed=17)
    large = get_workload_config("large", seed=17, allow_large=True)
    assert (large.user_count, large.candidate_count) == (1_000, 25_000)
    with pytest.raises(ValueError, match="max_users"):
        get_workload_config("small", seed=17, max_users=19)
    with pytest.raises(ValueError, match="max_candidates"):
        get_workload_config("small", seed=17, max_candidates=99)
    with pytest.raises(ValueError, match="max_generated_records"):
        get_workload_config("small", seed=17, max_generated_records=100)
    with pytest.raises(ValueError, match="max_batch_size"):
        get_workload_config("small", seed=17, batch_size=501)
    with pytest.raises(ValueError, match="cutoffs"):
        get_workload_config("small", seed=17, ks=(5, 5))
    with pytest.raises(ValueError, match="max_intermediate_batch_records"):
        get_workload_config("small", seed=17, max_intermediate_batch_records=100)


def test_synthetic_workload_and_report_are_deterministic() -> None:
    first = run_synthetic_evaluation("small", seed=77, repetitions=2)
    second = run_synthetic_evaluation("small", seed=77, repetitions=2)
    assert first["stable_sha256"] == second["stable_sha256"]
    assert first["workload_sha256"] == second["workload_sha256"]
    assert first["metrics"] == second["metrics"]
    assert first["input_counts"] == {
        "train_records": 120,
        "validation_records": 24,
        "candidate_items": 100,
        "evaluable_users": 20,
        "generated_records_total": 144,
        "cold_positive_validation_records": 4,
        "rejected_records": 0,
    }
    assert first["cohort_audit"]["eligible_positive_target_count"] == 20  # type: ignore[index]
    assert first["cohort_audit"]["cold_item_positive_observation_count"] == 4  # type: ignore[index]
    assert first["metrics"]["candidate_pool_item_count"] == 100  # type: ignore[index]
    assert first["resources"][0]["wall_time_seconds"] >= 0  # type: ignore[index]
    memory = first["resources"][0]["process_peak_working_set_bytes"]  # type: ignore[index]
    assert memory["status"] in {"available", "unavailable"}
    assert "scope" in memory

    workload_a = build_synthetic_workload(get_workload_config("small", seed=77))
    workload_b = build_synthetic_workload(get_workload_config("small", seed=77))
    assert workload_a.workload_sha256 == workload_b.workload_sha256
    assert workload_a.output_counts == workload_b.output_counts
    assert workload_a.output_sha256 == workload_b.output_sha256
    assert (
        workload_a.output_sha256
        != build_synthetic_workload(get_workload_config("small", seed=78)).output_sha256
    )


def test_empty_recommendations_are_valid_zero_result_lists() -> None:
    cohort = build_validation_cohort(
        [_event("catalog", "target", "train"), _event("u1", "seen", "train")],
        [_event("u1", "target", "validation")],
        {"target", "seen"},
    )
    result = evaluate_rankings(
        cohort, {"u1": []}, candidate_items={"target", "seen"}, ks=(5,)
    )
    metrics = result.metrics_by_k[5]
    assert metrics.recall == 0
    assert metrics.ndcg == 0
    assert metrics.hit_rate == 0
    assert metrics.mrr == 0
    assert metrics.candidate_coverage == 0
    assert metrics.recommendation_count == 0


def test_report_publication_is_atomic_and_refuses_overwrite(tmp_path: Path) -> None:
    report = run_synthetic_evaluation("small", seed=10, repetitions=1)
    target = tmp_path / "report.json"
    temp_dir = tmp_path / "temporary"
    temp_dir.mkdir()
    published = publish_report(
        report, target, max_report_bytes=100_000, temp_dir=temp_dir
    )
    assert published == target
    payload = target.read_bytes()
    assert json.loads(payload) == report
    assert (
        hashlib.sha256(payload).hexdigest()
        == hashlib.sha256(
            (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode()
        ).hexdigest()
    )
    with pytest.raises(FileExistsError):
        publish_report({"different": True}, target, max_report_bytes=100_000)
    assert target.read_bytes() == payload
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "report.json",
        "temporary",
    ]
    assert list(temp_dir.iterdir()) == []


def test_report_size_limit_rejects_before_publication(tmp_path: Path) -> None:
    report = run_synthetic_evaluation("small", seed=10, repetitions=1)
    with pytest.raises(ValueError, match="report exceeds"):
        publish_report(report, tmp_path / "report.json", max_report_bytes=1)
    assert list(tmp_path.iterdir()) == []


def test_profiler_reports_unavailable_memory_without_inventing_a_value() -> None:
    _, measurements = _measure(
        lambda: 1,
        memory_probe=lambda: {
            "value": None,
            "status": "unavailable",
            "reason": "test platform has no supported peak API",
            "scope": "current process only",
        },
    )
    memory = measurements["process_peak_working_set_bytes"]
    assert memory["status"] == "unavailable"
    assert memory["value"] is None
    assert measurements["wall_time_seconds"] >= 0
    process_time = measurements["process_time_seconds"]
    assert process_time["status"] in {"available", "unavailable"}
    if process_time["status"] == "unavailable":
        assert process_time["value"] is None


def test_empty_metric_cohort_reports_unavailable_denominators() -> None:
    cohort = build_validation_cohort([], [], set())
    result = evaluate_rankings(cohort, {}, candidate_items=set(), ks=(5,))
    metrics = result.metrics_by_k[5]
    assert result.evaluated_user_count == 0
    assert metrics.recall is None
    assert metrics.ndcg is None
    assert metrics.candidate_coverage is None


def test_malformed_rankings_remain_rejected() -> None:
    cohort = build_validation_cohort(
        [
            _event("catalog", "a", "train"),
            _event("catalog", "b", "train"),
            _event("u1", "a", "train"),
        ],
        [_event("u1", "b", "validation")],
        {"a", "b"},
    )
    with pytest.raises(ValueError, match="unique items"):
        evaluate_rankings(cohort, {"u1": ["b", "b"]}, candidate_items={"a", "b"})
    with pytest.raises(ValueError, match="exclude train-seen"):
        evaluate_rankings(cohort, {"u1": ["a"]}, candidate_items={"a", "b"})


def test_interrupted_report_publish_cleans_temporary_and_claimed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import recfusion_ml.evaluation.synthetic_workload as workload_module

    report = run_synthetic_evaluation("small", seed=10, repetitions=1)

    def fail_replace(source: str, target: Path) -> None:
        raise OSError("simulated interruption")

    monkeypatch.setattr(workload_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated interruption"):
        publish_report(report, tmp_path / "report.json", max_report_bytes=100_000)
    assert list(tmp_path.iterdir()) == []
