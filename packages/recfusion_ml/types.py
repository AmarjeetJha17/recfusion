"""Small typed records used by offline recommendation experiments."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class RatingEvent:
    user_key: str
    item_key: str
    rating: Decimal
    split: str

    def __post_init__(self) -> None:
        if not self.user_key.strip() or not self.item_key.strip():
            raise ValueError("Rating event identifiers must be non-empty.")
        if self.split not in {"train", "validation", "test"}:
            raise ValueError("Rating event split must be train, validation, or test.")
        if not self.rating.is_finite() or not Decimal("1") <= self.rating <= Decimal(
            "5"
        ):
            raise ValueError("Rating event rating must be finite and between 1 and 5.")
