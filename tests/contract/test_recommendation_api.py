from __future__ import annotations

from importlib import import_module
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from recfusion_api.app import create_app
from recfusion_api.config import Environment, Settings
from recfusion_api.dependencies.recommendation import require_loopback_scope

pytestmark = pytest.mark.contract


def _app(*, enabled: bool = True, environment: Environment = "test") -> FastAPI:
    return create_app(Settings(environment=environment, synthetic_demo_enabled=enabled))


def _request(mode: str = "product_to_product", **updates: Any) -> dict[str, Any]:
    requests: dict[str, dict[str, Any]] = {
        "product_to_product": {
            "algorithm_id": "tfidf_content",
            "policy_id": "content-similarity-v1",
            "candidate_policy": "content_catalog",
            "query": {
                "kind": "product_to_product",
                "product_id": "synthetic-electronics-v1:item:000001",
            },
        },
        "synthetic_user": {
            "algorithm_id": "tfidf_content",
            "policy_id": "synthetic-user-content-v1",
            "candidate_policy": "content_catalog",
            "query": {
                "kind": "synthetic_user",
                "user_id": "synthetic-electronics-v1:user:000001",
            },
        },
        "hybrid": {
            "algorithm_id": "weighted_rrf",
            "policy_id": "synthetic-hybrid-content-v1",
            "candidate_policy": "content_eligible_hybrid",
            "query": {
                "kind": "hybrid",
                "user_id": "synthetic-electronics-v1:user:000001",
            },
        },
    }
    value: dict[str, Any] = {
        "schema_version": "recfusion.recommendation-request.v1",
        "mode": mode,
        "catalog_id": "synthetic-electronics-v1",
        "algorithm_version": "1",
        "k": 5,
        "excluded_product_ids": [],
        "constraints": {},
        **requests[mode],
    }
    value.update(updates)
    return value


def _local_client(
    app: FastAPI,
    *,
    peer: str = "127.0.0.1",
    server: str = "127.0.0.1",
) -> TestClient:
    return TestClient(
        app,
        base_url=f"http://{server}",
        client=(peer, 43123),
    )


def test_demo_is_disabled_by_default_and_route_is_absent_from_openapi() -> None:
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        assert client.get("/ready").json() == {"status": "ready"}
        assert client.post("/v1/recommendations", json=_request()).status_code == 404
        openapi = client.get("/openapi.json").json()

    assert "/v1/recommendations" not in openapi["paths"]


def test_production_rejects_synthetic_demo_activation() -> None:
    with pytest.raises(ValueError, match="production"):
        Settings(environment="production", synthetic_demo_enabled=True)


def test_enabled_app_serves_all_three_modes_with_versioned_responses() -> None:
    app = _app()

    with _local_client(app) as client:
        assert client.get("/ready").json() == {"status": "ready"}
        for mode in ("product_to_product", "synthetic_user", "hybrid"):
            response = client.post("/v1/recommendations", json=_request(mode))
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["schema_version"] == "recfusion.recommendation-response.v1"
            assert body["mode"] == mode
            assert body["request_id"] == response.headers["x-request-id"]
            assert body["result_count"] == len(body["recommendations"])
            returned = {item["product_id"] for item in body["recommendations"]}
            if mode == "synthetic_user":
                assert "synthetic-electronics-v1:item:000001" not in returned
            if mode == "hybrid":
                cold_id = "synthetic-electronics-v1:item:000006"
                cold_item = next(
                    (
                        item
                        for item in body["recommendations"]
                        if item["product_id"] == cold_id
                    ),
                    None,
                )
                assert (
                    cold_item is None
                    or "synthetic_item_cf" not in cold_item["source_names"]
                )


def test_openapi_describes_request_and_versioned_responses() -> None:
    with _local_client(_app()) as client:
        operation = client.get("/openapi.json").json()["paths"]["/v1/recommendations"][
            "post"
        ]

    assert operation["requestBody"]["content"]["application/json"]["schema"]
    assert "200" in operation["responses"]
    assert "422" in operation["responses"]


def test_non_loopback_peer_is_rejected() -> None:
    with _local_client(_app(), peer="203.0.113.4") as client:
        response = client.post("/v1/recommendations", json=_request())

    assert response.status_code == 403
    assert "203.0.113.4" not in response.text


def test_non_loopback_server_is_rejected() -> None:
    with _local_client(_app(), server="example.test") as client:
        response = client.post("/v1/recommendations", json=_request())

    assert response.status_code == 403


def test_missing_asgi_addresses_fail_closed() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/recommendations",
            "headers": [],
            "client": None,
            "server": ("127.0.0.1", 8000),
        }
    )

    assert require_loopback_scope(request) is False


def test_request_body_bounds_and_schema_failures_are_safe() -> None:
    with _local_client(_app()) as client:
        oversized = client.post(
            "/v1/recommendations",
            content=b" " * 16_385,
            headers={"content-type": "application/json"},
        )
        malformed = client.post(
            "/v1/recommendations",
            content=b"not-json",
            headers={"content-type": "application/json"},
        )
        unsupported = client.post(
            "/v1/recommendations",
            json=_request(schema_version="recfusion.recommendation-request.v9"),
        )

    assert oversized.status_code == 422
    assert oversized.json()["error"]["code"] == "INVALID_REQUEST"
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "INVALID_REQUEST"
    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["code"] == "UNSUPPORTED_CONTRACT_VERSION"


def test_top_k_and_exclusion_bounds_have_specific_error_codes() -> None:
    too_many_exclusions = _request(
        excluded_product_ids=[
            f"synthetic-electronics-v1:item:{index:06d}" for index in range(65)
        ]
    )
    with _local_client(_app()) as client:
        top_k_response = client.post("/v1/recommendations", json=_request(k=21))
        exclusion_response = client.post(
            "/v1/recommendations", json=too_many_exclusions
        )

    assert top_k_response.status_code == 422
    assert top_k_response.json()["error"]["code"] == "TOP_K_LIMIT_EXCEEDED"
    assert exclusion_response.status_code == 422
    assert exclusion_response.json()["error"]["code"] == "EXCLUSION_LIMIT_EXCEEDED"


def test_unknown_ids_have_typed_not_found_errors() -> None:
    unknown_product = _request(
        query={
            "kind": "product_to_product",
            "product_id": "synthetic-electronics-v1:item:999999",
        }
    )
    with _local_client(_app()) as client:
        response = client.post("/v1/recommendations", json=unknown_product)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "UNKNOWN_SYNTHETIC_PRODUCT"


def test_unexpected_runtime_errors_are_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app()

    with _local_client(app) as client:
        service = app.state.recommendation_service
        monkeypatch.setattr(
            service,
            "recommend",
            lambda _request: (_ for _ in ()).throw(RuntimeError("private detail")),
        )
        response = client.post("/v1/recommendations", json=_request())

    assert response.status_code == 500
    assert "private detail" not in response.text
    assert response.json()["error"]["code"] == "EXECUTION_FAILED"


def test_repeated_requests_are_deterministic_except_request_id() -> None:
    with _local_client(_app()) as client:
        first = client.post("/v1/recommendations", json=_request()).json()
        second = client.post("/v1/recommendations", json=_request()).json()

    first.pop("request_id")
    second.pop("request_id")
    assert first == second


def test_service_is_built_once_per_app_lifespan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_module = import_module("recfusion_api.app")
    original = app_module.build_synthetic_recommendation_service
    calls = 0

    def counted_builder() -> Any:
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(
        app_module, "build_synthetic_recommendation_service", counted_builder
    )
    app = _app()
    with _local_client(app) as client:
        client.post("/v1/recommendations", json=_request())
        client.post("/v1/recommendations", json=_request())
        assert app.state.recommendation_service is not None

    assert calls == 1
    assert app.state.recommendation_service is None


def test_app_instances_have_separate_runtime_state() -> None:
    first_app = _app()
    second_app = _app()

    with _local_client(first_app), _local_client(second_app):
        assert first_app.state.recommendation_service is not None
        assert second_app.state.recommendation_service is not None
        assert (
            first_app.state.recommendation_service
            is not second_app.state.recommendation_service
        )


def test_missing_runtime_is_not_ready_and_returns_typed_503() -> None:
    app = _app()

    with _local_client(app) as client:
        app.state.recommendation_service = None
        readiness = client.get("/ready")
        response = client.post("/v1/recommendations", json=_request())

    assert readiness.status_code == 503
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEMO_UNAVAILABLE"


def test_artifact_startup_failure_prevents_app_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_module = import_module("recfusion_api.app")

    def fail_builder() -> Any:
        raise RuntimeError("private artifact detail")

    monkeypatch.setattr(
        app_module, "build_synthetic_recommendation_service", fail_builder
    )
    app = _app()

    with (
        pytest.raises(RuntimeError, match="private artifact detail"),
        _local_client(app),
    ):
        pytest.fail("app startup should fail before serving requests")

    assert app.state.initialized is False
    assert app.state.recommendation_service is None
