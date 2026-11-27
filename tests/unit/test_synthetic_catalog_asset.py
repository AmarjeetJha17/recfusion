from __future__ import annotations

import json
from importlib.resources import files

import pytest

from recfusion_core.synthetic_catalog import (
    SyntheticCatalogAssetError,
    _parse_asset,
    load_shared_synthetic_catalog,
)


def _asset() -> dict[str, object]:
    payload = (
        files("recfusion_core")
        .joinpath("data", "synthetic-electronics-v2.json")
        .read_bytes()
    )
    return json.loads(payload)


def test_shared_catalog_fingerprints_match_manifest_and_keep_authoritative_ids() -> (
    None
):
    catalog = load_shared_synthetic_catalog()
    manifest = json.loads(
        files("recfusion_core")
        .joinpath("data", "synthetic-electronics-v2.manifest.json")
        .read_bytes()
    )

    assert catalog.catalog_id == "synthetic-electronics-v1"
    assert catalog.version == "2"
    assert catalog.asset_fingerprint == manifest["asset_fingerprint"]
    assert catalog.compatibility_fingerprint == manifest["compatibility_fingerprint"]
    assert [product.item_key[-6:] for product in catalog.products] == [
        f"{number:06d}" for number in range(1, 11)
    ]
    assert catalog.products[7].title is None
    assert catalog.products[7].features == ()
    assert catalog.products[8].catalog_eligible is False
    assert catalog.products[9].visible is False


@pytest.mark.parametrize(
    ("mutation", "expected_message"),
    [
        (
            lambda value: value.update(
                schema_version="recfusion.synthetic-catalog.v99"
            ),
            "identity or version",
        ),
        (
            lambda value: value["products"].append(value["products"][0]),
            "identity or version",
        ),
        (lambda value: value["products"][0].update(title=12), "product data"),
        (lambda value: value["products"][0].update(synthetic=False), "product data"),
    ],
)
def test_shared_catalog_rejects_incompatible_assets(
    mutation: object, expected_message: str
) -> None:
    record = _asset()
    mutation(record)  # type: ignore[operator]

    with pytest.raises(SyntheticCatalogAssetError, match=expected_message):
        _parse_asset(json.dumps(record).encode())
