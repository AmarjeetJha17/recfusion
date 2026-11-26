"""Separate history-aware user and identity-based item retrieval towers."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise
from typing import cast

import torch
from torch import Tensor, nn


def _projection(
    input_dim: int, hidden_dims: Sequence[int], output_dim: int
) -> nn.Sequential:
    dimensions = (input_dim, *hidden_dims, output_dim)
    layers: list[nn.Module] = []
    for index, (left, right) in enumerate(pairwise(dimensions)):
        layers.append(nn.Linear(left, right))
        if index < len(dimensions) - 2:
            layers.append(nn.GELU())
    return nn.Sequential(*layers)


class TwoTowerNetwork(nn.Module):
    """Map user identity/history and item identity into a shared vector space."""

    def __init__(
        self,
        *,
        user_count: int,
        item_count: int,
        embedding_dim: int,
        hidden_dims: Sequence[int],
        retrieval_dim: int,
    ) -> None:
        super().__init__()
        for name, value in (
            ("user_count", user_count),
            ("item_count", item_count),
            ("embedding_dim", embedding_dim),
            ("retrieval_dim", retrieval_dim),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        if not hidden_dims or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in hidden_dims
        ):
            raise ValueError("hidden_dims must contain positive integers.")

        self.embedding_dim = embedding_dim
        self.retrieval_dim = retrieval_dim
        self.user_identity_embeddings = nn.Embedding(
            user_count + 1, embedding_dim, padding_idx=0
        )
        self.history_item_embeddings = nn.Embedding(
            item_count + 1, embedding_dim, padding_idx=0
        )
        self.item_identity_embeddings = nn.Embedding(
            item_count + 1, embedding_dim, padding_idx=0
        )
        self.user_projection = _projection(
            2 * embedding_dim, hidden_dims, retrieval_dim
        )
        self.item_projection = _projection(embedding_dim, hidden_dims, retrieval_dim)
        self.reset_parameters()

    def reset_parameters(self) -> None:
        for embedding in (
            self.user_identity_embeddings,
            self.history_item_embeddings,
            self.item_identity_embeddings,
        ):
            nn.init.normal_(embedding.weight, mean=0.0, std=0.01)
            with torch.no_grad():
                embedding.weight[0].zero_()
        for module in (self.user_projection, self.item_projection):
            for layer in module:
                if isinstance(layer, nn.Linear):
                    nn.init.xavier_uniform_(layer.weight)
                    nn.init.zeros_(layer.bias)

    def encode_users(self, user_indices: Tensor, history_indices: Tensor) -> Tensor:
        if user_indices.dtype != torch.long or history_indices.dtype != torch.long:
            raise ValueError("User and history indices must use torch.int64 tensors.")
        if (
            user_indices.ndim != 1
            or history_indices.ndim != 2
            or user_indices.shape[0] != history_indices.shape[0]
        ):
            raise ValueError(
                "User indices and history rows must have matching batches."
            )
        history_vectors = self.history_item_embeddings(history_indices)
        history_mask = history_indices.ne(0).unsqueeze(-1)
        history_sum = (history_vectors * history_mask).sum(dim=1)
        history_count = history_mask.sum(dim=1).clamp_min(1)
        history_mean = history_sum / history_count
        user_identity = self.user_identity_embeddings(user_indices)
        vectors = self.user_projection(torch.cat((user_identity, history_mean), dim=-1))
        self._require_finite(vectors, "user tower")
        return cast(Tensor, vectors)

    def encode_items(self, item_indices: Tensor) -> Tensor:
        if item_indices.dtype != torch.long or item_indices.ndim != 1:
            raise ValueError("Item indices must be a one-dimensional int64 tensor.")
        vectors = self.item_projection(self.item_identity_embeddings(item_indices))
        self._require_finite(vectors, "item tower")
        return cast(Tensor, vectors)

    def score(
        self, user_indices: Tensor, history_indices: Tensor, item_indices: Tensor
    ) -> Tensor:
        if item_indices.dtype != torch.long or item_indices.ndim != 1:
            raise ValueError("Item indices must be a one-dimensional int64 tensor.")
        user_vectors = self.encode_users(user_indices, history_indices)
        item_vectors = self.encode_items(item_indices)
        if item_vectors.shape[0] != user_vectors.shape[0]:
            raise ValueError("User and item vector batches must match.")
        scores = torch.sum(user_vectors * item_vectors, dim=-1)
        self._require_finite(scores, "retrieval score")
        return scores

    @staticmethod
    def _require_finite(values: Tensor, label: str) -> None:
        if not torch.isfinite(values).all():
            raise ValueError(f"{label} produced a non-finite value.")
