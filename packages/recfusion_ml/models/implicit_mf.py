"""CPU-first implicit matrix factorization primitives."""

from __future__ import annotations

import torch
from torch import Tensor, nn
from torch.nn import functional as F


class ImplicitMF(nn.Module):
    """User and item embeddings scored by their dot product."""

    def __init__(self, *, user_count: int, item_count: int, embedding_dim: int) -> None:
        super().__init__()
        for name, value in (
            ("user_count", user_count),
            ("item_count", item_count),
            ("embedding_dim", embedding_dim),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        self.user_count = user_count
        self.item_count = item_count
        self.embedding_dim = embedding_dim
        self.user_embeddings = nn.Embedding(user_count, embedding_dim)
        self.item_embeddings = nn.Embedding(item_count, embedding_dim)
        nn.init.normal_(self.user_embeddings.weight, mean=0.0, std=0.01)
        nn.init.normal_(self.item_embeddings.weight, mean=0.0, std=0.01)

    def score(self, user_indices: Tensor, item_indices: Tensor) -> Tensor:
        if user_indices.dtype != torch.long or item_indices.dtype != torch.long:
            raise ValueError("Embedding indices must use torch.int64 tensors.")
        if user_indices.shape != item_indices.shape:
            raise ValueError("User and item index tensors must have matching shapes.")
        user_vectors: Tensor = self.user_embeddings(user_indices)
        item_vectors: Tensor = self.item_embeddings(item_indices)
        return torch.sum(user_vectors * item_vectors, dim=-1)


def pairwise_bpr_loss(positive_scores: Tensor, negative_scores: Tensor) -> Tensor:
    """Return mean softplus(negative score - positive score)."""
    if positive_scores.shape != negative_scores.shape or positive_scores.numel() == 0:
        raise ValueError("BPR score tensors must have equal, non-empty shapes.")
    if (
        not torch.isfinite(positive_scores).all()
        or not torch.isfinite(negative_scores).all()
    ):
        raise ValueError("BPR scores must be finite.")
    loss = F.softplus(negative_scores - positive_scores).mean()
    if not torch.isfinite(loss):
        raise ValueError("BPR loss is not finite.")
    return loss
