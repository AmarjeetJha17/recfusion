"""Deterministic manifest and checksum utilities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_count = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                byte_count += len(chunk)
    except OSError as error:
        raise ValueError("Cannot checksum source file.") from error
    return digest.hexdigest(), byte_count


def source_record_fingerprint(
    record: Mapping[str, object], *, source_id: str, source_version: str
) -> str:
    payload: dict[str, Any] = {
        "source_id": source_id,
        "source_version": source_version,
        "record": record,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_manifest(path: Path, manifest: Mapping[str, object]) -> bytes:
    encoded = (
        json.dumps(
            manifest,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    path.write_bytes(encoded)
    return encoded
