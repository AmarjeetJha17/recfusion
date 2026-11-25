"""Deterministic preprocessing and quality reporting for canonical interactions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import cast

from recfusion_core.contracts import DataSplit, Interaction, JSONValue
from recfusion_data.ingestion.errors import IngestionError, RecordValidationError
from recfusion_data.ingestion.manifest import sha256_file, write_manifest
from recfusion_data.ingestion.readers import SourceRow, read_jsonl
from recfusion_data.validation import validate_interaction

DERIVED_SCHEMA_VERSION = "recfusion.interaction-preprocessing.v1"
_SPLITS = (DataSplit.TRAIN, DataSplit.VALIDATION, DataSplit.TEST)
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_FIELDS = frozenset(
    {
        "user_key",
        "item_key",
        "event_time_ms",
        "rating",
        "split",
        "source_event_fingerprint",
        "source_event_id",
        "event_type",
        "source_timestamp_value",
    }
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_PROCESSED_ROOT = (_REPOSITORY_ROOT / "data" / "processed").resolve()


class RatingLabel(StrEnum):
    OBSERVED_POSITIVE = "observed_positive_signal"
    NEUTRAL = "neutral"
    OBSERVED_LOW = "observed_low_rating"
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True, slots=True)
class RatingLabelConfig:
    """Provisional configurable thresholds for observed rating feedback."""

    positive_min: Decimal = Decimal("4")
    neutral_rating: Decimal = Decimal("3")
    low_max: Decimal = Decimal("2")

    def __post_init__(self) -> None:
        thresholds = (self.low_max, self.neutral_rating, self.positive_min)
        if not all(value.is_finite() for value in thresholds):
            raise ValueError("Rating thresholds must be finite.")
        if not (
            Decimal("1")
            <= self.low_max
            < self.neutral_rating
            < self.positive_min
            <= Decimal("5")
        ):
            raise ValueError(
                "Rating thresholds must satisfy 1 <= low_max < neutral_rating "
                "< positive_min <= 5."
            )

    def label(self, rating: Decimal) -> RatingLabel:
        if rating >= self.positive_min:
            return RatingLabel.OBSERVED_POSITIVE
        if rating <= self.low_max:
            return RatingLabel.OBSERVED_LOW
        if rating == self.neutral_rating:
            return RatingLabel.NEUTRAL
        return RatingLabel.UNCLASSIFIED

    def as_record(self) -> dict[str, str]:
        return {
            "positive_min": str(self.positive_min),
            "neutral_rating": str(self.neutral_rating),
            "low_max": str(self.low_max),
        }


@dataclass(frozen=True, slots=True)
class PreprocessingResult:
    output_dir: Path
    manifest: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _PreparedInteraction:
    interaction: Interaction
    source_rating_value: JSONValue
    source_timestamp_value: JSONValue
    source_event_id: str | None
    source_event_id_present: bool
    event_type: str | None
    event_type_present: bool
    event_time_utc: str
    rating_label: RatingLabel

    def as_record(self) -> dict[str, object]:
        interaction = self.interaction
        return {
            "schema_version": DERIVED_SCHEMA_VERSION,
            "user_key": interaction.user_key,
            "item_key": interaction.item_key,
            "event_time_ms": interaction.event_time_ms,
            "event_time_utc": self.event_time_utc,
            "source_timestamp_value": self.source_timestamp_value,
            "source_timestamp_unit": "unix_ms",
            "rating": str(interaction.rating),
            "source_rating_value": self.source_rating_value,
            "rating_label": self.rating_label.value,
            "event_type": self.event_type,
            "event_type_present": self.event_type_present,
            "source_event_id": self.source_event_id,
            "source_event_id_present": self.source_event_id_present,
            "source_event_fingerprint": interaction.source_event_fingerprint,
            "split": interaction.split.value,
        }


class _JsonlSink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.file = path.open("w", encoding="utf-8", newline="\n")
        self.digest = hashlib.sha256()
        self.record_count = 0

    def write(self, record: Mapping[str, object]) -> None:
        line = (
            json.dumps(
                record,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )
        self.file.write(line)
        self.digest.update(line.encode("utf-8"))
        self.record_count += 1

    def close(self) -> None:
        self.file.close()

    def manifest_record(self) -> dict[str, object]:
        self.file.flush()
        return {
            "file": self.path.name,
            "records": self.record_count,
            "sha256": self.digest.hexdigest(),
            "size_bytes": self.path.stat().st_size,
        }


class _InteractionIndex:
    """Disk-backed event spool; collisions are resolved independent of row order."""

    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=OFF")
        self.connection.execute("PRAGMA synchronous=OFF")
        self.connection.execute("PRAGMA temp_store=FILE")
        self.connection.execute("PRAGMA cache_size=-8192")
        self.connection.executescript(
            """
            CREATE TABLE events (
                split TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                signature TEXT NOT NULL,
                event_time_ms INTEGER NOT NULL,
                user_key TEXT NOT NULL,
                item_key TEXT NOT NULL,
                rating TEXT NOT NULL,
                rating_label TEXT NOT NULL,
                event_type TEXT,
                event_type_present INTEGER NOT NULL,
                payload TEXT NOT NULL,
                occurrences INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (split, fingerprint, signature)
            ) WITHOUT ROWID;
            CREATE INDEX events_fingerprint_idx ON events (fingerprint);
            """
        )

    def add(self, event: _PreparedInteraction) -> None:
        record = event.as_record()
        signature_record = {
            key: value for key, value in record.items() if key != "split"
        }
        signature = _canonical_json(signature_record)
        payload = _canonical_json(record)
        interaction = event.interaction
        self.connection.execute(
            """
            INSERT INTO events (
                split, fingerprint, signature, event_time_ms, user_key, item_key,
                rating, rating_label, event_type, event_type_present, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (split, fingerprint, signature)
            DO UPDATE SET occurrences = occurrences + 1
            """,
            (
                interaction.split.value,
                interaction.source_event_fingerprint,
                signature,
                interaction.event_time_ms,
                interaction.user_key,
                interaction.item_key,
                str(interaction.rating),
                event.rating_label.value,
                event.event_type,
                int(event.event_type_present),
                payload,
            ),
        )

    def finalize(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE conflicts (
                split TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                PRIMARY KEY (split, fingerprint)
            ) WITHOUT ROWID
            """
        )
        self.connection.execute(
            """
            INSERT INTO conflicts (split, fingerprint)
            SELECT split, fingerprint
            FROM events
            GROUP BY split, fingerprint
            HAVING COUNT(*) > 1
            """
        )
        self.connection.execute(
            """
            CREATE TABLE train_users (user_key TEXT PRIMARY KEY) WITHOUT ROWID
            """
        )
        self.connection.execute(
            """
            INSERT INTO train_users
            SELECT DISTINCT e.user_key
            FROM events AS e
            WHERE e.split = 'train'
              AND NOT EXISTS (
                  SELECT 1 FROM conflicts AS c
                  WHERE c.fingerprint = e.fingerprint
                    AND c.split = e.split
              )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE train_items (item_key TEXT PRIMARY KEY) WITHOUT ROWID
            """
        )
        self.connection.execute(
            """
            INSERT INTO train_items
            SELECT DISTINCT e.item_key
            FROM events AS e
            WHERE e.split = 'train'
              AND NOT EXISTS (
                  SELECT 1 FROM conflicts AS c
                  WHERE c.fingerprint = e.fingerprint
                    AND c.split = e.split
              )
            """
        )
        self.connection.commit()

    def iter_split(self, split: DataSplit) -> Iterator[tuple[str]]:
        yield from self.connection.execute(
            """
            SELECT payload
            FROM events AS e
            WHERE e.split = ?
              AND NOT EXISTS (
                  SELECT 1 FROM conflicts AS c
                  WHERE c.fingerprint = e.fingerprint
                    AND c.split = e.split
              )
            ORDER BY e.event_time_ms, e.fingerprint, e.signature
            """,
            (split.value,),
        )

    def scalar(self, query: str, parameters: tuple[object, ...] = ()) -> int:
        row = self.connection.execute(query, parameters).fetchone()
        return int(row[0]) if row is not None else 0

    def grouped_counts(
        self, query: str, parameters: tuple[object, ...] = ()
    ) -> dict[str, int]:
        return {
            str(key): int(count)
            for key, count in self.connection.execute(query, parameters)
        }

    def close(self) -> None:
        self.connection.commit()
        self.connection.close()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _is_json_value(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return value == value and abs(value) != float("inf")
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_value(item) for key, item in value.items()
        )
    return False


def _utc_timestamp(event_time_ms: int) -> str:
    try:
        timestamp = _EPOCH + timedelta(milliseconds=event_time_ms)
    except OverflowError:
        raise ValueError("impossible_timestamp") from None
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _prepare_row(
    row: SourceRow,
    *,
    split: DataSplit,
    labels: RatingLabelConfig,
) -> _PreparedInteraction:
    if row.error_code is not None or row.values is None:
        raise ValueError(row.error_code or "empty_record")
    values = row.values
    unknown_fields = set(values) - _ALLOWED_FIELDS
    if unknown_fields:
        raise ValueError("unsupported_interaction_field")
    if values.get("split") != split.value:
        raise ValueError("split_mismatch")
    fingerprint = values.get("source_event_fingerprint")
    if not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint):
        raise ValueError("invalid_source_event_fingerprint")
    source_timestamp_value = values.get(
        "source_timestamp_value", values.get("event_time_ms")
    )
    if not _is_json_value(source_timestamp_value):
        raise ValueError("invalid_source_timestamp_value")
    source_rating_value = values.get("rating")
    if not _is_json_value(source_rating_value):
        raise ValueError("invalid_rating")
    for field in ("event_type", "source_event_id"):
        if field in values:
            optional_value = values[field]
            if optional_value is not None and (
                not isinstance(optional_value, str) or not optional_value.strip()
            ):
                raise ValueError(f"invalid_{field}")
    try:
        interaction = validate_interaction(values, split, fingerprint)
    except RecordValidationError as error:
        raise ValueError(error.issues[0].code) from None
    try:
        event_time_utc = _utc_timestamp(interaction.event_time_ms)
    except ValueError:
        raise ValueError("impossible_timestamp") from None
    return _PreparedInteraction(
        interaction=interaction,
        source_rating_value=cast(JSONValue, source_rating_value),
        source_timestamp_value=cast(JSONValue, source_timestamp_value),
        source_event_id=cast(str | None, values.get("source_event_id")),
        source_event_id_present="source_event_id" in values,
        event_type=cast(str | None, values.get("event_type")),
        event_type_present="event_type" in values,
        event_time_utc=event_time_utc,
        rating_label=labels.label(interaction.rating),
    )


def _source_manifest(
    files: Mapping[DataSplit, Path],
    *,
    source_id: str,
    source_version: str,
    output_dir: Path,
) -> tuple[Path, dict[str, dict[str, object]]]:
    if not all(_SAFE_TOKEN.fullmatch(value) for value in (source_id, source_version)):
        raise IngestionError("Source identity and version must be safe ASCII tokens.")
    resolved_inputs: set[Path] = set()
    input_manifest: dict[str, dict[str, object]] = {}
    for split, path in files.items():
        resolved = path.resolve()
        if resolved in resolved_inputs:
            raise IngestionError("Each split input must be a distinct file.")
        resolved_inputs.add(resolved)
        if not path.is_file():
            raise IngestionError(f"Required {split.value} input is not a local file.")
        try:
            checksum, size = sha256_file(path)
        except ValueError as error:
            raise IngestionError(f"Cannot checksum {split.value} input.") from error
        input_manifest[split.value] = {
            "file": path.name,
            "sha256": checksum,
            "size_bytes": size,
        }

    requested_output = (
        output_dir if output_dir.is_absolute() else _REPOSITORY_ROOT / output_dir
    )
    if requested_output.is_symlink():
        raise IngestionError("Output directory cannot be a symbolic link.")
    resolved_output = requested_output.resolve()
    try:
        relative_output = resolved_output.relative_to(_PROCESSED_ROOT)
    except ValueError:
        raise IngestionError(
            "Output must be inside the ignored data/processed directory."
        ) from None
    if not relative_output.parts:
        raise IngestionError("Output must name a new child directory.")
    if resolved_output.exists() or resolved_output.is_symlink():
        raise IngestionError("Output directory already exists; refusing to overwrite.")
    if resolved_output in resolved_inputs:
        raise IngestionError("Output directory cannot replace a source file.")
    return resolved_output, input_manifest


def _split_quality(
    index: _InteractionIndex,
    split: DataSplit,
    *,
    input_records: int,
    valid_records: int,
    invalid_records: int,
    invalid_reasons: Mapping[str, int],
    duplicate_occurrences: int,
    skipped_duplicates: int,
    conflict_records: int,
) -> dict[str, object]:
    retained = index.scalar(
        """
        SELECT COUNT(*)
        FROM events AS e
        WHERE e.split = ?
          AND NOT EXISTS (
              SELECT 1 FROM conflicts AS c
              WHERE c.fingerprint = e.fingerprint AND c.split = e.split
          )
        """,
        (split.value,),
    )
    unique_users = index.scalar(
        """
        SELECT COUNT(DISTINCT e.user_key)
        FROM events AS e
        WHERE e.split = ?
          AND NOT EXISTS (
              SELECT 1 FROM conflicts AS c
              WHERE c.fingerprint = e.fingerprint AND c.split = e.split
          )
        """,
        (split.value,),
    )
    unique_items = index.scalar(
        """
        SELECT COUNT(DISTINCT e.item_key)
        FROM events AS e
        WHERE e.split = ?
          AND NOT EXISTS (
              SELECT 1 FROM conflicts AS c
              WHERE c.fingerprint = e.fingerprint AND c.split = e.split
          )
        """,
        (split.value,),
    )
    bounds = index.connection.execute(
        """
        SELECT MIN(e.event_time_ms), MAX(e.event_time_ms)
        FROM events AS e
        WHERE e.split = ?
          AND NOT EXISTS (
              SELECT 1 FROM conflicts AS c
              WHERE c.fingerprint = e.fingerprint AND c.split = e.split
          )
        """,
        (split.value,),
    ).fetchone()
    rating_distribution = index.grouped_counts(
        """
        SELECT e.rating, COUNT(*)
        FROM events AS e
        WHERE e.split = ?
          AND NOT EXISTS (
              SELECT 1 FROM conflicts AS c
              WHERE c.fingerprint = e.fingerprint AND c.split = e.split
          )
        GROUP BY e.rating
        ORDER BY e.rating
        """,
        (split.value,),
    )
    label_distribution = index.grouped_counts(
        """
        SELECT e.rating_label, COUNT(*)
        FROM events AS e
        WHERE e.split = ?
          AND NOT EXISTS (
              SELECT 1 FROM conflicts AS c
              WHERE c.fingerprint = e.fingerprint AND c.split = e.split
          )
        GROUP BY e.rating_label
        ORDER BY e.rating_label
        """,
        (split.value,),
    )
    event_type_counts: dict[str, object] = {
        "missing_records": index.scalar(
            """
            SELECT COALESCE(
                SUM(CASE WHEN e.event_type_present = 0 THEN 1 ELSE 0 END), 0
            )
            FROM events AS e
            WHERE e.split = ?
              AND NOT EXISTS (
                  SELECT 1 FROM conflicts AS c
                  WHERE c.fingerprint = e.fingerprint AND c.split = e.split
              )
            """,
            (split.value,),
        ),
        "null_records": index.scalar(
            """
            SELECT COALESCE(
                SUM(CASE WHEN e.event_type_present = 1 THEN 1 ELSE 0 END), 0
            )
            FROM events AS e
            WHERE e.split = ?
              AND e.event_type IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM conflicts AS c
                  WHERE c.fingerprint = e.fingerprint AND c.split = e.split
              )
            """,
            (split.value,),
        ),
    }
    event_type_counts = {
        **event_type_counts,
        "values": index.grouped_counts(
            """
            SELECT e.event_type, COUNT(*)
            FROM events AS e
            WHERE e.split = ?
              AND e.event_type IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM conflicts AS c
                  WHERE c.fingerprint = e.fingerprint AND c.split = e.split
              )
            GROUP BY e.event_type
            ORDER BY e.event_type
            """,
            (split.value,),
        ),
    }
    rejection_counts = Counter(invalid_reasons)
    if conflict_records:
        rejection_counts["fingerprint_conflict"] = conflict_records
    return {
        "input_records": input_records,
        "valid_records_before_deduplication": valid_records,
        "invalid_records": invalid_records,
        "retained_unique_records": retained,
        "exact_duplicate_occurrences": duplicate_occurrences,
        "exact_duplicate_rows_skipped": skipped_duplicates,
        "fingerprint_conflict_records": conflict_records,
        "rejected_records": invalid_records + conflict_records,
        "rejection_counts_by_reason": dict(sorted(rejection_counts.items())),
        "unique_users": unique_users,
        "unique_items": unique_items,
        "rating_distribution": rating_distribution,
        "rating_label_distribution": label_distribution,
        "event_type_distribution": event_type_counts,
        "timestamp_range_ms": (
            {"min": bounds[0], "max": bounds[1]}
            if bounds is not None and bounds[0] is not None
            else None
        ),
        "timestamp_range_utc": (
            {
                "min": _utc_timestamp(int(bounds[0])),
                "max": _utc_timestamp(int(bounds[1])),
            }
            if bounds is not None and bounds[0] is not None
            else None
        ),
    }


def _cold_start_counts(index: _InteractionIndex, split: DataSplit) -> dict[str, int]:
    return {
        "users_unseen_in_train": index.scalar(
            """
            SELECT COUNT(DISTINCT e.user_key)
            FROM events AS e
            WHERE e.split = ?
              AND NOT EXISTS (
                  SELECT 1 FROM conflicts AS c
                  WHERE c.fingerprint = e.fingerprint AND c.split = e.split
              )
              AND NOT EXISTS (
                  SELECT 1 FROM train_users AS t WHERE t.user_key = e.user_key
              )
            """,
            (split.value,),
        ),
        "items_unseen_in_train": index.scalar(
            """
            SELECT COUNT(DISTINCT e.item_key)
            FROM events AS e
            WHERE e.split = ?
              AND NOT EXISTS (
                  SELECT 1 FROM conflicts AS c
                  WHERE c.fingerprint = e.fingerprint AND c.split = e.split
              )
              AND NOT EXISTS (
                  SELECT 1 FROM train_items AS t WHERE t.item_key = e.item_key
              )
            """,
            (split.value,),
        ),
    }


def preprocess_interaction_files(
    *,
    train_path: Path,
    validation_path: Path,
    test_path: Path,
    output_dir: Path,
    source_id: str,
    source_version: str,
    label_config: RatingLabelConfig = RatingLabelConfig(),
) -> PreprocessingResult:
    """Validate, deduplicate, label, and atomically publish canonical JSONL splits."""
    files = {
        DataSplit.TRAIN: train_path,
        DataSplit.VALIDATION: validation_path,
        DataSplit.TEST: test_path,
    }
    final_output, input_manifest = _source_manifest(
        files,
        source_id=source_id,
        source_version=source_version,
        output_dir=output_dir,
    )
    final_output.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{final_output.name}.tmp-", dir=final_output.parent)
    )
    input_counts = {split: 0 for split in _SPLITS}
    valid_counts = {split: 0 for split in _SPLITS}
    invalid_counts: dict[DataSplit, Counter[str]] = {
        split: Counter() for split in _SPLITS
    }
    sinks: dict[DataSplit, _JsonlSink] = {}
    index: _InteractionIndex | None = None

    try:
        with tempfile.TemporaryDirectory(prefix="recfusion-preprocess-") as scratch:
            index = _InteractionIndex(Path(scratch) / "events.sqlite3")
            for split, path in files.items():
                for row in read_jsonl(path):
                    input_counts[split] += 1
                    try:
                        event = _prepare_row(row, split=split, labels=label_config)
                    except ValueError as error:
                        invalid_counts[split][str(error)] += 1
                        continue
                    valid_counts[split] += 1
                    index.add(event)

            index.finalize()
            sinks = {
                split: _JsonlSink(
                    staging_dir / f"interactions.{split.value}.processed.jsonl"
                )
                for split in _SPLITS
            }
            for split in _SPLITS:
                for (payload,) in index.iter_split(split):
                    sinks[split].write(cast(dict[str, object], json.loads(payload)))

            conflict_by_split = {
                split: index.scalar(
                    """
                    SELECT COALESCE(SUM(e.occurrences), 0)
                    FROM events AS e
                    JOIN conflicts AS c
                      ON c.fingerprint = e.fingerprint AND c.split = e.split
                    WHERE e.split = ?
                    """,
                    (split.value,),
                )
                for split in _SPLITS
            }
            duplicate_by_split = {
                split: index.scalar(
                    """
                    SELECT COALESCE(SUM(e.occurrences - 1), 0)
                    FROM events AS e
                    WHERE e.split = ?
                    """,
                    (split.value,),
                )
                for split in _SPLITS
            }
            skipped_duplicate_by_split = {
                split: index.scalar(
                    """
                    SELECT COALESCE(SUM(e.occurrences - 1), 0)
                    FROM events AS e
                    WHERE e.split = ?
                      AND NOT EXISTS (
                          SELECT 1 FROM conflicts AS c
                          WHERE c.fingerprint = e.fingerprint
                            AND c.split = e.split
                      )
                    """,
                    (split.value,),
                )
                for split in _SPLITS
            }
            conflict_groups = index.scalar("SELECT COUNT(*) FROM conflicts")
            cross_split_duplicate_groups = index.scalar(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT e.fingerprint
                    FROM events AS e
                    WHERE NOT EXISTS (
                        SELECT 1 FROM conflicts AS c
                        WHERE c.fingerprint = e.fingerprint AND c.split = e.split
                    )
                    GROUP BY e.fingerprint
                    HAVING COUNT(DISTINCT e.split) > 1
                       AND COUNT(DISTINCT e.signature) = 1
                )
                """
            )
            cross_split_fingerprint_conflicts = index.scalar(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT e.fingerprint
                    FROM events AS e
                    WHERE NOT EXISTS (
                        SELECT 1 FROM conflicts AS c
                        WHERE c.fingerprint = e.fingerprint AND c.split = e.split
                    )
                    GROUP BY e.fingerprint
                    HAVING COUNT(DISTINCT e.split) > 1
                       AND COUNT(DISTINCT e.signature) > 1
                )
                """
            )
            per_split = {
                split.value: _split_quality(
                    index,
                    split,
                    input_records=input_counts[split],
                    valid_records=valid_counts[split],
                    invalid_records=sum(invalid_counts[split].values()),
                    invalid_reasons=invalid_counts[split],
                    duplicate_occurrences=duplicate_by_split[split],
                    skipped_duplicates=skipped_duplicate_by_split[split],
                    conflict_records=conflict_by_split[split],
                )
                for split in _SPLITS
            }
            overall_input = sum(input_counts.values())
            overall_valid = sum(valid_counts.values())
            overall_invalid = sum(
                sum(counter.values()) for counter in invalid_counts.values()
            )
            overall_conflict_records = sum(conflict_by_split.values())
            overall_duplicate_occurrences = sum(duplicate_by_split.values())
            overall_skipped_duplicates = sum(skipped_duplicate_by_split.values())
            overall_retained = sum(sink.record_count for sink in sinks.values())
            overall_users = index.scalar(
                """
                SELECT COUNT(DISTINCT e.user_key)
                FROM events AS e
                WHERE NOT EXISTS (
                    SELECT 1 FROM conflicts AS c
                    WHERE c.fingerprint = e.fingerprint AND c.split = e.split
                )
                """
            )
            overall_items = index.scalar(
                """
                SELECT COUNT(DISTINCT e.item_key)
                FROM events AS e
                WHERE NOT EXISTS (
                    SELECT 1 FROM conflicts AS c
                    WHERE c.fingerprint = e.fingerprint AND c.split = e.split
                )
                """
            )
            all_bounds = index.connection.execute(
                """
                SELECT MIN(e.event_time_ms), MAX(e.event_time_ms)
                FROM events AS e
                WHERE NOT EXISTS (
                    SELECT 1 FROM conflicts AS c
                    WHERE c.fingerprint = e.fingerprint AND c.split = e.split
                )
                """
            ).fetchone()
            overall_rating_distribution: Counter[str] = Counter()
            overall_label_distribution: Counter[str] = Counter()
            for split_quality in per_split.values():
                overall_rating_distribution.update(
                    cast(dict[str, int], split_quality["rating_distribution"])
                )
                overall_label_distribution.update(
                    cast(dict[str, int], split_quality["rating_label_distribution"])
                )
            rejection_counts: Counter[str] = Counter()
            for counter in invalid_counts.values():
                rejection_counts.update(counter)
            if overall_conflict_records:
                rejection_counts["fingerprint_conflict"] = overall_conflict_records

            quality_report: dict[str, object] = {
                "descriptive_all_splits": {
                    "input_records": overall_input,
                    "valid_records_before_deduplication": overall_valid,
                    "retained_unique_records": overall_retained,
                    "rejected_records": overall_invalid + overall_conflict_records,
                    "exact_duplicate_occurrences": overall_duplicate_occurrences,
                    "exact_duplicate_rows_skipped": overall_skipped_duplicates,
                    "fingerprint_conflict_groups": conflict_groups,
                    "fingerprint_conflict_records": overall_conflict_records,
                    "cross_split_duplicate_fingerprint_groups": (
                        cross_split_duplicate_groups
                    ),
                    "cross_split_fingerprint_conflict_groups": (
                        cross_split_fingerprint_conflicts
                    ),
                    "exact_duplicate_rate": {
                        "numerator": overall_duplicate_occurrences,
                        "denominator": overall_valid,
                        "fraction": (
                            str(
                                Decimal(overall_duplicate_occurrences)
                                / Decimal(overall_valid)
                            )
                            if overall_valid
                            else None
                        ),
                    },
                    "unique_users": overall_users,
                    "unique_items": overall_items,
                    "rating_distribution": dict(
                        sorted(overall_rating_distribution.items())
                    ),
                    "rating_label_distribution": dict(
                        sorted(overall_label_distribution.items())
                    ),
                    "timestamp_range_ms": (
                        {"min": all_bounds[0], "max": all_bounds[1]}
                        if all_bounds is not None and all_bounds[0] is not None
                        else None
                    ),
                    "timestamp_range_utc": (
                        {
                            "min": _utc_timestamp(int(all_bounds[0])),
                            "max": _utc_timestamp(int(all_bounds[1])),
                        }
                        if all_bounds is not None and all_bounds[0] is not None
                        else None
                    ),
                    "split_distribution": {
                        split: values["retained_unique_records"]
                        for split, values in per_split.items()
                    },
                    "rejection_counts_by_reason": dict(
                        sorted(rejection_counts.items())
                    ),
                    "per_split": per_split,
                    "cold_start_diagnostics": {
                        split.value: _cold_start_counts(index, split)
                        for split in (DataSplit.VALIDATION, DataSplit.TEST)
                    },
                },
                "training_only": {
                    "source_split": DataSplit.TRAIN.value,
                    "purpose": "descriptive counts; no fitted transform or ID map",
                    "statistics": per_split[DataSplit.TRAIN.value],
                },
            }
            configuration = {
                "duplicate_policy": (
                    "Collapse exact repeated fingerprints within each split; reject "
                    "all conflicting variants within that split; retain and report "
                    "cross-split payload conflicts without changing either split."
                ),
                "ordering": (
                    "event_time_ms, source_event_fingerprint, then canonical payload "
                    "signature; equal timestamps use this stable tie-break."
                ),
                "timestamp_policy": (
                    "Require non-negative integer Unix milliseconds representable as "
                    "UTC datetime; retain source value and normalized UTC timestamp."
                ),
                "rating_labels": label_config.as_record(),
                "unobserved_items": "unknown, never negative",
                "identifier_mapping": "deferred; no mapping is fit in this step",
            }

            outputs = [sinks[split].manifest_record() for split in _SPLITS]
            manifest: dict[str, object] = {
                "manifest_schema_version": "recfusion.interaction-manifest.v1",
                "derived_schema_version": DERIVED_SCHEMA_VERSION,
                "source": {"source_id": source_id, "source_version": source_version},
                "inputs": input_manifest,
                "configuration": configuration,
                "quality_report": quality_report,
                "outputs": outputs,
            }
            for split, path in files.items():
                checksum, size = sha256_file(path)
                expected = input_manifest[split.value]
                if checksum != expected["sha256"] or size != expected["size_bytes"]:
                    raise IngestionError(
                        f"{split.value} input changed during preprocessing."
                    )
            write_manifest(staging_dir / "manifest.json", manifest)
            for sink in sinks.values():
                sink.close()
            sinks.clear()
            index.close()
            index = None

        os.replace(staging_dir, final_output)
        return PreprocessingResult(final_output, manifest)
    except (OSError, sqlite3.Error, ValueError, TypeError) as error:
        raise IngestionError(f"Interaction preprocessing failed: {error}") from error
    finally:
        for sink in sinks.values():
            sink.close()
        if index is not None:
            index.close()
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
