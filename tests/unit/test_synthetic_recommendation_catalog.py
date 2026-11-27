from __future__ import annotations

from recfusion_api.services.synthetic_catalog import (
    SYNTHETIC_CATALOG_ID,
    build_synthetic_catalog,
)
from recfusion_core.contracts import DataSplit


def test_synthetic_catalog_is_bounded_versioned_and_deterministic() -> None:
    first = build_synthetic_catalog()
    second = build_synthetic_catalog()

    assert first.catalog_id == SYNTHETIC_CATALOG_ID
    assert first.version == "1"
    assert first.catalog_fingerprint == second.catalog_fingerprint
    assert first.bundle_fingerprint == second.bundle_fingerprint
    assert len(first.list_products()) == 10
    assert len(first.list_products()) <= first.max_catalog_size


def test_catalog_distinguishes_warm_cold_missing_conflicted_and_hidden() -> None:
    catalog = build_synthetic_catalog()
    warm_ids = catalog.train_known_item_keys
    visible = {product.item_key: product for product in catalog.list_products()}

    assert len(warm_ids) == 5
    assert visible["synthetic-electronics-v1:item:000006"].item_key not in warm_ids
    assert visible["synthetic-electronics-v1:item:000008"].content_fields == ()
    assert not visible["synthetic-electronics-v1:item:000009"].catalog_eligible
    assert not visible["synthetic-electronics-v1:item:000010"].visible


def test_synthetic_histories_are_train_only_bounded_and_namespaced() -> None:
    catalog = build_synthetic_catalog()
    context = catalog.get_user_context("synthetic-electronics-v1:user:000001")

    assert context.prediction_time_ms == 2_000
    assert len(context.training_history) == 3
    assert all(event.split is DataSplit.TRAIN for event in context.training_history)
    assert all(event.user_key == context.user_key for event in context.training_history)
    assert len(context.training_history) <= catalog.max_history_events
    assert (
        catalog.get_user_context(
            "synthetic-electronics-v1:user:000003"
        ).training_history
        == ()
    )


def test_synthetic_collaborative_rankings_are_fixed_and_read_only() -> None:
    catalog = build_synthetic_catalog()
    rankings = catalog.get_collaborative_rankings(
        "synthetic-electronics-v1:user:000001"
    )

    assert rankings["synthetic_item_cf"][0] == "synthetic-electronics-v1:item:000006"
    assert rankings["synthetic_item_cf"][1] == "synthetic-electronics-v1:item:000004"
