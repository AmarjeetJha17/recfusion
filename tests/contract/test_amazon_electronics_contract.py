from dataclasses import fields
from decimal import Decimal

import pytest

from recfusion_core.contracts import DataSplit, Interaction
from recfusion_data.ingestion.adapters import AmazonReviews2023ElectronicsAdapter
from recfusion_data.validation import validate_interaction

pytestmark = pytest.mark.contract


def test_amazon_adapter_produces_the_existing_interaction_contract() -> None:
    fields_from_source = AmazonReviews2023ElectronicsAdapter().interaction_fields(
        {
            "user_id": "synthetic_contract_user",
            "parent_asin": "synthetic_contract_item",
            "rating": "1.0",
            "timestamp": "1628643414042",
        },
        DataSplit.TRAIN,
    )
    interaction = validate_interaction(fields_from_source, DataSplit.TRAIN, "c" * 64)

    assert isinstance(interaction, Interaction)
    assert interaction.rating == Decimal("1.0")
    assert interaction.split is DataSplit.TRAIN
    assert interaction.event_time_ms == 1628643414042
    assert {field.name for field in fields(Interaction)} == {
        "user_key",
        "item_key",
        "event_time_ms",
        "rating",
        "split",
        "source_event_fingerprint",
    }
