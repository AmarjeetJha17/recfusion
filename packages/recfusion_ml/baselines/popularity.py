"""A train-only, positive-rating-count popularity recommender."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass
from decimal import Decimal

from recfusion_ml.types import RatingEvent


@dataclass(frozen=True, slots=True)
class PopularityRecommender:
    """Ranks train-known items by positive-review count, then item key."""

    candidate_items: tuple[str, ...]
    positive_review_counts: Mapping[str, int]

    @classmethod
    def fit(
        cls,
        training_events: Iterable[RatingEvent],
        candidate_items: Set[str],
        *,
        positive_min_rating: Decimal = Decimal("4"),
    ) -> PopularityRecommender:
        events = tuple(training_events)
        if any(event.split != "train" for event in events):
            raise ValueError("Popularity can only be fit from the training split.")

        train_items = {event.item_key for event in events}
        pool = set(candidate_items)
        if pool - train_items:
            raise ValueError("Candidate pool contains items that are not train-known.")
        if train_items - pool:
            raise ValueError("Candidate pool must contain every train-known item.")

        counts: Counter[str] = Counter()
        for event in events:
            if event.rating >= positive_min_rating:
                counts[event.item_key] += 1

        ordered = tuple(sorted(pool, key=lambda item: (-counts[item], item)))
        return cls(ordered, {item: counts[item] for item in ordered})

    def recommend(self, *, seen_items: Set[str], k: int) -> tuple[str, ...]:
        if isinstance(k, bool) or k < 0:
            raise ValueError("Recommendation limit must be a non-negative integer.")
        if k == 0:
            return ()
        return tuple(item for item in self.candidate_items if item not in seen_items)[
            :k
        ]
