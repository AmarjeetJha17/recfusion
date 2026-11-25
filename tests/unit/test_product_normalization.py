import json
from pathlib import Path

import pytest

from recfusion_data.ingestion.adapters import CanonicalSourceAdapter
from recfusion_data.ingestion.errors import RecordValidationError
from recfusion_data.ingestion.manifest import source_record_fingerprint
from recfusion_data.ingestion.readers import InputFormat, read_records
from recfusion_data.normalization import (
    NormalizationStatus,
    normalize_product_metadata,
)
from recfusion_data.validation import validate_product

pytestmark = pytest.mark.unit

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "ingestion"
_SOURCE_ID = "synthetic-product-normalization"
_SOURCE_VERSION = "v1"


def _normalized_fixture_records() -> list[dict[str, object]]:
    adapter = CanonicalSourceAdapter()
    normalized_records = []
    for row in read_records(
        _FIXTURES / "products-normalization.jsonl", InputFormat.JSONL
    ):
        assert row.values is not None
        adapted = adapter.product_fields(row.values)
        fingerprint = source_record_fingerprint(
            row.values, source_id=_SOURCE_ID, source_version=_SOURCE_VERSION
        )
        product, warnings = validate_product(adapted, fingerprint)
        normalized = normalize_product_metadata(
            product,
            raw_price=row.values.get("price"),
            invalid_price=any(issue.field == "price" for issue in warnings),
        )
        normalized_records.append(
            normalized.as_record(
                {
                    "item_key": product.item_key,
                    "title": product.title,
                    "category": product.category,
                    "attributes": product.attributes,
                    "source_record_fingerprint": product.source_record_fingerprint,
                },
                conflict_retained=None,
            )
        )
    return normalized_records


def test_electronics_specifications_use_explicit_conversions() -> None:
    records = _normalized_fixture_records()
    by_id = {record["product"]["item_key"]: record for record in records}

    laptop = by_id["synthetic_laptop"]["normalization"]
    assert laptop["brand"]["value"] == "acme systems"
    assert laptop["category"]["value"] == "laptops"
    assert laptop["specifications"]["ram_capacity_bytes"]["value"] == 16_000_000_000
    assert (
        laptop["specifications"]["storage_capacity_bytes"]["value"] == 1_000_000_000_000
    )
    assert laptop["specifications"]["storage_type"]["value"] == "ssd"
    assert laptop["specifications"]["display_size_mm"]["value"] == "396.24"
    assert laptop["specifications"]["weight_g"]["value"] == "1800"
    assert laptop["specifications"]["battery_capacity"]["value"] == "70"
    assert laptop["specifications"]["battery_capacity"]["unit"] == "Wh"
    assert laptop["specifications"]["processor_name"]["value"] == "Synthetic Core 7"
    assert laptop["specifications"]["gpu_name"]["value"] == "Synthetic Graphics 100"

    phone = by_id["synthetic_phone"]["normalization"]["specifications"]
    assert phone["ram_capacity_bytes"]["value"] == 8_589_934_592
    assert phone["storage_capacity_bytes"]["value"] == 256_000_000_000
    assert phone["storage_type"]["value"] == "ufs"
    assert phone["display_size_mm"]["value"] == "170.18"
    assert phone["weight_g"]["value"] == "190"
    assert phone["battery_capacity"]["value"] == "5000"
    assert phone["battery_capacity"]["unit"] == "mAh"


def test_missing_ambiguous_and_invalid_specifications_remain_unknown() -> None:
    by_id = {
        record["product"]["item_key"]: record["normalization"]
        for record in _normalized_fixture_records()
    }

    headphones = by_id["synthetic_headphones"]
    assert headphones["specifications"]["ram_capacity_bytes"]["status"] == "missing"
    assert headphones["specifications"]["battery_capacity"]["value"] == "0.04"
    assert headphones["specifications"]["battery_capacity"]["unit"] == "Wh"

    ambiguous = by_id["synthetic_ambiguous_units"]["specifications"]
    assert ambiguous["ram_capacity_bytes"]["value"] is None
    assert ambiguous["ram_capacity_bytes"]["status"] == "unsupported"
    assert ambiguous["storage_capacity_bytes"]["value"] is None
    assert ambiguous["storage_capacity_bytes"]["status"] == "unsupported"
    assert ambiguous["battery_capacity"]["value"] is None
    assert ambiguous["battery_capacity"]["status"] == "unsupported"
    assert ambiguous["display_size_mm"]["status"] == "unsupported"

    conflict = by_id["synthetic_attribute_conflict"]["specifications"]
    assert conflict["ram_capacity_bytes"]["value"] is None
    assert conflict["ram_capacity_bytes"]["status"] == "ambiguous"
    assert conflict["storage_type"]["value"] is None
    assert conflict["storage_type"]["status"] == "ambiguous"

    invalid = by_id["synthetic_invalid_ranges"]["specifications"]
    for field in (
        "ram_capacity_bytes",
        "storage_capacity_bytes",
        "display_size_mm",
        "weight_g",
        "battery_capacity",
    ):
        assert invalid[field]["value"] is None
        assert invalid[field]["status"] == "invalid"
    malformed = by_id["synthetic_malformed_numbers"]["specifications"]
    assert malformed["ram_capacity_bytes"]["status"] == "invalid"
    assert malformed["weight_g"]["status"] == "invalid"


def test_raw_values_provenance_and_explicit_currency_are_preserved() -> None:
    records = _normalized_fixture_records()
    laptop = next(
        record
        for record in records
        if record["product"]["item_key"] == "synthetic_laptop"
    )
    normalized = laptop["normalization"]

    assert (
        normalized["source_record_fingerprint"]
        == laptop["product"]["source_record_fingerprint"]
    )
    assert normalized["brand"]["raw_values"] == ("  ACME   Systems ",)
    assert normalized["specifications"]["ram_capacity_bytes"]["raw_values"] == (
        "16 GB",
    )
    assert normalized["price"]["raw_values"] == (
        {"amount": "999.00", "currency": "USD"},
    )
    assert normalized["price"]["value"] == {"amount": "999.00", "currency": "USD"}
    assert normalized["price"]["status"] == "normalized"

    product, warnings = validate_product(
        {"item_key": "synthetic_no_currency", "price": {"amount": "10.00"}},
        "c" * 64,
    )
    normalized_without_currency = normalize_product_metadata(
        product,
        raw_price={"amount": "10.00"},
        invalid_price=any(issue.field == "price" for issue in warnings),
    )
    assert normalized_without_currency.price.value is None
    assert normalized_without_currency.price.status is NormalizationStatus.INVALID
    assert normalized_without_currency.price.raw_values == ({"amount": "10.00"},)

    adapted = CanonicalSourceAdapter().product_fields(
        {"item_key": "synthetic_price_sentinel", "price": "None"}
    )
    product, warnings = validate_product(adapted, "f" * 64)
    normalized_sentinel = normalize_product_metadata(
        product,
        raw_price="None",
        invalid_price=any(issue.field == "price" for issue in warnings),
    )
    assert normalized_sentinel.price.raw_values == ("None",)
    assert normalized_sentinel.price.value is None
    assert normalized_sentinel.price.status is NormalizationStatus.INVALID


def test_normalization_results_are_order_independent() -> None:
    records = _normalized_fixture_records()
    forward = sorted(
        records,
        key=lambda record: (
            record["product"]["item_key"],
            record["normalization"]["source_record_fingerprint"],
        ),
    )
    reverse = sorted(
        reversed(records),
        key=lambda record: (
            record["product"]["item_key"],
            record["normalization"]["source_record_fingerprint"],
        ),
    )

    assert json.dumps(forward, sort_keys=True) == json.dumps(reverse, sort_keys=True)


def test_invalid_attribute_shapes_are_rejected_by_existing_product_contract() -> None:
    with pytest.raises(RecordValidationError, match="invalid_optional_field"):
        validate_product(
            {
                "item_key": "synthetic_invalid_attributes",
                "attributes": {"RAM": object()},
            },
            "d" * 64,
        )


def test_source_attributes_remain_unmodified() -> None:
    row = next(
        read_records(_FIXTURES / "products-normalization.jsonl", InputFormat.JSONL)
    )
    assert row.values is not None
    original_attributes = row.values["attributes"]
    product, _ = validate_product(
        CanonicalSourceAdapter().product_fields(row.values),
        source_record_fingerprint(
            row.values, source_id=_SOURCE_ID, source_version=_SOURCE_VERSION
        ),
    )
    normalized = normalize_product_metadata(product)

    assert product.attributes == original_attributes
    assert normalized.product.attributes == original_attributes


def test_explicit_null_attributes_and_price_remain_missing_with_raw_provenance() -> (
    None
):
    product, warnings = validate_product(
        {
            "item_key": "synthetic_null_values",
            "attributes": {"Brand": None, "RAM": None, "RAM Capacity": "8 GB"},
            "price": None,
        },
        "1" * 64,
    )
    normalized = normalize_product_metadata(
        product,
        raw_price=None,
        invalid_price=any(issue.field == "price" for issue in warnings),
        raw_price_present=True,
    )

    ram = normalized.specifications["ram_capacity_bytes"]
    assert ram.status is NormalizationStatus.NORMALIZED
    assert ram.raw_values == (None, "8 GB")
    assert normalized.brand.status is NormalizationStatus.MISSING
    assert normalized.brand.raw_values == (None,)
    assert normalized.price.status is NormalizationStatus.MISSING
    assert normalized.price.raw_values == (None,)
    assert normalized.price.source_keys == ("price",)
