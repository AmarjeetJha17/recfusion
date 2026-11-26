"""Deterministic train-only Two-Tower retrieval training."""

from __future__ import annotations

import hashlib
import json
import math
import random
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import groupby

import torch
from torch import Tensor
from torch.nn import functional as F

from recfusion_ml.models.two_tower import TwoTowerNetwork
from recfusion_ml.training.bpr import NegativeSampler, TrainingData
from recfusion_ml.types import RatingEvent

_POSITIVE_MIN_RATING = Decimal("4")


@dataclass(frozen=True, slots=True)
class TwoTowerConfig:
    """Model, objective, sampling, and deterministic training configuration."""

    embedding_dim: int = 32
    hidden_dims: tuple[int, ...] = (64,)
    retrieval_dim: int = 32
    max_history_items: int = 50
    negative_count: int = 4
    negative_sampling_retries: int = 16
    temperature: float = 0.1
    epochs: int = 10
    batch_size: int = 128
    learning_rate: float = 0.001
    regularization: float = 0.0001
    seed: int = 42

    def __post_init__(self) -> None:
        for name in (
            "embedding_dim",
            "retrieval_dim",
            "max_history_items",
            "negative_count",
            "negative_sampling_retries",
            "epochs",
            "batch_size",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        if not self.hidden_dims or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in self.hidden_dims
        ):
            raise ValueError("hidden_dims must contain positive integers.")
        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or self.seed < 0
        ):
            raise ValueError("seed must be a non-negative integer.")
        for name in ("temperature", "learning_rate", "regularization"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number.")
            if (
                not math.isfinite(value)
                or value < 0
                or (name in {"temperature", "learning_rate"} and value == 0)
            ):
                requirement = (
                    "positive"
                    if name in {"temperature", "learning_rate"}
                    else "non-negative"
                )
                raise ValueError(f"{name} must be finite and {requirement}.")


@dataclass(frozen=True, slots=True)
class TwoTowerEvent:
    """Canonical training interaction with its UTC Unix-millisecond timestamp."""

    user_key: str
    item_key: str
    rating: Decimal
    event_time_ms: int
    split: str = "train"
    training_eligible: bool = True

    def __post_init__(self) -> None:
        if not self.user_key.strip() or not self.item_key.strip():
            raise ValueError("Interaction identifiers must be non-empty.")
        if self.split not in {"train", "validation", "test"}:
            raise ValueError("Interaction split is invalid.")
        if not isinstance(self.training_eligible, bool):
            raise ValueError("training_eligible must be a boolean.")
        if (
            isinstance(self.event_time_ms, bool)
            or not isinstance(self.event_time_ms, int)
            or self.event_time_ms < 0
        ):
            raise ValueError("event_time_ms must be a non-negative integer.")
        if not self.rating.is_finite() or not Decimal("1") <= self.rating <= Decimal(
            "5"
        ):
            raise ValueError("rating must be finite and between 1 and 5.")


@dataclass(frozen=True, slots=True)
class TwoTowerExample:
    """Unique positive target and its bounded, target-masked prior history."""

    user_key: str
    item_key: str
    event_time_ms: int
    history_item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TwoTowerTrainingData:
    """Train-only vocabularies and histories for a two-tower model."""

    user_ids: tuple[str, ...]
    item_ids: tuple[str, ...]
    examples: tuple[TwoTowerExample, ...]
    seen_items_by_user: Mapping[str, frozenset[str]]
    inference_history_by_user: Mapping[str, tuple[str, ...]]
    training_fingerprint: str
    source_artifact_fingerprints: tuple[str, ...]
    train_event_count: int
    excluded_ineligible_event_count: int
    positive_observation_count: int
    unique_positive_pairs: int
    collapsed_positive_observations: int

    @property
    def candidate_items(self) -> frozenset[str]:
        return frozenset(self.item_ids)


@dataclass(frozen=True, slots=True)
class TwoTowerSummary:
    train_event_count: int
    excluded_ineligible_event_count: int
    positive_observation_count: int
    unique_positive_pairs: int
    collapsed_positive_observations: int
    training_examples: int
    skipped_examples_without_negative: int
    sampled_negative_count_per_epoch: int


@dataclass(frozen=True, slots=True)
class TwoTowerEpoch:
    epoch: int
    retrieval_loss: float
    regularization_loss: float
    total_loss: float
    training_example_count: int
    sampled_negative_count: int
    duration_seconds: float


def build_two_tower_data(
    events: Iterable[TwoTowerEvent],
    *,
    max_history_items: int,
    source_artifact_fingerprints: Iterable[str] = (),
) -> TwoTowerTrainingData:
    """Build unique positive targets from train-only strictly-prior histories."""
    if (
        isinstance(max_history_items, bool)
        or not isinstance(max_history_items, int)
        or max_history_items < 1
    ):
        raise ValueError("max_history_items must be a positive integer.")
    all_records = tuple(events)
    if not all_records:
        raise ValueError("Training data must contain at least one train event.")
    if any(event.split != "train" for event in all_records):
        raise ValueError("Two-Tower training accepts train-split events only.")
    records = tuple(event for event in all_records if event.training_eligible)
    if not records:
        raise ValueError("Training data must contain an eligible train event.")
    fingerprints = tuple(sorted(set(source_artifact_fingerprints)))
    if any(
        len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in fingerprints
    ):
        raise ValueError("Source artifact fingerprints must be lowercase SHA-256 hex.")

    user_ids = tuple(sorted({event.user_key for event in records}))
    item_ids = tuple(sorted({event.item_key for event in records}))
    events_by_user: dict[str, list[TwoTowerEvent]] = defaultdict(list)
    seen_items: dict[str, set[str]] = defaultdict(set)
    first_positive_time: dict[tuple[str, str], int] = {}
    positive_observations = 0
    canonical_rows: list[tuple[str, str, str, int]] = []
    for event in records:
        events_by_user[event.user_key].append(event)
        seen_items[event.user_key].add(event.item_key)
        rating = format(event.rating.normalize(), "f")
        canonical_rows.append(
            (event.user_key, event.item_key, rating, event.event_time_ms)
        )
        if event.rating >= _POSITIVE_MIN_RATING:
            positive_observations += 1
            pair = (event.user_key, event.item_key)
            first_positive_time[pair] = min(
                event.event_time_ms, first_positive_time.get(pair, event.event_time_ms)
            )
    if not first_positive_time:
        raise ValueError("Training data must contain a rating >= 4 positive target.")

    targets_by_user_time: dict[str, dict[int, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for (user_key, item_key), timestamp in first_positive_time.items():
        targets_by_user_time[user_key][timestamp].append(item_key)

    examples: list[TwoTowerExample] = []
    inference_history: dict[str, tuple[str, ...]] = {}
    for user_key in user_ids:
        user_events = sorted(
            events_by_user[user_key],
            key=lambda row: (row.event_time_ms, row.item_key, row.rating),
        )
        last_seen_by_item: dict[str, int] = {}
        for timestamp, group in groupby(user_events, key=lambda row: row.event_time_ms):
            for target_item in sorted(
                targets_by_user_time[user_key].get(timestamp, ())
            ):
                prior_items = sorted(
                    (
                        (item, prior_timestamp)
                        for item, prior_timestamp in last_seen_by_item.items()
                        if item != target_item
                    ),
                    key=lambda pair: (-pair[1], pair[0]),
                )[:max_history_items]
                examples.append(
                    TwoTowerExample(
                        user_key=user_key,
                        item_key=target_item,
                        event_time_ms=timestamp,
                        history_item_ids=tuple(item for item, _ in prior_items),
                    )
                )
            for event in group:
                last_seen_by_item[event.item_key] = timestamp
        inference_history[user_key] = tuple(
            item
            for item, _ in sorted(
                last_seen_by_item.items(), key=lambda pair: (-pair[1], pair[0])
            )[:max_history_items]
        )
    examples.sort(key=lambda row: (row.user_key, row.event_time_ms, row.item_key))
    digest = hashlib.sha256(
        json.dumps(
            sorted(canonical_rows), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return TwoTowerTrainingData(
        user_ids=user_ids,
        item_ids=item_ids,
        examples=tuple(examples),
        seen_items_by_user={
            user: frozenset(items) for user, items in sorted(seen_items.items())
        },
        inference_history_by_user=inference_history,
        training_fingerprint=digest,
        source_artifact_fingerprints=fingerprints,
        train_event_count=len(records),
        excluded_ineligible_event_count=len(all_records) - len(records),
        positive_observation_count=positive_observations,
        unique_positive_pairs=len(first_positive_time),
        collapsed_positive_observations=positive_observations
        - len(first_positive_time),
    )


def sampled_softmax_loss(
    positive_scores: Tensor,
    negative_scores: Tensor,
    negative_mask: Tensor,
    *,
    temperature: float,
) -> Tensor:
    """Cross-entropy over one positive and each row's sampled negatives."""
    if (
        positive_scores.ndim != 1
        or negative_scores.ndim != 2
        or negative_mask.dtype != torch.bool
        or negative_mask.shape != negative_scores.shape
        or negative_scores.shape[0] != positive_scores.shape[0]
        or positive_scores.numel() == 0
        or negative_scores.shape[1] == 0
    ):
        raise ValueError("Sampled-softmax score and mask shapes are invalid.")
    if (
        isinstance(temperature, bool)
        or not math.isfinite(temperature)
        or temperature <= 0
    ):
        raise ValueError("temperature must be a finite positive number.")
    if not negative_mask.any(dim=1).all():
        raise ValueError("Each sampled-softmax row needs at least one negative.")
    if (
        not torch.isfinite(positive_scores).all()
        or not torch.isfinite(negative_scores[negative_mask]).all()
    ):
        raise ValueError("Sampled-softmax scores must be finite.")
    logits = torch.cat((positive_scores.unsqueeze(1), negative_scores), dim=1)
    logits = logits.masked_fill(
        torch.cat(
            (
                torch.ones_like(positive_scores, dtype=torch.bool).unsqueeze(1),
                negative_mask,
            ),
            dim=1,
        ).logical_not(),
        -torch.inf,
    )
    loss = F.cross_entropy(
        logits / temperature, torch.zeros_like(positive_scores, dtype=torch.long)
    )
    if not torch.isfinite(loss):
        raise ValueError("Sampled-softmax loss is non-finite.")
    return loss


@dataclass(slots=True)
class TwoTowerRecommender:
    model: TwoTowerNetwork
    config: TwoTowerConfig
    data: TwoTowerTrainingData
    summary: TwoTowerSummary
    epoch_statistics: tuple[TwoTowerEpoch, ...]
    _user_indices: dict[str, int] = field(init=False, repr=False)
    _item_indices: dict[str, int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._user_indices = {
            key: index + 1 for index, key in enumerate(self.data.user_ids)
        }
        self._item_indices = {
            key: index + 1 for index, key in enumerate(self.data.item_ids)
        }

    def _user_history_tensor(self, user_id: str) -> Tensor:
        history = self.data.inference_history_by_user[user_id]
        indices = [self._item_indices[item] for item in history]
        indices.extend([0] * (self.config.max_history_items - len(indices)))
        return torch.tensor([indices], dtype=torch.long)

    def item_vectors(self, item_ids: Sequence[str]) -> Tensor:
        """Encode known items independently of any user request or history."""
        unknown = set(item_ids) - set(self._item_indices)
        if unknown:
            raise ValueError("Item IDs must be train-known.")
        indices = torch.tensor(
            [self._item_indices[item] for item in item_ids], dtype=torch.long
        )
        self.model.eval()
        with torch.no_grad():
            return self.model.encode_items(indices)

    def score(self, user_id: str, item_id: str) -> float:
        if user_id not in self._user_indices:
            raise ValueError("Unknown user ID.")
        if item_id not in self._item_indices:
            raise ValueError("Item ID is not train-known.")
        self.model.eval()
        with torch.no_grad():
            score = self.model.score(
                torch.tensor([self._user_indices[user_id]], dtype=torch.long),
                self._user_history_tensor(user_id),
                torch.tensor([self._item_indices[item_id]], dtype=torch.long),
            )
        value = float(score.item())
        if not math.isfinite(value):
            raise ValueError("Model produced a non-finite score.")
        return value

    def recommend(
        self, user_id: str, *, k: int, chunk_size: int = 4096
    ) -> tuple[str, ...]:
        for name, value in (("k", k), ("chunk_size", chunk_size)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        if user_id not in self._user_indices:
            return ()
        seen = self.data.seen_items_by_user[user_id]
        candidates = tuple(item for item in self.data.item_ids if item not in seen)
        if not candidates:
            return ()
        self.model.eval()
        user_index = torch.tensor([self._user_indices[user_id]], dtype=torch.long)
        history = self._user_history_tensor(user_id)
        with torch.no_grad():
            user_vector = self.model.encode_users(user_index, history)[0]
            scored: list[tuple[str, float]] = []
            for start in range(0, len(candidates), chunk_size):
                chunk = candidates[start : start + chunk_size]
                indices = torch.tensor(
                    [self._item_indices[item] for item in chunk], dtype=torch.long
                )
                item_vectors = self.model.encode_items(indices)
                scores = item_vectors @ user_vector
                if not torch.isfinite(scores).all():
                    raise ValueError("Model produced a non-finite score.")
                order = torch.argsort(scores, descending=True, stable=True)[:k].tolist()
                scored.extend((chunk[index], float(scores[index])) for index in order)
        return tuple(
            item for item, _ in sorted(scored, key=lambda pair: (-pair[1], pair[0]))[:k]
        )

    def recommend_many(
        self,
        user_ids: Iterable[str],
        *,
        k: int,
        chunk_size: int = 4096,
    ) -> dict[str, tuple[str, ...]]:
        users = tuple(user_ids)
        if len(set(users)) != len(users):
            raise ValueError("Requested user IDs must be unique.")
        return {
            user_id: self.recommend(user_id, k=k, chunk_size=chunk_size)
            for user_id in sorted(users)
        }


def fit_two_tower(
    events: Iterable[TwoTowerEvent],
    *,
    config: TwoTowerConfig = TwoTowerConfig(),
    source_artifact_fingerprints: Iterable[str] = (),
) -> TwoTowerRecommender:
    """Train a history-aware retrieval model using train events only."""
    records = tuple(events)
    data = build_two_tower_data(
        records,
        max_history_items=config.max_history_items,
        source_artifact_fingerprints=source_artifact_fingerprints,
    )
    rating_events = tuple(
        RatingEvent(event.user_key, event.item_key, event.rating, "train")
        for event in records
        if event.training_eligible
    )
    sampler_data = TrainingData.from_events(
        rating_events,
        source_artifact_fingerprints=data.source_artifact_fingerprints,
    )
    negative_sampler = NegativeSampler(
        sampler_data, max_retries=config.negative_sampling_retries
    )
    user_indices = {key: index + 1 for index, key in enumerate(data.user_ids)}
    item_indices = {key: index + 1 for index, key in enumerate(data.item_ids)}
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(config.seed)
        model = TwoTowerNetwork(
            user_count=len(data.user_ids),
            item_count=len(data.item_ids),
            embedding_dim=config.embedding_dim,
            hidden_dims=config.hidden_dims,
            retrieval_dim=config.retrieval_dim,
        ).cpu()
    if any(not torch.isfinite(parameter).all() for parameter in model.parameters()):
        raise ValueError("Two-Tower initialization produced non-finite parameters.")
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    epoch_statistics: list[TwoTowerEpoch] = []
    skipped_without_negative = 0

    for epoch in range(config.epochs):
        epoch_started = time.perf_counter()
        rng = random.Random(config.seed + epoch)
        order = list(range(len(data.examples)))
        rng.shuffle(order)
        retrieval_loss_sum = 0.0
        regularization_loss_sum = 0.0
        example_count = 0
        negative_count = 0
        skipped_this_epoch = 0
        model.train()
        for start in range(0, len(order), config.batch_size):
            batch_examples = [
                data.examples[index]
                for index in order[start : start + config.batch_size]
            ]
            batch_negatives: list[tuple[str, ...]] = []
            retained_examples: list[TwoTowerExample] = []
            for example in batch_examples:
                negatives = negative_sampler.sample_many(
                    example.user_key, rng, config.negative_count
                )
                if negatives:
                    retained_examples.append(example)
                    batch_negatives.append(negatives)
                else:
                    skipped_this_epoch += 1
            if not retained_examples:
                continue

            user_tensor = torch.tensor(
                [user_indices[row.user_key] for row in retained_examples],
                dtype=torch.long,
            )
            history_tensor = torch.tensor(
                [
                    [item_indices[item] for item in row.history_item_ids]
                    + [0] * (config.max_history_items - len(row.history_item_ids))
                    for row in retained_examples
                ],
                dtype=torch.long,
            )
            positive_tensor = torch.tensor(
                [item_indices[row.item_key] for row in retained_examples],
                dtype=torch.long,
            )
            padded_negative_count = max(map(len, batch_negatives))
            negative_rows = [
                [item_indices[item] for item in negatives]
                + [0] * (padded_negative_count - len(negatives))
                for negatives in batch_negatives
            ]
            negative_tensor = torch.tensor(negative_rows, dtype=torch.long)
            negative_mask = torch.tensor(
                [
                    [True] * len(negatives)
                    + [False] * (padded_negative_count - len(negatives))
                    for negatives in batch_negatives
                ],
                dtype=torch.bool,
            )
            user_vectors = model.encode_users(user_tensor, history_tensor)
            positive_vectors = model.encode_items(positive_tensor)
            negative_vectors = model.encode_items(negative_tensor.flatten()).reshape(
                len(retained_examples), padded_negative_count, config.retrieval_dim
            )
            positive_scores = (user_vectors * positive_vectors).sum(dim=1)
            negative_scores = (user_vectors.unsqueeze(1) * negative_vectors).sum(dim=2)
            retrieval_loss = sampled_softmax_loss(
                positive_scores,
                negative_scores,
                negative_mask,
                temperature=config.temperature,
            )
            negative_weights = negative_mask.to(dtype=negative_vectors.dtype)
            negative_regularization = (
                negative_vectors.square().sum(dim=2) * negative_weights
            ).sum() / negative_weights.sum()
            regularization_loss = config.regularization * (
                user_vectors.square().sum(dim=1).mean()
                + positive_vectors.square().sum(dim=1).mean()
                + negative_regularization
            )
            loss = retrieval_loss + regularization_loss
            if not torch.isfinite(loss):
                raise ValueError("Two-Tower training loss is non-finite.")
            optimizer.zero_grad(set_to_none=True)
            gradients = torch.autograd.grad(loss, tuple(model.parameters()))
            for parameter, gradient in zip(model.parameters(), gradients, strict=True):
                parameter.grad = gradient
            if any(
                parameter.grad is not None and not torch.isfinite(parameter.grad).all()
                for parameter in model.parameters()
            ):
                raise ValueError("Two-Tower training produced non-finite gradients.")
            optimizer.step()
            if any(
                not torch.isfinite(parameter).all() for parameter in model.parameters()
            ):
                raise ValueError("Two-Tower training produced non-finite parameters.")
            batch_size = len(retained_examples)
            retrieval_loss_sum += float(retrieval_loss.detach()) * batch_size
            regularization_loss_sum += float(regularization_loss.detach()) * batch_size
            example_count += batch_size
            negative_count += int(negative_mask.sum())
        if epoch == 0:
            skipped_without_negative = skipped_this_epoch
        if example_count == 0:
            raise ValueError(
                "No positive target has a permissible train-known negative."
            )
        retrieval_epoch_loss = retrieval_loss_sum / example_count
        regularization_epoch_loss = regularization_loss_sum / example_count
        epoch_statistics.append(
            TwoTowerEpoch(
                epoch=epoch + 1,
                retrieval_loss=retrieval_epoch_loss,
                regularization_loss=regularization_epoch_loss,
                total_loss=retrieval_epoch_loss + regularization_epoch_loss,
                training_example_count=example_count,
                sampled_negative_count=negative_count,
                duration_seconds=time.perf_counter() - epoch_started,
            )
        )

    model.eval()
    summary = TwoTowerSummary(
        train_event_count=data.train_event_count,
        excluded_ineligible_event_count=data.excluded_ineligible_event_count,
        positive_observation_count=data.positive_observation_count,
        unique_positive_pairs=data.unique_positive_pairs,
        collapsed_positive_observations=data.collapsed_positive_observations,
        training_examples=len(data.examples) - skipped_without_negative,
        skipped_examples_without_negative=skipped_without_negative,
        sampled_negative_count_per_epoch=epoch_statistics[-1].sampled_negative_count,
    )
    return TwoTowerRecommender(
        model=model,
        config=config,
        data=data,
        summary=summary,
        epoch_statistics=tuple(epoch_statistics),
    )
