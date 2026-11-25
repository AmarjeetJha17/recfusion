import pytest

from recfusion_data.normalization import normalize_product_metadata
from recfusion_data.validation import validate_product

pytestmark = pytest.mark.contract


def test_normalized_product_wrapper_reuses_canonical_product_contract() -> None:
    product, _ = validate_product(
        {
            "item_key": "synthetic_contract_product",
            "title": "Synthetic Contract Product",
            "category": " Electronics ",
            "description": ["Synthetic description"],
            "attributes": {"Brand": " Example Brand ", "RAM": "8 GiB"},
        },
        "e" * 64,
    )
    normalized = normalize_product_metadata(product)
    record = normalized.as_record(
        {
            "item_key": product.item_key,
            "title": product.title,
            "category": product.category,
            "description": product.description,
            "attributes": product.attributes,
            "source_record_fingerprint": product.source_record_fingerprint,
        },
        conflict_retained=False,
    )

    assert record["product"]["item_key"] == "synthetic_contract_product"
    assert record["product"]["description"] == ("Synthetic description",)
    assert record["normalization"]["schema_version"] == (
        "recfusion.product-normalization.v1"
    )
    assert record["normalization"]["brand"]["value"] == "example brand"
    assert record["normalization"]["category"]["value"] == "electronics"
    assert record["normalization"]["specifications"]["ram_capacity_bytes"] == {
        "raw_values": ("8 GiB",),
        "value": 8_589_934_592,
        "unit": "B",
        "status": "normalized",
        "source_keys": ("RAM",),
    }
