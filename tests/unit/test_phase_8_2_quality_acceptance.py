"""Frozen, synthetic-only scenario contracts for Phase 8.2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from recfusion_api.services.synthetic_catalog import build_synthetic_catalog
from recfusion_ml.evaluation.content_benchmark import (
    generate_synthetic_benchmark,
    run_content_benchmark,
)
from recfusion_ml.evaluation.hybrid_benchmark import run_hybrid_benchmark
from recfusion_ml.ranking.rrf import RRFConfig
from recfusion_ml.retrieval.content import ContentIndex
from recfusion_ml.retrieval.hybrid import (
    HybridCandidatePolicy,
    HybridConfig,
    HybridUserContext,
    retrieve_hybrid,
)

pytestmark = pytest.mark.unit

_MANIFEST_PATH = (
    Path(__file__).parents[1] / "fixtures" / "phase_8_2_synthetic_scenarios.json"
)
_CODE_REVISION = "phase-8.2-frozen-synthetic-scenarios"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _manifest() -> dict[str, Any]:
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))


def _empty_history_projection(seed: int) -> dict[str, object]:
    benchmark = generate_synthetic_benchmark(seed=seed)
    products = benchmark.products_by_key
    index = ContentIndex.fit(
        tuple(products[key] for key in sorted(benchmark.reference_item_keys)),
        benchmark.products,
        code_revision=_CODE_REVISION,
    )
    train_items = frozenset(event.item_key for event in benchmark.training_interactions)
    config = HybridConfig(
        rrf=RRFConfig(
            rank_constant=60,
            source_weights={"item_cf": 1.0, "tfidf_content": 1.0},
            source_depths={"item_cf": 20, "tfidf_content": 20},
        ),
        content_source_name="tfidf_content",
    )
    result = retrieve_hybrid(
        context=HybridUserContext(
            user_key="synthetic_user_without_history",
            training_interactions=benchmark.training_interactions,
            prediction_time_ms=10_000,
        ),
        content_index=index,
        collaborative_rankings={},
        train_known_item_keys=train_items,
        candidate_policy=HybridCandidatePolicy.CONTENT_ELIGIBLE_HYBRID,
        config=config,
        k=5,
    )
    return {
        "content_profile_empty": result.content_profile_empty,
        "candidate_item_count": len(result.candidate_item_keys),
        "recommendations": list(result.fusion.recommended_items),
        "raw_generated_counts": dict(result.fusion.raw_generated_counts),
    }


def _scenario_output(scenario: dict[str, Any]) -> dict[str, object]:
    benchmark = generate_synthetic_benchmark(seed=scenario["seed"])
    assert benchmark.source_checksums == scenario["source_checksums"]
    assert (
        benchmark.source_checksums["metadata_source_sha256"]
        == scenario["catalog_fingerprint"]
    )

    if scenario["scenario_id"] == "warm_only":
        result = run_content_benchmark(benchmark, code_revision=_CODE_REVISION)
        policy = result.aggregate["candidate_policies"]["warm_only"]
        assert policy["eligible_candidate_count"] == 24
        assert policy["evaluated_user_count"] == 16
        return policy

    if scenario["scenario_id"] == "content_eligible_cold":
        result = run_hybrid_benchmark(benchmark, code_revision=_CODE_REVISION)
        policy = result.aggregate["candidate_policies"]["content_eligible_hybrid"]
        assert policy["candidate_catalog_size"] == 32
        assert policy["eligible_cold_target_count"] == 8
        assert policy["eligible_cold_user_denominator"] == 8
        return policy

    if scenario["scenario_id"] == "sparse_empty":
        return _empty_history_projection(scenario["seed"])

    raise AssertionError(f"Unknown frozen scenario: {scenario['scenario_id']}")


def test_phase_8_2_manifest_freezes_scenario_inputs_and_fingerprints() -> None:
    manifest = _manifest()

    assert manifest["schema_version"] == "recfusion.phase-8.2-scenarios.v1"
    catalog = build_synthetic_catalog()
    assert manifest["application_catalog"] == {
        "catalog_id": catalog.catalog_id,
        "catalog_fingerprint": catalog.catalog_fingerprint,
        "compatibility_fingerprint": catalog.compatibility_fingerprint,
        "bundle_fingerprint": catalog.bundle_fingerprint,
    }
    assert {row["scenario_id"] for row in manifest["scenarios"]} == {
        "warm_only",
        "content_eligible_cold",
        "sparse_empty",
    }
    for scenario in manifest["scenarios"]:
        benchmark = generate_synthetic_benchmark(seed=scenario["seed"])
        assert scenario["generator_schema"] == benchmark.generator_schema
        assert scenario["source_checksums"] == benchmark.source_checksums
        assert (
            scenario["catalog_fingerprint"]
            == benchmark.source_checksums["metadata_source_sha256"]
        )
        bundle_descriptor = {
            "manifest_schema": manifest["schema_version"],
            "scenario_id": scenario["scenario_id"],
            "family": scenario["family"],
            "seed": scenario["seed"],
            "generator_schema": scenario["generator_schema"],
            "candidate_policy": scenario["candidate_policy"],
            "catalog_fingerprint": scenario["catalog_fingerprint"],
            "source_checksums": scenario["source_checksums"],
        }
        assert scenario["bundle_fingerprint"] == _sha256_json(bundle_descriptor)


@pytest.mark.parametrize(
    "scenario_id",
    ["warm_only", "content_eligible_cold", "sparse_empty"],
)
def test_frozen_synthetic_scenario_outputs_are_repeatable_and_match_manifest(
    scenario_id: str,
) -> None:
    manifest = _manifest()
    scenario = next(
        row for row in manifest["scenarios"] if row["scenario_id"] == scenario_id
    )

    first = _scenario_output(scenario)
    second = _scenario_output(scenario)

    first_hash = _sha256_json(first)
    assert first_hash == _sha256_json(second)
    assert first_hash == scenario["expected_output_sha256"]
    assert {key: first.get(key) for key in scenario["expected_summary"]} == scenario[
        "expected_summary"
    ]
