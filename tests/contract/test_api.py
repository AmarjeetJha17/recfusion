from fastapi import FastAPI
from fastapi.testclient import TestClient

from recfusion_api.app import create_app
from recfusion_api.config import Settings
from recfusion_api.exceptions import ApplicationError
from recfusion_api.schemas.errors import ErrorCode


def make_test_app(settings: Settings | None = None) -> FastAPI:
    return create_app(settings or Settings(environment="test"))


def test_health_and_ready_endpoints_report_local_status() -> None:
    app = make_test_app()

    with TestClient(app) as client:
        health = client.get("/health")
        readiness = client.get("/ready")

        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        assert readiness.status_code == 200
        assert readiness.json() == {"status": "ready"}
        assert health.headers["x-request-id"]

        app.state.initialized = False
        not_ready = client.get("/ready")

        assert not_ready.status_code == 503
        assert not_ready.json() == {"status": "not_ready"}

    assert app.state.initialized is False


def test_openapi_is_available_outside_production() -> None:
    with TestClient(make_test_app()) as client:
        openapi = client.get("/openapi.json")
        docs = client.get("/docs")

    assert openapi.status_code == 200
    assert openapi.json()["info"]["title"] == "RecFusion API"
    assert docs.status_code == 200


def test_openapi_is_disabled_in_production() -> None:
    settings = Settings(environment="production")

    with TestClient(make_test_app(settings)) as client:
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/docs").status_code == 404


def test_validation_errors_keep_fastapi_response_shape() -> None:
    app = make_test_app()

    def validation_probe(count: int) -> dict[str, int]:
        return {"count": count}

    app.add_api_route("/_test/validation/{count}", validation_probe)

    with TestClient(app) as client:
        response = client.get("/_test/validation/not-an-integer")

    assert response.status_code == 422
    assert "detail" in response.json()
    assert response.headers["x-request-id"]


def test_application_errors_use_safe_json_envelope() -> None:
    app = make_test_app()

    def application_error_probe() -> None:
        raise ApplicationError(
            code=ErrorCode.INVALID_CONSTRAINT,
            message="The operation cannot be completed.",
            status_code=422,
        )

    app.add_api_route("/_test/application-error", application_error_probe)

    with TestClient(app) as client:
        response = client.get("/_test/application-error")

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "INVALID_CONSTRAINT",
            "message": "The operation cannot be completed.",
        },
        "request_id": response.headers["x-request-id"],
    }


def test_unexpected_errors_do_not_expose_exception_details() -> None:
    app = make_test_app()

    def unexpected_error_probe() -> None:
        raise RuntimeError("sensitive exception detail")

    app.add_api_route("/_test/unexpected-error", unexpected_error_probe)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_test/unexpected-error")

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "INTERNAL_SERVER_ERROR",
        "message": "An unexpected error occurred.",
    }
    assert "sensitive exception detail" not in response.text


def test_http_errors_use_safe_json_envelope() -> None:
    with TestClient(make_test_app()) as client:
        response = client.get("/not-found")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_ERROR"
    assert response.json()["request_id"] == response.headers["x-request-id"]
