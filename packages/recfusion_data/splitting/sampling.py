"""Stable user sampling based only on the eligible training-user population."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path

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


def select_train_users_disk_backed(
    eligible_user_keys: Iterable[str],
    *,
    max_users: int,
    seed: str,
    source_id: str,
    database_path: Path,
) -> tuple[frozenset[str], int]:
    """Select the stable top-K users while keeping the eligible set on disk."""
    if max_users < 1:
        raise ValueError("max_users must be positive.")
    if not _SAFE_TOKEN.fullmatch(seed) or not _SAFE_TOKEN.fullmatch(source_id):
        raise ValueError("seed and source_id must be non-empty safe tokens.")

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "CREATE TABLE eligible_users ("
            "user_key TEXT PRIMARY KEY, rank BLOB NOT NULL)"
        )
        connection.executemany(
            "INSERT OR IGNORE INTO eligible_users (user_key, rank) VALUES (?, ?)",
            (
                (
                    user_key,
                    hashlib.sha256(f"{seed}|{source_id}|{user_key}".encode()).digest(),
                )
                for user_key in eligible_user_keys
            ),
        )
        eligible_count = connection.execute(
            "SELECT COUNT(*) FROM eligible_users"
        ).fetchone()[0]
        if eligible_count < max_users:
            raise ValueError(
                f"Requested {max_users} users, but only {eligible_count} "
                "eligible train users were found."
            )
        rows = connection.execute(
            "SELECT user_key FROM eligible_users ORDER BY rank, user_key LIMIT ?",
            (max_users,),
        )
        selected = frozenset(row[0] for row in rows)
        return selected, eligible_count
    finally:
        connection.close()
