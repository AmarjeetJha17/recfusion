from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from recfusion_api.schemas.recommendation import (
    RecommendationDiagnostics,
    RecommendationErrorCode,
    RecommendationErrorResponse,
    RecommendationRequest,
    RecommendationResponse,
    parse_recommendation_request,
)


def _base_request(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "recfusion.recommendation-request.v1",
        "mode": "product_to_product",
        "catalog_id": "synthetic-electronics-v1",
        "algorithm_id": "tfidf_content",
        "algorithm_version": "1",
        "policy_id": "content-similarity-v1",
        "candidate_policy": "content_catalog",
        "k": 5,
        "query": {
            "kind": "product_to_product",
            "product_id": "synthetic-electronics-v1:item:000001",
        },
        "excluded_product_ids": [],
    }
    value.update(updates)
    return value


def test_request_schema_accepts_explicit_versioned_product_mode() -> None:
    request = RecommendationRequest.model_validate(_base_request())

    assert request.mode == "product_to_product"
    assert request.algorithm_id == "tfidf_content"
    assert request.algorithm_version == "1"
    assert request.candidate_policy == "content_catalog"
    assert request.k == 5


def test_request_schema_rejects_mode_query_mismatch() -> None:
    value = _base_request(
        mode="hybrid",
        algorithm_id="weighted_rrf",
        policy_id="synthetic-hybrid-content-v1",
        candidate_policy="content_eligible_hybrid",
        query={
            "kind": "product_to_product",
            "product_id": "synthetic-electronics-v1:item:000001",
        },
    )

    with pytest.raises(ValidationError, match="mode and query kind"):
        RecommendationRequest.model_validate(value)


def test_request_schema_bounds_k_and_exclusion_list() -> None:
    with pytest.raises(ValidationError):
        RecommendationRequest.model_validate(_base_request(k=21))

    with pytest.raises(ValidationError):
        RecommendationRequest.model_validate(
            _base_request(
                excluded_product_ids=[
                    f"synthetic-electronics-v1:item:{index:06d}" for index in range(65)
                ]
            )
        )


def test_request_schema_rejects_untrusted_paths_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        RecommendationRequest.model_validate(
            _base_request(checkpoint_path="C:/private/model.pt")
        )


def test_payload_parser_bounds_bytes_and_identifies_contract_version() -> None:
    with pytest.raises(ValueError, match="payload limit"):
        parse_recommendation_request(b" " * 16_385)

    unsupported = _base_request(schema_version="recfusion.recommendation-request.v9")
    with pytest.raises(ValueError, match="Unsupported contract version"):
        parse_recommendation_request(json.dumps(unsupported).encode())


def test_response_and_error_contracts_are_versioned_and_history_safe() -> None:
    response = RecommendationResponse(
        schema_version="recfusion.recommendation-response.v1",
        request_id="request-1",
        mode="product_to_product",
        algorithm_id="tfidf_content",
        algorithm_version="1",
        candidate_policy="content_catalog",
        policy_id="content-similarity-v1",
        catalog_id="synthetic-electronics-v1",
        catalog_fingerprint="a" * 64,
        artifact_fingerprint="b" * 64,
        status="ok",
        result_count=1,
        diagnostics=RecommendationDiagnostics(
            candidate_count=2, eligible_count=1, returned_count=1
        ),
        recommendations=(
            {
                "product_id": "synthetic-electronics-v1:item:000002",
                "rank": 1,
                "source_names": ["tfidf_content"],
                "reason_codes": ["content_similarity"],
            },
        ),
        warnings=(),
    )
    body = response.model_dump_json()

    assert "training_interactions" not in body
    assert "source_user_id" not in body
    assert response.recommendations[0].rank == 1

    error = RecommendationErrorResponse(
        request_id="request-1",
        error={
            "code": RecommendationErrorCode.ARTIFACT_MISSING,
            "message": "The requested recommendation algorithm is unavailable.",
        },
    )
    assert error.error.code is RecommendationErrorCode.ARTIFACT_MISSING
