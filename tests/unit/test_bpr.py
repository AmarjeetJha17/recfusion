import random
from decimal import Decimal

import pytest
import torch

from recfusion_ml.models.implicit_mf import ImplicitMF, pairwise_bpr_loss
from recfusion_ml.training.bpr import (
    BPRConfig,
    NegativeSampler,
    TrainingData,
    fit_bpr,
    load_checkpoint,
    save_checkpoint,
)
from recfusion_ml.types import RatingEvent


def event(user: str, item: str, rating: str = "5", split: str = "train") -> RatingEvent:
    return RatingEvent(user, item, Decimal(rating), split)


def test_embedding_shapes_and_dot_product_scoring() -> None:
    model = ImplicitMF(user_count=2, item_count=3, embedding_dim=4)
    with torch.no_grad():
        model.user_embeddings.weight[0] = torch.tensor([1.0, 2.0, 3.0, 4.0])
        model.item_embeddings.weight[1] = torch.tensor([2.0, 1.0, 0.0, -1.0])

    assert model.user_embeddings.weight.shape == (2, 4)
    assert model.item_embeddings.weight.shape == (3, 4)
    assert model.score(torch.tensor([0]), torch.tensor([1])).tolist() == [0.0]


def test_bpr_loss_is_stable_and_backpropagates_finite_gradients() -> None:
    positive = torch.tensor([1e4, -1e4], requires_grad=True)
    negative = torch.tensor([-1e4, 1e4], requires_grad=True)

    loss = pairwise_bpr_loss(positive, negative)
    loss.backward()

    assert torch.isfinite(loss)
    assert torch.isfinite(positive.grad).all()
    assert torch.isfinite(negative.grad).all()
    assert loss.item() == pytest.approx(1e4)


def test_training_data_uses_train_only_vocab_and_deduplicated_positive_pairs() -> None:
    data = TrainingData.from_events(
        [
            event("u1", "a"),
            event("u1", "a"),
            event("u1", "seen-low", "2"),
            event("u2", "b", "3"),
        ]
    )

    assert data.user_ids == ("u1", "u2")
    assert data.item_ids == ("a", "b", "seen-low")
    assert data.positive_pairs == (("u1", "a"),)
    assert data.seen_items_by_user["u1"] == frozenset({"a", "seen-low"})
    assert data.collapsed_positive_observations == 1
    with pytest.raises(ValueError, match="train-split"):
        TrainingData.from_events([event("heldout", "future", "5", "validation")])


def test_negative_sampler_excludes_every_observed_item_and_has_dense_fallback() -> None:
    data = TrainingData.from_events(
        [event("dense", "a"), event("dense", "b"), event("dense", "c", "2")]
    )
    sampler = NegativeSampler(data)

    assert sampler.sample("dense", random.Random(7)) is None

    data = TrainingData.from_events(
        [
            event("u", "a"),
            event("u", "b", "2"),
            event("v", "a"),
            event("v", "c"),
        ]
    )
    sampler = NegativeSampler(data)
    negative = sampler.sample("u", random.Random(3))
    assert negative == "c"
    assert negative not in data.seen_items_by_user["u"]


def test_training_is_deterministic_and_improves_positive_pair_score() -> None:
    training = [
        event("u1", "positive"),
        event("u2", "positive"),
        event("owner", "negative", "2"),
    ]
    config = BPRConfig(embedding_dim=8, epochs=12, batch_size=2, seed=17)
    first = fit_bpr(training, config=config)
    second = fit_bpr(reversed(training), config=config)

    assert first.epoch_losses == second.epoch_losses
    assert first.model.state_dict().keys() == second.model.state_dict().keys()
    for name, weights in first.model.state_dict().items():
        assert torch.equal(weights, second.model.state_dict()[name])
    assert first.score("u1", "positive") > first.score("u1", "negative")
    assert first.summary.unique_positive_pairs == 2
    assert first.summary.collapsed_positive_observations == 0
    duplicated = fit_bpr([*training, event("u1", "positive")], config=config)
    for name, weights in first.model.state_dict().items():
        assert torch.equal(weights, duplicated.model.state_dict()[name])


def test_sampling_does_not_use_heldout_rows_and_empty_or_heldout_only_fails() -> None:
    training = [event("u", "a"), event("v", "b")]
    original = fit_bpr(training, config=BPRConfig(epochs=1, seed=4))
    assert original.data.user_ids == ("u", "v")
    assert original.data.item_ids == ("a", "b")

    with pytest.raises(ValueError, match="train"):
        TrainingData.from_events([event("u", "a", split="validation")])
    with pytest.raises(ValueError, match="at least one"):
        TrainingData.from_events([])
    with pytest.raises(ValueError, match="train-split"):
        fit_bpr([*training, event("future-user", "future-item", split="test")])
    with pytest.raises(ValueError, match="permissible"):
        fit_bpr([event("u", "only-positive")])


def test_scoring_filters_seen_items_and_has_stable_ties_and_chunk_equivalence() -> None:
    result = fit_bpr(
        [
            event("u", "seen", "2"),
            event("u", "own"),
            event("v", "a"),
            event("owner", "b", "2"),
        ],
        config=BPRConfig(embedding_dim=2, epochs=1),
    )
    with torch.no_grad():
        result.model.user_embeddings.weight.zero_()
    assert result.recommend("u", k=5) == ("a", "b")
    assert result.recommend("unknown", k=5) == ()
    assert result.recommend("u", k=5, chunk_size=1) == result.recommend(
        "u", k=5, chunk_size=100
    )
    assert result.recommend_many(["u"], k=5) == {"u": ("a", "b")}
    with pytest.raises(ValueError, match="train-known"):
        result.score("u", "not-in-vocabulary")


def test_checkpoint_round_trip_is_safe_and_preserves_scores(tmp_path) -> None:
    result = fit_bpr(
        [event("u", "a"), event("u", "b", "2"), event("v", "b")],
        config=BPRConfig(embedding_dim=4, epochs=2),
        source_artifact_fingerprints=["b" * 64],
    )
    target = tmp_path / "data" / "processed" / "bpr.pt"
    path = save_checkpoint(result, target, repository_root=tmp_path)
    restored = load_checkpoint(path, repository_root=tmp_path)

    assert restored.score("u", "a") == pytest.approx(result.score("u", "a"))
    assert restored.data.user_ids == result.data.user_ids
    assert restored.data.positive_pairs == result.data.positive_pairs
    assert restored.data.source_artifact_fingerprints == ("b" * 64,)
    assert restored.data.training_fingerprint == result.data.training_fingerprint
    with pytest.raises(FileExistsError):
        save_checkpoint(result, target, repository_root=tmp_path)
    with pytest.raises(ValueError, match="data/processed"):
        save_checkpoint(result, tmp_path / "outside.pt", repository_root=tmp_path)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"embedding_dim": 0},
        {"epochs": 0},
        {"batch_size": 0},
        {"learning_rate": 0.0},
        {"regularization": -1.0},
        {"seed": True},
        {"negative_sampling_retries": 0},
    ],
)
def test_invalid_training_configuration_is_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="must be"):
        BPRConfig(**kwargs)  # type: ignore[arg-type]


def test_source_artifact_fingerprints_are_validated_and_preserved() -> None:
    fingerprint = "a" * 64
    data = TrainingData.from_events(
        [event("u", "item")], source_artifact_fingerprints=[fingerprint]
    )

    assert data.source_artifact_fingerprints == (fingerprint,)
    with pytest.raises(ValueError, match="SHA-256"):
        TrainingData.from_events(
            [event("u", "item")], source_artifact_fingerprints=["bad"]
        )
