"""Versioned offline recommendation request and response contracts."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

REQUEST_SCHEMA = "recfusion.recommendation-request.v1"
RESPONSE_SCHEMA = "recfusion.recommendation-response.v1"
ERROR_SCHEMA = "recfusion.recommendation-error.v1"
MAX_REQUEST_BYTES = 16_384
MAX_RECOMMENDATIONS = 20
MAX_EXCLUSIONS = 64
_ITEM_ID_PATTERN = r"^synthetic-electronics-v1:item:[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
_USER_ID_PATTERN = r"^synthetic-electronics-v1:user:[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"


class RecommendationMode(StrEnum):
    PRODUCT_TO_PRODUCT = "product_to_product"
    SYNTHETIC_USER = "synthetic_user"
    HYBRID = "hybrid"


class RecommendationErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_CONTRACT_VERSION = "UNSUPPORTED_CONTRACT_VERSION"
    UNSUPPORTED_ALGORITHM = "UNSUPPORTED_ALGORITHM"
    UNKNOWN_SYNTHETIC_PRODUCT = "UNKNOWN_SYNTHETIC_PRODUCT"
    UNKNOWN_SYNTHETIC_USER = "UNKNOWN_SYNTHETIC_USER"
    ARTIFACT_MISSING = "ARTIFACT_MISSING"
    ARTIFACT_CHECKSUM_INVALID = "ARTIFACT_CHECKSUM_INVALID"
    ARTIFACT_SCHEMA_INCOMPATIBLE = "ARTIFACT_SCHEMA_INCOMPATIBLE"
    CATALOG_MISMATCH = "CATALOG_MISMATCH"
    QUERY_PRODUCT_INELIGIBLE = "QUERY_PRODUCT_INELIGIBLE"
    UNSUPPORTED_CANDIDATE_POLICY = "UNSUPPORTED_CANDIDATE_POLICY"
    TOP_K_LIMIT_EXCEEDED = "TOP_K_LIMIT_EXCEEDED"
    EXCLUSION_LIMIT_EXCEEDED = "EXCLUSION_LIMIT_EXCEEDED"
    MISSING_CONTENT_SOURCE = "MISSING_CONTENT_SOURCE"
    MISSING_COLLABORATIVE_SOURCE = "MISSING_COLLABORATIVE_SOURCE"
    EXECUTION_FAILED = "EXECUTION_FAILED"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProductToProductQuery(_StrictModel):
    kind: Literal["product_to_product"]
    product_id: str = Field(pattern=_ITEM_ID_PATTERN, max_length=100)


class UserRecommendationQuery(_StrictModel):
    kind: Literal["synthetic_user", "hybrid"]
    user_id: str = Field(pattern=_USER_ID_PATTERN, max_length=100)
    target_product_id: str | None = Field(
        default=None, pattern=_ITEM_ID_PATTERN, max_length=100
    )


RecommendationQuery = Annotated[
    ProductToProductQuery | UserRecommendationQuery,
    Field(discriminator="kind"),
]


class PriceConstraint(_StrictModel):
    amount: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$", min_length=3, max_length=3)


class RecommendationConstraints(_StrictModel):
    category: str | None = Field(default=None, min_length=1, max_length=80)
    max_price: PriceConstraint | None = None


class RecommendationRequest(_StrictModel):
    schema_version: str
    mode: RecommendationMode
    catalog_id: Literal["synthetic-electronics-v1"]
    algorithm_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,47}$", max_length=48)
    algorithm_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
    policy_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$", max_length=64)
    candidate_policy: str = Field(pattern=r"^[a-z][a-z0-9_]{1,47}$", max_length=48)
    k: Annotated[int, Field(ge=1, le=MAX_RECOMMENDATIONS, strict=True)]
    query: RecommendationQuery
    excluded_product_ids: tuple[
        str,
        ...,
    ] = Field(default=(), max_length=MAX_EXCLUSIONS)
    constraints: RecommendationConstraints = Field(
        default_factory=RecommendationConstraints
    )

    @model_validator(mode="after")
    def validate_version_and_mode(self) -> RecommendationRequest:
        if self.schema_version != REQUEST_SCHEMA:
            raise ValueError("Unsupported recommendation request schema version.")
        if self.mode.value != self.query.kind:
            raise ValueError("Request mode and query kind must match.")
        if len(set(self.excluded_product_ids)) != len(self.excluded_product_ids):
            raise ValueError("Excluded product identifiers must be unique.")
        if any(
            not re.fullmatch(_ITEM_ID_PATTERN, item)
            for item in self.excluded_product_ids
        ):
            raise ValueError(
                "Excluded product identifiers must use the synthetic catalog namespace."
            )
        return self


class RecommendationItem(_StrictModel):
    product_id: str = Field(pattern=_ITEM_ID_PATTERN, max_length=100)
    rank: Annotated[int, Field(ge=1, le=MAX_RECOMMENDATIONS)]
    source_names: tuple[str, ...] = Field(max_length=4)
    reason_codes: tuple[str, ...] = Field(max_length=4)


class RecommendationStatus(StrEnum):
    OK = "ok"
    NO_RESULTS = "no_results"


class RecommendationDiagnostics(_StrictModel):
    candidate_count: Annotated[int, Field(ge=0)]
    eligible_count: Annotated[int, Field(ge=0)]
    returned_count: Annotated[int, Field(ge=0, le=MAX_RECOMMENDATIONS)]
    history_event_count: Annotated[int, Field(ge=0)] = 0
    seen_exclusion_count: Annotated[int, Field(ge=0)] = 0


class RecommendationResponse(_StrictModel):
    schema_version: Literal["recfusion.recommendation-response.v1"]
    request_id: str = Field(min_length=1, max_length=64)
    mode: RecommendationMode
    algorithm_id: str
    algorithm_version: str
    candidate_policy: str
    policy_id: str
    catalog_id: Literal["synthetic-electronics-v1"]
    catalog_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: RecommendationStatus
    result_count: Annotated[int, Field(ge=0, le=MAX_RECOMMENDATIONS)]
    diagnostics: RecommendationDiagnostics
    recommendations: tuple[RecommendationItem, ...] = Field(
        max_length=MAX_RECOMMENDATIONS
    )
    warnings: tuple[str, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def validate_result_reconciliation(self) -> RecommendationResponse:
        if self.result_count != len(self.recommendations):
            raise ValueError("Result count must match recommendation count.")
        expected_status = (
            RecommendationStatus.OK
            if self.recommendations
            else RecommendationStatus.NO_RESULTS
        )
        if self.status is not expected_status:
            raise ValueError("Response status must match whether results exist.")
        if tuple(item.rank for item in self.recommendations) != tuple(
            range(1, self.result_count + 1)
        ):
            raise ValueError("Recommendation ranks must be contiguous and ordered.")
        if self.diagnostics.returned_count != self.result_count:
            raise ValueError("Returned count must match result count.")
        if self.diagnostics.eligible_count > self.diagnostics.candidate_count:
            raise ValueError("Eligible count cannot exceed candidate count.")
        return self


class RecommendationError(_StrictModel):
    code: RecommendationErrorCode
    message: str = Field(min_length=1, max_length=160)


class RecommendationErrorResponse(_StrictModel):
    schema_version: Literal["recfusion.recommendation-error.v1"] = (
        "recfusion.recommendation-error.v1"
    )
    request_id: str = Field(min_length=1, max_length=64)
    error: RecommendationError


def parse_recommendation_request(payload: bytes) -> RecommendationRequest:
    """Bound untrusted payload bytes before schema validation."""
    if len(payload) > MAX_REQUEST_BYTES:
        raise ValueError("Recommendation request payload limit exceeded.")
    try:
        raw = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as error:
        raise ValueError("Invalid recommendation request payload.") from error
    if not isinstance(raw, dict):
        raise ValueError("Invalid recommendation request payload.")
    if raw.get("schema_version") != REQUEST_SCHEMA:
        raise ValueError("Unsupported contract version.")
    return RecommendationRequest.model_validate(raw)
