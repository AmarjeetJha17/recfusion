from enum import StrEnum

from pydantic import BaseModel


class ErrorCode(StrEnum):
    INVALID_CONSTRAINT = "INVALID_CONSTRAINT"
    UNAUTHORIZED = "UNAUTHORIZED"
    NO_ELIGIBLE_PRODUCTS = "NO_ELIGIBLE_PRODUCTS"
    CATALOG_UNAVAILABLE = "CATALOG_UNAVAILABLE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    HTTP_ERROR = "HTTP_ERROR"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str
