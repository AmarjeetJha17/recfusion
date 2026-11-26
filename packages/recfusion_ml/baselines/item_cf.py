"""Sparse, binary item-item collaborative filtering baseline."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from math import sqrt

from recfusion_ml.types import RatingEvent

_POSITIVE_MIN_RATING = Decimal("4")


@dataclass(frozen=True, slots=True)
class ItemCFConfig:
    """Fixed safeguards for sparse similarity and per-user pair expansion."""

    max_positive_history_items: int = 20
    min_shared_users: int = 2
    max_neighbors_per_item: int = 100

    def __post_init__(self) -> None:
        for name, value in (
            ("max_positive_history_items", self.max_positive_history_items),
            ("min_shared_users", self.min_shared_users),
            ("max_neighbors_per_item", self.max_neighbors_per_item),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        if self.min_shared_users < 2:
            raise ValueError("min_shared_users must be at least 2.")


@dataclass(frozen=True, slots=True)
class ItemCFFitSummary:
    positive_observation_count: int
    unique_positive_user_item_pairs: int
    repeated_positive_observations_collapsed: int
    users_with_positive_history: int
    truncated_user_count: int
    truncated_positive_item_count: int
    cooccurrence_pair_count: int
    supported_similarity_pair_count: int
    retained_neighbor_edges: int


@dataclass(frozen=True, slots=True)
class ItemCFRecommendation:
    items: tuple[str, ...]
    candidate_count: int
    positive_history_count: int
    fallback_used: bool = False


@dataclass(frozen=True, slots=True)
class ItemBasedCollaborativeFilter:
    """Cosine neighbors over binary positive user-item interactions."""

    candidate_items: frozenset[str]
    positive_history_by_user: Mapping[str, frozenset[str]]
    seen_items_by_user: Mapping[str, frozenset[str]]
    positive_user_counts: Mapping[str, int]
    neighbors_by_item: Mapping[str, tuple[tuple[str, float], ...]]
    fit_summary: ItemCFFitSummary
    config: ItemCFConfig

    @classmethod
    def fit(
        cls,
        training_events: Iterable[RatingEvent],
        candidate_items: Set[str],
        *,
        config: ItemCFConfig = ItemCFConfig(),
    ) -> ItemBasedCollaborativeFilter:
        events = tuple(training_events)
        if any(event.split != "train" for event in events):
            raise ValueError("Item-CF can only be fit from the training split.")

        train_items = {event.item_key for event in events}
        pool = frozenset(candidate_items)
        if pool != train_items:
            raise ValueError("Candidate pool must exactly match train-known items.")

        seen_by_user: dict[str, set[str]] = defaultdict(set)
        positive_by_user: dict[str, set[str]] = defaultdict(set)
        positive_observation_count = 0
        for event in events:
            seen_by_user[event.user_key].add(event.item_key)
            if event.rating >= _POSITIVE_MIN_RATING:
                positive_observation_count += 1
                positive_by_user[event.user_key].add(event.item_key)

        positive_user_counts: Counter[str] = Counter()
        for items in positive_by_user.values():
            positive_user_counts.update(items)

        truncated_user_count = 0
        truncated_positive_item_count = 0
        capped_histories: dict[str, tuple[str, ...]] = {}
        for user_key in sorted(seen_by_user):
            ranked_history = sorted(
                positive_by_user[user_key],
                key=lambda item: (-positive_user_counts[item], item),
            )
            retained = tuple(ranked_history[: config.max_positive_history_items])
            capped_histories[user_key] = retained
            if len(retained) < len(ranked_history):
                truncated_user_count += 1
                truncated_positive_item_count += len(ranked_history) - len(retained)

        item_ids = tuple(sorted(pool))
        item_indexes = {item: index for index, item in enumerate(item_ids)}
        degrees = [0] * len(item_ids)
        sparse_pair_counts: Counter[int] = Counter()
        for history in capped_histories.values():
            indexes = sorted(item_indexes[item] for item in history)
            for index in indexes:
                degrees[index] += 1
            for left, right in combinations(indexes, 2):
                sparse_pair_counts[left * len(item_ids) + right] += 1

        neighbors: dict[str, list[tuple[str, float]]] = defaultdict(list)
        supported_pair_count = 0
        for pair_key, shared_users in sparse_pair_counts.items():
            if shared_users < config.min_shared_users:
                continue
            left, right = divmod(pair_key, len(item_ids))
            similarity = shared_users / sqrt(degrees[left] * degrees[right])
            left_item = item_ids[left]
            right_item = item_ids[right]
            neighbors[left_item].append((right_item, similarity))
            neighbors[right_item].append((left_item, similarity))
            supported_pair_count += 1

        limited_neighbors = {
            item: tuple(
                sorted(values, key=lambda entry: (-entry[1], entry[0]))[
                    : config.max_neighbors_per_item
                ]
            )
            for item, values in neighbors.items()
        }
        summary = ItemCFFitSummary(
            positive_observation_count=positive_observation_count,
            unique_positive_user_item_pairs=sum(
                len(items) for items in positive_by_user.values()
            ),
            repeated_positive_observations_collapsed=(
                positive_observation_count
                - sum(len(items) for items in positive_by_user.values())
            ),
            users_with_positive_history=sum(
                bool(items) for items in positive_by_user.values()
            ),
            truncated_user_count=truncated_user_count,
            truncated_positive_item_count=truncated_positive_item_count,
            cooccurrence_pair_count=len(sparse_pair_counts),
            supported_similarity_pair_count=supported_pair_count,
            retained_neighbor_edges=sum(map(len, limited_neighbors.values())),
        )
        return cls(
            candidate_items=pool,
            positive_history_by_user={
                user: frozenset(items) for user, items in capped_histories.items()
            },
            seen_items_by_user={
                user: frozenset(items) for user, items in seen_by_user.items()
            },
            positive_user_counts=dict(positive_user_counts),
            neighbors_by_item=limited_neighbors,
            fit_summary=summary,
            config=config,
        )

    def recommend(self, user_key: str, *, k: int) -> ItemCFRecommendation:
        if isinstance(k, bool) or not isinstance(k, int) or k < 0:
            raise ValueError("Recommendation limit must be a non-negative integer.")
        history = self.positive_history_by_user.get(user_key, frozenset())
        seen = self.seen_items_by_user.get(user_key, frozenset())
        scores: dict[str, float] = defaultdict(float)
        for history_item in sorted(history):
            for neighbor, similarity in self.neighbors_by_item.get(history_item, ()):
                if neighbor in self.candidate_items and neighbor not in seen:
                    scores[neighbor] += similarity
        ranked = tuple(
            item
            for item, _ in sorted(
                scores.items(), key=lambda entry: (-entry[1], entry[0])
            )
        )
        return ItemCFRecommendation(
            items=ranked[:k],
            candidate_count=len(scores),
            positive_history_count=len(history),
        )
