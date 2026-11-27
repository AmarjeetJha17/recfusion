"""Application-neutral contracts for offline recommendation inference."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Protocol

from recfusion_core.contracts.data import DataSplit, Interaction, Money

_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class SyntheticProduct:
    item_key: str
    title: str | None
    category: str | None
    description: tuple[str, ...]
    features: tuple[str, ...]
    price: Money | None
    source_record_fingerprint: str
    catalog_eligible: bool = True
    visible: bool = True

    def __post_init__(self) -> None:
        if not self.item_key.strip():
            raise ValueError("Synthetic product identity must be non-empty.")
        if not _FINGERPRINT.fullmatch(self.source_record_fingerprint):
            raise ValueError("Synthetic product fingerprint must be SHA-256.")
        if not all(
            isinstance(value, str) for value in (*self.description, *self.features)
        ):
            raise ValueError("Synthetic product content fields must be strings.")

    @property
    def content_fields(self) -> tuple[tuple[str, str], ...]:
        values: list[tuple[str, str]] = []
        if self.title:
            values.append(("title", self.title))
        if self.category:
            values.append(("category", self.category))
        if self.description:
            values.append(("description", " ".join(self.description)))
        if self.features:
            values.append(("features", " ".join(self.features)))
        return tuple(values)


@dataclass(frozen=True, slots=True)
class SyntheticUserContext:
    user_key: str
    prediction_time_ms: int
    training_history: tuple[Interaction, ...]

    def __post_init__(self) -> None:
        if not self.user_key.strip():
            raise ValueError("Synthetic user identity must be non-empty.")
        if (
            isinstance(self.prediction_time_ms, bool)
            or not isinstance(self.prediction_time_ms, int)
            or self.prediction_time_ms < 0
        ):
            raise ValueError("Prediction timestamp must be non-negative milliseconds.")
        if any(
            event.user_key != self.user_key or event.split is not DataSplit.TRAIN
            for event in self.training_history
        ):
            raise ValueError(
                "Synthetic user context must contain its train history only."
            )


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    item_key: str
    score: float | None
    source_names: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.item_key.strip():
            raise ValueError("Candidate identity must be non-empty.")
        if self.score is not None and (
            isinstance(self.score, bool) or not isfinite(self.score)
        ):
            raise ValueError("Candidate score must be finite when present.")
        if len(self.source_names) > 4 or len(self.reason_codes) > 4:
            raise ValueError("Candidate provenance exceeds configured bounds.")


@dataclass(frozen=True, slots=True)
class HybridInferenceConfig:
    rank_constant: int
    source_weights: Mapping[str, float]
    source_depths: Mapping[str, int]

    def __post_init__(self) -> None:
        if (
            isinstance(self.rank_constant, bool)
            or not isinstance(self.rank_constant, int)
            or self.rank_constant < 1
        ):
            raise ValueError("RRF rank constant must be a positive integer.")
        if not self.source_weights or set(self.source_weights) != set(
            self.source_depths
        ):
            raise ValueError("Hybrid source weights and depths must match.")
        if len(self.source_weights) > 4:
            raise ValueError("Hybrid source count exceeds the configured limit.")
        if any(
            isinstance(weight, bool) or not isfinite(weight) or weight < 0
            for weight in self.source_weights.values()
        ):
            raise ValueError("Hybrid source weights must be finite and non-negative.")
        if any(
            isinstance(depth, bool)
            or not isinstance(depth, int)
            or not 1 <= depth <= 100
            for depth in self.source_depths.values()
        ):
            raise ValueError("Hybrid source depth must be between 1 and 100.")
        object.__setattr__(
            self, "source_weights", MappingProxyType(dict(self.source_weights))
        )
        object.__setattr__(
            self, "source_depths", MappingProxyType(dict(self.source_depths))
        )


class SyntheticCatalog(Protocol):
    catalog_id: str
    version: str
    catalog_fingerprint: str
    bundle_fingerprint: str
    generator_schema: str
    seed: int
    max_catalog_size: int
    max_history_events: int

    def list_products(self) -> tuple[SyntheticProduct, ...]: ...

    def get_product(self, item_key: str) -> SyntheticProduct | None: ...

    def get_user_context(self, user_key: str) -> SyntheticUserContext: ...

    def get_training_interactions(self) -> tuple[Interaction, ...]: ...

    @property
    def train_known_item_keys(self) -> frozenset[str]: ...

    def get_collaborative_rankings(
        self, user_key: str
    ) -> Mapping[str, tuple[str, ...]]: ...


class RecommendationInferenceSource(Protocol):
    artifact_id: str
    catalog_id: str
    catalog_fingerprint: str
    artifact_fingerprint: str
    supported_algorithms: Mapping[str, str]
    supported_candidate_policies: frozenset[str]

    def recommend_product_to_product(
        self,
        query_product: SyntheticProduct,
        *,
        eligible_item_keys: frozenset[str],
        excluded_item_keys: frozenset[str],
        k: int,
    ) -> tuple[RankedCandidate, ...]: ...

    def recommend_synthetic_user(
        self,
        context: SyntheticUserContext,
        *,
        target_item_key: str | None,
        excluded_item_keys: frozenset[str],
        k: int,
    ) -> tuple[RankedCandidate, ...]: ...

    def recommend_hybrid(
        self,
        context: SyntheticUserContext,
        *,
        target_item_key: str | None,
        all_training_interactions: Sequence[Interaction],
        collaborative_rankings: Mapping[str, Sequence[str]],
        train_known_item_keys: frozenset[str],
        candidate_policy: str,
        config: HybridInferenceConfig,
        k: int,
    ) -> tuple[RankedCandidate, ...]: ...


class RecommendationArtifactRegistry(Protocol):
    def get(self, artifact_id: str) -> RecommendationInferenceSource | None: ...
