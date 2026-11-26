"""Synthetic-only contracts for the Phase 4.3B content benchmark."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from recfusion_core.contracts import DataSplit, Interaction
from recfusion_ml.evaluation.content_benchmark import (
    BENCHMARK_SCHEMA,
    CandidatePolicy,
    evaluate_macro_rankings,
    generate_synthetic_benchmark,
    run_content_benchmark,
)
from recfusion_ml.retrieval.content import ContentConfig, ContentIndex

pytestmark = pytest.mark.unit

_SEED = 43031
_REVISION = "synthetic-content-benchmark-test"


def test_generator_is_deterministic_and_records_generation_parameters() -> None:
    first = generate_synthetic_benchmark(seed=_SEED)
    second = generate_synthetic_benchmark(seed=_SEED)

    assert first.source_checksums == second.source_checksums
    assert first.manifest_bytes == second.manifest_bytes
    assert first.generator_config == second.generator_config
    assert first.generator_config["seed"] == _SEED
    assert first.generator_schema == "recfusion.synthetic-content-generator.v1"
    assert first.manifest["schema_version"] == BENCHMARK_SCHEMA


def test_generator_seed_changes_synthetic_partitions() -> None:
    first = generate_synthetic_benchmark(seed=_SEED)
    second = generate_synthetic_benchmark(seed=_SEED + 1)

    assert (
        first.source_checksums["training_interactions_sha256"]
        != second.source_checksums["training_interactions_sha256"]
    )


def test_partitions_are_explicit_and_cold_items_have_no_training_events() -> None:
    benchmark = generate_synthetic_benchmark(seed=_SEED)
    training_items = {event.item_key for event in benchmark.training_interactions}

    assert benchmark.reference_item_keys == benchmark.warm_item_keys
    assert benchmark.warm_item_keys.isdisjoint(benchmark.cold_item_keys)
    assert benchmark.warm_item_keys <= training_items
    assert benchmark.cold_item_keys.isdisjoint(training_items)
    assert benchmark.evaluation_users
    assert benchmark.evaluation_events


def test_temporal_partitions_are_sorted_and_training_history_is_strictly_prior() -> (
    None
):
    benchmark = generate_synthetic_benchmark(seed=_SEED)
    assert all(
        event.split is DataSplit.TRAIN for event in benchmark.training_interactions
    )
    assert all(
        event.split is DataSplit.VALIDATION and event.event_time_ms == 10_000
        for event in benchmark.evaluation_events
    )
    assert list(benchmark.training_interactions) == sorted(
        benchmark.training_interactions,
        key=lambda event: (
            event.event_time_ms,
            event.user_key,
            event.item_key,
            event.rating,
        ),
    )


def test_cold_candidate_text_does_not_refit_reference_vocabulary() -> None:
    benchmark = generate_synthetic_benchmark(seed=_SEED)
    products = benchmark.products_by_key
    references = tuple(products[key] for key in sorted(benchmark.reference_item_keys))
    warm_candidates = tuple(products[key] for key in sorted(benchmark.warm_item_keys))
    full_candidates = benchmark.products
    warm_index = ContentIndex.fit(references, warm_candidates, code_revision=_REVISION)
    cold_index = ContentIndex.fit(references, full_candidates, code_revision=_REVISION)

    assert warm_index.vocabulary_sha256 == cold_index.vocabulary_sha256
    assert cold_index.eligible_candidate_count > warm_index.eligible_candidate_count


def test_report_separates_warm_only_and_content_eligible_candidate_policies() -> None:
    benchmark = generate_synthetic_benchmark(seed=_SEED)
    result = run_content_benchmark(benchmark, code_revision=_REVISION)

    warm = result.aggregate["candidate_policies"][CandidatePolicy.WARM_ONLY.value]
    content = result.aggregate["candidate_policies"][
        CandidatePolicy.CONTENT_ELIGIBLE.value
    ]
    assert warm["eligible_candidate_count"] == len(benchmark.warm_item_keys)
    assert content["eligible_candidate_count"] > warm["eligible_candidate_count"]
    assert content["cold_eligible_candidate_count"] > 0
    assert warm["evaluated_user_count"] == content["evaluated_user_count"]


def test_all_models_keep_users_with_empty_predictions_in_macro_denominator() -> None:
    result = evaluate_macro_rankings(
        relevant_by_user={"u1": frozenset({"a"}), "u2": frozenset({"b"})},
        rankings_by_user={"u1": (), "u2": ("a",)},
        eligible_candidate_count=2,
        ks=(1,),
    )

    assert result["evaluated_user_count"] == 2
    assert result["metrics_by_k"]["1"]["recall"] == 0.0
    assert result["metrics_by_k"]["1"]["ndcg"] == 0.0
    assert result["metrics_by_k"]["1"]["hit_rate"] == 0.0
    assert result["metrics_by_k"]["1"]["mrr"] == 0.0
    assert result["metrics_by_k"]["1"]["catalog_coverage"] == 0.5


def test_rank_metrics_reject_missing_user_predictions() -> None:
    with pytest.raises(ValueError, match="every evaluated user"):
        evaluate_macro_rankings(
            relevant_by_user={"u1": frozenset({"a"}), "u2": frozenset({"b"})},
            rankings_by_user={"u1": ("a",)},
            eligible_candidate_count=2,
            ks=(5,),
        )


def test_benchmark_reports_fixed_k_metrics_and_short_list_diagnostics() -> None:
    result = run_content_benchmark(
        generate_synthetic_benchmark(seed=_SEED), code_revision=_REVISION
    )
    for policy in result.aggregate["candidate_policies"].values():
        for model in policy["metrics_by_model"].values():
            assert set(model["metrics_by_k"]) == {"5", "10", "20"}
            for metric in model["metrics_by_k"].values():
                assert "recall" in metric
                assert "ndcg" in metric
                assert "hit_rate" in metric
                assert "mrr" in metric
                assert "unique_recommended_products" in metric
                assert "catalog_coverage" in metric
                assert "users_with_short_lists" in metric
                assert "mean_list_length" in metric


def test_benchmark_accounts_for_metadata_readiness_conflicts_and_zero_vectors() -> None:
    result = run_content_benchmark(
        generate_synthetic_benchmark(seed=_SEED), code_revision=_REVISION
    )
    metadata = result.aggregate["metadata_diagnostics"]

    assert metadata["synthetic_product_count"] > 0
    assert metadata["duplicate_metadata_occurrences"] > 0
    assert metadata["metadata_matched_product_count"] > 0
    assert metadata["feature_ready_product_count"] > 0
    assert metadata["conflict_excluded_product_count"] > 0
    assert metadata["zero_vector_product_count"] > 0
    assert metadata["cold_zero_vector_product_count"] > 0
    assert metadata["malformed_metadata_product_count"] > 0


def test_cold_positive_denominator_excludes_ineligible_items_and_is_explicit() -> None:
    result = run_content_benchmark(
        generate_synthetic_benchmark(seed=_SEED), code_revision=_REVISION
    )
    content = result.aggregate["candidate_policies"][
        CandidatePolicy.CONTENT_ELIGIBLE.value
    ]
    cold = content["cold_item_recall"]

    assert (
        cold["averaging"] == "macro over users with at least one eligible cold positive"
    )
    assert cold["eligible_target_denominator"] > 0
    assert cold["eligible_user_denominator"] > 0
    assert cold["ineligible_cold_positive_count"] > 0
    assert set(cold["recall_by_k"]) == {"5", "10", "20"}


def test_content_retrieval_finds_a_content_bearing_cold_item() -> None:
    result = run_content_benchmark(
        generate_synthetic_benchmark(seed=_SEED), code_revision=_REVISION
    )
    cold = result.aggregate["examples"]

    assert cold["retrieved_eligible_cold_positive_count"] > 0
    assert cold["unretrievable_missing_metadata_cold_positive_count"] == 1
    assert cold["unretrievable_unseen_vocabulary_cold_positive_count"] == 1
    assert cold["ineligible_conflicted_cold_positive_count"] == 1


def test_ablation_set_is_fixed_and_does_not_select_a_winner() -> None:
    result = run_content_benchmark(
        generate_synthetic_benchmark(seed=_SEED), code_revision=_REVISION
    )

    assert set(result.aggregate["ablations"]) == {
        "title_only",
        "no_usable_text",
        "unseen_vocabulary_cold",
        "empty_history",
    }
    no_text = result.aggregate["ablations"]["no_usable_text"]
    assert no_text["status"] == "no_usable_reference_content"
    assert no_text["recommendation_count"] == 0


def test_cold_item_transform_does_not_change_fitted_vocabulary_checksum() -> None:
    result = run_content_benchmark(
        generate_synthetic_benchmark(seed=_SEED), code_revision=_REVISION
    )
    tfidf = result.aggregate["tfidf"]

    assert tfidf["reference_item_count"] > 0
    assert tfidf["cold_items_refit_vocabulary"] is False
    assert tfidf["vocabulary_sha256"]
    assert tfidf["unseen_vocabulary_cold_item_count"] > 0


def test_aggregate_manifest_is_deterministic_and_contains_no_user_rows() -> None:
    benchmark = generate_synthetic_benchmark(seed=_SEED)
    first = run_content_benchmark(benchmark, code_revision=_REVISION)
    second = run_content_benchmark(benchmark, code_revision=_REVISION)

    assert first.manifest_bytes == second.manifest_bytes
    assert first.manifest_sha256 == second.manifest_sha256
    decoded = json.loads(first.manifest_bytes)
    assert decoded["source_checksums"] == benchmark.source_checksums
    assert "synthetic_user_" not in first.manifest_bytes.decode()
    assert "recommendations_by_user" not in decoded


def test_manifest_requires_a_source_code_revision() -> None:
    with pytest.raises(ValueError, match="code revision"):
        run_content_benchmark(
            generate_synthetic_benchmark(seed=_SEED), code_revision=" "
        )


def test_manifest_records_dirty_source_state_without_claiming_a_commit() -> None:
    result = run_content_benchmark(
        generate_synthetic_benchmark(seed=_SEED),
        code_revision="base-revision",
        working_tree_dirty=True,
    )

    assert result.aggregate["code_revision"] == "base-revision"
    assert result.aggregate["working_tree_dirty"] is True


def test_profile_masks_target_and_excludes_equal_time_and_future_training_events() -> (
    None
):
    benchmark = generate_synthetic_benchmark(seed=_SEED)
    products = benchmark.products_by_key
    index = ContentIndex.fit(
        tuple(products[key] for key in sorted(benchmark.reference_item_keys)),
        benchmark.products,
        code_revision=_REVISION,
        config=ContentConfig(),
    )
    user = next(
        event.user_key
        for event in benchmark.training_interactions
        if event.user_key.startswith("synthetic_user_")
    )
    history = tuple(
        event
        for event in benchmark.training_interactions
        if event.user_key == user and event.rating >= Decimal("4")
    )
    assert history
    target = history[0].item_key
    equal_time = Interaction(
        user,
        "synthetic_equal_time_only",
        10_000,
        Decimal("5"),
        DataSplit.TRAIN,
        "e" * 64,
    )
    future = replace(equal_time, item_key="synthetic_future_only", event_time_ms=10_001)

    with_target_masked = index.profile_from_training_history(
        (*history, equal_time, future),
        user_key=user,
        prediction_time_ms=10_000,
        target_item_key=target,
    )
    without_target = index.profile_from_training_history(
        tuple(event for event in history if event.item_key != target),
        user_key=user,
        prediction_time_ms=10_000,
    )

    assert with_target_masked.vector == without_target.vector
    assert "synthetic_equal_time_only" not in with_target_masked.seen_item_keys
    assert "synthetic_future_only" not in with_target_masked.seen_item_keys
