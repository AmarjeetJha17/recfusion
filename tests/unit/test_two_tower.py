from __future__ import annotations

import random
from decimal import Decimal
from pathlib import Path

import pytest
import torch

from recfusion_ml.evaluation.metrics import build_validation_cohort, evaluate_rankings
from recfusion_ml.models.two_tower import TwoTowerNetwork
from recfusion_ml.training.bpr import NegativeSampler, TrainingData
from recfusion_ml.training.two_tower import (
    TwoTowerConfig,
    TwoTowerEvent,
    build_two_tower_data,
    fit_two_tower,
    sampled_softmax_loss,
)
from recfusion_ml.training.two_tower_checkpoint import (
    load_two_tower_checkpoint,
    save_two_tower_checkpoint,
)
from recfusion_ml.types import RatingEvent


def event(
    user: str,
    item: str,
    rating: str,
    timestamp: int,
    split: str = "train",
    training_eligible: bool = True,
) -> TwoTowerEvent:
    return TwoTowerEvent(
        user_key=user,
        item_key=item,
        rating=Decimal(rating),
        event_time_ms=timestamp,
        split=split,
        training_eligible=training_eligible,
    )


def sample_events() -> tuple[TwoTowerEvent, ...]:
    return (
        event("u1", "a", "5", 100),
        event("u1", "a", "5", 150),
        event("u1", "b", "4", 200),
        event("u1", "low", "2", 250),
        event("u1", "future", "5", 400),
        event("u2", "c", "5", 100),
        event("u2", "d", "5", 200),
    )


def test_training_histories_are_strictly_prior_target_masked_and_deduplicated() -> None:
    data = build_two_tower_data(sample_events(), max_history_items=10)
    examples = {(row.user_key, row.item_key): row for row in data.examples}

    assert examples[("u1", "a")].event_time_ms == 100
    assert examples[("u1", "a")].history_item_ids == ()
    assert examples[("u1", "b")].history_item_ids == ("a",)
    assert "b" not in examples[("u1", "b")].history_item_ids
    assert "future" not in examples[("u1", "b")].history_item_ids
    assert data.inference_history_by_user["u1"] == ("future", "low", "b", "a")
    assert data.collapsed_positive_observations == 1


def test_equal_timestamp_events_are_simultaneous_and_not_history() -> None:
    data = build_two_tower_data(
        [event("u1", "a", "5", 100), event("u1", "b", "5", 100)],
        max_history_items=10,
    )

    assert [row.history_item_ids for row in data.examples] == [(), ()]


def test_history_limit_keeps_most_recent_unique_items() -> None:
    data = build_two_tower_data(
        [
            event("u1", "a", "3", 10),
            event("u1", "b", "2", 20),
            event("u1", "c", "5", 30),
            event("u1", "d", "4", 40),
            event("u1", "e", "5", 50),
        ],
        max_history_items=2,
    )
    examples = {(row.user_key, row.item_key): row for row in data.examples}

    assert examples[("u1", "c")].history_item_ids == ("b", "a")
    assert examples[("u1", "d")].history_item_ids == ("c", "b")


def test_training_rejects_heldout_events() -> None:
    with pytest.raises(ValueError, match="train-split events only"):
        build_two_tower_data(
            [event("u1", "a", "5", 100, split="validation")],
            max_history_items=10,
        )


def test_training_excludes_rows_marked_ineligible_by_temporal_contract() -> None:
    data = build_two_tower_data(
        [
            event("u1", "a", "5", 100),
            event("u1", "duplicate", "5", 150, training_eligible=False),
            event("u2", "b", "5", 100),
        ],
        max_history_items=10,
    )

    assert data.item_ids == ("a", "b")
    assert data.train_event_count == 2
    assert data.excluded_ineligible_event_count == 1
    assert all("duplicate" not in row.history_item_ids for row in data.examples)


def test_towers_emit_finite_shared_vectors_and_backpropagate() -> None:
    config = TwoTowerConfig(
        embedding_dim=8, hidden_dims=(12,), retrieval_dim=6, epochs=1
    )
    model = TwoTowerNetwork(
        user_count=3,
        item_count=5,
        embedding_dim=config.embedding_dim,
        hidden_dims=config.hidden_dims,
        retrieval_dim=config.retrieval_dim,
    )
    users = torch.tensor([1, 2], dtype=torch.long)
    history = torch.tensor([[0, 0], [1, 0]], dtype=torch.long)
    items = torch.tensor([2, 3], dtype=torch.long)
    scores = model.score(users, history, items)
    loss = scores.square().mean()
    loss.backward()

    assert model.encode_users(users, history).shape == (2, config.retrieval_dim)
    assert model.encode_items(items).shape == (2, config.retrieval_dim)
    assert torch.isfinite(scores).all()
    assert model.user_identity_embeddings.weight.grad is not None
    assert model.history_item_embeddings.weight.grad is not None
    assert model.item_identity_embeddings.weight.grad is not None
    assert all(torch.isfinite(param.grad).all() for param in model.parameters())
    assert torch.count_nonzero(model.user_identity_embeddings.weight[0]) == 0
    assert torch.count_nonzero(model.history_item_embeddings.weight[0]) == 0
    assert torch.count_nonzero(model.item_identity_embeddings.weight[0]) == 0
    assert torch.isfinite(
        model.encode_users(
            torch.tensor([1], dtype=torch.long), torch.empty((1, 0), dtype=torch.long)
        )
    ).all()


def test_sampled_softmax_loss_is_stable_and_masks_unavailable_negatives() -> None:
    positive = torch.tensor([1.0e4, -1.0e4], requires_grad=True)
    negatives = torch.tensor([[0.0, 1.0e4], [1.0e4, -1.0e4]], requires_grad=True)
    mask = torch.tensor([[True, False], [True, False]])
    loss = sampled_softmax_loss(positive, negatives, mask, temperature=0.2)
    loss.backward()

    assert torch.isfinite(loss)
    assert torch.isfinite(positive.grad).all()
    assert torch.isfinite(negatives.grad).all()
    assert negatives.grad[0, 1] == 0


def test_negative_sampler_returns_distinct_unobserved_items() -> None:
    training = [
        RatingEvent("u1", "seen-a", Decimal("5"), "train"),
        RatingEvent("u1", "seen-b", Decimal("2"), "train"),
        RatingEvent("u2", "candidate-a", Decimal("5"), "train"),
        RatingEvent("u2", "candidate-b", Decimal("5"), "train"),
    ]
    data = TrainingData.from_events(training)
    sampler = NegativeSampler(data)

    negatives = sampler.sample_many("u1", random.Random(12), 5)

    assert len(negatives) == 2
    assert len(set(negatives)) == len(negatives)
    assert not set(negatives) & data.seen_items_by_user["u1"]


def test_training_is_seed_deterministic_and_uses_rating_threshold() -> None:
    config = TwoTowerConfig(
        embedding_dim=8,
        hidden_dims=(12,),
        retrieval_dim=6,
        epochs=2,
        batch_size=2,
        seed=7,
        negative_count=2,
    )
    first = fit_two_tower(sample_events(), config=config)
    second = fit_two_tower(reversed(sample_events()), config=config)

    assert first.data.user_ids == ("u1", "u2")
    assert first.data.item_ids == ("a", "b", "c", "d", "future", "low")
    assert first.summary.unique_positive_pairs == 5
    assert first.summary.sampled_negative_count_per_epoch == 10
    assert [row.total_loss for row in first.epoch_statistics] == pytest.approx(
        [row.total_loss for row in second.epoch_statistics]
    )
    for name, weights in first.model.state_dict().items():
        assert torch.equal(weights, second.model.state_dict()[name])


def test_retrieval_is_bounded_seen_filtered_and_evaluator_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    train = sample_events()
    recommender = fit_two_tower(
        train,
        config=TwoTowerConfig(
            embedding_dim=8,
            hidden_dims=(12,),
            retrieval_dim=6,
            epochs=1,
            batch_size=2,
            seed=3,
            negative_count=2,
        ),
    )
    observed_chunk_sizes: list[int] = []
    encode_items = recommender.model.encode_items

    def track_chunks(indices: torch.Tensor) -> torch.Tensor:
        observed_chunk_sizes.append(indices.numel())
        return encode_items(indices)

    monkeypatch.setattr(recommender.model, "encode_items", track_chunks)
    recommendations = recommender.recommend_many(["u1"], k=5, chunk_size=2)

    assert not set(recommendations["u1"]) & recommender.data.seen_items_by_user["u1"]
    assert recommendations["u1"] == tuple(
        sorted(
            recommendations["u1"],
            key=lambda item: (-recommender.score("u1", item), item),
        )
    )
    assert max(observed_chunk_sizes) <= 2
    assert recommender.recommend("unknown-user", k=5) == ()
    with pytest.raises(ValueError, match="Unknown user"):
        recommender.score("unknown-user", "a")
    with pytest.raises(ValueError, match="train-known"):
        recommender.score("u1", "unknown-item")

    with torch.no_grad():
        for parameter in recommender.model.parameters():
            parameter.zero_()
    assert recommender.recommend("u1", k=5) == ("c", "d")

    training_ratings = [
        RatingEvent(row.user_key, row.item_key, row.rating, "train") for row in train
    ]
    validation_ratings = [RatingEvent("u1", "c", Decimal("5"), "validation")]
    cohort = build_validation_cohort(
        training_ratings,
        validation_ratings,
        recommender.data.candidate_items,
    )
    evaluator_rankings = recommender.recommend_many(
        cohort.targets_by_user, k=5, chunk_size=2
    )
    evaluation = evaluate_rankings(
        cohort,
        evaluator_rankings,
        candidate_items=recommender.data.candidate_items,
        ks=(5,),
    )
    assert evaluation.evaluated_user_count == 1


def test_independent_item_vectors_are_repeatable_and_checkpoint_round_trips(
    tmp_path: Path,
) -> None:
    config = TwoTowerConfig(
        embedding_dim=8,
        hidden_dims=(12,),
        retrieval_dim=6,
        epochs=1,
        batch_size=2,
        seed=9,
        negative_count=2,
    )
    recommender = fit_two_tower(
        sample_events(), config=config, source_artifact_fingerprints=("a" * 64,)
    )
    vectors = recommender.item_vectors(("a", "b"))
    assert torch.equal(vectors, recommender.item_vectors(("a", "b")))
    with pytest.raises(ValueError, match="train-known"):
        recommender.item_vectors(("outside",))

    target = tmp_path / "data" / "processed" / "tower.pt"
    saved = save_two_tower_checkpoint(recommender, target, repository_root=tmp_path)
    restored = load_two_tower_checkpoint(saved, repository_root=tmp_path)

    assert restored.config == recommender.config
    assert restored.data.training_fingerprint == recommender.data.training_fingerprint
    assert restored.item_vectors(("a", "b")).equal(vectors)
    assert restored.recommend_many(("u1", "u2"), k=5) == recommender.recommend_many(
        ("u1", "u2"), k=5
    )


def test_tiny_single_item_training_fails_without_sampled_negatives() -> None:
    with pytest.raises(ValueError, match="permissible train-known negative"):
        fit_two_tower(
            [event("u1", "only", "5", 100)],
            config=TwoTowerConfig(epochs=1),
        )
