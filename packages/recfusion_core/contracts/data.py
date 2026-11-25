"""Canonical contracts shared by offline data tooling."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

type JSONValue = (
    bool | int | float | str | list[JSONValue] | dict[str, JSONValue] | None
)
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class DataSplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


@dataclass(frozen=True, slots=True)
class Interaction:
    user_key: str
    item_key: str
    event_time_ms: int
    rating: Decimal
    split: DataSplit
    source_event_fingerprint: str

    def __post_init__(self) -> None:
        if not self.user_key.strip() or not self.item_key.strip():
            raise ValueError("Interaction identifiers must be non-empty.")
        if isinstance(self.event_time_ms, bool) or self.event_time_ms < 0:
            raise ValueError("Interaction timestamp must be non-negative milliseconds.")
        if not self.rating.is_finite() or not Decimal("1") <= self.rating <= Decimal(
            "5"
        ):
            raise ValueError("Interaction rating must be finite and between 1 and 5.")
        if not _FINGERPRINT_PATTERN.fullmatch(self.source_event_fingerprint):
            raise ValueError("Interaction fingerprint must be a SHA-256 hex digest.")


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not self.amount.is_finite() or self.amount <= 0:
            raise ValueError("Money amount must be finite and positive.")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("Money currency must be a three-letter uppercase code.")


@dataclass(frozen=True, slots=True)
class ProductMetadata:
    item_key: str
    title: str | None
    category: str | None
    description: tuple[str, ...] | None
    features: tuple[str, ...] | None
    categories: tuple[str, ...] | None
    average_rating: Decimal | None
    rating_count: int | None
    price: Money | None
    images: tuple[JSONValue, ...] | None
    videos: tuple[JSONValue, ...] | None
    attributes: dict[str, JSONValue]
    source_record_fingerprint: str

    def __post_init__(self) -> None:
        if not self.item_key.strip():
            raise ValueError("Product item identifier must be non-empty.")
        if self.average_rating is not None and (
            not self.average_rating.is_finite()
            or not Decimal("0") <= self.average_rating <= Decimal("5")
        ):
            raise ValueError(
                "Product average rating must be finite and between 0 and 5."
            )
        if self.rating_count is not None and (
            isinstance(self.rating_count, bool) or self.rating_count < 0
        ):
            raise ValueError("Product rating count must be non-negative.")
        if not _FINGERPRINT_PATTERN.fullmatch(self.source_record_fingerprint):
            raise ValueError("Product fingerprint must be a SHA-256 hex digest.")
