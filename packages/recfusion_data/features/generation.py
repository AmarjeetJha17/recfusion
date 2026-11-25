"""Deterministic feature generation over Step 2.5 temporal artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol, cast

from recfusion_core.contracts import DataSplit
from recfusion_data.ingestion.errors import IngestionError
from recfusion_data.ingestion.manifest import sha256_file, write_manifest
from recfusion_data.ingestion.readers import SourceRow, read_jsonl
from recfusion_data.normalization import NormalizationStatus

FEATURE_SCHEMA_VERSION = "recfusion.feature-schema.v1"
FEATURE_INTERACTION_SCHEMA = "recfusion.feature-interaction.v1"
FEATURE_ITEM_SCHEMA = "recfusion.item-feature.v1"
TRANSFORMERS_SCHEMA_VERSION = "recfusion.feature-transformers.v1"
FEATURE_MANIFEST_SCHEMA = "recfusion.feature-generation-manifest.v1"
_TEMPORAL_MANIFEST_SCHEMA = "recfusion.temporal-split-manifest.v1"
_TEMPORAL_RECORD_SCHEMA = "recfusion.temporal-interaction.v1"
_VOCABULARY_SCHEMA = "recfusion.train-vocabulary.v1"
_CANDIDATE_SCHEMA = "recfusion.train-candidate-pool.v1"
_PRODUCT_NORMALIZATION_SCHEMA = "recfusion.product-normalization.v1"
_UNKNOWN_INDEX = 0
_SPLITS = (DataSplit.TRAIN, DataSplit.VALIDATION, DataSplit.TEST)
_CATEGORICAL_FIELDS = (
    "brand",
    "category",
    "storage_type",
    "processor_name",
    "gpu_name",
)
_NUMERIC_FIELDS = (
    "ram_capacity_bytes",
    "storage_capacity_bytes",
    "display_size_mm",
    "weight_g",
    "battery_charge_mah",
    "battery_energy_wh",
)
_SPECIFICATION_FIELDS = (
    "ram_capacity_bytes",
    "storage_capacity_bytes",
    "storage_type",
    "display_size_mm",
    "weight_g",
    "battery_capacity",
    "processor_name",
    "gpu_name",
)
_SPECS_FOR_NUMERIC = {
    "ram_capacity_bytes": ("ram_capacity_bytes", "B"),
    "storage_capacity_bytes": ("storage_capacity_bytes", "B"),
    "display_size_mm": ("display_size_mm", "mm"),
    "weight_g": ("weight_g", "g"),
}
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_PROCESSED_ROOT = (_REPOSITORY_ROOT / "data" / "processed").resolve()
_TEMPORAL_FILES = (
    "interactions.train.jsonl",
    "interactions.validation.jsonl",
    "interactions.test.jsonl",
    "evaluation.jsonl",
    "vocabulary.users.jsonl",
    "vocabulary.items.jsonl",
    "candidate-pool.items.jsonl",
)
_FEATURE_CONFIG: dict[str, object] = {
    "history_source": "eligible training interactions only",
    "history_time_rule": "event_time_ms strictly less than target timestamp",
    "equal_timestamp_rule": "all simultaneous events are excluded from one another",
    "validation_test_history": "training interactions only",
    "training_history_exclusions": ["repeated_exact_record_within_split"],
    "item_catalog": "Step 2.5 training candidate pool only",
    "item_metadata_fit_scope": "unique, non-conflicting training-catalog records",
    "item_metadata_temporal_scope": "source snapshot; effective time unknown",
    "categorical_unknown_index": _UNKNOWN_INDEX,
    "numeric_transform": "population z-score fitted per feature on training items",
    "zero_variance_scale": "1; observed values transform to 0",
    "missing_numeric_values": "null with explicit status; never imputed",
    "battery_units": {
        "battery_charge_mah": "mAh only",
        "battery_energy_wh": "Wh only",
        "conversion_between_them": "not performed; voltage is unknown",
    },
    "price_and_rating_aggregates": "excluded from feature generation",
    "unobserved_items": "unknown; never treated as negative",
}
_ALLOWED_TRAIN_FLAGS = frozenset({"repeated_exact_record_within_split"})
_ALLOWED_NORMALIZATION_STATUSES = frozenset(
    status.value for status in NormalizationStatus
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class FeatureGenerationResult:
    """Published feature artifacts and their aggregate manifest."""

    output_dir: Path
    manifest: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class CategoryEncoding:
    """Encoded category with independent missing and unknown states."""

    index: int
    missing: bool
    unknown: bool
    unavailable: bool


@dataclass(frozen=True, slots=True)
class _InputBundle:
    temporal_dir: Path
    product_dir: Path
    temporal_manifest: dict[str, object]
    product_manifest: dict[str, object]
    checksums: dict[str, dict[str, object]]


class _SqliteAggregate(Protocol):
    def step(self, *values: Any) -> Any: ...

    def finalize(self) -> Any: ...


class _JsonlSink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.file = path.open("w", encoding="utf-8", newline="\n")
        self.digest = hashlib.sha256()
        self.records = 0

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
        self.records += 1

    def close(self) -> None:
        self.file.close()

    def output_record(self) -> dict[str, object]:
        self.file.flush()
        return {
            "file": self.path.name,
            "records": self.records,
            "size_bytes": self.path.stat().st_size,
            "sha256": self.digest.hexdigest(),
        }


class _FeatureStore:
    """Disk-backed feature spool and train-only as-of aggregate indexes."""

    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=OFF")
        self.connection.execute("PRAGMA synchronous=OFF")
        self.connection.execute("PRAGMA temp_store=FILE")
        self.connection.execute("PRAGMA cache_size=-8192")
        self.connection.create_aggregate("DECIMAL_SUM", 1, _new_decimal_sum)
        self.connection.create_function("DECIMAL_ADD", 2, _decimal_add)
        self.connection.executescript(
            """
            CREATE TABLE user_vocab (
                source_key TEXT PRIMARY KEY,
                vocabulary_index INTEGER NOT NULL UNIQUE
            ) WITHOUT ROWID;
            CREATE TABLE item_vocab (
                source_key TEXT PRIMARY KEY,
                vocabulary_index INTEGER NOT NULL UNIQUE
            ) WITHOUT ROWID;
            CREATE TABLE training_items (
                source_key TEXT PRIMARY KEY,
                item_index INTEGER NOT NULL UNIQUE
            ) WITHOUT ROWID;
            CREATE TABLE events (
                split TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                signature TEXT NOT NULL,
                duplicate_ordinal INTEGER NOT NULL,
                user_key TEXT NOT NULL,
                item_key TEXT NOT NULL,
                user_index INTEGER NOT NULL,
                item_index INTEGER NOT NULL,
                event_time_ms INTEGER NOT NULL,
                rating TEXT NOT NULL,
                rating_label TEXT NOT NULL,
                interaction_json TEXT NOT NULL,
                source_split TEXT,
                integrity_flags_json TEXT NOT NULL,
                evaluation_json TEXT,
                train_eligible INTEGER NOT NULL,
                PRIMARY KEY (
                    split, fingerprint, signature, duplicate_ordinal
                )
            ) WITHOUT ROWID;
            CREATE INDEX events_time_idx
                ON events (event_time_ms, split, fingerprint, signature);
            CREATE INDEX events_user_time_idx
                ON events (user_key, event_time_ms, split, train_eligible);
            CREATE INDEX events_item_time_idx
                ON events (item_key, event_time_ms, split, train_eligible);
            CREATE TABLE user_history (
                user_key TEXT PRIMARY KEY,
                event_count INTEGER NOT NULL,
                rating_sum TEXT NOT NULL
            ) WITHOUT ROWID;
            CREATE TABLE item_history (
                item_key TEXT PRIMARY KEY,
                event_count INTEGER NOT NULL,
                rating_sum TEXT NOT NULL
            ) WITHOUT ROWID;
            CREATE TABLE product_records (
                item_key TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                signature TEXT NOT NULL,
                decision TEXT NOT NULL,
                payload TEXT NOT NULL,
                occurrences INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (item_key, fingerprint, signature)
            ) WITHOUT ROWID;
            CREATE INDEX product_records_item_idx ON product_records (item_key);
            CREATE TABLE product_fields (
                item_key TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                signature TEXT NOT NULL,
                field_name TEXT NOT NULL,
                status TEXT NOT NULL,
                value_json TEXT,
                unit TEXT,
                source_keys_json TEXT NOT NULL,
                raw_values_json TEXT NOT NULL,
                PRIMARY KEY (item_key, fingerprint, signature, field_name)
            ) WITHOUT ROWID;
            CREATE TABLE category_vocab (
                field_name TEXT NOT NULL,
                category_value TEXT NOT NULL COLLATE BINARY,
                category_index INTEGER NOT NULL,
                PRIMARY KEY (field_name, category_value)
            ) WITHOUT ROWID;
            CREATE TABLE numeric_stats (
                field_name TEXT PRIMARY KEY,
                observation_count INTEGER NOT NULL,
                mean TEXT,
                scale TEXT
            ) WITHOUT ROWID;
            """
        )

    def close(self) -> None:
        self.connection.commit()
        self.connection.close()


class _DecimalSum:
    def __init__(self) -> None:
        self.total = Decimal(0)

    def step(self, *values: object) -> None:
        if len(values) != 1 or values[0] is None:
            return
        self.total += Decimal(str(values[0]))

    def finalize(self) -> str:
        return _format_decimal(self.total)


def _new_decimal_sum() -> _SqliteAggregate:
    return _DecimalSum()


def _decimal_add(left: str, right: str) -> str:
    return _format_decimal(Decimal(left) + Decimal(right))


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _format_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise IngestionError("A non-finite decimal reached feature generation.")
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def encode_categorical_value(
    value: object,
    status: str,
    vocabulary: Mapping[str, int],
) -> CategoryEncoding:
    """Encode a normalized category without conflating missing and unseen values."""
    if status == NormalizationStatus.MISSING.value:
        return CategoryEncoding(_UNKNOWN_INDEX, True, False, False)
    if status != NormalizationStatus.NORMALIZED.value:
        return CategoryEncoding(_UNKNOWN_INDEX, False, False, True)
    if not isinstance(value, str) or not value:
        return CategoryEncoding(_UNKNOWN_INDEX, False, True, False)
    category_index = vocabulary.get(value)
    if category_index is None:
        return CategoryEncoding(_UNKNOWN_INDEX, False, True, False)
    return CategoryEncoding(category_index, False, False, False)


def _read_manifest(path: Path, expected_schema: str | int) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IngestionError(f"Cannot read input manifest {path.name}.") from error
    if not isinstance(value, dict):
        raise IngestionError(f"Input manifest {path.name} must be a JSON object.")
    if value.get("manifest_schema_version") != expected_schema:
        raise IngestionError(f"Unsupported input manifest schema in {path.name}.")
    return cast(dict[str, object], value)


def _manifest_outputs(
    directory: Path, manifest: Mapping[str, object], expected_files: Sequence[str]
) -> dict[str, dict[str, object]]:
    raw_outputs = manifest.get("outputs")
    if not isinstance(raw_outputs, list):
        raise IngestionError(f"{directory.name} manifest has no output list.")
    outputs: dict[str, dict[str, object]] = {}
    for raw in raw_outputs:
        if not isinstance(raw, dict):
            raise IngestionError(f"{directory.name} manifest has a malformed output.")
        name = raw.get("file")
        checksum = raw.get("sha256")
        if not isinstance(name, str) or not isinstance(checksum, str):
            raise IngestionError(f"{directory.name} manifest has an invalid output.")
        if (
            Path(name).name != name
            or "/" in name
            or "\\" in name
            or name in {".", ".."}
        ):
            raise IngestionError(
                f"{directory.name} manifest has an unsafe output name."
            )
        if name in outputs:
            raise IngestionError(f"{directory.name} manifest repeats output {name}.")
        path = directory / name
        try:
            actual_checksum, actual_size = sha256_file(path)
        except ValueError as error:
            raise IngestionError(f"Cannot verify {directory.name}/{name}.") from error
        if actual_checksum != checksum:
            raise IngestionError(f"Checksum mismatch for {directory.name}/{name}.")
        expected_size = raw.get("size_bytes")
        if (
            isinstance(expected_size, int)
            and not isinstance(expected_size, bool)
            and expected_size != actual_size
        ):
            raise IngestionError(f"Size mismatch for {directory.name}/{name}.")
        outputs[name] = dict(raw)
    missing = sorted(set(expected_files) - set(outputs))
    if missing:
        raise IngestionError(
            f"{directory.name} manifest is missing required output {missing[0]}."
        )
    return outputs


def _load_inputs(temporal_dir: Path, product_dir: Path) -> _InputBundle:
    temporal_manifest_path = temporal_dir / "manifest.json"
    product_manifest_path = product_dir / "manifest.json"
    temporal_manifest = _read_manifest(
        temporal_manifest_path, _TEMPORAL_MANIFEST_SCHEMA
    )
    product_manifest = _read_manifest(product_manifest_path, 1)
    if (
        temporal_manifest.get("split_policy_version")
        != "recfusion.temporal-split-policy.v1"
    ):
        raise IngestionError("Unsupported temporal split policy version.")
    integrity = temporal_manifest.get("integrity_status")
    if (
        not isinstance(integrity, dict)
        or integrity.get("evaluation_eligible") is not True
    ):
        raise IngestionError("Temporal input has blocking integrity violations.")
    temporal_outputs = _manifest_outputs(
        temporal_dir, temporal_manifest, _TEMPORAL_FILES
    )

    configuration = product_manifest.get("configuration")
    if not isinstance(configuration, dict):
        raise IngestionError("Product ingestion manifest has no configuration.")
    if configuration.get("normalize_products") is not True:
        raise IngestionError("Product input must include normalized metadata.")
    if (
        configuration.get("product_normalization_schema_version")
        != _PRODUCT_NORMALIZATION_SCHEMA
    ):
        raise IngestionError("Unsupported product-normalization schema version.")
    _manifest_outputs(product_dir, product_manifest, ("products.normalized.jsonl",))

    temporal_manifest_hash, temporal_manifest_size = sha256_file(temporal_manifest_path)
    product_manifest_hash, product_manifest_size = sha256_file(product_manifest_path)
    checksums: dict[str, dict[str, object]] = {
        "temporal_manifest.json": {
            "sha256": temporal_manifest_hash,
            "size_bytes": temporal_manifest_size,
        },
        "product_ingestion_manifest.json": {
            "sha256": product_manifest_hash,
            "size_bytes": product_manifest_size,
        },
    }
    for name in sorted(_TEMPORAL_FILES):
        output = temporal_outputs[name]
        checksums[f"temporal/{name}"] = {
            "sha256": output["sha256"],
            "size_bytes": output.get("size_bytes"),
        }
    product_output = product_dir / "products.normalized.jsonl"
    product_hash, product_size = sha256_file(product_output)
    checksums["products.normalized.jsonl"] = {
        "sha256": product_hash,
        "size_bytes": product_size,
    }
    return _InputBundle(
        temporal_dir,
        product_dir,
        temporal_manifest,
        product_manifest,
        checksums,
    )


def _expected_vocab_index(store: _FeatureStore, entity: str, key: str) -> int:
    table = "user_vocab" if entity == "user" else "item_vocab"
    row = store.connection.execute(
        f"SELECT vocabulary_index FROM {table} WHERE source_key = ?", (key,)
    ).fetchone()
    return _UNKNOWN_INDEX if row is None else int(row[0])


def _load_vocabulary(
    store: _FeatureStore,
    path: Path,
    *,
    entity: str,
    table: str,
) -> None:
    expected_index = _UNKNOWN_INDEX
    previous_key: str | None = None
    saw_unknown = False
    for row in read_jsonl(path):
        record = _record_values(row, "vocabulary")
        if (
            record.get("schema_version") != _VOCABULARY_SCHEMA
            or record.get("entity_type") != entity
        ):
            raise IngestionError(f"Invalid {entity} vocabulary contract.")
        index = record.get("index")
        is_unknown = record.get("is_unknown")
        if isinstance(index, bool) or not isinstance(index, int):
            raise IngestionError(f"Invalid index in {entity} vocabulary.")
        if not isinstance(is_unknown, bool):
            raise IngestionError(f"Invalid unknown marker in {entity} vocabulary.")
        if is_unknown:
            if saw_unknown or index != _UNKNOWN_INDEX or "source_key" in record:
                raise IngestionError(f"Invalid unknown entry in {entity} vocabulary.")
            saw_unknown = True
            continue
        key = record.get("source_key")
        if not saw_unknown or not isinstance(key, str) or not key:
            raise IngestionError(f"Invalid source key in {entity} vocabulary.")
        if index != expected_index + 1:
            raise IngestionError(f"Non-contiguous {entity} vocabulary indices.")
        if previous_key is not None and key <= previous_key:
            raise IngestionError(f"Unsorted {entity} vocabulary keys.")
        store.connection.execute(
            f"INSERT INTO {table} (source_key, vocabulary_index) VALUES (?, ?)",
            (key, index),
        )
        expected_index = index
        previous_key = key
    if not saw_unknown:
        raise IngestionError(f"{entity} vocabulary has no reserved unknown entry.")


def _load_candidate_pool(store: _FeatureStore, path: Path) -> None:
    for row in read_jsonl(path):
        record = _record_values(row, "candidate pool")
        if record.get("schema_version") != _CANDIDATE_SCHEMA:
            raise IngestionError("Invalid training candidate-pool contract.")
        key = record.get("item_key")
        index = record.get("item_index")
        if (
            not isinstance(key, str)
            or isinstance(index, bool)
            or not isinstance(index, int)
        ):
            raise IngestionError("Malformed training candidate-pool row.")
        if (
            _expected_vocab_index(store, "item", key) != index
            or index == _UNKNOWN_INDEX
        ):
            raise IngestionError("Candidate pool disagrees with training vocabulary.")
        store.connection.execute(
            "INSERT INTO training_items (source_key, item_index) VALUES (?, ?)",
            (key, index),
        )
    missing = store.connection.execute(
        """
        SELECT COUNT(*) FROM item_vocab AS v
        LEFT JOIN training_items AS t ON t.source_key = v.source_key
        WHERE t.source_key IS NULL
        """
    ).fetchone()
    if missing is None or int(missing[0]) != 0:
        raise IngestionError(
            "Training candidate pool does not cover the item vocabulary."
        )


def _record_values(row: SourceRow, label: str) -> dict[str, object]:
    if row.error_code is not None or row.values is None:
        raise IngestionError(
            f"Malformed {label} JSONL row: {row.error_code or 'empty'}."
        )
    return dict(row.values)


def _load_temporal_events(store: _FeatureStore, bundle: _InputBundle) -> Counter[str]:
    split_counts: Counter[str] = Counter()
    for split in _SPLITS:
        path = bundle.temporal_dir / f"interactions.{split.value}.jsonl"
        for row in read_jsonl(path):
            record = _record_values(row, f"{split.value} temporal interaction")
            interaction = record.get("interaction")
            if (
                record.get("schema_version") != _TEMPORAL_RECORD_SCHEMA
                or not isinstance(interaction, dict)
                or record.get("split") != split.value
            ):
                raise IngestionError(f"Invalid {split.value} temporal interaction.")
            user_key = interaction.get("user_key")
            item_key = interaction.get("item_key")
            fingerprint = interaction.get("source_event_fingerprint")
            timestamp = interaction.get("event_time_ms")
            rating = interaction.get("rating")
            rating_label = interaction.get("rating_label")
            duplicate_ordinal = record.get("source_duplicate_ordinal")
            flags = record.get("integrity_flags")
            if (
                not isinstance(user_key, str)
                or not user_key
                or not isinstance(item_key, str)
                or not item_key
                or not isinstance(fingerprint, str)
                or not _SHA256.fullmatch(fingerprint)
                or isinstance(timestamp, bool)
                or not isinstance(timestamp, int)
                or timestamp < 0
                or not isinstance(rating, str)
                or not isinstance(rating_label, str)
                or interaction.get("split") != split.value
                or interaction.get("source_timestamp_unit") != "unix_ms"
                or not isinstance(interaction.get("event_time_utc"), str)
                or "source_timestamp_value" not in interaction
                or "source_rating_value" not in interaction
                or not isinstance(interaction.get("event_type_present"), bool)
                or not isinstance(interaction.get("source_event_id_present"), bool)
                or isinstance(duplicate_ordinal, bool)
                or not isinstance(duplicate_ordinal, int)
                or duplicate_ordinal < 0
                or not isinstance(flags, list)
                or any(not isinstance(flag, str) for flag in flags)
            ):
                raise IngestionError(f"Malformed {split.value} interaction fields.")
            try:
                rating_value = Decimal(rating)
            except InvalidOperation:
                raise IngestionError(
                    "Temporal interaction rating is not decimal."
                ) from None
            if not rating_value.is_finite() or not Decimal(
                1
            ) <= rating_value <= Decimal(5):
                raise IngestionError("Temporal interaction rating is outside [1, 5].")
            if rating_label not in {
                "observed_positive_signal",
                "observed_low_rating",
                "neutral",
                "unclassified",
            }:
                raise IngestionError(
                    "Temporal interaction has an invalid feedback label."
                )
            for name, present_name in (
                ("event_type", "event_type_present"),
                ("source_event_id", "source_event_id_present"),
            ):
                value = interaction.get(name)
                if value is not None and not isinstance(value, str):
                    raise IngestionError(f"Temporal interaction has invalid {name}.")
                if not interaction[present_name] and value is not None:
                    raise IngestionError(
                        f"Temporal interaction has inconsistent {name} presence."
                    )
            if any(flag not in _ALLOWED_TRAIN_FLAGS for flag in flags):
                raise IngestionError(
                    "Temporal interaction contains a blocking integrity flag."
                )
            if (duplicate_ordinal > 0) != (
                "repeated_exact_record_within_split" in flags
            ):
                raise IngestionError("Temporal duplicate ordinal and flags disagree.")
            expected_user_index = _expected_vocab_index(store, "user", user_key)
            expected_item_index = _expected_vocab_index(store, "item", item_key)
            user_index = record.get("user_index")
            item_index = record.get("item_index")
            if (
                isinstance(user_index, bool)
                or not isinstance(user_index, int)
                or isinstance(item_index, bool)
                or not isinstance(item_index, int)
            ):
                raise IngestionError("Temporal record indices must be integers.")
            if user_index != expected_user_index or item_index != expected_item_index:
                raise IngestionError(
                    "Temporal record ID indices disagree with vocabularies."
                )
            source_split = record.get("source_split")
            if source_split not in (split.value, None):
                raise IngestionError("Temporal source split is inconsistent.")
            evaluation = record.get("evaluation_eligibility")
            if split is DataSplit.TRAIN:
                if evaluation is not None:
                    raise IngestionError(
                        "Training row must not have evaluation eligibility."
                    )
                evaluation_json = None
            else:
                evaluation_json = None
            signature = _canonical_json(interaction)
            train_eligible = split is DataSplit.TRAIN and not flags
            store.connection.execute(
                """
                INSERT INTO events (
                    split, fingerprint, signature, duplicate_ordinal,
                    user_key, item_key, user_index, item_index, event_time_ms,
                    rating, rating_label, interaction_json, source_split,
                    integrity_flags_json, evaluation_json, train_eligible
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    split.value,
                    fingerprint,
                    signature,
                    duplicate_ordinal,
                    user_key,
                    item_key,
                    user_index,
                    item_index,
                    timestamp,
                    _format_decimal(rating_value),
                    rating_label,
                    _canonical_json(interaction),
                    source_split,
                    _canonical_json(flags),
                    evaluation_json,
                    int(train_eligible),
                ),
            )
            split_counts[split.value] += 1
    return split_counts


def _load_evaluation_records(store: _FeatureStore, path: Path) -> None:
    record_count = 0
    for row in read_jsonl(path):
        record = _record_values(row, "evaluation eligibility")
        interaction = record.get("interaction")
        split = record.get("split")
        ordinal = record.get("source_duplicate_ordinal")
        evaluation = record.get("evaluation_eligibility")
        fingerprint = (
            interaction.get("source_event_fingerprint")
            if isinstance(interaction, dict)
            else None
        )
        if (
            not isinstance(interaction, dict)
            or split not in {DataSplit.VALIDATION.value, DataSplit.TEST.value}
            or isinstance(ordinal, bool)
            or not isinstance(ordinal, int)
            or not isinstance(fingerprint, str)
            or not isinstance(evaluation, dict)
            or evaluation.get("schema_version") != "recfusion.evaluation-eligibility.v1"
            or evaluation.get("split") != split
            or not isinstance(evaluation.get("cohort"), str)
            or not isinstance(evaluation.get("warm_metric_eligible"), bool)
            or not isinstance(evaluation.get("exclusion_reasons"), list)
        ):
            raise IngestionError("Malformed evaluation eligibility record.")
        signature = _canonical_json(interaction)
        cursor = store.connection.execute(
            """
            UPDATE events SET evaluation_json = ?
            WHERE split = ? AND fingerprint = ? AND signature = ?
              AND duplicate_ordinal = ?
            """,
            (_canonical_json(evaluation), split, fingerprint, signature, ordinal),
        )
        if cursor.rowcount != 1:
            raise IngestionError(
                "Evaluation record does not match exactly one held-out interaction."
            )
        record_count += 1
    heldout_count = int(
        store.connection.execute(
            """
            SELECT COUNT(*) FROM events
            WHERE split != 'train' AND evaluation_json IS NOT NULL
            """
        ).fetchone()[0]
    )
    expected_count = int(
        store.connection.execute(
            "SELECT COUNT(*) FROM events WHERE split != 'train'"
        ).fetchone()[0]
    )
    if record_count != expected_count or heldout_count != expected_count:
        raise IngestionError("Evaluation artifact does not preserve all held-out rows.")


def _normalization_field(
    normalization: Mapping[str, object], field_name: str
) -> dict[str, object]:
    if field_name in ("brand", "category"):
        raw_field = normalization.get(field_name)
    else:
        raw_specifications = normalization.get("specifications")
        if not isinstance(raw_specifications, dict):
            raise IngestionError("Normalized product has malformed specifications.")
        raw_field = raw_specifications.get(field_name)
    if not isinstance(raw_field, dict):
        raise IngestionError(f"Normalized product is missing field {field_name}.")
    status = raw_field.get("status")
    value = raw_field.get("value")
    unit = raw_field.get("unit")
    source_keys = raw_field.get("source_keys")
    raw_values = raw_field.get("raw_values")
    if (
        not isinstance(status, str)
        or status not in _ALLOWED_NORMALIZATION_STATUSES
        or (unit is not None and not isinstance(unit, str))
        or not isinstance(source_keys, list)
        or any(not isinstance(key, str) for key in source_keys)
        or not isinstance(raw_values, list)
    ):
        raise IngestionError(f"Malformed normalized field {field_name}.")
    if status == NormalizationStatus.NORMALIZED.value and value is None:
        raise IngestionError(f"Normalized field {field_name} has no value.")
    try:
        json.dumps(value, allow_nan=False)
        json.dumps(raw_values, allow_nan=False)
    except (TypeError, ValueError):
        raise IngestionError(
            f"Non-JSON value in normalized field {field_name}."
        ) from None
    return {
        "status": status,
        "value": value,
        "unit": unit,
        "source_keys": source_keys,
        "raw_values": raw_values,
    }


def _load_products(store: _FeatureStore, bundle: _InputBundle) -> Counter[str]:
    counts: Counter[str] = Counter()
    path = bundle.product_dir / "products.normalized.jsonl"
    for row in read_jsonl(path):
        record = _record_values(row, "normalized product")
        product = record.get("product")
        normalization = record.get("normalization")
        if not isinstance(product, dict) or not isinstance(normalization, dict):
            raise IngestionError("Malformed normalized product wrapper.")
        if normalization.get("schema_version") != _PRODUCT_NORMALIZATION_SCHEMA:
            raise IngestionError("Unsupported normalized product schema.")
        item_key = product.get("item_key")
        fingerprint = product.get("source_record_fingerprint")
        normalized_fingerprint = normalization.get("source_record_fingerprint")
        decision = normalization.get("product_decision")
        if (
            not isinstance(item_key, str)
            or not item_key
            or not isinstance(fingerprint, str)
            or not _SHA256.fullmatch(fingerprint)
            or fingerprint != normalized_fingerprint
            or decision not in {"unique_retained", "conflict_retained"}
        ):
            raise IngestionError("Malformed normalized product identity or decision.")
        fields: dict[str, dict[str, object]] = {}
        for field_name in ("brand", "category", *_SPECIFICATION_FIELDS):
            fields[field_name] = _normalization_field(normalization, field_name)
        payload = _canonical_json(record)
        signature = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        existing = store.connection.execute(
            """
            SELECT 1 FROM product_records
            WHERE item_key = ? AND fingerprint = ? AND signature = ?
            """,
            (item_key, fingerprint, signature),
        ).fetchone()
        if existing is None:
            store.connection.execute(
                """
                INSERT INTO product_records (
                    item_key, fingerprint, signature, decision, payload
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (item_key, fingerprint, signature, decision, payload),
            )
        else:
            store.connection.execute(
                """
                UPDATE product_records SET occurrences = occurrences + 1
                WHERE item_key = ? AND fingerprint = ? AND signature = ?
                """,
                (item_key, fingerprint, signature),
            )
        if existing is None:
            for field_name, field in fields.items():
                value = field["value"]
                store.connection.execute(
                    """
                    INSERT INTO product_fields (
                        item_key, fingerprint, signature, field_name, status,
                        value_json, unit, source_keys_json, raw_values_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_key,
                        fingerprint,
                        signature,
                        field_name,
                        field["status"],
                        None if value is None else _canonical_json(value),
                        field["unit"],
                        _canonical_json(field["source_keys"]),
                        _canonical_json(field["raw_values"]),
                    ),
                )
        counts["input_product_records"] += 1
    return counts


def _training_product_rows(
    store: _FeatureStore, field_name: str
) -> Iterator[tuple[str, str, str | None, str | None]]:
    yield from store.connection.execute(
        """
        SELECT f.item_key, f.status, f.value_json, f.unit
        FROM product_fields AS f
        JOIN product_records AS p
          ON p.item_key = f.item_key
         AND p.fingerprint = f.fingerprint
         AND p.signature = f.signature
        JOIN training_items AS t ON t.source_key = f.item_key
        WHERE f.field_name = ?
          AND p.decision = 'unique_retained'
          AND (SELECT COUNT(*) FROM product_records AS all_p
               WHERE all_p.item_key = p.item_key) = 1
        ORDER BY f.item_key COLLATE BINARY
        """,
        (field_name,),
    )


def _fit_transformers(store: _FeatureStore) -> dict[str, object]:
    for field_name in _CATEGORICAL_FIELDS:
        for item_key, status, value_json, _ in _training_product_rows(
            store, field_name
        ):
            del item_key
            if status != NormalizationStatus.NORMALIZED.value or value_json is None:
                continue
            value = json.loads(value_json)
            if not isinstance(value, str) or not value:
                continue
            store.connection.execute(
                """
                INSERT OR IGNORE INTO category_vocab (
                    field_name, category_value, category_index
                )
                VALUES (?, ?, 0)
                """,
                (field_name, value),
            )
        for category_index, (category_value,) in enumerate(
            store.connection.execute(
                "SELECT category_value FROM category_vocab "
                "WHERE field_name = ? ORDER BY category_value COLLATE BINARY",
                (field_name,),
            ),
            start=1,
        ):
            store.connection.execute(
                "UPDATE category_vocab SET category_index = ? "
                "WHERE field_name = ? AND category_value = ?",
                (category_index, field_name, category_value),
            )

    numeric_fits: dict[str, dict[str, object]] = {}
    for feature_name in _NUMERIC_FIELDS:
        source_field, expected_unit = _numeric_source(feature_name)
        count = 0
        total = Decimal(0)
        square_total = Decimal(0)
        for _, status, value_json, unit in _training_product_rows(store, source_field):
            if status != NormalizationStatus.NORMALIZED.value or value_json is None:
                continue
            value = json.loads(value_json)
            if feature_name.startswith("battery_"):
                if unit != expected_unit:
                    continue
            elif unit != expected_unit:
                raise IngestionError(
                    f"Unexpected unit for normalized numeric feature {feature_name}."
                )
            try:
                decimal_value = Decimal(str(value))
            except InvalidOperation:
                raise IngestionError(
                    f"Invalid normalized number for feature {feature_name}."
                ) from None
            if not decimal_value.is_finite():
                raise IngestionError(
                    f"Non-finite normalized number for feature {feature_name}."
                )
            count += 1
            total += decimal_value
            square_total += decimal_value * decimal_value
        mean = total / count if count else None
        if count:
            variance = square_total / count - cast(Decimal, mean) ** 2
            if variance < 0:
                variance = Decimal(0)
            scale = variance.sqrt() if variance else Decimal(1)
        else:
            scale = None
        mean_text = None if mean is None else _format_decimal(mean)
        scale_text = None if scale is None else _format_decimal(scale)
        store.connection.execute(
            """
            INSERT INTO numeric_stats (field_name, observation_count, mean, scale)
            VALUES (?, ?, ?, ?)
            """,
            (feature_name, count, mean_text, scale_text),
        )
        numeric_fits[feature_name] = {
            "fit_split": DataSplit.TRAIN.value,
            "fit_scope": "unique non-conflicting training-catalog products",
            "observation_count": count,
            "unit": expected_unit,
            "mean": mean_text,
            "scale": scale_text,
            "scale_rule": "population standard deviation; 1 when variance is zero",
        }
    categorical_counts = {
        field: int(
            store.connection.execute(
                "SELECT COUNT(*) FROM category_vocab WHERE field_name = ?", (field,)
            ).fetchone()[0]
        )
        for field in _CATEGORICAL_FIELDS
    }
    return {
        "categorical_category_counts": categorical_counts,
        "numeric_standardizers": numeric_fits,
    }


def _numeric_source(feature_name: str) -> tuple[str, str]:
    if feature_name in _SPECS_FOR_NUMERIC:
        return _SPECS_FOR_NUMERIC[feature_name]
    if feature_name == "battery_charge_mah":
        return "battery_capacity", "mAh"
    if feature_name == "battery_energy_wh":
        return "battery_capacity", "Wh"
    raise IngestionError(f"Unsupported numeric feature {feature_name}.")


def _category_encoding(
    store: _FeatureStore, field_name: str, value: object, status: str
) -> CategoryEncoding:
    if status != NormalizationStatus.NORMALIZED.value or not isinstance(value, str):
        return encode_categorical_value(value, status, {})
    row = store.connection.execute(
        "SELECT category_index FROM category_vocab "
        "WHERE field_name = ? AND category_value = ?",
        (field_name, value),
    ).fetchone()
    if row is None:
        return CategoryEncoding(_UNKNOWN_INDEX, False, True, False)
    return CategoryEncoding(int(row[0]), False, False, False)


def _load_product_field_rows(
    store: _FeatureStore, item_key: str
) -> dict[str, dict[str, object]]:
    rows = store.connection.execute(
        """
        SELECT field_name, status, value_json, unit, source_keys_json, raw_values_json
        FROM product_fields
        WHERE item_key = ?
        ORDER BY field_name
        """,
        (item_key,),
    )
    result: dict[str, dict[str, object]] = {}
    for name, status, value_json, unit, source_keys_json, raw_values_json in rows:
        result[str(name)] = {
            "status": str(status),
            "value": None if value_json is None else json.loads(str(value_json)),
            "unit": unit,
            "source_keys": json.loads(str(source_keys_json)),
            "raw_values": json.loads(str(raw_values_json)),
        }
    return result


def _metadata_state(store: _FeatureStore, item_key: str) -> tuple[str, str | None]:
    row = store.connection.execute(
        """
        SELECT COUNT(*),
               MAX(CASE WHEN decision = 'conflict_retained' THEN 1 ELSE 0 END),
               MAX(fingerprint)
        FROM product_records WHERE item_key = ?
        """,
        (item_key,),
    ).fetchone()
    if row is None or int(row[0]) == 0:
        return "metadata_missing", None
    count = int(row[0])
    conflict_marker = bool(row[1])
    if count != 1 or conflict_marker:
        return "conflict_excluded", None
    return "normalized", cast(str, row[2])


def _category_feature(
    store: _FeatureStore,
    field_name: str,
    raw_field: Mapping[str, object] | None,
    metadata_status: str,
) -> dict[str, object]:
    if metadata_status == "unknown_item" or metadata_status == "metadata_missing":
        status = NormalizationStatus.MISSING.value
        value = None
        source_keys: object = []
        raw_values: object = []
        unavailable = False
    elif metadata_status == "conflict_excluded":
        status = "conflict_excluded"
        value = None
        source_keys = []
        raw_values = []
        unavailable = True
    else:
        if raw_field is None:
            raise IngestionError(f"Product feature {field_name} is absent.")
        status = cast(str, raw_field["status"])
        value = raw_field["value"]
        source_keys = raw_field["source_keys"]
        raw_values = raw_field["raw_values"]
        unavailable = status not in {
            NormalizationStatus.NORMALIZED.value,
            NormalizationStatus.MISSING.value,
        }
    encoded = _category_encoding(store, field_name, value, status)
    return {
        "index": encoded.index,
        "missing": encoded.missing,
        "unknown": encoded.unknown,
        "unavailable": unavailable or encoded.unavailable,
        "status": ("unknown_category" if encoded.unknown else status),
        "source_keys": source_keys,
        "raw_values": raw_values,
    }


def _numeric_feature(
    store: _FeatureStore,
    feature_name: str,
    raw_field: Mapping[str, object] | None,
    metadata_status: str,
) -> dict[str, object]:
    expected_unit = _numeric_source(feature_name)[1]
    status = "missing"
    raw_value: object = None
    source_unit: str | None = None
    source_keys: object = []
    raw_values: object = []
    not_applicable = False
    unavailable = False
    missing = False
    if metadata_status == "conflict_excluded":
        status = "conflict_excluded"
        unavailable = True
    elif metadata_status == "unknown_item" or metadata_status == "metadata_missing":
        status = NormalizationStatus.MISSING.value
        missing = True
    else:
        if raw_field is None:
            raise IngestionError(f"Product feature {feature_name} is absent.")
        status = cast(str, raw_field["status"])
        raw_value = raw_field["value"]
        source_unit_value = raw_field["unit"]
        source_unit = source_unit_value if isinstance(source_unit_value, str) else None
        source_keys = raw_field["source_keys"]
        raw_values = raw_field["raw_values"]
        if status == NormalizationStatus.MISSING.value:
            missing = True
        elif status != NormalizationStatus.NORMALIZED.value:
            unavailable = True
        elif feature_name.startswith("battery_") and source_unit != expected_unit:
            status = "not_applicable"
            raw_value = None
            source_unit = None
            source_keys = []
            raw_values = []
            not_applicable = True
        elif source_unit != expected_unit:
            raise IngestionError(
                f"Unexpected unit in normalized feature {feature_name}."
            )
    standardized: str | None = None
    if status == NormalizationStatus.NORMALIZED.value and not unavailable:
        try:
            value = Decimal(str(raw_value))
        except InvalidOperation:
            raise IngestionError(
                f"Invalid numeric value in feature {feature_name}."
            ) from None
        if not value.is_finite():
            raise IngestionError(f"Non-finite feature value in {feature_name}.")
        stats = store.connection.execute(
            "SELECT mean, scale FROM numeric_stats WHERE field_name = ?",
            (feature_name,),
        ).fetchone()
        if stats is not None and stats[0] is not None and stats[1] is not None:
            standardized = _format_decimal(
                (value - Decimal(str(stats[0]))) / Decimal(str(stats[1]))
            )
    return {
        "value": standardized,
        "normalized_value": raw_value
        if status == NormalizationStatus.NORMALIZED.value
        else None,
        "unit": expected_unit
        if status == NormalizationStatus.NORMALIZED.value
        else None,
        "missing": missing,
        "unknown": False,
        "unavailable": unavailable,
        "not_applicable": not_applicable,
        "status": status,
        "source_unit": source_unit,
        "source_keys": source_keys,
        "raw_values": raw_values,
    }


def _write_item_features(
    store: _FeatureStore,
    path: Path,
) -> tuple[dict[str, object], dict[str, object], int]:
    sink = _JsonlSink(path)
    status_counts: dict[str, Counter[str]] = {
        name: Counter() for name in (*_CATEGORICAL_FIELDS, *_NUMERIC_FIELDS)
    }
    missingness_counts: dict[str, Counter[str]] = {
        name: Counter() for name in (*_CATEGORICAL_FIELDS, *_NUMERIC_FIELDS)
    }

    def record_feature_state(field: str, feature: Mapping[str, object]) -> None:
        status_counts[field][cast(str, feature["status"])] += 1
        for flag in ("missing", "unknown", "unavailable", "not_applicable"):
            if feature.get(flag) is True:
                missingness_counts[field][flag] += 1

    try:
        sink.write(
            {
                "schema_version": FEATURE_ITEM_SCHEMA,
                "item_index": _UNKNOWN_INDEX,
                "metadata_status": "unknown_item",
                "metadata_temporal_scope": "source_snapshot_effective_time_unknown",
                "source_record_fingerprint": None,
                "categorical": {
                    field: _category_feature(store, field, None, "unknown_item")
                    for field in _CATEGORICAL_FIELDS
                },
                "numeric": {
                    field: _numeric_feature(store, field, None, "unknown_item")
                    for field in _NUMERIC_FIELDS
                },
            }
        )
        for item_key, item_index in store.connection.execute(
            "SELECT source_key, item_index FROM training_items ORDER BY item_index"
        ):
            metadata_status, fingerprint = _metadata_state(store, str(item_key))
            fields = (
                _load_product_field_rows(store, str(item_key))
                if metadata_status == "normalized"
                else {}
            )
            categorical: dict[str, object] = {}
            numeric: dict[str, object] = {}
            for field in _CATEGORICAL_FIELDS:
                raw_field = fields.get(field)
                categorical[field] = _category_feature(
                    store, field, raw_field, metadata_status
                )
                record_feature_state(field, cast(dict[str, object], categorical[field]))
            for field in _NUMERIC_FIELDS:
                source_field, _ = _numeric_source(field)
                numeric[field] = _numeric_feature(
                    store, field, fields.get(source_field), metadata_status
                )
                record_feature_state(field, cast(dict[str, object], numeric[field]))
            sink.write(
                {
                    "schema_version": FEATURE_ITEM_SCHEMA,
                    "item_index": int(item_index),
                    "metadata_status": metadata_status,
                    "metadata_temporal_scope": "source_snapshot_effective_time_unknown",
                    "source_record_fingerprint": fingerprint,
                    "categorical": categorical,
                    "numeric": numeric,
                }
            )
    finally:
        sink.close()
    return (
        {
            name: dict(sorted(counter.items()))
            for name, counter in sorted(status_counts.items())
        },
        {
            name: dict(sorted(counter.items()))
            for name, counter in sorted(missingness_counts.items())
        },
        sink.records,
    )


def _history_upsert(store: _FeatureStore, timestamp: int, table: str) -> None:
    key = "user_key" if table == "user_history" else "item_key"
    store.connection.execute(
        f"""
        INSERT INTO {table} ({key}, event_count, rating_sum)
        SELECT {key}, COUNT(*), DECIMAL_SUM(rating)
        FROM events INDEXED BY events_time_idx
        WHERE event_time_ms = ?
          AND split = 'train'
          AND train_eligible = 1
        GROUP BY {key}
        ON CONFLICT ({key}) DO UPDATE SET
            event_count = {table}.event_count + excluded.event_count,
            rating_sum = DECIMAL_ADD({table}.rating_sum, excluded.rating_sum)
        """,
        (timestamp,),
    )


def _history_value(
    store: _FeatureStore, table: str, key_name: str, key: str
) -> tuple[int, str | None]:
    row = store.connection.execute(
        f"SELECT event_count, rating_sum FROM {table} WHERE {key_name} = ?",
        (key,),
    ).fetchone()
    if row is None:
        return 0, None
    count = int(row[0])
    return count, _format_decimal(Decimal(str(row[1])) / count)


def _write_interaction_features(
    store: _FeatureStore,
    path: Path,
    split_counts: Mapping[str, int],
) -> dict[str, object]:
    sink = _JsonlSink(path)
    counts: Counter[str] = Counter()
    try:
        timestamps = store.connection.execute(
            "SELECT DISTINCT event_time_ms FROM events ORDER BY event_time_ms"
        )
        for (timestamp_value,) in timestamps:
            timestamp = int(timestamp_value)
            rows = store.connection.execute(
                """
                SELECT split, fingerprint, duplicate_ordinal, user_key, item_key,
                       user_index, item_index, rating, rating_label,
                       interaction_json, source_split, integrity_flags_json,
                       evaluation_json, train_eligible
                FROM events
                WHERE event_time_ms = ?
                ORDER BY split, fingerprint, signature, duplicate_ordinal
                """,
                (timestamp,),
            )
            for row in rows:
                (
                    split,
                    fingerprint,
                    duplicate_ordinal,
                    user_key,
                    item_key,
                    user_index,
                    item_index,
                    rating,
                    rating_label,
                    interaction_json,
                    source_split,
                    integrity_flags_json,
                    evaluation_json,
                    train_eligible,
                ) = row
                user_count, user_mean = _history_value(
                    store, "user_history", "user_key", str(user_key)
                )
                item_count, item_mean = _history_value(
                    store, "item_history", "item_key", str(item_key)
                )
                split_name = str(split)
                counts[f"{split_name}.records"] += 1
                counts[f"{split_name}.unknown_user_records"] += int(
                    int(user_index) == _UNKNOWN_INDEX
                )
                counts[f"{split_name}.unknown_item_records"] += int(
                    int(item_index) == _UNKNOWN_INDEX
                )
                counts[f"{split_name}.no_prior_user_history"] += int(user_count == 0)
                counts[f"{split_name}.no_prior_item_history"] += int(item_count == 0)
                counts[f"{split_name}.training_eligible_records"] += int(
                    bool(train_eligible)
                )
                counts[f"{split_name}.excluded_training_duplicates"] += int(
                    split_name == DataSplit.TRAIN.value and not bool(train_eligible)
                )
                eligibility = (
                    None
                    if evaluation_json is None
                    else cast(dict[str, object], json.loads(str(evaluation_json)))
                )
                interaction_record = cast(
                    dict[str, object], json.loads(str(interaction_json))
                )
                sink.write(
                    {
                        "schema_version": FEATURE_INTERACTION_SCHEMA,
                        "user_index": int(user_index),
                        "item_index": int(item_index),
                        "observed_rating": str(rating),
                        "feedback_label": str(rating_label),
                        "event_time_ms": timestamp,
                        "event_time_utc": interaction_record["event_time_utc"],
                        "source_timestamp_value": interaction_record[
                            "source_timestamp_value"
                        ],
                        "source_timestamp_unit": "unix_ms",
                        "source_rating_value": interaction_record[
                            "source_rating_value"
                        ],
                        "event_type": interaction_record["event_type"],
                        "event_type_present": interaction_record["event_type_present"],
                        "source_event_id_present": interaction_record[
                            "source_event_id_present"
                        ],
                        "split": split_name,
                        "source_split": source_split,
                        "source_duplicate_ordinal": int(duplicate_ordinal),
                        "source_event_fingerprint": str(fingerprint),
                        "integrity_flags": json.loads(str(integrity_flags_json)),
                        "training_eligible": bool(train_eligible),
                        "evaluation_eligibility": eligibility,
                        "history": {
                            "policy": "training_only_strictly_prior",
                            "user_prior_interaction_count": user_count,
                            "user_prior_mean_rating": user_mean,
                            "user_prior_mean_rating_missing": user_mean is None,
                            "item_prior_interaction_count": item_count,
                            "item_prior_mean_rating": item_mean,
                            "item_prior_mean_rating_missing": item_mean is None,
                        },
                    }
                )
            _history_upsert(store, timestamp, "user_history")
            _history_upsert(store, timestamp, "item_history")
    finally:
        sink.close()
    if sink.records != sum(split_counts.values()):
        raise IngestionError(
            "Generated interaction feature count does not match input."
        )
    per_split: dict[str, dict[str, object]] = {}
    for split in _SPLITS:
        split_name = split.value
        denominator = counts[f"{split_name}.records"]
        metrics: dict[str, object] = {
            key.removeprefix(f"{split_name}."): value
            for key, value in sorted(counts.items())
            if key.startswith(f"{split_name}.")
        }
        rate_pairs = (
            ("unknown_user_rate", "unknown_user_records"),
            ("unknown_item_rate", "unknown_item_records"),
            ("no_prior_user_history_rate", "no_prior_user_history"),
            ("no_prior_item_history_rate", "no_prior_item_history"),
        )
        for rate_name, count_name in rate_pairs:
            metrics[rate_name] = (
                _format_decimal(
                    Decimal(cast(int, metrics.get(count_name, 0)))
                    / Decimal(denominator)
                )
                if denominator
                else "0"
            )
        per_split[split_name] = metrics
    return {
        "records": sink.records,
        "per_split": per_split,
    }


def _feature_schema() -> dict[str, object]:
    categories = [
        {
            "name": name,
            "type": "integer",
            "unknown_index": _UNKNOWN_INDEX,
            "missingness": "separate missing, unknown, and unavailable flags",
            "fit_scope": "training items only",
            "temporal_scope": "snapshot metadata; effective time unknown",
        }
        for name in _CATEGORICAL_FIELDS
    ]
    numeric = [
        {
            "name": name,
            "type": "decimal-string|null",
            "unit": _numeric_source(name)[1],
            "transformation": "training-only population z-score",
            "missingness": "null plus missing/unavailable/not_applicable flags",
            "imputation": "none",
            "temporal_scope": "snapshot metadata; effective time unknown",
        }
        for name in _NUMERIC_FIELDS
    ]
    return {
        "schema_version": FEATURE_SCHEMA_VERSION,
        "interaction_record_schema": FEATURE_INTERACTION_SCHEMA,
        "item_record_schema": FEATURE_ITEM_SCHEMA,
        "encoded_interaction_fields": [
            {"name": "user_index", "type": "integer", "unknown_index": 0},
            {"name": "item_index", "type": "integer", "unknown_index": 0},
            {"name": "observed_rating", "type": "decimal-string"},
            {"name": "feedback_label", "type": "string"},
            {"name": "event_time_ms", "type": "integer", "unit": "unix_ms"},
            {"name": "split", "type": "enum", "values": [s.value for s in _SPLITS]},
            {"name": "source_event_fingerprint", "type": "sha256"},
            {"name": "source_timestamp_value", "type": "json"},
            {"name": "source_rating_value", "type": "json"},
            {"name": "event_type", "type": "string|null"},
            {"name": "event_type_present", "type": "boolean"},
            {"name": "source_event_id_present", "type": "boolean"},
        ],
        "temporal_interaction_features": [
            {
                "name": "user_prior_interaction_count",
                "type": "integer",
                "source": "training split, training-eligible events only",
                "boundary": "strictly earlier timestamps; equal timestamps excluded",
            },
            {
                "name": "user_prior_mean_rating",
                "type": "decimal-string|null",
                "missing": "null when the user has no prior eligible training event",
                "source": "observed ratings only",
            },
            {
                "name": "item_prior_interaction_count",
                "type": "integer",
                "semantics": (
                    "training-observed popularity, not exposure or availability"
                ),
            },
            {
                "name": "item_prior_mean_rating",
                "type": "decimal-string|null",
                "missing": "null when the item has no prior eligible training event",
                "source": "observed ratings only",
            },
        ],
        "history_policy": {
            "training": "eligible train interactions strictly before target time",
            "validation": "training interactions only, strictly before target time",
            "test": "training interactions only, strictly before target time",
            "equal_timestamps": "excluded from one another",
            "held_out_events_update_history": False,
        },
        "snapshot_product_features": {
            "temporal_scope": "snapshot metadata; effective time unknown",
            "historical_availability_claims": False,
            "metadata_source_ids": "not emitted",
            "categorical": categories,
            "numeric": numeric,
            "conflicting_product_policy": (
                "exclude all metadata for the item; never merge"
            ),
            "price_and_rating_aggregates": "excluded",
        },
        "source_event_identifiers": (
            "opaque source event fingerprints only; raw user/item keys are not emitted"
        ),
        "unobserved_items": "unknown, never negative",
    }


def _write_transformers(
    path: Path, store: _FeatureStore, fits: Mapping[str, object]
) -> None:
    categorical_counts = cast(Mapping[str, int], fits["categorical_category_counts"])
    numeric_stats = cast(Mapping[str, object], fits["numeric_standardizers"])
    with path.open("w", encoding="utf-8", newline="\n") as output:
        output.write('{"categorical_encoders":{')
        for field_index, field_name in enumerate(_CATEGORICAL_FIELDS):
            if field_index:
                output.write(",")
            output.write(_canonical_json(field_name))
            output.write(':{"fit_split":"train","unknown_index":0,"values":[')
            first = True
            for value, category_index in store.connection.execute(
                "SELECT category_value, category_index FROM category_vocab "
                "WHERE field_name = ? ORDER BY category_index",
                (field_name,),
            ):
                if not first:
                    output.write(",")
                output.write(
                    _canonical_json({"index": int(category_index), "value": str(value)})
                )
                first = False
            output.write("]}")
        output.write('},"categorical_category_counts":')
        output.write(_canonical_json(dict(categorical_counts)))
        output.write(',"numeric_standardizers":')
        output.write(_canonical_json(dict(numeric_stats)))
        output.write(',"schema_version":')
        output.write(_canonical_json(TRANSFORMERS_SCHEMA_VERSION))
        output.write("}\n")


def _feature_dataset_id(checksums: Mapping[str, object], config_hash: str) -> str:
    identity = {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "configuration_sha256": config_hash,
        "inputs": checksums,
    }
    digest = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()
    return f"rf-features-v1-{digest[:16]}"


def _output_path(output_dir: Path, bundle: _InputBundle) -> Path:
    requested = (
        output_dir if output_dir.is_absolute() else _REPOSITORY_ROOT / output_dir
    )
    if requested.is_symlink():
        raise IngestionError("Feature output directory cannot be a symbolic link.")
    resolved = requested.resolve()
    try:
        relative = resolved.relative_to(_PROCESSED_ROOT)
    except ValueError:
        raise IngestionError(
            "Feature outputs must be inside ignored data/processed."
        ) from None
    if not relative.parts:
        raise IngestionError("Feature output must be a new child directory.")
    if resolved.exists() or resolved.is_symlink():
        raise IngestionError("Feature output already exists; refusing to overwrite.")
    for input_dir in (bundle.temporal_dir.resolve(), bundle.product_dir.resolve()):
        if (
            resolved == input_dir
            or resolved in input_dir.parents
            or input_dir in resolved.parents
        ):
            raise IngestionError("Feature output cannot overlap an input directory.")
    return resolved


def _verify_inputs_unchanged(bundle: _InputBundle) -> None:
    paths = {
        "temporal_manifest.json": bundle.temporal_dir / "manifest.json",
        "product_ingestion_manifest.json": bundle.product_dir / "manifest.json",
        "products.normalized.jsonl": bundle.product_dir / "products.normalized.jsonl",
    }
    paths.update(
        {f"temporal/{name}": bundle.temporal_dir / name for name in _TEMPORAL_FILES}
    )
    for name, path in paths.items():
        checksum, size = sha256_file(path)
        expected = bundle.checksums[name]
        if checksum != expected["sha256"] or size != expected["size_bytes"]:
            raise IngestionError(f"Feature input changed during processing: {name}.")


def generate_features(
    *,
    temporal_dir: Path,
    product_ingestion_dir: Path,
    output_dir: Path,
) -> FeatureGenerationResult:
    """Generate train-only transforms and strict as-of interaction features."""
    temporal_dir = temporal_dir.resolve()
    product_ingestion_dir = product_ingestion_dir.resolve()
    if not temporal_dir.is_dir() or not product_ingestion_dir.is_dir():
        raise IngestionError(
            "Temporal and product ingestion inputs must be directories."
        )
    bundle = _load_inputs(temporal_dir, product_ingestion_dir)
    final_output = _output_path(output_dir, bundle)
    final_output.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{final_output.name}.tmp-", dir=final_output.parent)
    )
    store: _FeatureStore | None = None
    try:
        scratch = tempfile.TemporaryDirectory(prefix="recfusion-features-")
        try:
            store = _FeatureStore(Path(scratch.name) / "features.sqlite3")
            _load_vocabulary(
                store,
                temporal_dir / "vocabulary.users.jsonl",
                entity="user",
                table="user_vocab",
            )
            _load_vocabulary(
                store,
                temporal_dir / "vocabulary.items.jsonl",
                entity="item",
                table="item_vocab",
            )
            _load_candidate_pool(store, temporal_dir / "candidate-pool.items.jsonl")
            split_counts = _load_temporal_events(store, bundle)
            _load_evaluation_records(store, temporal_dir / "evaluation.jsonl")
            product_counts = _load_products(store, bundle)
            fits = _fit_transformers(store)

            (
                item_status_counts,
                item_missingness_counts,
                item_records,
            ) = _write_item_features(store, staging_dir / "items.features.jsonl")
            event_stats = _write_interaction_features(
                store,
                staging_dir / "interactions.features.jsonl",
                split_counts,
            )

            schema_path = staging_dir / "feature-schema.json"
            write_manifest(schema_path, _feature_schema())
            transformer_path = staging_dir / "transformers.json"
            _write_transformers(transformer_path, store, fits)

            _verify_inputs_unchanged(bundle)
            output_files = [
                staging_dir / "interactions.features.jsonl",
                staging_dir / "items.features.jsonl",
                schema_path,
                transformer_path,
            ]
            outputs: list[dict[str, object]] = []
            for path in output_files[:2]:
                checksum, size = sha256_file(path)
                record_stats = (
                    cast(Mapping[str, object], event_stats)
                    if path.name == "interactions.features.jsonl"
                    else {}
                )
                outputs.append(
                    {
                        "file": path.name,
                        "records": (
                            record_stats.get("records")
                            if path.name == "interactions.features.jsonl"
                            else item_records
                        ),
                        "size_bytes": size,
                        "sha256": checksum,
                    }
                )
            for path in output_files[2:]:
                checksum, size = sha256_file(path)
                outputs.append(
                    {"file": path.name, "size_bytes": size, "sha256": checksum}
                )
            config_json = _canonical_json(_FEATURE_CONFIG)
            config_hash = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
            dataset_id = _feature_dataset_id(bundle.checksums, config_hash)
            user_vocab_hash, _ = sha256_file(temporal_dir / "vocabulary.users.jsonl")
            item_vocab_hash, _ = sha256_file(temporal_dir / "vocabulary.items.jsonl")
            product_conflicts = len(
                store.connection.execute(
                    """
                    SELECT COUNT(*) FROM training_items AS t
                    JOIN product_records AS p ON p.item_key = t.source_key
                    GROUP BY t.source_key
                    HAVING COUNT(*) > 1 OR MAX(p.decision = 'conflict_retained') = 1
                    """
                ).fetchall()
            )
            product_training_items = int(
                store.connection.execute(
                    """
                    SELECT COUNT(DISTINCT p.item_key)
                    FROM product_records AS p
                    JOIN training_items AS t ON t.source_key = p.item_key
                    """
                ).fetchone()[0]
            )
            total_product_items = int(
                store.connection.execute(
                    "SELECT COUNT(DISTINCT item_key) FROM product_records"
                ).fetchone()[0]
            )
            duplicate_product_occurrences = int(
                store.connection.execute(
                    "SELECT COALESCE(SUM(occurrences - 1), 0) FROM product_records"
                ).fetchone()[0]
            )
            input_count = sum(split_counts.values())
            training_eligible = int(
                store.connection.execute(
                    "SELECT COUNT(*) FROM events "
                    "WHERE split='train' AND train_eligible=1"
                ).fetchone()[0]
            )
            train_duplicates_excluded = int(
                store.connection.execute(
                    "SELECT COUNT(*) FROM events "
                    "WHERE split='train' AND train_eligible=0"
                ).fetchone()[0]
            )
            manifest: dict[str, object] = {
                "manifest_schema_version": FEATURE_MANIFEST_SCHEMA,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "feature_dataset_id": dataset_id,
                "source": {
                    "temporal_source": bundle.temporal_manifest.get("source"),
                    "product_source": bundle.product_manifest.get("source"),
                },
                "input_checksums": bundle.checksums,
                "training_vocabulary_sha256": {
                    "users": user_vocab_hash,
                    "items": item_vocab_hash,
                },
                "configuration": _FEATURE_CONFIG,
                "configuration_sha256": config_hash,
                "schemas": {
                    "temporal_split": bundle.temporal_manifest.get(
                        "split_policy_version"
                    ),
                    "product_normalization": _PRODUCT_NORMALIZATION_SCHEMA,
                    "feature_interaction": FEATURE_INTERACTION_SCHEMA,
                    "feature_item": FEATURE_ITEM_SCHEMA,
                    "transformers": TRANSFORMERS_SCHEMA_VERSION,
                },
                "counts": {
                    "interaction_records": input_count,
                    "interaction_records_by_split": dict(sorted(split_counts.items())),
                    "training_eligible_interactions": training_eligible,
                    "training_duplicate_records_excluded_from_history": (
                        train_duplicates_excluded
                    ),
                    "held_out_interactions_retained": (
                        split_counts[DataSplit.VALIDATION.value]
                        + split_counts[DataSplit.TEST.value]
                    ),
                    "item_feature_records_including_unknown": item_records,
                    "training_candidate_items": item_records - 1,
                    "training_catalog_items_with_product_metadata": (
                        product_training_items
                    ),
                    "training_catalog_items_without_product_metadata": (
                        item_records - 1 - product_training_items
                    ),
                    "training_catalog_items_with_conflicting_metadata": (
                        product_conflicts
                    ),
                    "product_items_outside_training_catalog": (
                        total_product_items - product_training_items
                    ),
                    "input_product_records": product_counts["input_product_records"],
                    "exact_duplicate_product_records": duplicate_product_occurrences,
                    "unknown_id_and_history_counts_by_split": event_stats["per_split"],
                },
                "feature_statistics": {
                    "item_field_status_counts": item_status_counts,
                    "item_missingness_counts": item_missingness_counts,
                    "fitted_transformers": fits,
                },
                "integrity": {
                    "training_only_vocabulary_fit": True,
                    "training_only_history": True,
                    "strictly_prior_timestamp_features": True,
                    "simultaneous_events_excluded": True,
                    "held_out_records_preserved": True,
                    "conflicting_product_metadata_merged": False,
                    "historical_metadata_availability_proven": False,
                    "price_or_rating_aggregate_features_used": False,
                },
                "outputs": outputs,
            }
            write_manifest(staging_dir / "manifest.json", manifest)
            if final_output.exists():
                raise IngestionError("Feature output appeared during processing.")
            os.replace(staging_dir, final_output)
            return FeatureGenerationResult(final_output, manifest)
        finally:
            if store is not None:
                store.close()
                store = None
            scratch.cleanup()
    except (OSError, sqlite3.Error) as error:
        raise IngestionError(
            "Feature generation failed before publishing outputs."
        ) from error
    finally:
        if store is not None:
            store.close()
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
