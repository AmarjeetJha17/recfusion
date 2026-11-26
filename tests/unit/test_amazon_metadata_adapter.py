from __future__ import annotations

import json
from decimal import Decimal

import pytest

from recfusion_data.ingestion.adapters import amazon_electronics_item_key
from recfusion_data.ingestion.amazon_metadata import adapt_amazon_metadata_record
from recfusion_data.ingestion.errors import AdapterError


def test_metadata_adapter_maps_parent_key_and_conservative_fields() -> None:
    mapped = adapt_amazon_metadata_record(
        {
            "parent_asin": "Synthetic-Parent-01",
            "title": "Synthetic laptop",
            "main_category": "Electronics",
            "categories": ["Computers", "Laptops"],
            "description": ["Synthetic description"],
            "features": ["Synthetic feature"],
            "store": "Synthetic Store",
            "details": {"RAM": "16 GB", "Brand": "Synthetic Brand"},
            "average_rating": 4.8,
            "rating_number": 50,
            "price": 999.5,
            "images": [{"hi_res": "https://example.invalid/image"}],
            "videos": [{"title": "Synthetic video"}],
        },
        source_id="synthetic-amazon-electronics",
        source_version="fixture-v1",
    )

    assert mapped.product.item_key == amazon_electronics_item_key("Synthetic-Parent-01")
    assert mapped.product.title == "Synthetic laptop"
    assert mapped.product.category == "Electronics"
    assert mapped.product.categories == ("Computers", "Laptops")
    assert mapped.product.description == ("Synthetic description",)
    assert mapped.product.features == ("Synthetic feature",)
    assert mapped.product.attributes["store"] == "Synthetic Store"
    assert mapped.product.attributes["Brand"] == "Synthetic Brand"
    assert mapped.product.attributes["RAM"] == "16 GB"
    assert mapped.product.attributes["source_average_rating_raw"] == 4.8
    assert mapped.product.attributes["source_rating_count_raw"] == 50
    assert mapped.product.price is not None
    assert mapped.product.price.amount == Decimal("999.5")
    assert mapped.product.price.currency == "USD"
    assert mapped.product.images is None
    assert mapped.product.videos is None
    assert mapped.normalized.brand.value == "synthetic brand"
    assert mapped.normalized.brand.status.value == "normalized"
    assert (
        mapped.normalized.specifications["ram_capacity_bytes"].value == 16_000_000_000
    )
    assert mapped.field_issues == ()


def test_metadata_adapter_preserves_missing_title_nullable_and_empty_fields() -> None:
    mapped = adapt_amazon_metadata_record(
        {
            "parent_asin": "Synthetic-Parent-02",
            "title": None,
            "categories": [],
            "description": None,
            "features": None,
            "details": None,
        },
        source_id="synthetic-amazon-electronics",
        source_version="fixture-v1",
    )

    assert mapped.product.title is None
    assert mapped.product.categories == ()
    assert mapped.product.description is None
    assert mapped.product.features is None
    assert mapped.normalized.brand.status.value == "missing"
    assert mapped.normalized.price.status.value == "missing"
    assert mapped.field_issues == ()


def test_metadata_adapter_records_malformed_details_without_unsafe_parsing() -> None:
    mapped = adapt_amazon_metadata_record(
        {
            "parent_asin": "Synthetic-Parent-03",
            "details": "{'RAM': '16 GB'}",
            "store": "Not a brand",
        },
        source_id="synthetic-amazon-electronics",
        source_version="fixture-v1",
    )

    assert mapped.product.attributes["details_raw"] == "{'RAM': '16 GB'}"
    assert mapped.normalized.specifications["ram_capacity_bytes"].value is None
    assert mapped.normalized.brand.status.value == "missing"
    assert "malformed_details" in mapped.field_issues
    assert "brand" not in mapped.product.attributes


def test_metadata_adapter_parses_json_text_details_without_eval() -> None:
    mapped = adapt_amazon_metadata_record(
        {
            "parent_asin": "Synthetic-Parent-04",
            "details": json.dumps({"Processor": "Synthetic CPU", "Brand": "Acme"}),
            "store": "Synthetic Store",
        },
        source_id="synthetic-amazon-electronics",
        source_version="fixture-v1",
    )

    assert mapped.product.attributes["details_raw"] == json.dumps(
        {"Processor": "Synthetic CPU", "Brand": "Acme"}
    )
    assert mapped.normalized.specifications["processor_name"].value == "Synthetic CPU"
    assert mapped.normalized.brand.value == "acme"
    assert mapped.product.attributes["store"] == "Synthetic Store"


def test_metadata_adapter_marks_conflicting_explicit_attributes_ambiguous() -> None:
    mapped = adapt_amazon_metadata_record(
        {
            "parent_asin": "Synthetic-Parent-05",
            "details": {"RAM": "16 GB", "RAM Capacity": "32 GB"},
        },
        source_id="synthetic-amazon-electronics",
        source_version="fixture-v1",
    )

    assert mapped.normalized.specifications["ram_capacity_bytes"].status.value == (
        "ambiguous"
    )
    assert mapped.normalized.specifications["ram_capacity_bytes"].value is None


@pytest.mark.parametrize("parent_asin", [None, "", "   ", 123])
def test_metadata_adapter_rejects_invalid_parent_identifier(
    parent_asin: object,
) -> None:
    with pytest.raises(AdapterError, match="invalid_source_identifier"):
        adapt_amazon_metadata_record(
            {"parent_asin": parent_asin},
            source_id="synthetic-amazon-electronics",
            source_version="fixture-v1",
        )


def test_metadata_adapter_records_unsupported_optional_field_types() -> None:
    mapped = adapt_amazon_metadata_record(
        {
            "parent_asin": "Synthetic-Parent-06",
            "title": 12,
            "main_category": ["Electronics"],
            "categories": ["Computers", 2],
            "features": {"unexpected": "mapping"},
            "details": ["unexpected"],
            "price": "not-a-price",
        },
        source_id="synthetic-amazon-electronics",
        source_version="fixture-v1",
    )

    assert mapped.product.title is None
    assert mapped.product.category is None
    assert mapped.product.categories is None
    assert mapped.product.features is None
    assert mapped.product.price is None
    assert {
        "unsupported_title",
        "unsupported_main_category",
        "unsupported_categories",
        "unsupported_features",
        "unsupported_details",
        "invalid_price",
    }.issubset(mapped.field_issues)
