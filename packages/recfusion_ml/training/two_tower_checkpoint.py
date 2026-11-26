"""Private, weights-only checkpoint persistence for Two-Tower models."""

from __future__ import annotations

import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import torch

from recfusion_ml.models.two_tower import TwoTowerNetwork
from recfusion_ml.training.two_tower import (
    TwoTowerConfig,
    TwoTowerEpoch,
    TwoTowerRecommender,
    TwoTowerSummary,
    TwoTowerTrainingData,
)

_CHECKPOINT_FORMAT_VERSION = 1


def _checkpoint_location(path: Path, repository_root: Path) -> Path:
    allowed = (repository_root.resolve() / "data" / "processed").resolve()
    destination = path.resolve()
    try:
        destination.relative_to(allowed)
    except ValueError as error:
        raise ValueError("Checkpoints must be stored under data/processed.") from error
    return destination


def save_two_tower_checkpoint(
    recommender: TwoTowerRecommender,
    path: Path,
    *,
    repository_root: Path | None = None,
) -> Path:
    """Save train-only mappings and weights atomically under ignored storage."""
    root = repository_root or Path(__file__).resolve().parents[3]
    destination = _checkpoint_location(path, root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    payload: dict[str, Any] = {
        "format_version": _CHECKPOINT_FORMAT_VERSION,
        "config": asdict(recommender.config),
        "user_ids": list(recommender.data.user_ids),
        "item_ids": list(recommender.data.item_ids),
        "seen_items_by_user": {
            user: sorted(items)
            for user, items in sorted(recommender.data.seen_items_by_user.items())
        },
        "inference_history_by_user": {
            user: list(items)
            for user, items in sorted(
                recommender.data.inference_history_by_user.items()
            )
        },
        "training_fingerprint": recommender.data.training_fingerprint,
        "source_artifact_fingerprints": list(
            recommender.data.source_artifact_fingerprints
        ),
        "train_event_count": recommender.data.train_event_count,
        "excluded_ineligible_event_count": (
            recommender.data.excluded_ineligible_event_count
        ),
        "positive_observation_count": recommender.data.positive_observation_count,
        "unique_positive_pairs": recommender.data.unique_positive_pairs,
        "collapsed_positive_observations": (
            recommender.data.collapsed_positive_observations
        ),
        "summary": asdict(recommender.summary),
        "epoch_statistics": [asdict(row) for row in recommender.epoch_statistics],
        "torch_version": str(torch.__version__),
        "state_dict": {
            key: value.detach().cpu()
            for key, value in recommender.model.state_dict().items()
        },
    }
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        torch.save(payload, temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def load_two_tower_checkpoint(
    path: Path, *, repository_root: Path | None = None
) -> TwoTowerRecommender:
    """Load a local weights-only checkpoint under data/processed."""
    root = repository_root or Path(__file__).resolve().parents[3]
    source = _checkpoint_location(path, root)
    payload = torch.load(source, map_location="cpu", weights_only=True)
    if (
        not isinstance(payload, dict)
        or payload.get("format_version") != _CHECKPOINT_FORMAT_VERSION
    ):
        raise ValueError("Unsupported Two-Tower checkpoint format.")
    user_ids = tuple(payload["user_ids"])
    item_ids = tuple(payload["item_ids"])
    if (
        not user_ids
        or not item_ids
        or user_ids != tuple(sorted(set(user_ids)))
        or item_ids != tuple(sorted(set(item_ids)))
    ):
        raise ValueError("Two-Tower checkpoint vocabularies are malformed.")
    seen = {
        user: frozenset(items) for user, items in payload["seen_items_by_user"].items()
    }
    histories = {
        user: tuple(items)
        for user, items in payload["inference_history_by_user"].items()
    }
    if set(seen) != set(user_ids) or set(histories) != set(user_ids):
        raise ValueError("Two-Tower checkpoint user state is malformed.")
    config_data = dict(payload["config"])
    config_data["hidden_dims"] = tuple(config_data["hidden_dims"])
    config = TwoTowerConfig(**config_data)
    data = TwoTowerTrainingData(
        user_ids=user_ids,
        item_ids=item_ids,
        examples=(),
        seen_items_by_user=seen,
        inference_history_by_user=histories,
        training_fingerprint=payload["training_fingerprint"],
        source_artifact_fingerprints=tuple(payload["source_artifact_fingerprints"]),
        train_event_count=payload["train_event_count"],
        excluded_ineligible_event_count=payload["excluded_ineligible_event_count"],
        positive_observation_count=payload["positive_observation_count"],
        unique_positive_pairs=payload["unique_positive_pairs"],
        collapsed_positive_observations=payload["collapsed_positive_observations"],
    )
    model = TwoTowerNetwork(
        user_count=len(user_ids),
        item_count=len(item_ids),
        embedding_dim=config.embedding_dim,
        hidden_dims=config.hidden_dims,
        retrieval_dim=config.retrieval_dim,
    ).cpu()
    model.load_state_dict(payload["state_dict"], strict=True)
    model.eval()
    return TwoTowerRecommender(
        model=model,
        config=config,
        data=data,
        summary=TwoTowerSummary(**payload["summary"]),
        epoch_statistics=tuple(
            TwoTowerEpoch(**record) for record in payload["epoch_statistics"]
        ),
    )
