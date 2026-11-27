"""Fail-closed scope and bounded body helpers for the demo recommendation API."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from anyio import CapacityLimiter
from fastapi import Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from recfusion_api.schemas.recommendation import (
    MAX_REQUEST_BYTES,
    REQUEST_SCHEMA,
    RecommendationErrorCode,
    RecommendationRequest,
)


class RecommendationRequestParseError(ValueError):
    def __init__(self, code: RecommendationErrorCode) -> None:
        super().__init__("The recommendation request is invalid.")
        self.code = code


def require_loopback_scope(request: Request) -> bool:
    """Require loopback ASGI addresses and a supported local Host authority."""
    for address in (request.scope.get("client"), request.scope.get("server")):
        if not isinstance(address, (tuple, list)) or not address:
            return False
        host = address[0]
        if not isinstance(host, str):
            return False
        try:
            if not ipaddress.ip_address(host).is_loopback:
                return False
        except ValueError:
            return False
    return _is_loopback_host_authority(request.headers.get("host"))


def _is_loopback_host_authority(authority: str | None) -> bool:
    if (
        not authority
        or authority.endswith(":")
        or "," in authority
        or any(char.isspace() for char in authority)
    ):
        return False
    try:
        parsed = urlsplit(f"//{authority}")
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65_535)
        or parsed.hostname is None
    ):
        return False
    hostname = parsed.hostname.casefold()
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def has_json_content_type(request: Request) -> bool:
    content_type = request.headers.get("content-type")
    if content_type is None:
        return False
    media_type = content_type.split(";", maxsplit=1)[0].strip().casefold()
    return media_type == "application/json"


async def run_with_capacity[ResultT](
    function: Callable[[], ResultT], limiter: CapacityLimiter
) -> ResultT:
    """Run one synchronous inference while holding one non-queued capacity token."""
    limiter.acquire_nowait()
    try:
        return await run_in_threadpool(function)
    finally:
        limiter.release()


def parse_recommendation_payload(payload: bytes) -> RecommendationRequest:
    if len(payload) > MAX_REQUEST_BYTES:
        raise RecommendationRequestParseError(RecommendationErrorCode.INVALID_REQUEST)

    def reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON object field.")
            result[key] = value
        return result

    try:
        raw: Any = json.loads(payload, object_pairs_hook=reject_duplicate_fields)
    except (ValueError, UnicodeDecodeError, TypeError):
        raise RecommendationRequestParseError(
            RecommendationErrorCode.INVALID_REQUEST
        ) from None
    if not isinstance(raw, dict):
        raise RecommendationRequestParseError(RecommendationErrorCode.INVALID_REQUEST)
    if raw.get("schema_version") != REQUEST_SCHEMA:
        raise RecommendationRequestParseError(
            RecommendationErrorCode.UNSUPPORTED_CONTRACT_VERSION
        )
    try:
        return RecommendationRequest.model_validate(raw)
    except ValidationError as error:
        locations = {tuple(entry["loc"]) for entry in error.errors()}
        if any("k" in location for location in locations):
            code = RecommendationErrorCode.TOP_K_LIMIT_EXCEEDED
        elif any("excluded_product_ids" in location for location in locations):
            code = RecommendationErrorCode.EXCLUSION_LIMIT_EXCEEDED
        else:
            code = RecommendationErrorCode.INVALID_REQUEST
        raise RecommendationRequestParseError(code) from None


async def read_bounded_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            raise RecommendationRequestParseError(
                RecommendationErrorCode.INVALID_REQUEST
            ) from None
        if declared_length < 0 or declared_length > MAX_REQUEST_BYTES:
            raise RecommendationRequestParseError(
                RecommendationErrorCode.INVALID_REQUEST
            )
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_REQUEST_BYTES:
            raise RecommendationRequestParseError(
                RecommendationErrorCode.INVALID_REQUEST
            )
        chunks.append(chunk)
    return b"".join(chunks)
