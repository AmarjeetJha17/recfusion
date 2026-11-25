"""Stable user sampling based only on the eligible training-user population."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def select_train_users(
    eligible_user_keys: Iterable[str],
    *,
    max_users: int,
    seed: str,
    source_id: str,
) -> frozenset[str]:
    if max_users < 1:
        raise ValueError("max_users must be positive.")
    if not _SAFE_TOKEN.fullmatch(seed) or not _SAFE_TOKEN.fullmatch(source_id):
        raise ValueError("seed and source_id must be non-empty safe tokens.")

    unique_users = set(eligible_user_keys)
    ranked_users = sorted(
        unique_users,
        key=lambda user_key: (
            hashlib.sha256(f"{seed}|{source_id}|{user_key}".encode()).digest(),
            user_key,
        ),
    )
    return frozenset(ranked_users[:max_users])
