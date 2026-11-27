from __future__ import annotations

from decimal import Decimal

import pytest

from recfusion_api.schemas.recommendation import (
    RecommendationRequest,
    RecommendationStatus,
)
from recfusion_api.services.recommendation import (
    InMemoryRecommendationArtifactRegistry,
    RecommendationService,
    RecommendationServiceError,
)
from recfusion_api.services.synthetic_catalog import build_synthetic_catalog
from recfusion_ml.inference.artifacts import (
    load_recommendation_artifact,
    prepare_synthetic_recommendation_artifact,
)
from recfusion_ml.inference.recommendation import SyntheticRecommendationSource
from recfusion_ml.retrieval.content import ContentIndex

pytestmark = pytest.mark.integration


def _runtime() -> tuple[RecommendationService, object]:
    catalog = build_synthetic_catalog()
    prepared = prepare_synthetic_recommendation_artifact(catalog)
    loaded = load_recommendation_artifact(
        prepared.payload,
        expected_sha256=prepared.sha256,
        expected_catalog_id=catalog.catalog_id,
        expected_catalog_fingerprint=catalog.catalog_fingerprint,
    )
    source = SyntheticRecommendationSource(loaded)
    return RecommendationService(
        catalog=catalog,
        artifacts=InMemoryRecommendationArtifactRegistry((source,)),
    ), catalog


def _request(
    *,
    mode: str,
    algorithm_id: str,
    policy_id: str,
    candidate_policy: str,
    query: dict[str, str],
    k: int = 5,
    excluded_product_ids: list[str] | None = None,
    constraints: dict[str, object] | None = None,
) -> RecommendationRequest:
    return RecommendationRequest.model_validate(
        {
            "schema_version": "recfusion.recommendation-request.v1",
            "mode": mode,
            "catalog_id": "synthetic-electronics-v1",
            "algorithm_id": algorithm_id,
            "algorithm_version": "1",
            "policy_id": policy_id,
            "candidate_policy": candidate_policy,
            "k": k,
            "query": query,
            "excluded_product_ids": excluded_product_ids or [],
            "constraints": constraints or {},
        }
    )


def _product_request(**updates: object) -> RecommendationRequest:
    values: dict[str, object] = {
        "mode": "product_to_product",
        "algorithm_id": "tfidf_content",
        "policy_id": "content-similarity-v1",
        "candidate_policy": "content_catalog",
        "query": {
            "kind": "product_to_product",
            "product_id": "synthetic-electronics-v1:item:000001",
        },
    }
    values.update(updates)
    return _request(**values)  # type: ignore[arg-type]


def test_product_to_product_returns_deterministic_eligible_products() -> None:
    service, _catalog = _runtime()
    request = _product_request(k=5)

    first = service.recommend(request)
    second = service.recommend(request)

    assert first.status is RecommendationStatus.OK
    assert first.recommendations == second.recommendations
    assert first.result_count <= request.k
    assert all(
        item.product_id != request.query.product_id for item in first.recommendations
    )
    assert all(
        item.reason_codes == ("content_similarity",) for item in first.recommendations
    )


def test_synthetic_user_content_uses_strictly_prior_history_and_filters_seen() -> None:
    service, _catalog = _runtime()
    request = _request(
        mode="synthetic_user",
        algorithm_id="tfidf_content",
        policy_id="synthetic-user-content-v1",
        candidate_policy="content_catalog",
        query={
            "kind": "synthetic_user",
            "user_id": "synthetic-electronics-v1:user:000001",
        },
    )

    response = service.recommend(request)

    assert response.status is RecommendationStatus.OK
    assert response.diagnostics.history_event_count == 1
    assert response.diagnostics.seen_exclusion_count == 1
    assert "synthetic-electronics-v1:item:000001" not in {
        item.product_id for item in response.recommendations
    }


def test_hybrid_policy_keeps_cold_products_content_only() -> None:
    service, _catalog = _runtime()
    request = _request(
        mode="hybrid",
        algorithm_id="weighted_rrf",
        policy_id="synthetic-hybrid-content-v1",
        candidate_policy="content_eligible_hybrid",
        query={"kind": "hybrid", "user_id": "synthetic-electronics-v1:user:000001"},
        k=10,
    )

    response = service.recommend(request)
    cold = "synthetic-electronics-v1:item:000006"
    item = next(
        (row for row in response.recommendations if row.product_id == cold), None
    )

    assert response.status is RecommendationStatus.OK
    assert item is None or "synthetic_item_cf" not in item.source_names
    assert all(
        "synthetic_bpr_control" in row.source_names
        or "tfidf_content" in row.source_names
        for row in response.recommendations
    )


def test_warm_hybrid_policy_does_not_return_cold_content_items() -> None:
    service, catalog = _runtime()
    request = _request(
        mode="hybrid",
        algorithm_id="weighted_rrf",
        policy_id="synthetic-hybrid-warm-v1",
        candidate_policy="warm_hybrid",
        query={"kind": "hybrid", "user_id": "synthetic-electronics-v1:user:000001"},
        k=10,
    )

    response = service.recommend(request)

    assert all(
        row.product_id in catalog.train_known_item_keys
        for row in response.recommendations
    )


def test_constraints_and_explicit_exclusions_are_enforced_after_retrieval() -> None:
    service, _catalog = _runtime()
    request = _product_request(
        k=10,
        excluded_product_ids=["synthetic-electronics-v1:item:000002"],
        constraints={
            "category": "laptop",
            "max_price": {"amount": Decimal("1000"), "currency": "USD"},
        },
    )

    response = service.recommend(request)

    assert all(
        row.product_id != "synthetic-electronics-v1:item:000002"
        for row in response.recommendations
    )


def test_invalid_query_catalog_algorithm_and_missing_artifact_fail_closed() -> None:
    service, _catalog = _runtime()
    unknown_product = _product_request(
        query={
            "kind": "product_to_product",
            "product_id": "synthetic-electronics-v1:item:999999",
        }
    )
    with pytest.raises(
        RecommendationServiceError, match="synthetic product is unknown"
    ):
        service.recommend(unknown_product)

    missing_registry = RecommendationService(
        catalog=build_synthetic_catalog(),
        artifacts=InMemoryRecommendationArtifactRegistry(()),
    )
    with pytest.raises(RecommendationServiceError, match="artifact"):
        missing_registry.recommend(_product_request())

    unsupported = _product_request().model_copy(update={"algorithm_version": "99"})
    with pytest.raises(RecommendationServiceError, match="algorithm"):
        service.recommend(unsupported)


def test_inference_never_refits_content_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _catalog = _runtime()

    def reject_fit(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("request-time TF-IDF fitting is forbidden")

    monkeypatch.setattr(ContentIndex, "fit", reject_fit)

    response = service.recommend(_product_request())

    assert response.status is RecommendationStatus.OK


def test_unexpected_retrieval_failures_return_safe_typed_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _catalog = _runtime()

    def fail_with_sensitive_detail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("private row value")

    monkeypatch.setattr(
        SyntheticRecommendationSource,
        "recommend_product_to_product",
        fail_with_sensitive_detail,
    )

    with pytest.raises(RecommendationServiceError) as error:
        service.recommend(_product_request())

    assert error.value.code.value == "EXECUTION_FAILED"
    assert "private row value" not in error.value.message
