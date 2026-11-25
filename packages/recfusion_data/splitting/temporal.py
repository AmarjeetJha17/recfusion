"""Temporal split validation, train-only vocabularies, and evaluation eligibility."""

from __future__ import annotations

import hashlib
import itertools
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
from enum import StrEnum
from pathlib import Path
from typing import cast

from recfusion_core.contracts import DataSplit
from recfusion_data.ingestion.errors import IngestionError, RecordValidationError
from recfusion_data.ingestion.manifest import sha256_file, write_manifest
from recfusion_data.ingestion.readers import SourceRow, read_jsonl
from recfusion_data.preprocessing.interactions import RatingLabel
from recfusion_data.validation import validate_interaction

SPLIT_POLICY_VERSION = "recfusion.temporal-split-policy.v1"
TEMPORAL_RECORD_SCHEMA = "recfusion.temporal-interaction.v1"
VOCABULARY_SCHEMA = "recfusion.train-vocabulary.v1"
CANDIDATE_POOL_SCHEMA = "recfusion.train-candidate-pool.v1"
EVALUATION_SCHEMA = "recfusion.evaluation-eligibility.v1"
MANIFEST_SCHEMA = "recfusion.temporal-split-manifest.v1"
UNKNOWN_INDEX = 0

_STEP_24_SCHEMA = "recfusion.interaction-preprocessing.v1"
_SPLITS = (DataSplit.TRAIN, DataSplit.VALIDATION, DataSplit.TEST)
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_RATING_LABELS = frozenset(label.value for label in RatingLabel)
_ALLOWED_INPUT_FIELDS = frozenset(
    {
        "schema_version",
        "user_key",
        "item_key",
        "event_time_ms",
        "event_time_utc",
        "source_timestamp_value",
        "source_timestamp_unit",
        "rating",
        "source_rating_value",
        "rating_label",
        "event_type",
        "event_type_present",
        "source_event_id",
        "source_event_id_present",
        "source_event_fingerprint",
        "split",
    }
)
_REQUIRED_INPUT_FIELDS = frozenset(
    {
        "schema_version",
        "user_key",
        "item_key",
        "event_time_ms",
        "event_time_utc",
        "source_timestamp_value",
        "source_timestamp_unit",
        "rating",
        "source_rating_value",
        "rating_label",
        "event_type",
        "event_type_present",
        "source_event_id",
        "source_event_id_present",
        "source_event_fingerprint",
    }
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_PROCESSED_ROOT = (_REPOSITORY_ROOT / "data" / "processed").resolve()


class SplitMode(StrEnum):
    TRUSTED_PRE_SPLIT = "trusted-pre-split"
    ABSOLUTE_CUTOFFS = "absolute-cutoffs"


@dataclass(frozen=True, slots=True)
class TemporalCutoffs:
    """Global half-open split boundaries, expressed as Unix milliseconds."""

    train_end_ms: int
    test_start_ms: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.train_end_ms, int)
            or not isinstance(self.test_start_ms, int)
            or isinstance(self.train_end_ms, bool)
            or isinstance(self.test_start_ms, bool)
            or self.train_end_ms < 0
            or self.test_start_ms < 0
            or self.train_end_ms >= self.test_start_ms
        ):
            raise ValueError("Cutoffs must satisfy 0 <= train_end < test_start.")

    def assign(self, event_time_ms: int) -> DataSplit:
        if event_time_ms < self.train_end_ms:
            return DataSplit.TRAIN
        if event_time_ms < self.test_start_ms:
            return DataSplit.VALIDATION
        return DataSplit.TEST

    def as_record(self) -> dict[str, object]:
        return {
            "train_end_utc": _utc_timestamp(self.train_end_ms),
            "train_end_ms_exclusive": self.train_end_ms,
            "test_start_utc": _utc_timestamp(self.test_start_ms),
            "test_start_ms_inclusive": self.test_start_ms,
            "intervals": {
                "train": "[0, train_end)",
                "validation": "[train_end, test_start)",
                "test": "[test_start, +infinity)",
            },
        }


@dataclass(frozen=True, slots=True)
class TemporalSplitResult:
    output_dir: Path
    manifest: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _PreparedRecord:
    split: DataSplit
    user_key: str
    item_key: str
    event_time_ms: int
    source_event_fingerprint: str
    rating_label: str
    signature: str
    payload: str
    boundary_mismatch: bool


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

    def manifest_record(self) -> dict[str, object]:
        self.file.flush()
        return {
            "file": self.path.name,
            "records": self.record_count,
            "size_bytes": self.path.stat().st_size,
            "sha256": self.digest.hexdigest(),
        }

    def close(self) -> None:
        self.file.close()


class _EventStore:
    """Disk-backed event and vocabulary indexes; never materializes a full split."""

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
                rating_label TEXT NOT NULL,
                payload TEXT NOT NULL,
                occurrences INTEGER NOT NULL DEFAULT 1,
                boundary_mismatch INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (split, fingerprint, signature)
            ) WITHOUT ROWID;
            CREATE INDEX events_fingerprint_idx ON events (fingerprint);
            CREATE INDEX events_split_time_idx ON events (split, event_time_ms);
            """
        )

    def add(self, event: _PreparedRecord) -> None:
        self.connection.execute(
            """
            INSERT INTO events (
                split, fingerprint, signature, event_time_ms, user_key, item_key,
                rating_label, payload, boundary_mismatch
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (split, fingerprint, signature)
            DO UPDATE SET occurrences = occurrences + 1
            """,
            (
                event.split.value,
                event.source_event_fingerprint,
                event.signature,
                event.event_time_ms,
                event.user_key,
                event.item_key,
                event.rating_label,
                event.payload,
                int(event.boundary_mismatch),
            ),
        )

    def finalize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE fingerprint_summary (
                fingerprint TEXT PRIMARY KEY,
                signature_count INTEGER NOT NULL,
                split_count INTEGER NOT NULL
            ) WITHOUT ROWID;
            INSERT INTO fingerprint_summary
            SELECT fingerprint, COUNT(DISTINCT signature), COUNT(DISTINCT split)
            FROM events
            GROUP BY fingerprint;

            CREATE TABLE fingerprint_conflicts (
                fingerprint TEXT PRIMARY KEY
            ) WITHOUT ROWID;
            INSERT INTO fingerprint_conflicts
            SELECT fingerprint
            FROM fingerprint_summary
            WHERE signature_count > 1;

            CREATE TABLE cross_split_duplicates (
                fingerprint TEXT PRIMARY KEY
            ) WITHOUT ROWID;
            INSERT INTO cross_split_duplicates
            SELECT fingerprint
            FROM fingerprint_summary
            WHERE signature_count = 1 AND split_count > 1;

            CREATE TABLE within_split_conflicts (
                split TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                PRIMARY KEY (split, fingerprint)
            ) WITHOUT ROWID;
            INSERT INTO within_split_conflicts
            SELECT split, fingerprint
            FROM events
            GROUP BY split, fingerprint
            HAVING COUNT(*) > 1;

            CREATE TABLE user_vocabulary (
                user_key TEXT PRIMARY KEY,
                vocabulary_index INTEGER NOT NULL UNIQUE
            ) WITHOUT ROWID;
            INSERT INTO user_vocabulary
            SELECT user_key,
                   ROW_NUMBER() OVER (ORDER BY user_key COLLATE BINARY)
            FROM (SELECT DISTINCT user_key FROM events WHERE split = 'train');

            CREATE TABLE item_vocabulary (
                item_key TEXT PRIMARY KEY,
                vocabulary_index INTEGER NOT NULL UNIQUE
            ) WITHOUT ROWID;
            INSERT INTO item_vocabulary
            SELECT item_key,
                   ROW_NUMBER() OVER (ORDER BY item_key COLLATE BINARY)
            FROM (SELECT DISTINCT item_key FROM events WHERE split = 'train');
            """
        )
        self.connection.commit()

    def scalar(self, query: str, params: tuple[object, ...] = ()) -> int:
        row = self.connection.execute(query, params).fetchone()
        return int(row[0]) if row is not None else 0

    def rows(
        self, query: str, params: tuple[object, ...] = ()
    ) -> Iterator[tuple[object, ...]]:
        yield from self.connection.execute(query, params)

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


def _utc_timestamp(event_time_ms: int) -> str:
    try:
        timestamp = _EPOCH + timedelta(milliseconds=event_time_ms)
    except OverflowError:
        raise ValueError("Timestamp is outside the UTC datetime range.") from None
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc_cutoff_ms(value: str) -> int:
    """Parse an explicit UTC ISO-8601 cutoff aligned to canonical milliseconds."""
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise ValueError("Cutoff must be an ISO-8601 UTC timestamp.") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("Cutoff must include an explicit UTC offset.")
    if parsed.microsecond % 1000:
        raise ValueError("Cutoff precision must not exceed milliseconds.")
    utc_value = parsed.astimezone(UTC)
    delta = utc_value - _EPOCH
    result = (
        delta.days * 86_400_000 + delta.seconds * 1_000 + delta.microseconds // 1_000
    )
    if result < 0:
        raise ValueError("Cutoff must be at or after the Unix epoch.")
    return result


def _parse_row(
    row: SourceRow,
    *,
    mode: SplitMode,
    source_split: DataSplit | None,
    cutoffs: TemporalCutoffs | None,
) -> _PreparedRecord:
    if row.error_code is not None or row.values is None:
        raise ValueError(row.error_code or "empty_record")
    values = dict(row.values)
    if set(values) - _ALLOWED_INPUT_FIELDS:
        raise ValueError("unsupported_field")
    if not _REQUIRED_INPUT_FIELDS.issubset(values):
        raise ValueError("missing_derived_field")
    if values.get("schema_version") != _STEP_24_SCHEMA:
        raise ValueError("schema_version_mismatch")
    for field in ("source_timestamp_value", "source_rating_value"):
        try:
            json.dumps(values[field], allow_nan=False)
        except (TypeError, ValueError):
            raise ValueError(f"invalid_{field}") from None
    fingerprint = values.get("source_event_fingerprint")
    if not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint):
        raise ValueError("invalid_source_event_fingerprint")

    if mode is SplitMode.TRUSTED_PRE_SPLIT:
        raw_split = values.get("split")
        if not isinstance(raw_split, str) or raw_split not in {
            split.value for split in _SPLITS
        }:
            raise ValueError("invalid_split_label")
        if source_split is None or raw_split != source_split.value:
            raise ValueError("split_file_mismatch")
        assigned_split = DataSplit(raw_split)
    else:
        if "split" in values:
            raw_split = values["split"]
            if not isinstance(raw_split, str) or raw_split not in {
                split.value for split in _SPLITS
            }:
                raise ValueError("invalid_split_label")
            raise ValueError("preassigned_split_in_unsplit_input")
        if cutoffs is None:
            raise ValueError("missing_cutoffs")
        assigned_split = DataSplit.TRAIN

    event_time_value = values.get("event_time_ms")
    if isinstance(event_time_value, bool) or not isinstance(event_time_value, int):
        raise ValueError("invalid_derived_timestamp_type")
    if not isinstance(values.get("rating"), str):
        raise ValueError("invalid_derived_rating_type")
    try:
        interaction = validate_interaction(values, assigned_split, fingerprint)
    except RecordValidationError as error:
        raise ValueError(error.issues[0].code) from None

    try:
        expected_utc = _utc_timestamp(interaction.event_time_ms)
    except ValueError:
        raise ValueError("impossible_timestamp") from None
    if values.get("event_time_utc") != expected_utc:
        raise ValueError("timestamp_provenance_mismatch")
    if values.get("source_timestamp_unit") != "unix_ms":
        raise ValueError("invalid_source_timestamp_unit")
    rating_label = values.get("rating_label")
    if not isinstance(rating_label, str) or rating_label not in _RATING_LABELS:
        raise ValueError("invalid_rating_label")
    for field in ("event_type_present", "source_event_id_present"):
        if not isinstance(values.get(field), bool):
            raise ValueError(f"invalid_{field}")
    for field, present_field in (
        ("event_type", "event_type_present"),
        ("source_event_id", "source_event_id_present"),
    ):
        value = values.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"invalid_{field}")
        if not values[present_field] and value is not None:
            raise ValueError(f"inconsistent_{field}_presence")

    boundary_mismatch = False
    if mode is SplitMode.ABSOLUTE_CUTOFFS:
        if cutoffs is None:
            raise ValueError("missing_cutoffs")
        assigned_split = cutoffs.assign(interaction.event_time_ms)
        values.pop("split", None)
    elif cutoffs is not None:
        boundary_mismatch = (
            cutoffs.assign(interaction.event_time_ms) is not assigned_split
        )

    signature_record = {key: value for key, value in values.items() if key != "split"}
    return _PreparedRecord(
        split=assigned_split,
        user_key=interaction.user_key,
        item_key=interaction.item_key,
        event_time_ms=interaction.event_time_ms,
        source_event_fingerprint=fingerprint,
        rating_label=rating_label,
        signature=_canonical_json(signature_record),
        payload=_canonical_json(values),
        boundary_mismatch=boundary_mismatch,
    )


def _validate_inputs(
    files: Mapping[str, Path],
    *,
    source_id: str,
    source_version: str,
    output_dir: Path,
) -> tuple[Path, dict[str, dict[str, object]]]:
    if not all(_SAFE_TOKEN.fullmatch(value) for value in (source_id, source_version)):
        raise IngestionError("Source identity and version must be safe ASCII tokens.")
    resolved_inputs: set[Path] = set()
    input_manifest: dict[str, dict[str, object]] = {}
    for role, path in files.items():
        resolved = path.resolve()
        if resolved in resolved_inputs:
            raise IngestionError("Each split/input source must be a distinct file.")
        resolved_inputs.add(resolved)
        if not path.is_file():
            raise IngestionError(f"Required {role} input is not a local file.")
        try:
            checksum, size = sha256_file(path)
        except ValueError as error:
            raise IngestionError(f"Cannot checksum {role} input.") from error
        input_manifest[role] = {
            "file": path.name,
            "size_bytes": size,
            "sha256": checksum,
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


def _chronology_violations(store: _EventStore) -> int:
    store.connection.execute(
        """
        CREATE TEMP TABLE chronology_affected (
            split TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            signature TEXT NOT NULL,
            occurrences INTEGER NOT NULL,
            PRIMARY KEY (split, fingerprint, signature)
        ) WITHOUT ROWID
        """
    )
    non_empty = [
        split
        for split in _SPLITS
        if store.scalar("SELECT COUNT(*) FROM events WHERE split = ?", (split.value,))
    ]
    for earlier, later in itertools.pairwise(non_empty):
        earlier_max = store.connection.execute(
            "SELECT MAX(event_time_ms) FROM events WHERE split = ?",
            (earlier.value,),
        ).fetchone()[0]
        later_min = store.connection.execute(
            "SELECT MIN(event_time_ms) FROM events WHERE split = ?",
            (later.value,),
        ).fetchone()[0]
        if (
            earlier_max is not None
            and later_min is not None
            and earlier_max >= later_min
        ):
            store.connection.execute(
                """
                INSERT OR IGNORE INTO chronology_affected
                SELECT split, fingerprint, signature, occurrences
                FROM events
                WHERE split = ? AND event_time_ms >= ?
                """,
                (earlier.value, later_min),
            )
            store.connection.execute(
                """
                INSERT OR IGNORE INTO chronology_affected
                SELECT split, fingerprint, signature, occurrences
                FROM events
                WHERE split = ? AND event_time_ms <= ?
                """,
                (later.value, earlier_max),
            )
    store.connection.commit()
    return store.scalar("SELECT COALESCE(SUM(occurrences), 0) FROM chronology_affected")


def _timestamp_range(
    store: _EventStore, split: DataSplit
) -> dict[str, int | str] | None:
    row = store.connection.execute(
        """
        SELECT MIN(event_time_ms), MAX(event_time_ms)
        FROM events
        WHERE split = ?
        """,
        (split.value,),
    ).fetchone()
    if row is None or row[0] is None or row[1] is None:
        return None
    minimum = int(row[0])
    maximum = int(row[1])
    return {
        "min_ms": minimum,
        "max_ms": maximum,
        "min_utc": _utc_timestamp(minimum),
        "max_utc": _utc_timestamp(maximum),
    }


def _integrity_counts(store: _EventStore) -> dict[str, int]:
    return {
        "fingerprint_conflict_groups": store.scalar(
            "SELECT COUNT(*) FROM fingerprint_conflicts"
        ),
        "fingerprint_conflict_records": store.scalar(
            """
            SELECT COALESCE(SUM(e.occurrences), 0)
            FROM events AS e
            JOIN fingerprint_conflicts AS f USING (fingerprint)
            """
        ),
        "exact_cross_split_duplicate_groups": store.scalar(
            "SELECT COUNT(*) FROM cross_split_duplicates"
        ),
        "exact_cross_split_duplicate_records": store.scalar(
            """
            SELECT COALESCE(SUM(e.occurrences), 0)
            FROM events AS e
            JOIN cross_split_duplicates AS d USING (fingerprint)
            """
        ),
        "within_split_conflict_groups": store.scalar(
            "SELECT COUNT(*) FROM within_split_conflicts"
        ),
        "within_split_conflict_records": store.scalar(
            """
            SELECT COALESCE(SUM(e.occurrences), 0)
            FROM events AS e
            JOIN within_split_conflicts AS c
              ON c.split = e.split AND c.fingerprint = e.fingerprint
            """
        ),
        "within_split_exact_duplicate_occurrences": store.scalar(
            "SELECT COALESCE(SUM(occurrences - 1), 0) FROM events"
        ),
        "boundary_mismatch_records": store.scalar(
            """
            SELECT COALESCE(SUM(occurrences), 0)
            FROM events
            WHERE boundary_mismatch = 1
            """
        ),
    }


def _write_vocabularies(store: _EventStore, staging_dir: Path) -> list[_JsonlSink]:
    user_sink = _JsonlSink(staging_dir / "vocabulary.users.jsonl")
    item_sink = _JsonlSink(staging_dir / "vocabulary.items.jsonl")
    for entity_type, sink, table, column in (
        ("user", user_sink, "user_vocabulary", "user_key"),
        ("item", item_sink, "item_vocabulary", "item_key"),
    ):
        sink.write(
            {
                "schema_version": VOCABULARY_SCHEMA,
                "entity_type": entity_type,
                "index": UNKNOWN_INDEX,
                "is_unknown": True,
            }
        )
        for identifier, vocabulary_index in store.rows(
            f"SELECT {column}, vocabulary_index FROM {table} ORDER BY vocabulary_index"
        ):
            sink.write(
                {
                    "schema_version": VOCABULARY_SCHEMA,
                    "entity_type": entity_type,
                    "index": vocabulary_index,
                    "is_unknown": False,
                    "source_key": identifier,
                }
            )
    return [user_sink, item_sink]


def _record_integrity_flags(
    *,
    occurrence_index: int,
    boundary_mismatch: bool,
    fingerprint_conflict: bool,
    cross_split_duplicate: bool,
    within_split_conflict: bool,
) -> list[str]:
    flags: list[str] = []
    if fingerprint_conflict:
        flags.append("conflicting_source_event_fingerprint")
    if cross_split_duplicate:
        flags.append("exact_cross_split_duplicate")
    if within_split_conflict:
        flags.append("within_split_fingerprint_conflict")
    if occurrence_index > 0:
        flags.append("repeated_exact_record_within_split")
    if boundary_mismatch:
        flags.append("temporal_boundary_mismatch")
    return flags


def _evaluation_eligibility(
    *,
    split: DataSplit,
    user_index: int,
    item_index: int,
    rating_label: str,
    integrity_flags: list[str],
    dataset_blocked: bool,
) -> dict[str, object]:
    user_warm = user_index != UNKNOWN_INDEX
    item_warm = item_index != UNKNOWN_INDEX
    if user_warm and item_warm:
        cohort = "warm_user_and_item"
    elif not user_warm and not item_warm:
        cohort = "both_user_and_item_cold"
    elif not user_warm:
        cohort = "cold_user"
    else:
        cohort = "cold_item"

    reasons = list(integrity_flags)
    if not user_warm:
        reasons.append("user_unseen_in_train")
    if not item_warm:
        reasons.append("item_unseen_in_train")
    is_positive = rating_label == RatingLabel.OBSERVED_POSITIVE.value
    if not is_positive:
        reasons.append("not_observed_positive")
    warm_positive = user_warm and item_warm and is_positive
    if dataset_blocked:
        reasons.append("dataset_integrity_blocked")
    eligible = warm_positive and not integrity_flags and not dataset_blocked
    return {
        "schema_version": EVALUATION_SCHEMA,
        "split": split.value,
        "cohort": cohort,
        "warm_positive_candidate": warm_positive,
        "warm_metric_eligible": eligible,
        "exclusion_reasons": reasons,
    }


def _write_split_records(
    store: _EventStore,
    *,
    mode: SplitMode,
    split: DataSplit,
    split_sink: _JsonlSink,
    evaluation_sink: _JsonlSink,
    dataset_blocked: bool,
    evaluation_counts: Counter[str],
    evaluation_reasons: Counter[str],
) -> None:
    cursor = store.connection.execute(
        """
        SELECT e.fingerprint, e.signature, e.event_time_ms, e.payload,
               e.occurrences, e.boundary_mismatch,
               u.vocabulary_index, i.vocabulary_index, e.rating_label,
               fc.fingerprint IS NOT NULL,
               cd.fingerprint IS NOT NULL,
               wc.fingerprint IS NOT NULL
        FROM events AS e
        LEFT JOIN user_vocabulary AS u ON u.user_key = e.user_key
        LEFT JOIN item_vocabulary AS i ON i.item_key = e.item_key
        LEFT JOIN fingerprint_conflicts AS fc USING (fingerprint)
        LEFT JOIN cross_split_duplicates AS cd USING (fingerprint)
        LEFT JOIN within_split_conflicts AS wc
          ON wc.split = e.split AND wc.fingerprint = e.fingerprint
        WHERE e.split = ?
        ORDER BY e.event_time_ms, e.fingerprint, e.signature
        """,
        (split.value,),
    )
    for (
        _fingerprint,
        _signature,
        _event_time_ms,
        payload,
        occurrences,
        boundary_mismatch,
        user_index_value,
        item_index_value,
        rating_label,
        fingerprint_conflict,
        cross_split_duplicate,
        within_split_conflict,
    ) in cursor:
        user_index = int(user_index_value or UNKNOWN_INDEX)
        item_index = int(item_index_value or UNKNOWN_INDEX)
        interaction = cast(dict[str, object], json.loads(payload))
        for occurrence_index in range(int(occurrences)):
            integrity_flags = _record_integrity_flags(
                occurrence_index=occurrence_index,
                boundary_mismatch=bool(boundary_mismatch),
                fingerprint_conflict=bool(fingerprint_conflict),
                cross_split_duplicate=bool(cross_split_duplicate),
                within_split_conflict=bool(within_split_conflict),
            )
            record: dict[str, object] = {
                "schema_version": TEMPORAL_RECORD_SCHEMA,
                "split_policy_version": SPLIT_POLICY_VERSION,
                "split": split.value,
                "split_origin": (
                    "trusted_pre_split"
                    if mode is SplitMode.TRUSTED_PRE_SPLIT
                    else "absolute_utc_cutoffs"
                ),
                "source_split": (
                    split.value if mode is SplitMode.TRUSTED_PRE_SPLIT else None
                ),
                "source_duplicate_ordinal": occurrence_index,
                "interaction": interaction,
                "user_index": user_index,
                "item_index": item_index,
                "integrity_flags": integrity_flags,
            }
            split_sink.write(record)
            if split is not DataSplit.TRAIN:
                eligibility = _evaluation_eligibility(
                    split=split,
                    user_index=user_index,
                    item_index=item_index,
                    rating_label=str(rating_label),
                    integrity_flags=integrity_flags,
                    dataset_blocked=dataset_blocked,
                )
                record["evaluation_eligibility"] = eligibility
                evaluation_sink.write(record)
                evaluation_counts[f"{split.value}.records"] += 1
                evaluation_counts[f"{split.value}.{eligibility['cohort']}"] += 1
                if eligibility["warm_positive_candidate"]:
                    evaluation_counts[f"{split.value}.warm_positive_candidates"] += 1
                if eligibility["warm_metric_eligible"]:
                    evaluation_counts["warm_metric_eligible_records"] += 1
                else:
                    evaluation_counts["excluded_heldout_records"] += 1
                for reason in cast(list[str], eligibility["exclusion_reasons"]):
                    evaluation_reasons[reason] += 1


def _process(
    *,
    mode: SplitMode,
    files: Mapping[str, tuple[Path, DataSplit | None]],
    output_dir: Path,
    source_id: str,
    source_version: str,
    cutoffs: TemporalCutoffs | None,
) -> TemporalSplitResult:
    if mode is SplitMode.ABSOLUTE_CUTOFFS and cutoffs is None:
        raise IngestionError("Absolute-cutoff mode requires both UTC cutoffs.")
    if (
        mode is SplitMode.TRUSTED_PRE_SPLIT
        and cutoffs is not None
        and cutoffs.train_end_ms >= cutoffs.test_start_ms
    ):
        raise IngestionError("Pre-split validation requires ordered cutoffs.")
    resolved_output, input_manifest = _validate_inputs(
        {role: path for role, (path, _) in files.items()},
        source_id=source_id,
        source_version=source_version,
        output_dir=output_dir,
    )
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{resolved_output.name}.tmp-", dir=resolved_output.parent
        )
    )
    invalid_by_reason: Counter[str] = Counter()
    invalid_by_input: dict[str, Counter[str]] = {role: Counter() for role in files}
    input_rows_by_role: Counter[str] = Counter()
    input_rows = 0
    valid_rows = 0
    sinks: list[_JsonlSink] = []
    store: _EventStore | None = None

    try:
        with tempfile.TemporaryDirectory(prefix="recfusion-temporal-split-") as scratch:
            store = _EventStore(Path(scratch) / "events.sqlite3")
            for role, (path, source_split) in files.items():
                for row in read_jsonl(path):
                    input_rows += 1
                    input_rows_by_role[role] += 1
                    try:
                        event = _parse_row(
                            row,
                            mode=mode,
                            source_split=source_split,
                            cutoffs=cutoffs,
                        )
                    except ValueError as error:
                        invalid_by_reason[str(error)] += 1
                        invalid_by_input[role][str(error)] += 1
                        continue
                    valid_rows += 1
                    store.add(event)
            store.finalize()

            empty_splits = {
                split.value: store.scalar(
                    "SELECT COUNT(*) FROM events WHERE split = ?", (split.value,)
                )
                == 0
                for split in _SPLITS
            }
            boundary_mismatches = store.scalar(
                """
                SELECT COALESCE(SUM(occurrences), 0)
                FROM events
                WHERE boundary_mismatch = 1
                """
            )
            chronology_violations = (
                _chronology_violations(store)
                if mode is SplitMode.TRUSTED_PRE_SPLIT and cutoffs is None
                else 0
            )
            integrity = _integrity_counts(store)
            blocking: Counter[str] = Counter(invalid_by_reason)
            if boundary_mismatches:
                blocking["temporal_boundary_mismatch"] += boundary_mismatches
            if chronology_violations:
                blocking["chronological_overlap"] += chronology_violations
            for reason, count_key in (
                (
                    "conflicting_source_event_fingerprint",
                    "fingerprint_conflict_records",
                ),
                (
                    "exact_cross_split_duplicate",
                    "exact_cross_split_duplicate_records",
                ),
                ("within_split_fingerprint_conflict", "within_split_conflict_records"),
            ):
                if integrity[count_key]:
                    blocking[reason] += integrity[count_key]
            if empty_splits[DataSplit.TRAIN.value]:
                blocking["empty_training_split"] += 1
            dataset_blocked = bool(blocking)

            warning_counts: Counter[str] = Counter()
            if integrity["within_split_exact_duplicate_occurrences"]:
                warning_counts["within_split_exact_duplicate_occurrences"] = integrity[
                    "within_split_exact_duplicate_occurrences"
                ]
            for split in (DataSplit.VALIDATION, DataSplit.TEST):
                if empty_splits[split.value]:
                    warning_counts[f"empty_{split.value}_split"] += 1

            user_count = store.scalar("SELECT COUNT(*) FROM user_vocabulary")
            item_count = store.scalar("SELECT COUNT(*) FROM item_vocabulary")
            if not item_count:
                warning_counts["empty_training_candidate_pool"] += 1

            split_sinks = {
                split: _JsonlSink(staging_dir / f"interactions.{split.value}.jsonl")
                for split in _SPLITS
            }
            sinks.extend(split_sinks.values())
            evaluation_sink = _JsonlSink(staging_dir / "evaluation.jsonl")
            sinks.append(evaluation_sink)
            vocabulary_sinks = _write_vocabularies(store, staging_dir)
            sinks.extend(vocabulary_sinks)
            candidate_sink = _JsonlSink(staging_dir / "candidate-pool.items.jsonl")
            sinks.append(candidate_sink)
            for item_key, vocabulary_index in store.rows(
                "SELECT item_key, vocabulary_index FROM item_vocabulary "
                "ORDER BY vocabulary_index"
            ):
                candidate_sink.write(
                    {
                        "schema_version": CANDIDATE_POOL_SCHEMA,
                        "item_index": vocabulary_index,
                        "item_key": item_key,
                        "eligibility_basis": "observed_in_training_split",
                    }
                )

            evaluation_counts: Counter[str] = Counter()
            evaluation_reasons: Counter[str] = Counter()
            for split in _SPLITS:
                _write_split_records(
                    store,
                    mode=mode,
                    split=split,
                    split_sink=split_sinks[split],
                    evaluation_sink=evaluation_sink,
                    dataset_blocked=dataset_blocked,
                    evaluation_counts=evaluation_counts,
                    evaluation_reasons=evaluation_reasons,
                )
            if not evaluation_counts["warm_metric_eligible_records"]:
                warning_counts["no_warm_positive_evaluation_targets"] += 1

            split_counts = {
                split.value: {
                    "input_accepted_records": store.scalar(
                        """
                        SELECT COALESCE(SUM(occurrences), 0)
                        FROM events WHERE split = ?
                        """,
                        (split.value,),
                    ),
                    "distinct_event_payloads": store.scalar(
                        "SELECT COUNT(*) FROM events WHERE split = ?", (split.value,)
                    ),
                    "unique_users": store.scalar(
                        "SELECT COUNT(DISTINCT user_key) FROM events WHERE split = ?",
                        (split.value,),
                    ),
                    "unique_items": store.scalar(
                        "SELECT COUNT(DISTINCT item_key) FROM events WHERE split = ?",
                        (split.value,),
                    ),
                    "rating_label_distribution": {
                        cast(str, label): cast(int, count)
                        for label, count in store.rows(
                            """
                            SELECT rating_label, SUM(occurrences)
                            FROM events
                            WHERE split = ?
                            GROUP BY rating_label
                            ORDER BY rating_label
                            """,
                            (split.value,),
                        )
                    },
                    "timestamp_range_ms": _timestamp_range(store, split),
                }
                for split in _SPLITS
            }
            for role, (path, _) in files.items():
                checksum, size = sha256_file(path)
                expected = input_manifest[role]
                if checksum != expected["sha256"] or size != expected["size_bytes"]:
                    raise IngestionError(
                        f"{role} input changed during split processing."
                    )

            output_sinks = [split_sinks[split] for split in _SPLITS] + [
                evaluation_sink,
                *vocabulary_sinks,
                candidate_sink,
            ]
            outputs = [sink.manifest_record() for sink in output_sinks]
            manifest: dict[str, object] = {
                "manifest_schema_version": MANIFEST_SCHEMA,
                "split_policy_version": SPLIT_POLICY_VERSION,
                "source": {"source_id": source_id, "source_version": source_version},
                "mode": mode.value,
                "inputs": input_manifest,
                "configuration": {
                    "input_record_schema": _STEP_24_SCHEMA,
                    "cutoffs": cutoffs.as_record() if cutoffs is not None else None,
                    "pre_split_policy": (
                        "preserve source split membership; never reassign rows"
                        if mode is SplitMode.TRUSTED_PRE_SPLIT
                        else None
                    ),
                    "unsplit_policy": (
                        "require split member to be absent; assign by absolute "
                        "UTC cutoffs"
                        if mode is SplitMode.ABSOLUTE_CUTOFFS
                        else None
                    ),
                    "vocabulary_order": "SQLite BINARY order of exact source keys",
                    "unknown_index": UNKNOWN_INDEX,
                    "candidate_policy": "unique item keys observed in train only",
                    "unobserved_items": "unknown; never treated as negatives",
                    "item_availability": (
                        "not established; catalog snapshots have no "
                        "effective-time proof"
                    ),
                },
                "counts": {
                    "input_records": input_rows,
                    "input_records_by_file": dict(sorted(input_rows_by_role.items())),
                    "valid_input_records": valid_rows,
                    "rejected_records": sum(invalid_by_reason.values()),
                    "rejected_by_reason": dict(sorted(invalid_by_reason.items())),
                    "rejected_by_input": {
                        role: dict(sorted(reasons.items()))
                        for role, reasons in sorted(invalid_by_input.items())
                    },
                    "split_counts": split_counts,
                    "empty_splits": empty_splits,
                    "train_vocabulary": {
                        "users": user_count,
                        "items": item_count,
                        "unknown_index": UNKNOWN_INDEX,
                        "fit_split": DataSplit.TRAIN.value,
                    },
                    "candidate_pool": {
                        "items": item_count,
                        "source_split": DataSplit.TRAIN.value,
                        "uses_validation_or_test": False,
                    },
                    "integrity": integrity,
                    "evaluation": {
                        "records": evaluation_sink.record_count,
                        "counts": dict(sorted(evaluation_counts.items())),
                        "exclusion_reason_counts": dict(
                            sorted(evaluation_reasons.items())
                        ),
                        "warm_metric_status": (
                            "blocked" if dataset_blocked else "eligible"
                        ),
                    },
                },
                "integrity_status": {
                    "evaluation_eligible": not dataset_blocked,
                    "blocking_violations": dict(sorted(blocking.items())),
                    "report_only_warnings": dict(sorted(warning_counts.items())),
                    "chronological_overlap_records": chronology_violations,
                    "source_split_membership_changed": 0,
                },
                "outputs": outputs,
            }
            write_manifest(staging_dir / "manifest.json", manifest)
            for sink in sinks:
                sink.close()
            sinks.clear()
            store.close()
            store = None

        os.replace(staging_dir, resolved_output)
        return TemporalSplitResult(resolved_output, manifest)
    except (OSError, sqlite3.Error, ValueError, TypeError) as error:
        raise IngestionError(f"Temporal split processing failed: {error}") from error
    finally:
        for sink in sinks:
            sink.close()
        if store is not None:
            store.close()
        if staging_dir.exists():
            shutil.rmtree(staging_dir)


def process_trusted_pre_split(
    *,
    train_path: Path,
    validation_path: Path,
    test_path: Path,
    output_dir: Path,
    source_id: str,
    source_version: str,
    cutoffs: TemporalCutoffs | None = None,
) -> TemporalSplitResult:
    """Validate a trusted split, preserving every valid row's original membership."""
    files = {
        split.value: (path, split)
        for split, path in (
            (DataSplit.TRAIN, train_path),
            (DataSplit.VALIDATION, validation_path),
            (DataSplit.TEST, test_path),
        )
    }
    return _process(
        mode=SplitMode.TRUSTED_PRE_SPLIT,
        files=files,
        output_dir=output_dir,
        source_id=source_id,
        source_version=source_version,
        cutoffs=cutoffs,
    )


def process_unsplit_with_cutoffs(
    *,
    input_path: Path,
    output_dir: Path,
    source_id: str,
    source_version: str,
    cutoffs: TemporalCutoffs,
) -> TemporalSplitResult:
    """Assign an explicitly unpartitioned Step 2.4 projection by UTC cutoffs."""
    return _process(
        mode=SplitMode.ABSOLUTE_CUTOFFS,
        files={"unsplit": (input_path, None)},
        output_dir=output_dir,
        source_id=source_id,
        source_version=source_version,
        cutoffs=cutoffs,
    )
