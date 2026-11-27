"""Fail-closed scope and bounded body helpers for the demo recommendation API."""

from __future__ import annotations

import ipaddress
import json
from typing import Any

from fastapi import Request
from pydantic import ValidationError

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
    """Return true only when direct ASGI peer and server addresses are loopback."""
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
    return True


def parse_recommendation_payload(payload: bytes) -> RecommendationRequest:
    if len(payload) > MAX_REQUEST_BYTES:
        raise RecommendationRequestParseError(RecommendationErrorCode.INVALID_REQUEST)
    try:
        raw: Any = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
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
