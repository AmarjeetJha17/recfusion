from typing import cast

import pytest

from recfusion_data.features.generation import (
    FEATURE_INTERACTION_SCHEMA,
    FEATURE_ITEM_SCHEMA,
    FEATURE_SCHEMA_VERSION,
    TRANSFORMERS_SCHEMA_VERSION,
    _feature_schema,
)

pytestmark = pytest.mark.contract


def test_feature_schema_separates_temporal_and_snapshot_metadata() -> None:
    schema = _feature_schema()
    snapshot = cast(dict[str, object], schema["snapshot_product_features"])

    assert schema["schema_version"] == FEATURE_SCHEMA_VERSION
    assert schema["interaction_record_schema"] == FEATURE_INTERACTION_SCHEMA
    assert schema["item_record_schema"] == FEATURE_ITEM_SCHEMA
    assert snapshot["historical_availability_claims"] is False
    assert snapshot["price_and_rating_aggregates"] == "excluded"
    assert schema["unobserved_items"] == "unknown, never negative"


def test_feature_schema_declares_train_only_fitting_and_strict_history() -> None:
    schema = _feature_schema()
    temporal = cast(list[dict[str, object]], schema["temporal_interaction_features"])

    assert {field["name"] for field in temporal} == {
        "user_prior_interaction_count",
        "user_prior_mean_rating",
        "item_prior_interaction_count",
        "item_prior_mean_rating",
    }
    policy = cast(dict[str, object], schema["history_policy"])
    assert (
        policy["validation"]
        == "training interactions only, strictly before target time"
    )
    assert policy["test"] == "training interactions only, strictly before target time"
    assert policy["held_out_events_update_history"] is False
    assert TRANSFORMERS_SCHEMA_VERSION == "recfusion.feature-transformers.v1"
