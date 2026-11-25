"""Canonical normalization and validation, separate from file parsing."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import cast

from recfusion_core.contracts import (
    DataSplit,
    Interaction,
    JSONValue,
    Money,
    ProductMetadata,
)
from recfusion_data.ingestion.errors import RecordValidationError, ValidationIssue

_INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")


def _required_identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecordValidationError(
            (ValidationIssue("missing_or_invalid_identifier", field),)
        )
    return value


def _decimal(value: object, field: str, code: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise RecordValidationError((ValidationIssue(code, field),))
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise RecordValidationError((ValidationIssue(code, field),)) from None
    if not result.is_finite():
        raise RecordValidationError((ValidationIssue(code, field),))
    return result


def _timestamp(value: object) -> int:
    if isinstance(value, bool) or value is None:
        raise RecordValidationError(
            (ValidationIssue("invalid_timestamp", "event_time_ms"),)
        )
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and _INTEGER_PATTERN.fullmatch(value.strip()):
        result = int(value)
    else:
        raise RecordValidationError(
            (ValidationIssue("invalid_timestamp", "event_time_ms"),)
        )
    if result < 0:
        raise RecordValidationError(
            (ValidationIssue("invalid_timestamp", "event_time_ms"),)
        )
    return result


def validate_interaction(
    values: Mapping[str, object],
    split: DataSplit,
    source_event_fingerprint: str,
) -> Interaction:
    user_key = _required_identifier(values.get("user_key"), "user_key")
    item_key = _required_identifier(values.get("item_key"), "item_key")
    event_time_ms = _timestamp(values.get("event_time_ms"))
    rating = _decimal(values.get("rating"), "rating", "invalid_rating")
    if not Decimal("1") <= rating <= Decimal("5"):
        raise RecordValidationError((ValidationIssue("invalid_rating", "rating"),))
    return Interaction(
        user_key=user_key,
        item_key=item_key,
        event_time_ms=event_time_ms,
        rating=rating,
        split=split,
        source_event_fingerprint=source_event_fingerprint,
    )


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RecordValidationError((ValidationIssue("invalid_optional_field", field),))
    return value


def _optional_text_tuple(value: object, field: str) -> tuple[str, ...] | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise RecordValidationError((ValidationIssue("invalid_optional_field", field),))


def _is_json_value(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_value(item) for key, item in value.items()
        )
    return False


def _optional_json_tuple(value: object, field: str) -> tuple[JSONValue, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(_is_json_value(item) for item in value):
        raise RecordValidationError((ValidationIssue("invalid_optional_field", field),))
    return cast(tuple[JSONValue, ...], tuple(value))


def _optional_decimal(
    value: object, field: str, low: Decimal, high: Decimal
) -> Decimal | None:
    if value is None or value == "":
        return None
    result = _decimal(value, field, "invalid_optional_field")
    if not low <= result <= high:
        raise RecordValidationError((ValidationIssue("invalid_optional_field", field),))
    return result


def _optional_integer(value: object, field: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise RecordValidationError((ValidationIssue("invalid_optional_field", field),))
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and _INTEGER_PATTERN.fullmatch(value.strip()):
        result = int(value)
    else:
        raise RecordValidationError((ValidationIssue("invalid_optional_field", field),))
    if result < 0:
        raise RecordValidationError((ValidationIssue("invalid_optional_field", field),))
    return result


def _attributes(value: object) -> dict[str, JSONValue]:
    if value is None or value == "":
        return {}
    if not isinstance(value, dict) or not _is_json_value(value):
        raise RecordValidationError(
            (ValidationIssue("invalid_optional_field", "attributes"),)
        )
    return cast(dict[str, JSONValue], dict(value))


def _price(value: object) -> tuple[Money | None, tuple[ValidationIssue, ...]]:
    if value is None or value == "":
        return None, ()
    if not isinstance(value, dict):
        return None, (ValidationIssue("invalid_optional_price", "price"),)
    amount = value.get("amount")
    currency = value.get("currency")
    if not isinstance(currency, str):
        return None, (ValidationIssue("invalid_optional_price", "price"),)
    try:
        money = Money(
            amount=_decimal(amount, "price.amount", "invalid_price"), currency=currency
        )
    except (RecordValidationError, ValueError):
        return None, (ValidationIssue("invalid_optional_price", "price"),)
    return money, ()


def validate_product(
    values: Mapping[str, object], source_record_fingerprint: str
) -> tuple[ProductMetadata, tuple[ValidationIssue, ...]]:
    item_key = _required_identifier(values.get("item_key"), "item_key")
    category = _optional_text(values.get("category"), "category")
    average_rating = _optional_decimal(
        values.get("average_rating"), "average_rating", Decimal("0"), Decimal("5")
    )
    rating_count = _optional_integer(values.get("rating_count"), "rating_count")
    price, warnings = _price(values.get("price"))
    product = ProductMetadata(
        item_key=item_key,
        title=_optional_text(values.get("title"), "title"),
        category=category,
        description=_optional_text_tuple(values.get("description"), "description"),
        features=_optional_text_tuple(values.get("features"), "features"),
        categories=_optional_text_tuple(values.get("categories"), "categories"),
        average_rating=average_rating,
        rating_count=rating_count,
        price=price,
        images=_optional_json_tuple(values.get("images"), "images"),
        videos=_optional_json_tuple(values.get("videos"), "videos"),
        attributes=_attributes(values.get("attributes")),
        source_record_fingerprint=source_record_fingerprint,
    )
    return product, warnings
