"""Adapters map source rows to canonical field names without validating them."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import ClassVar, Protocol

from recfusion_core.contracts import DataSplit
from recfusion_data.ingestion.errors import AdapterError

type SourceRecord = Mapping[str, object]


class SourceAdapter(Protocol):
    adapter_id: ClassVar[str]
    csv_headers: ClassVar[tuple[str, ...] | None]
    preserve_all_users: ClassVar[bool]
    deterministic_interaction_order: ClassVar[bool]

    def interaction_fields(
        self, record: SourceRecord, split: DataSplit
    ) -> Mapping[str, object]: ...

    def product_fields(self, record: SourceRecord) -> Mapping[str, object]: ...


_INTERACTION_FIELDS = frozenset({"user_key", "item_key", "event_time_ms", "rating"})
_PRODUCT_FIELDS = frozenset(
    {
        "item_key",
        "title",
        "category",
        "description",
        "features",
        "categories",
        "average_rating",
        "rating_count",
        "price",
        "images",
        "videos",
        "attributes",
    }
)
_JSON_FIELDS = frozenset(
    {"features", "categories", "price", "images", "videos", "attributes"}
)


class CanonicalSourceAdapter:
    """Accept files already using source-independent canonical field names."""

    adapter_id: ClassVar[str] = "canonical"
    csv_headers: ClassVar[tuple[str, ...] | None] = None
    preserve_all_users: ClassVar[bool] = False
    deterministic_interaction_order: ClassVar[bool] = False
    supports_products: ClassVar[bool] = True

    def interaction_fields(
        self, record: SourceRecord, split: DataSplit
    ) -> Mapping[str, object]:
        del split
        self._check_fields(record, _INTERACTION_FIELDS)
        return record

    def product_fields(self, record: SourceRecord) -> Mapping[str, object]:
        self._check_fields(record, _PRODUCT_FIELDS)
        adapted = dict(record)
        for field in _JSON_FIELDS:
            value = adapted.get(field)
            if isinstance(value, str) and value.strip():
                try:
                    adapted[field] = json.loads(value)
                except json.JSONDecodeError as error:
                    if field == "price":
                        continue
                    raise AdapterError("malformed_json_field", field) from error
        return adapted

    @staticmethod
    def _check_fields(record: SourceRecord, allowed_fields: frozenset[str]) -> None:
        unexpected = sorted(set(record) - allowed_fields)
        if unexpected:
            raise AdapterError("unexpected_field", unexpected[0])


class AmazonReviews2023ElectronicsAdapter:
    """Map the published Electronics 5-core timestamp CSV to canonical fields."""

    adapter_id: ClassVar[str] = "amazon-reviews-2023-electronics-5core-timestamp"
    csv_headers: ClassVar[tuple[str, ...] | None] = (
        "user_id",
        "parent_asin",
        "rating",
        "timestamp",
    )
    preserve_all_users: ClassVar[bool] = True
    deterministic_interaction_order: ClassVar[bool] = True
    retain_exact_duplicates: ClassVar[bool] = True
    supports_products: ClassVar[bool] = False
    record_rejections: ClassVar[bool] = True
    manifest_configuration: ClassVar[dict[str, object]] = {
        "adapter": adapter_id,
        "source_schema": ["user_id", "parent_asin", "rating", "timestamp"],
        "field_mapping": {
            "user_id": "user_key",
            "parent_asin": "item_key",
            "rating": "rating",
            "timestamp": "event_time_ms",
        },
        "timestamp_unit": "unix_ms",
        "split_mapping": {
            "train_file": "train",
            "validation_file": "validation",
            "test_file": "test",
        },
        "split_policy": "preserve explicit input file membership",
        "duplicate_policy": (
            "retain and count exact duplicate source rows; Step 2.4 preprocessing "
            "applies its documented duplicate policy"
        ),
        "history_source": "derived later from train events; source history unsupported",
        "user_key_policy": "sha256 of source, category, and exact user_id",
        "product_join": "disabled",
    }

    @staticmethod
    def unix_ms_to_utc(value: object) -> datetime:
        """Parse non-negative Unix milliseconds and return an aware UTC datetime."""
        if not isinstance(value, str) or not value.isascii() or not value.isdigit():
            raise AdapterError("invalid_timestamp", "timestamp")
        timestamp_ms = int(value)
        try:
            return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
                milliseconds=timestamp_ms
            )
        except (OverflowError, ValueError):
            raise AdapterError("invalid_timestamp", "timestamp") from None

    def interaction_fields(
        self, record: SourceRecord, split: DataSplit
    ) -> Mapping[str, object]:
        del split  # Split membership comes only from the caller's file mapping.
        expected_headers = self.csv_headers
        if expected_headers is None or set(record) != set(expected_headers):
            raise AdapterError("source_schema_mismatch")

        user_id = record["user_id"]
        parent_asin = record["parent_asin"]
        if (
            not isinstance(user_id, str)
            or not user_id.strip()
            or not isinstance(parent_asin, str)
            or not parent_asin.strip()
        ):
            raise AdapterError("invalid_source_identifier")

        user_digest = hashlib.sha256(
            f"amazon_reviews_2023\0Electronics\0{user_id}".encode()
        ).hexdigest()
        timestamp = record["timestamp"]
        utc_value = self.unix_ms_to_utc(timestamp)
        if not isinstance(timestamp, str):
            raise AdapterError("invalid_timestamp", "timestamp")
        assert utc_value.tzinfo is UTC
        return {
            "user_key": f"ar23:Electronics:user:{user_digest}",
            "item_key": f"ar23:Electronics:item:{parent_asin}",
            "rating": record["rating"],
            "event_time_ms": int(timestamp),
        }

    def product_fields(self, record: SourceRecord) -> Mapping[str, object]:
        del record
        raise AdapterError("unsupported_product_input")
