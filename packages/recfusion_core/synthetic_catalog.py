"""Load and validate the shared, synthetic-only electronics catalog asset."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

CATALOG_ASSET = "data/synthetic-electronics-v2.json"
CATALOG_MANIFEST = "data/synthetic-electronics-v2.manifest.json"
CATALOG_SCHEMA = "recfusion.synthetic-catalog.v2"
CATALOG_ID = "synthetic-electronics-v1"
CATALOG_VERSION = "2"
_ID = re.compile(r"^synthetic-electronics-v1:item:\d{6}$")
_FINGERPRINT = re.compile(r"^[a-f0-9]{64}$")
_CATEGORIES = {"laptop", "smartphone", "audio", "monitor", "accessory"}


class SyntheticCatalogAssetError(ValueError):
    """Raised when the shared asset is missing or fails its strict schema."""


@dataclass(frozen=True, slots=True)
class SharedSyntheticProduct:
    item_key: str
    title: str | None
    category: str | None
    description: tuple[str, ...]
    features: tuple[str, ...]
    source_record_fingerprint: str
    catalog_eligible: bool
    visible: bool


@dataclass(frozen=True, slots=True)
class SharedSyntheticCatalog:
    catalog_id: str
    version: str
    asset_fingerprint: str
    compatibility_fingerprint: str
    products: tuple[SharedSyntheticProduct, ...]


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _compatibility_bytes(products: list[dict[str, Any]]) -> bytes:
    projection = [
        {
            key: product[key]
            for key in (
                "id",
                "title",
                "category",
                "description",
                "features",
                "source_record_fingerprint",
                "catalog_eligible",
                "visible",
            )
        }
        for product in products
    ]
    return json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _parse_asset(payload: bytes) -> tuple[str, str, list[dict[str, Any]]]:
    try:
        record: Any = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as error:
        raise SyntheticCatalogAssetError("Shared catalog is not valid JSON.") from error
    if not isinstance(record, dict) or set(record) != {
        "schema_version",
        "catalog_id",
        "catalog_version",
        "products",
    }:
        raise SyntheticCatalogAssetError("Shared catalog envelope is invalid.")
    if (
        record["schema_version"] != CATALOG_SCHEMA
        or record["catalog_id"] != CATALOG_ID
        or record["catalog_version"] != CATALOG_VERSION
        or not isinstance(record["products"], list)
        or len(record["products"]) != 10
    ):
        raise SyntheticCatalogAssetError(
            "Shared catalog identity or version is invalid."
        )
    products: list[dict[str, Any]] = record["products"]
    expected_keys = {
        "id",
        "title",
        "category",
        "description",
        "features",
        "source_record_fingerprint",
        "catalog_eligible",
        "visible",
        "synthetic",
    }
    ids: set[str] = set()
    for product in products:
        if not isinstance(product, dict) or set(product) != expected_keys:
            raise SyntheticCatalogAssetError("Shared catalog product shape is invalid.")
        identity = product["id"]
        category = product["category"]
        if (
            not isinstance(identity, str)
            or not _ID.fullmatch(identity)
            or identity in ids
            or (product["title"] is not None and not isinstance(product["title"], str))
            or (category is not None and category not in _CATEGORIES)
            or not isinstance(product["description"], list)
            or not all(
                isinstance(value, str) and value for value in product["description"]
            )
            or not isinstance(product["features"], list)
            or not all(
                isinstance(value, str) and value for value in product["features"]
            )
            or not isinstance(product["source_record_fingerprint"], str)
            or not _FINGERPRINT.fullmatch(product["source_record_fingerprint"])
            or type(product["catalog_eligible"]) is not bool
            or type(product["visible"]) is not bool
            or product["synthetic"] is not True
        ):
            raise SyntheticCatalogAssetError("Shared catalog product data is invalid.")
        ids.add(identity)
    if ids != {f"{CATALOG_ID}:item:{number:06d}" for number in range(1, 11)}:
        raise SyntheticCatalogAssetError(
            "Shared catalog product identity set is invalid."
        )
    if [product["id"] for product in products] != sorted(ids):
        raise SyntheticCatalogAssetError(
            "Shared catalog products are not canonically ordered."
        )
    return CATALOG_ID, CATALOG_VERSION, products


def load_shared_synthetic_catalog() -> SharedSyntheticCatalog:
    """Read the installed package asset and compute asset/compatibility hashes."""
    try:
        package_files = files("recfusion_core")
        payload = package_files.joinpath(*CATALOG_ASSET.split("/")).read_bytes()
        manifest_payload = package_files.joinpath(
            *CATALOG_MANIFEST.split("/")
        ).read_bytes()
    except (FileNotFoundError, ModuleNotFoundError, OSError) as error:
        raise SyntheticCatalogAssetError(
            "Shared synthetic catalog is unavailable."
        ) from error
    catalog_id, version, records = _parse_asset(payload)
    try:
        manifest: Any = json.loads(manifest_payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise SyntheticCatalogAssetError(
            "Shared catalog manifest is invalid."
        ) from error
    asset_fingerprint = _sha256(payload)
    compatibility_fingerprint = _sha256(_compatibility_bytes(records))
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {
            "schema_version",
            "catalog_id",
            "catalog_version",
            "asset_fingerprint",
            "compatibility_fingerprint",
        }
        or manifest.get("schema_version") != "recfusion.synthetic-catalog-manifest.v1"
        or manifest.get("catalog_id") != catalog_id
        or manifest.get("catalog_version") != version
        or manifest.get("asset_fingerprint") != asset_fingerprint
        or manifest.get("compatibility_fingerprint") != compatibility_fingerprint
    ):
        raise SyntheticCatalogAssetError(
            "Shared catalog fingerprints do not match manifest."
        )
    products = tuple(
        SharedSyntheticProduct(
            item_key=record["id"],
            title=record["title"],
            category=record["category"],
            description=tuple(record["description"]),
            features=tuple(record["features"]),
            source_record_fingerprint=record["source_record_fingerprint"],
            catalog_eligible=record["catalog_eligible"],
            visible=record["visible"],
        )
        for record in records
    )
    return SharedSyntheticCatalog(
        catalog_id=catalog_id,
        version=version,
        asset_fingerprint=asset_fingerprint,
        compatibility_fingerprint=compatibility_fingerprint,
        products=products,
    )
