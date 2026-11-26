"""Deterministic train-only BPR training and private checkpoint helpers."""

from __future__ import annotations

import hashlib
import json
import math
import random
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import torch

from recfusion_ml.models.implicit_mf import ImplicitMF, pairwise_bpr_loss
from recfusion_ml.types import RatingEvent

_POSITIVE_MIN_RATING = Decimal("4")
_FORMAT_VERSION = 1
_NEGATIVE_SAMPLING_STRATEGY = "uniform rejection; seeded scan fallback"


@dataclass(frozen=True, slots=True)
class BPRConfig:
    """Reproducible CPU training parameters."""

    embedding_dim: int = 32
    epochs: int = 20
    batch_size: int = 1024
    learning_rate: float = 0.001
    regularization: float = 0.0001
    seed: int = 42
    negative_sampling_retries: int = 16

    def __post_init__(self) -> None:
        for name in (
            "embedding_dim",
            "epochs",
            "batch_size",
            "seed",
            "negative_sampling_retries",
        ):
            value = getattr(self, name)
            minimum = 0 if name == "seed" else 1
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}.")
        for name in ("learning_rate", "regularization"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number.")
            if (
                not math.isfinite(value)
                or value < 0
                or (name == "learning_rate" and value == 0)
            ):
                raise ValueError(
                    f"{name} must be finite and "
                    f"{'positive' if name == 'learning_rate' else 'non-negative'}."
                )


@dataclass(frozen=True, slots=True)
class TrainingData:
    """Train-only vocabularies, all-observed exclusions, and distinct positives."""

    user_ids: tuple[str, ...]
    item_ids: tuple[str, ...]
    positive_pairs: tuple[tuple[str, str], ...]
    seen_items_by_user: dict[str, frozenset[str]]
    collapsed_positive_observations: int
    training_fingerprint: str
    source_artifact_fingerprints: tuple[str, ...]

    @classmethod
    def from_events(
        cls,
        events: Iterable[RatingEvent],
        *,
        source_artifact_fingerprints: Iterable[str] = (),
    ) -> TrainingData:
        records = tuple(events)
        if not records:
            raise ValueError("Training data must contain at least one train event.")
        if any(record.split != "train" for record in records):
            raise ValueError("BPR training accepts train-split events only.")
        fingerprints = tuple(sorted(set(source_artifact_fingerprints)))
        if any(
            len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
            for fingerprint in fingerprints
        ):
            raise ValueError(
                "Source artifact fingerprints must be lowercase SHA-256 hex."
            )
        user_ids = tuple(sorted({record.user_key for record in records}))
        item_ids = tuple(sorted({record.item_key for record in records}))
        seen: dict[str, set[str]] = {}
        positives: set[tuple[str, str]] = set()
        positive_observations = 0
        canonical: list[tuple[str, str, str]] = []
        for record in records:
            seen.setdefault(record.user_key, set()).add(record.item_key)
            rating = format(record.rating.normalize(), "f")
            canonical.append((record.user_key, record.item_key, rating))
            if record.rating >= _POSITIVE_MIN_RATING:
                positive_observations += 1
                positives.add((record.user_key, record.item_key))
        digest = hashlib.sha256(
            json.dumps(
                sorted(canonical), ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        ordered_pairs = tuple(sorted(positives))
        return cls(
            user_ids=user_ids,
            item_ids=item_ids,
            positive_pairs=ordered_pairs,
            seen_items_by_user={
                user: frozenset(items) for user, items in sorted(seen.items())
            },
            collapsed_positive_observations=positive_observations - len(positives),
            training_fingerprint=digest,
            source_artifact_fingerprints=fingerprints,
        )


class NegativeSampler:
    """Seeded sampler from train-known items absent from a user's train history."""

    def __init__(self, data: TrainingData, *, max_retries: int = 16) -> None:
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or max_retries < 1
        ):
            raise ValueError("max_retries must be a positive integer.")
        self._items = data.item_ids
        self._seen = data.seen_items_by_user
        self.max_retries = max_retries

    def sample(self, user_id: str, rng: random.Random) -> str | None:
        seen = self._seen[user_id]
        if len(seen) >= len(self._items):
            return None
        for _ in range(self.max_retries):
            candidate = self._items[rng.randrange(len(self._items))]
            if candidate not in seen:
                return candidate
        start = rng.randrange(len(self._items))
        for offset in range(len(self._items)):
            candidate = self._items[(start + offset) % len(self._items)]
            if candidate not in seen:
                return candidate
        return None


@dataclass(frozen=True, slots=True)
class TrainingSummary:
    positive_observation_count: int
    unique_positive_pairs: int
    collapsed_positive_observations: int
    skipped_pairs_without_negative: int
    sampled_triplet_count_per_epoch: int


@dataclass(frozen=True, slots=True)
class TrainingEpoch:
    epoch: int
    bpr_loss: float
    regularization_loss: float
    total_loss: float
    triplet_count: int
    duration_seconds: float


@dataclass(slots=True)
class BPRRecommender:
    model: ImplicitMF
    config: BPRConfig
    data: TrainingData
    epoch_losses: tuple[float, ...]
    summary: TrainingSummary
    epoch_statistics: tuple[TrainingEpoch, ...] = ()
    _user_indices: dict[str, int] = field(init=False, repr=False)
    _item_indices: dict[str, int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._user_indices = {
            key: index for index, key in enumerate(self.data.user_ids)
        }
        self._item_indices = {
            key: index for index, key in enumerate(self.data.item_ids)
        }

    def score(self, user_id: str, item_id: str) -> float:
        if user_id not in self._user_indices:
            raise ValueError("Unknown user ID.")
        if item_id not in self._item_indices:
            raise ValueError("Item ID is not train-known.")
        self.model.eval()
        with torch.no_grad():
            score = self.model.score(
                torch.tensor(self._user_indices[user_id], dtype=torch.long),
                torch.tensor(self._item_indices[item_id], dtype=torch.long),
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
        scored: list[tuple[str, float]] = []
        self.model.eval()
        with torch.no_grad():
            user_index = self._user_indices[user_id]
            for start in range(0, len(candidates), chunk_size):
                items = candidates[start : start + chunk_size]
                user_tensor = torch.full((len(items),), user_index, dtype=torch.long)
                item_tensor = torch.tensor(
                    [self._item_indices[item] for item in items], dtype=torch.long
                )
                scores = self.model.score(user_tensor, item_tensor)
                if not torch.isfinite(scores).all():
                    raise ValueError("Model produced a non-finite score.")
                order = torch.argsort(scores, descending=True, stable=True)[:k].tolist()
                scored.extend((items[index], float(scores[index])) for index in order)
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
        """Return evaluator-ready rankings for the requested train users."""
        users = tuple(user_ids)
        if len(set(users)) != len(users):
            raise ValueError("Requested user IDs must be unique.")
        return {
            user_id: self.recommend(user_id, k=k, chunk_size=chunk_size)
            for user_id in sorted(users)
        }


def fit_bpr(
    events: Iterable[RatingEvent],
    *,
    config: BPRConfig = BPRConfig(),
    source_artifact_fingerprints: Iterable[str] = (),
    on_epoch_end: Callable[[BPRRecommender, TrainingEpoch], None] | None = None,
) -> BPRRecommender:
    """Train BPR on unique train-positive pairs and sampled unknown train items."""
    data = TrainingData.from_events(
        events, source_artifact_fingerprints=source_artifact_fingerprints
    )
    sampler = NegativeSampler(data, max_retries=config.negative_sampling_retries)
    user_indices = {key: index for index, key in enumerate(data.user_ids)}
    item_indices = {key: index for index, key in enumerate(data.item_ids)}
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(config.seed)
        model = ImplicitMF(
            user_count=len(data.user_ids),
            item_count=len(data.item_ids),
            embedding_dim=config.embedding_dim,
        ).cpu()
    if any(not torch.isfinite(parameter).all() for parameter in model.parameters()):
        raise ValueError("BPR initialization produced non-finite parameters.")
    with torch.no_grad():
        initial_score = model.score(
            torch.tensor([0], dtype=torch.long), torch.tensor([0], dtype=torch.long)
        )
    if not torch.isfinite(initial_score).all():
        raise ValueError("BPR initialization produced a non-finite score.")
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    epoch_losses: list[float] = []
    epoch_statistics: list[TrainingEpoch] = []
    triplet_count = 0
    skipped_count = 0
    positive_observation_count = (
        len(data.positive_pairs) + data.collapsed_positive_observations
    )

    for epoch in range(config.epochs):
        epoch_started = time.perf_counter()
        rng = random.Random(config.seed + epoch)
        triplets: list[tuple[str, str, str]] = []
        for user, positive in data.positive_pairs:
            negative = sampler.sample(user, rng)
            if negative is None:
                skipped_count += int(epoch == 0)
            else:
                triplets.append((user, positive, negative))
        rng.shuffle(triplets)
        if not triplets:
            if epoch == 0:
                raise ValueError(
                    "No positive pair has a permissible train-known negative."
                )
            raise RuntimeError("A later epoch unexpectedly produced no BPR triplets.")
        triplet_count = len(triplets)
        total_loss = 0.0
        total_bpr_loss = 0.0
        total_regularization_loss = 0.0
        model.train()
        for start in range(0, len(triplets), config.batch_size):
            batch = triplets[start : start + config.batch_size]
            users = torch.tensor(
                [user_indices[row[0]] for row in batch], dtype=torch.long
            )
            positive_items = torch.tensor(
                [item_indices[row[1]] for row in batch], dtype=torch.long
            )
            negative_items = torch.tensor(
                [item_indices[row[2]] for row in batch], dtype=torch.long
            )
            positive_scores = model.score(users, positive_items)
            negative_scores = model.score(users, negative_items)
            pair_loss = pairwise_bpr_loss(positive_scores, negative_scores)
            regularization = config.regularization * (
                model.user_embeddings(users).square().sum(dim=1).mean()
                + model.item_embeddings(positive_items).square().sum(dim=1).mean()
                + model.item_embeddings(negative_items).square().sum(dim=1).mean()
            )
            loss = pair_loss + regularization
            if not torch.isfinite(loss):
                raise ValueError("BPR training loss is not finite.")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            if any(
                parameter.grad is not None and not torch.isfinite(parameter.grad).all()
                for parameter in model.parameters()
            ):
                raise ValueError("BPR training produced a non-finite gradient.")
            optimizer.step()
            if any(
                not torch.isfinite(parameter).all() for parameter in model.parameters()
            ):
                raise ValueError("BPR training produced non-finite model parameters.")
            total_loss += float(loss.detach()) * len(batch)
            total_bpr_loss += float(pair_loss.detach()) * len(batch)
            total_regularization_loss += float(regularization.detach()) * len(batch)
        epoch_record = TrainingEpoch(
            epoch=epoch + 1,
            bpr_loss=total_bpr_loss / len(triplets),
            regularization_loss=total_regularization_loss / len(triplets),
            total_loss=total_loss / len(triplets),
            triplet_count=len(triplets),
            duration_seconds=time.perf_counter() - epoch_started,
        )
        epoch_losses.append(epoch_record.total_loss)
        epoch_statistics.append(epoch_record)
        if on_epoch_end is not None:
            on_epoch_end(
                BPRRecommender(
                    model=model,
                    config=config,
                    data=data,
                    epoch_losses=tuple(epoch_losses),
                    summary=TrainingSummary(
                        positive_observation_count=positive_observation_count,
                        unique_positive_pairs=len(data.positive_pairs),
                        collapsed_positive_observations=(
                            data.collapsed_positive_observations
                        ),
                        skipped_pairs_without_negative=skipped_count,
                        sampled_triplet_count_per_epoch=triplet_count,
                    ),
                    epoch_statistics=tuple(epoch_statistics),
                ),
                epoch_record,
            )

    return BPRRecommender(
        model=model,
        config=config,
        data=data,
        epoch_losses=tuple(epoch_losses),
        epoch_statistics=tuple(epoch_statistics),
        summary=TrainingSummary(
            positive_observation_count=positive_observation_count,
            unique_positive_pairs=len(data.positive_pairs),
            collapsed_positive_observations=data.collapsed_positive_observations,
            skipped_pairs_without_negative=skipped_count,
            sampled_triplet_count_per_epoch=triplet_count,
        ),
    )


def _checkpoint_location(path: Path, repository_root: Path) -> Path:
    root = repository_root.resolve()
    allowed = (root / "data" / "processed").resolve()
    destination = path.resolve()
    try:
        destination.relative_to(allowed)
    except ValueError as exc:
        raise ValueError("Checkpoints must be saved under data/processed.") from exc
    return destination


def save_checkpoint(
    recommender: BPRRecommender,
    path: Path,
    *,
    repository_root: Path | None = None,
) -> Path:
    """Atomically save a safe, weights-only checkpoint under ignored local data."""
    root = repository_root or Path(__file__).resolve().parents[3]
    destination = _checkpoint_location(path, root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    payload: dict[str, Any] = {
        "format_version": _FORMAT_VERSION,
        "config": asdict(recommender.config),
        "user_ids": list(recommender.data.user_ids),
        "item_ids": list(recommender.data.item_ids),
        "positive_pairs": [list(pair) for pair in recommender.data.positive_pairs],
        "seen_items_by_user": {
            key: sorted(value)
            for key, value in recommender.data.seen_items_by_user.items()
        },
        "collapsed_positive_observations": (
            recommender.data.collapsed_positive_observations
        ),
        "training_fingerprint": recommender.data.training_fingerprint,
        "source_artifact_fingerprints": list(
            recommender.data.source_artifact_fingerprints
        ),
        "negative_sampling_strategy": _NEGATIVE_SAMPLING_STRATEGY,
        "summary": asdict(recommender.summary),
        "epoch_losses": list(recommender.epoch_losses),
        "epoch_statistics": [asdict(record) for record in recommender.epoch_statistics],
        "state_dict": {
            key: value.detach().cpu()
            for key, value in recommender.model.state_dict().items()
        },
        "torch_version": str(torch.__version__),
    }
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        torch.save(payload, temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def load_checkpoint(
    path: Path, *, repository_root: Path | None = None
) -> BPRRecommender:
    """Load the project's own weights-only checkpoint from ignored local storage."""
    root = repository_root or Path(__file__).resolve().parents[3]
    source = _checkpoint_location(path, root)
    payload = torch.load(source, map_location="cpu", weights_only=True)
    if (
        not isinstance(payload, dict)
        or payload.get("format_version") != _FORMAT_VERSION
    ):
        raise ValueError("Unsupported BPR checkpoint format.")
    config = BPRConfig(**payload["config"])
    user_ids = tuple(payload["user_ids"])
    item_ids = tuple(payload["item_ids"])
    seen = {
        key: frozenset(value) for key, value in payload["seen_items_by_user"].items()
    }
    data = TrainingData(
        user_ids=user_ids,
        item_ids=item_ids,
        positive_pairs=tuple(tuple(pair) for pair in payload["positive_pairs"]),
        seen_items_by_user=seen,
        collapsed_positive_observations=payload["collapsed_positive_observations"],
        training_fingerprint=payload["training_fingerprint"],
        source_artifact_fingerprints=tuple(payload["source_artifact_fingerprints"]),
    )
    if payload.get("negative_sampling_strategy") != _NEGATIVE_SAMPLING_STRATEGY:
        raise ValueError("Unsupported BPR negative-sampling strategy.")
    model = ImplicitMF(
        user_count=len(user_ids),
        item_count=len(item_ids),
        embedding_dim=config.embedding_dim,
    ).cpu()
    model.load_state_dict(payload["state_dict"], strict=True)
    model.eval()
    return BPRRecommender(
        model=model,
        config=config,
        data=data,
        epoch_losses=tuple(payload["epoch_losses"]),
        summary=TrainingSummary(**payload["summary"]),
        epoch_statistics=tuple(
            TrainingEpoch(**record) for record in payload["epoch_statistics"]
        ),
    )
