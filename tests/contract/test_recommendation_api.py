from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Event
from typing import Any, NoReturn

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


def test_production_does_not_mount_synthetic_routes_when_disabled() -> None:
    app = create_app(Settings(environment="production"))

    with TestClient(app) as client:
        response = client.post("/v1/recommendations", json=_request())
        openapi = client.get("/openapi.json")

    assert response.status_code == 404
    assert openapi.status_code == 404


def test_explicit_development_activation_serves_local_synthetic_route() -> None:
    with _local_client(_app(environment="development")) as client:
        response = client.post("/v1/recommendations", json=_request())

    assert response.status_code == 200


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
    assert "415" in operation["responses"]
    assert "503" in operation["responses"]


def test_non_loopback_peer_is_rejected() -> None:
    with _local_client(_app(), peer="203.0.113.4") as client:
        response = client.post("/v1/recommendations", json=_request())

    assert response.status_code == 403
    assert "203.0.113.4" not in response.text


def test_non_loopback_server_is_rejected() -> None:
    with _local_client(_app(), server="example.test") as client:
        response = client.post("/v1/recommendations", json=_request())

    assert response.status_code == 403


def test_wildcard_server_binding_is_rejected() -> None:
    with _local_client(_app(), server="0.0.0.0") as client:
        response = client.post("/v1/recommendations", json=_request())

    assert response.status_code == 403


def test_unexpected_host_header_is_rejected() -> None:
    with _local_client(_app()) as client:
        response = client.post(
            "/v1/recommendations",
            json=_request(),
            headers={"host": "public.example.test"},
        )

    assert response.status_code == 403
    assert "public.example.test" not in response.text


def test_malformed_loopback_host_authority_is_rejected() -> None:
    with _local_client(_app()) as client:
        response = client.post(
            "/v1/recommendations",
            json=_request(),
            headers={"host": "localhost:"},
        )

    assert response.status_code == 403


def test_forwarded_headers_do_not_upgrade_non_loopback_peer() -> None:
    with _local_client(_app(), peer="203.0.113.4") as client:
        response = client.post(
            "/v1/recommendations",
            json=_request(),
            headers={"x-forwarded-for": "127.0.0.1", "x-real-ip": "127.0.0.1"},
        )

    assert response.status_code == 403


def test_origin_does_not_enable_cors() -> None:
    with _local_client(_app()) as client:
        response = client.post(
            "/v1/recommendations",
            json=_request(),
            headers={"origin": "https://public.example.test"},
        )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_ipv6_loopback_is_supported() -> None:
    app = _app()
    with TestClient(
        app,
        base_url="http://[::1]",
        client=("::1", 43123),
    ) as client:
        response = client.post("/v1/recommendations", json=_request())

    assert response.status_code == 200


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


def test_missing_fields_are_rejected_with_versioned_error() -> None:
    request = _request()
    request.pop("policy_id")
    with _local_client(_app()) as client:
        response = client.post("/v1/recommendations", json=request)

    assert response.status_code == 422
    assert response.json()["schema_version"] == "recfusion.recommendation-error.v1"
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_duplicate_json_fields_are_rejected_as_ambiguous() -> None:
    body = json.dumps(_request()).replace('"k": 5', '"k": 5, "k": 1', 1)
    with _local_client(_app()) as client:
        response = client.post(
            "/v1/recommendations",
            content=body,
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_chunked_oversized_body_is_rejected_without_content_length() -> None:
    chunks = iter((b" " * 8192, b" " * 8192, b" " * 1))
    app = _app()
    observed_content_lengths: list[str | None] = []

    @app.middleware("http")
    async def record_content_length(request: Request, call_next: Any) -> Any:
        observed_content_lengths.append(request.headers.get("content-length"))
        return await call_next(request)

    with _local_client(app) as client:
        response = client.post(
            "/v1/recommendations",
            content=chunks,
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert observed_content_lengths == [None]


@pytest.mark.parametrize(
    "content_type",
    [None, "text/plain", "application/jsonp"],
)
def test_unsupported_content_type_is_rejected(content_type: str | None) -> None:
    headers = {} if content_type is None else {"content-type": content_type}
    with _local_client(_app()) as client:
        response = client.post(
            "/v1/recommendations", content=json.dumps(_request()), headers=headers
        )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_CONTENT_TYPE"


def test_query_parameters_cannot_override_json_contract() -> None:
    with _local_client(_app()) as client:
        response = client.post("/v1/recommendations?k=1&k=20", json=_request(k=5))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    "injected_fields",
    [
        {"checkpoint_path": "C:/private/model.pt"},
        {"artifact_url": "https://example.invalid/artifact"},
        {"source_weights": {"tfidf_content": 1000}},
        {"history": ["synthetic-electronics-v1:item:000001"]},
        {"algorithm_id": "x" * 5000},
    ],
)
def test_untrusted_extra_fields_and_long_values_are_rejected(
    injected_fields: dict[str, Any],
) -> None:
    with _local_client(_app()) as client:
        response = client.post("/v1/recommendations", json=_request(**injected_fields))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_algorithm_policy_mismatch_is_rejected() -> None:
    with _local_client(_app()) as client:
        response = client.post(
            "/v1/recommendations", json=_request(policy_id="synthetic-hybrid-warm-v1")
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNSUPPORTED_ALGORITHM"


def test_empty_result_is_explicit_and_not_an_error() -> None:
    request = _request(constraints={"category": "no-such-category"})
    with _local_client(_app()) as client:
        response = client.post("/v1/recommendations", json=request)

    assert response.status_code == 200
    assert response.json()["status"] == "no_results"
    assert response.json()["result_count"] == 0


def test_hybrid_target_product_is_excluded_from_results() -> None:
    request = _request(
        "hybrid",
        query={
            "kind": "hybrid",
            "user_id": "synthetic-electronics-v1:user:000001",
            "target_product_id": "synthetic-electronics-v1:item:000003",
        },
    )
    with _local_client(_app()) as client:
        response = client.post("/v1/recommendations", json=request)

    assert response.status_code == 200
    assert "synthetic-electronics-v1:item:000003" not in {
        item["product_id"] for item in response.json()["recommendations"]
    }


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


def test_unknown_synthetic_user_has_typed_not_found_error() -> None:
    request = _request(
        "synthetic_user",
        query={
            "kind": "synthetic_user",
            "user_id": "synthetic-electronics-v1:user:999999",
        },
    )
    with _local_client(_app()) as client:
        response = client.post("/v1/recommendations", json=request)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "UNKNOWN_SYNTHETIC_USER"


def test_missing_artifact_error_is_a_sanitized_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from recfusion_api.schemas.recommendation import RecommendationErrorCode
    from recfusion_api.services.recommendation import RecommendationServiceError

    app = _app()
    with _local_client(app) as client:
        service = app.state.recommendation_service

        def unavailable(_request: Any) -> NoReturn:
            raise RecommendationServiceError(
                RecommendationErrorCode.ARTIFACT_MISSING,
                "private path C:/private/artifact.json",
            )

        monkeypatch.setattr(service, "recommend", unavailable)
        response = client.post("/v1/recommendations", json=_request())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ARTIFACT_MISSING"
    assert "C:/private" not in response.text


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


def test_request_secrets_do_not_appear_in_logs_or_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _app()
    sentinel = "secret-token-must-not-be-logged"
    request = _request(api_key=sentinel)

    with _local_client(app) as client:
        response = client.post("/v1/recommendations", json=request)

    assert response.status_code == 422
    assert sentinel not in response.text
    assert sentinel not in caplog.text


def test_repeated_requests_are_deterministic_except_request_id() -> None:
    with _local_client(_app()) as client:
        first = client.post("/v1/recommendations", json=_request()).json()
        second = client.post("/v1/recommendations", json=_request()).json()

    first.pop("request_id")
    second.pop("request_id")
    assert first == second


def test_concurrent_requests_within_limit_preserve_deterministic_results() -> None:
    with _local_client(_app()) as client, ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            client.post, "/v1/recommendations", json=_request("hybrid")
        )
        second = executor.submit(
            client.post, "/v1/recommendations", json=_request("hybrid")
        )
        first_response = first.result(timeout=3)
        second_response = second.result(timeout=3)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    first_body = first_response.json()
    second_body = second_response.json()
    first_body.pop("request_id")
    second_body.pop("request_id")
    assert first_body == second_body


@pytest.mark.parametrize("mode", ["product_to_product", "synthetic_user", "hybrid"])
def test_http_result_matches_offline_service(mode: str) -> None:
    from recfusion_api.schemas.recommendation import RecommendationRequest

    app = _app()
    request_value = _request(mode)
    with _local_client(app) as client:
        service_result = app.state.recommendation_service.recommend(
            RecommendationRequest.model_validate(request_value)
        )
        offline = service_result.model_dump(mode="json")
        online_response = client.post("/v1/recommendations", json=request_value)

    assert online_response.status_code == 200
    online = online_response.json()
    offline.pop("request_id")
    online.pop("request_id")
    assert online == offline
    allowed_sources = {
        "tfidf_content",
        "synthetic_item_cf",
        "synthetic_bpr_control",
    }
    allowed_reasons = {"content_similarity", "hybrid_rrf"}
    for item in online["recommendations"]:
        assert set(item["source_names"]) <= allowed_sources
        assert set(item["reason_codes"]) <= allowed_reasons


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


def test_artifact_preparation_does_not_repeat_per_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = import_module("recfusion_api.services.recommendation_runtime")
    original = runtime.prepare_synthetic_recommendation_artifact
    calls = 0

    def counted_prepare(catalog: Any) -> Any:
        nonlocal calls
        calls += 1
        return original(catalog)

    monkeypatch.setattr(
        runtime, "prepare_synthetic_recommendation_artifact", counted_prepare
    )
    with _local_client(_app()) as client:
        for _ in range(3):
            assert (
                client.post("/v1/recommendations", json=_request()).status_code == 200
            )

    assert calls == 1


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


def test_configured_inference_saturation_is_rejected_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        Settings(
            environment="test",
            synthetic_demo_enabled=True,
            synthetic_demo_max_concurrency=1,
        )
    )
    started = Event()
    release = Event()

    def block_first_request(_request: Any) -> Any:
        started.set()
        if not release.wait(timeout=4):
            raise RuntimeError("test release event timed out")
        return original(_request)

    with _local_client(app) as client:
        service = app.state.recommendation_service
        original = service.recommend
        monkeypatch.setattr(service, "recommend", block_first_request)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(client.post, "/v1/recommendations", json=_request())
            assert started.wait(timeout=2)
            second = executor.submit(
                client.post, "/v1/recommendations", json=_request()
            )
            try:
                second_response = second.result(timeout=3)
            finally:
                release.set()
            first_response = first.result(timeout=3)

    assert second_response.status_code == 503
    assert second_response.json()["error"]["code"] == "CONCURRENCY_LIMIT_EXCEEDED"
    assert first_response.status_code == 200


def test_inference_capacity_is_released_after_service_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        Settings(
            environment="test",
            synthetic_demo_enabled=True,
            synthetic_demo_max_concurrency=1,
        )
    )
    with _local_client(app) as client:
        service = app.state.recommendation_service
        original = service.recommend
        calls = 0

        def fail_once(request: Any) -> Any:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("synthetic internal error")
            return original(request)

        monkeypatch.setattr(service, "recommend", fail_once)
        first = client.post("/v1/recommendations", json=_request())
        second = client.post("/v1/recommendations", json=_request())
        borrowed_tokens = app.state.recommendation_limiter.borrowed_tokens

    assert first.status_code == 500
    assert second.status_code == 200
    assert borrowed_tokens == 0


def test_concurrency_setting_has_small_default_and_rejects_out_of_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(environment="test", synthetic_demo_enabled=True)

    assert settings.synthetic_demo_max_concurrency == 2
    monkeypatch.setenv("RECFUSION_SYNTHETIC_DEMO_MAX_CONCURRENCY", "1")
    assert (
        Settings(
            environment="test", synthetic_demo_enabled=True
        ).synthetic_demo_max_concurrency
        == 1
    )
    for value in (0, 5):
        with pytest.raises(
            ValueError, match=r"greater than or equal to 1|less than or equal to 4"
        ):
            Settings(
                environment="test",
                synthetic_demo_enabled=True,
                synthetic_demo_max_concurrency=value,
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
    assert app.state.recommendation_limiter is None


@pytest.mark.parametrize(
    "validation_code",
    ["MISSING", "CHECKSUM_INVALID", "SCHEMA_INCOMPATIBLE", "CATALOG_MISMATCH"],
)
def test_artifact_validation_failures_do_not_publish_or_rebuild_runtime(
    monkeypatch: pytest.MonkeyPatch, validation_code: str
) -> None:
    from recfusion_ml.inference.artifacts import (
        ArtifactLoadError,
        ArtifactValidationCode,
    )

    runtime = import_module("recfusion_api.services.recommendation_runtime")
    original_prepare = runtime.prepare_synthetic_recommendation_artifact
    prepare_calls = 0
    code = ArtifactValidationCode[validation_code]

    def counted_prepare(catalog: Any) -> Any:
        nonlocal prepare_calls
        prepare_calls += 1
        return original_prepare(catalog)

    def reject_artifact(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise ArtifactLoadError(code, "artifact validation failed")

    monkeypatch.setattr(
        runtime, "prepare_synthetic_recommendation_artifact", counted_prepare
    )
    monkeypatch.setattr(runtime, "load_recommendation_artifact", reject_artifact)
    app = _app()

    with pytest.raises(ArtifactLoadError), _local_client(app):
        pytest.fail("invalid artifact must fail before serving")

    assert prepare_calls == 1
    assert app.state.initialized is False
    assert app.state.recommendation_service is None
    assert app.state.recommendation_limiter is None
