from datetime import UTC
from decimal import Decimal

import pytest

from recfusion_core.contracts import DataSplit
from recfusion_data.ingestion.adapters import (
    AmazonReviews2023ElectronicsAdapter,
    amazon_electronics_item_key,
)
from recfusion_data.ingestion.errors import AdapterError, RecordValidationError
from recfusion_data.validation import validate_interaction


def test_amazon_row_maps_to_canonical_interaction_without_source_fields() -> None:
    adapter = AmazonReviews2023ElectronicsAdapter()
    mapped = adapter.interaction_fields(
        {
            "user_id": "synthetic_user_1",
            "parent_asin": "synthetic_item_1",
            "rating": "4.5",
            "timestamp": "1628643414042",
        },
        DataSplit.VALIDATION,
    )

    assert set(mapped) == {"user_key", "item_key", "rating", "event_time_ms"}
    assert mapped["user_key"].startswith("ar23:Electronics:user:")
    assert "synthetic_user_1" not in mapped["user_key"]
    assert mapped["item_key"] == "ar23:Electronics:item:synthetic_item_1"
    interaction = validate_interaction(mapped, DataSplit.VALIDATION, "a" * 64)
    assert interaction.rating == Decimal("4.5")
    assert interaction.event_time_ms == 1628643414042
    assert interaction.split is DataSplit.VALIDATION


def test_metadata_and_interaction_adapters_share_exact_item_key_mapping() -> None:
    parent_asin = "Synthetic-Parent-01"

    assert amazon_electronics_item_key(parent_asin) == (
        "ar23:Electronics:item:Synthetic-Parent-01"
    )
    mapped = AmazonReviews2023ElectronicsAdapter().interaction_fields(
        {
            "user_id": "synthetic_user_1",
            "parent_asin": parent_asin,
            "rating": "5",
            "timestamp": "1628643414042",
        },
        DataSplit.TRAIN,
    )
    assert mapped["item_key"] == amazon_electronics_item_key(parent_asin)


def test_amazon_item_key_mapping_does_not_normalize_source_identifier() -> None:
    parent_asin = " synthetic-ID "

    assert amazon_electronics_item_key(parent_asin) == (
        "ar23:Electronics:item: synthetic-ID "
    )


def test_amazon_timestamp_converts_to_aware_utc_datetime() -> None:
    converted = AmazonReviews2023ElectronicsAdapter.unix_ms_to_utc("1628643414042")

    assert converted.tzinfo is UTC
    assert converted.isoformat() == "2021-08-11T00:56:54.042000+00:00"


@pytest.mark.parametrize(
    "timestamp",
    ["", "1.5", "1e3", "-1", "9223372036854775807"],
)
def test_amazon_adapter_rejects_invalid_epoch_milliseconds(
    timestamp: str,
) -> None:
    with pytest.raises(AdapterError, match="invalid_timestamp"):
        AmazonReviews2023ElectronicsAdapter().interaction_fields(
            {
                "user_id": "synthetic_user",
                "parent_asin": "synthetic_item",
                "rating": "5",
                "timestamp": timestamp,
            },
            DataSplit.TRAIN,
        )


@pytest.mark.parametrize(
    ("user_id", "parent_asin"),
    [("", "synthetic_item"), ("synthetic_user", "")],
)
def test_amazon_adapter_rejects_missing_source_identifiers(
    user_id: str, parent_asin: str
) -> None:
    with pytest.raises(AdapterError, match="invalid_source_identifier"):
        AmazonReviews2023ElectronicsAdapter().interaction_fields(
            {
                "user_id": user_id,
                "parent_asin": parent_asin,
                "rating": "5",
                "timestamp": "1628643414042",
            },
            DataSplit.TRAIN,
        )


def test_amazon_source_does_not_define_product_mapping() -> None:
    with pytest.raises(AdapterError, match="unsupported_product_input"):
        AmazonReviews2023ElectronicsAdapter().product_fields({"parent_asin": "x"})


def test_mapped_rating_still_uses_canonical_range_validation() -> None:
    mapped = AmazonReviews2023ElectronicsAdapter().interaction_fields(
        {
            "user_id": "synthetic_user",
            "parent_asin": "synthetic_item",
            "rating": "5.1",
            "timestamp": "1628643414042",
        },
        DataSplit.TRAIN,
    )

    with pytest.raises(RecordValidationError, match="invalid_rating"):
        validate_interaction(mapped, DataSplit.TRAIN, "b" * 64)
