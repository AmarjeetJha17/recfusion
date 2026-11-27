from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from anyio import CapacityLimiter
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint

from recfusion_api.config import Settings
from recfusion_api.dependencies.recommendation import require_loopback_scope
from recfusion_api.exceptions import ApplicationError
from recfusion_api.logging_config import configure_logging, get_api_logger
from recfusion_api.routes.health import router as health_router
from recfusion_api.routes.recommendations import router as recommendations_router
from recfusion_api.schemas.errors import ErrorCode, ErrorDetail, ErrorResponse
from recfusion_api.services.recommendation_runtime import (
    build_synthetic_recommendation_service,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings()
    configure_logging(app_settings.log_level)
    logger = get_api_logger()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            if app_settings.synthetic_demo_enabled:
                app.state.recommendation_service = (
                    build_synthetic_recommendation_service()
                )
                app.state.recommendation_limiter = CapacityLimiter(
                    app_settings.synthetic_demo_max_concurrency
                )
            app.state.initialized = True
            yield
        finally:
            app.state.initialized = False
            app.state.recommendation_service = None
            app.state.recommendation_limiter = None

    app = FastAPI(
        title=app_settings.app_name,
        debug=app_settings.debug,
        docs_url=None if app_settings.environment == "production" else "/docs",
        openapi_url=(
            None if app_settings.environment == "production" else "/openapi.json"
        ),
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.initialized = False
    app.state.recommendation_service = None
    app.state.recommendation_limiter = None
    app.include_router(health_router)
    if app_settings.synthetic_demo_enabled:
        app.include_router(recommendations_router)

    @app.middleware("http")
    async def local_recommendation_origin_middleware(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not (
            app_settings.synthetic_demo_enabled
            and request.url.path == "/v1/recommendations"
        ):
            return await call_next(request)

        origin = request.headers.get("origin")
        if (
            origin is None
            or not require_loopback_scope(request)
            or origin != app_settings.synthetic_demo_allowed_origin
        ):
            response = JSONResponse(
                status_code=403,
                content={
                    "schema_version": "recfusion.recommendation-error.v1",
                    "request_id": getattr(request.state, "request_id", "unavailable"),
                    "error": {
                        "code": "INVALID_REQUEST",
                        "message": "The request could not be completed.",
                    },
                },
            )
            return response

        http_response: Response
        if request.method == "OPTIONS":
            requested_method = request.headers.get(
                "access-control-request-method", ""
            ).casefold()
            requested_headers = {
                header.strip().casefold()
                for header in request.headers.get(
                    "access-control-request-headers", ""
                ).split(",")
                if header.strip()
            }
            if requested_method != "post" or not requested_headers <= {"content-type"}:
                return JSONResponse(status_code=403, content={"detail": "Forbidden"})
            http_response = Response(status_code=204)
            http_response.headers["Access-Control-Allow-Methods"] = "POST"
            http_response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            http_response.headers["Access-Control-Max-Age"] = "0"
        else:
            http_response = await call_next(request)

        http_response.headers["Access-Control-Allow-Origin"] = origin
        http_response.headers["Vary"] = "Origin"
        return http_response

    @app.exception_handler(ApplicationError)
    async def application_error_handler(
        request: Request, error: ApplicationError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unavailable")
        logger.warning(
            "application_error",
            extra={
                "request_id": request_id,
                "error_code": error.code,
                "status_code": error.status_code,
            },
        )
        response = ErrorResponse(
            error=ErrorDetail(code=error.code, message=error.message),
            request_id=request_id,
        )
        return JSONResponse(
            status_code=error.status_code,
            content=response.model_dump(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unavailable")
        response = ErrorResponse(
            error=ErrorDetail(
                code=ErrorCode.HTTP_ERROR,
                message="The request could not be completed.",
            ),
            request_id=request_id,
        )
        return JSONResponse(
            status_code=error.status_code,
            content=response.model_dump(),
            headers=error.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(
        request: Request, _error: Exception
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unavailable")
        logger.error(
            "unhandled_application_error",
            extra={
                "request_id": request_id,
                "error_type": type(_error).__name__,
                "status_code": 500,
            },
        )
        response = ErrorResponse(
            error=ErrorDetail(
                code=ErrorCode.INTERNAL_SERVER_ERROR,
                message="An unexpected error occurred.",
            ),
            request_id=request_id,
        )
        return JSONResponse(status_code=500, content=response.model_dump())

    @app.middleware("http")
    async def request_correlation_middleware(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        route = request.scope.get("route")
        route_template = getattr(route, "path", None)
        if route_template is None:
            route_template = (
                request.url.path
                if request.url.path in {"/docs", "/openapi.json"}
                else "unmatched"
            )
        logger.info(
            "http_request",
            extra={
                "request_id": request_id,
                "http_method": request.method,
                "route": route_template,
                "status_code": response.status_code,
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response

    return app
