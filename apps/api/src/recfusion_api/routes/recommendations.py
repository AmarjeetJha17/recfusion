"""Development-only synthetic recommendation endpoint."""

from __future__ import annotations

from anyio import WouldBlock
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from recfusion_api.dependencies.recommendation import (
    RecommendationRequestParseError,
    has_json_content_type,
    parse_recommendation_payload,
    read_bounded_body,
    require_loopback_scope,
    run_with_capacity,
)
from recfusion_api.schemas.recommendation import (
    RecommendationError,
    RecommendationErrorCode,
    RecommendationErrorResponse,
    RecommendationRequest,
    RecommendationResponse,
)
from recfusion_api.services.recommendation import RecommendationServiceError

router = APIRouter(tags=["synthetic recommendations"])

_SERVICE_UNAVAILABLE = {
    RecommendationErrorCode.ARTIFACT_MISSING,
    RecommendationErrorCode.ARTIFACT_CHECKSUM_INVALID,
    RecommendationErrorCode.ARTIFACT_SCHEMA_INCOMPATIBLE,
    RecommendationErrorCode.CATALOG_MISMATCH,
    RecommendationErrorCode.MISSING_CONTENT_SOURCE,
    RecommendationErrorCode.MISSING_COLLABORATIVE_SOURCE,
    RecommendationErrorCode.DEMO_UNAVAILABLE,
}
_NOT_FOUND = {
    RecommendationErrorCode.UNKNOWN_SYNTHETIC_PRODUCT,
    RecommendationErrorCode.UNKNOWN_SYNTHETIC_USER,
}


def _error_response(
    request_id: str, code: RecommendationErrorCode, status_code: int
) -> JSONResponse:
    response = RecommendationErrorResponse(
        request_id=request_id,
        error=RecommendationError(
            code=code, message="The request could not be completed."
        ),
    )
    return JSONResponse(
        status_code=status_code, content=response.model_dump(mode="json")
    )


def _status_for(code: RecommendationErrorCode) -> int:
    if code in _NOT_FOUND:
        return 404
    if code in _SERVICE_UNAVAILABLE:
        return 503
    if code is RecommendationErrorCode.EXECUTION_FAILED:
        return 500
    return 422


@router.post(
    "/v1/recommendations",
    responses={
        200: {"model": RecommendationResponse},
        403: {"model": RecommendationErrorResponse},
        404: {"model": RecommendationErrorResponse},
        415: {"model": RecommendationErrorResponse},
        422: {"model": RecommendationErrorResponse},
        500: {"model": RecommendationErrorResponse},
        503: {"model": RecommendationErrorResponse},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": RecommendationRequest.model_json_schema(),
                }
            },
        }
    },
)
async def recommend(request: Request) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unavailable")
    if not require_loopback_scope(request):
        return _error_response(request_id, RecommendationErrorCode.INVALID_REQUEST, 403)
    if not has_json_content_type(request):
        return _error_response(
            request_id, RecommendationErrorCode.UNSUPPORTED_CONTENT_TYPE, 415
        )
    if request.query_params:
        return _error_response(request_id, RecommendationErrorCode.INVALID_REQUEST, 422)
    try:
        body = await read_bounded_body(request)
        recommendation_request = parse_recommendation_payload(body)
    except RecommendationRequestParseError as error:
        return _error_response(request_id, error.code, 422)

    service = getattr(request.app.state, "recommendation_service", None)
    limiter = getattr(request.app.state, "recommendation_limiter", None)
    if service is None or limiter is None:
        return _error_response(
            request_id, RecommendationErrorCode.DEMO_UNAVAILABLE, 503
        )
    try:
        result = await run_with_capacity(
            lambda: service.recommend(recommendation_request), limiter
        )
    except WouldBlock:
        return _error_response(
            request_id, RecommendationErrorCode.CONCURRENCY_LIMIT_EXCEEDED, 503
        )
    except RecommendationServiceError as error:
        return _error_response(request_id, error.code, _status_for(error.code))
    except Exception:
        return _error_response(
            request_id, RecommendationErrorCode.EXECUTION_FAILED, 500
        )
    response = result.model_copy(update={"request_id": request_id})
    return JSONResponse(status_code=200, content=response.model_dump(mode="json"))
