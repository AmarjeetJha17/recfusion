from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from recfusion_api.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
async def readiness(request: Request) -> ReadinessResponse | JSONResponse:
    demo_unavailable = (
        request.app.state.settings.synthetic_demo_enabled
        and request.app.state.recommendation_service is None
    )
    if not request.app.state.initialized or demo_unavailable:
        response = ReadinessResponse(status="not_ready")
        return JSONResponse(status_code=503, content=response.model_dump())
    return ReadinessResponse(status="ready")
