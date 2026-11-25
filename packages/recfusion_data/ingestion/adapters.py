"""Adapters map source rows to canonical field names without validating them."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol

from recfusion_core.contracts import DataSplit
from recfusion_data.ingestion.errors import AdapterError

type SourceRecord = Mapping[str, object]


class SourceAdapter(Protocol):
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
