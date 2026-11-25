from dataclasses import fields
from decimal import Decimal

import pytest

from recfusion_core.contracts import DataSplit, Interaction, Money, ProductMetadata
from recfusion_data.validation import validate_interaction, validate_product

pytestmark = pytest.mark.contract


def test_interaction_validator_returns_the_canonical_contract() -> None:
    interaction = validate_interaction(
        {
            "user_key": "synthetic_user",
            "item_key": "synthetic_item",
            "event_time_ms": 1_700_000_000_000,
            "rating": "4.5",
        },
        DataSplit.VALIDATION,
        "a" * 64,
    )

    assert isinstance(interaction, Interaction)
    assert interaction.split is DataSplit.VALIDATION
    assert interaction.rating == Decimal("4.5")
    assert {field.name for field in fields(interaction)} == {
        "user_key",
        "item_key",
        "event_time_ms",
        "rating",
        "split",
        "source_event_fingerprint",
    }


def test_product_contract_preserves_optional_unknowns_and_money() -> None:
    product, warnings = validate_product(
        {
            "item_key": "synthetic_item",
            "price": {"amount": "12.50", "currency": "USD"},
        },
        "b" * 64,
    )

    assert isinstance(product, ProductMetadata)
    assert product.title is None
    assert product.features is None
    assert product.images is None
    assert product.price == Money(amount=Decimal("12.50"), currency="USD")
    assert warnings == ()
