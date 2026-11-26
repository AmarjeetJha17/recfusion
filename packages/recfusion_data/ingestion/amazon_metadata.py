"""Source-specific mapping for Amazon Reviews 2023 product metadata."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import cast

from recfusion_core.contracts import JSONValue, ProductMetadata
from recfusion_data.ingestion.adapters import amazon_electronics_item_key
from recfusion_data.ingestion.errors import AdapterError
from recfusion_data.ingestion.manifest import source_record_fingerprint
from recfusion_data.normalization import (
    NormalizedProductMetadata,
    normalize_product_metadata,
)
from recfusion_data.validation import validate_product

AMAZON_ELECTRONICS_METADATA_FIELDS = frozenset(
    {
        "parent_asin",
        "title",
        "main_category",
        "categories",
        "description",
        "features",
        "store",
        "details",
        "average_rating",
        "rating_number",
        "price",
        "images",
        "videos",
        "bought_together",
    }
)


@dataclass(frozen=True, slots=True)
class MappedAmazonMetadata:
    product: ProductMetadata
    normalized: NormalizedProductMetadata
    field_issues: tuple[str, ...]
    unknown_fields: tuple[str, ...]


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


def _details_values(value: object) -> tuple[dict[str, object] | None, str | None]:
    if value is None:
        return None, None
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError):
            return None, "malformed_details"
    if isinstance(parsed, dict) and _is_json_value(parsed):
        return cast(dict[str, object], parsed), None
    return None, "unsupported_details"


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _text_or_tuple(value: object, *, allow_scalar: bool) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, str) and allow_scalar:
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    return None


def _price_amount(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None or isinstance(value, (dict, list)):
        return None
    if not isinstance(value, (str, int, float)):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() and amount > 0 else None


def adapt_amazon_metadata_record(
    record: Mapping[str, object], *, source_id: str, source_version: str
) -> MappedAmazonMetadata:
    """Map one validated JSON object while retaining only safe canonical fields."""
    parent_asin = record.get("parent_asin")
    if not isinstance(parent_asin, str) or not parent_asin.strip():
        raise AdapterError("invalid_source_identifier", "parent_asin")

    issues: set[str] = set()
    attributes: dict[str, JSONValue] = {}
    for source_name, target_name in (
        ("average_rating", "source_average_rating_raw"),
        ("rating_number", "source_rating_count_raw"),
        ("price", "source_price_raw"),
    ):
        if source_name in record:
            value = record[source_name]
            if _is_json_value(value):
                attributes[target_name] = cast(JSONValue, value)
            else:
                issues.add(f"unsupported_{source_name}")

    details: dict[str, object] | None = None
    if "details" in record:
        raw_details = record["details"]
        if _is_json_value(raw_details):
            attributes["details_raw"] = cast(JSONValue, raw_details)
        else:
            issues.add("unsupported_details")
        details, details_issue = _details_values(raw_details)
        if details_issue is not None:
            issues.add(details_issue)
        if details is not None:
            for key, value in details.items():
                if key in attributes or key == "store":
                    issues.add("conflicting_attribute_key")
                    continue
                if _is_json_value(value):
                    attributes[key] = cast(JSONValue, value)
                else:
                    issues.add("unsupported_details_value")

    if "store" in record:
        store = record["store"]
        if store is None or isinstance(store, str):
            attributes["store"] = store
        else:
            issues.add("unsupported_store")
    if "bought_together" in record:
        value = record["bought_together"]
        if _is_json_value(value):
            attributes["bought_together"] = cast(JSONValue, value)
        else:
            issues.add("unsupported_bought_together")

    title_value = record.get("title")
    if title_value is None or isinstance(title_value, str):
        title = title_value
    else:
        title = None
        issues.add("unsupported_title")

    category_value = record.get("main_category")
    if category_value is None or isinstance(category_value, str):
        category = category_value
    else:
        category = None
        issues.add("unsupported_main_category")

    text_fields: dict[str, tuple[str, ...] | None] = {}
    for field in ("categories", "description", "features"):
        if field not in record:
            text_fields[field] = None
            continue
        source_value = record[field]
        parsed = _text_or_tuple(source_value, allow_scalar=field != "categories")
        text_fields[field] = parsed
        if source_value is not None and parsed is None:
            issues.add(f"unsupported_{field}")

    price_present = "price" in record
    raw_price = record.get("price")
    price_amount = _price_amount(raw_price)
    if price_present and raw_price not in (None, "") and price_amount is None:
        issues.add("invalid_price")
    if price_present:
        attributes["source_price_status"] = (
            "invalid"
            if "invalid_price" in issues
            else "normalized"
            if price_amount is not None
            else "missing"
        )

    source_fields: dict[str, object] = {
        "item_key": amazon_electronics_item_key(parent_asin),
        "title": title,
        "category": category,
        "categories": (
            list(text_fields["categories"])
            if text_fields["categories"] is not None
            else None
        ),
        "description": (
            list(text_fields["description"])
            if text_fields["description"] is not None
            else None
        ),
        "features": (
            list(text_fields["features"])
            if text_fields["features"] is not None
            else None
        ),
        "price": (
            {"amount": str(price_amount), "currency": "USD"}
            if price_amount is not None
            else None
        ),
        "attributes": attributes,
    }
    fingerprint = source_record_fingerprint(
        record, source_id=source_id, source_version=source_version
    )
    product, warnings = validate_product(source_fields, fingerprint)
    if warnings:
        issues.update(issue.code for issue in warnings)
    normalized = normalize_product_metadata(
        product,
        raw_price=raw_price,
        invalid_price="invalid_price" in issues,
        raw_price_present=price_present,
    )
    return MappedAmazonMetadata(
        product=product,
        normalized=normalized,
        field_issues=tuple(sorted(issues)),
        unknown_fields=tuple(sorted(set(record) - AMAZON_ELECTRONICS_METADATA_FIELDS)),
    )
