"""Bounded streaming ingestion and train-only join for Amazon metadata."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import zlib
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, cast

from recfusion_core.contracts import ProductMetadata
from recfusion_data.ingestion.adapters import amazon_electronics_item_key
from recfusion_data.ingestion.amazon_metadata import (
    MappedAmazonMetadata,
    adapt_amazon_metadata_record,
)
from recfusion_data.ingestion.errors import IngestionError
from recfusion_data.ingestion.manifest import (
    sha256_file,
    source_record_fingerprint,
    write_manifest,
)
from recfusion_data.normalization import normalize_product_metadata
from recfusion_data.splitting.temporal import (
    MANIFEST_SCHEMA,
    VOCABULARY_SCHEMA,
)
from recfusion_data.validation import validate_product

AMAZON_METADATA_MANIFEST_SCHEMA = "recfusion.amazon-electronics-metadata.v1"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_PROCESSED_ROOT = (_REPOSITORY_ROOT / "data" / "processed").resolve()
_SOURCE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ITEM_KEY_PREFIX = "ar23:Electronics:item:"
_DEFAULT_MAX_RECORD_BYTES = 8 * 1024 * 1024
_SQLITE_CACHE_KIB = 8192


@dataclass(frozen=True, slots=True)
class AmazonMetadataIngestionResult:
    output_dir: Path
    manifest: Mapping[str, object]


class _JsonlSink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.file: TextIO = path.open("w", encoding="utf-8", newline="\n")
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

    def manifest_record(self) -> dict[str, object]:
        self.file.flush()
        return {
            "file": self.path.name,
            "records": self.records,
            "size_bytes": self.path.stat().st_size,
            "sha256": self.digest.hexdigest(),
        }

    def close(self) -> None:
        self.file.close()


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise IngestionError(f"{label} is malformed.")
    return cast(Mapping[str, object], value)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise IngestionError(f"{label} is malformed.")
    return value


def _verified_train_vocabulary(
    vocabulary_path: Path, temporal_manifest_path: Path
) -> tuple[str, int, str, int]:
    if vocabulary_path.name != "vocabulary.items.jsonl":
        raise IngestionError("Target must be a Step 2.5 item vocabulary file.")
    if vocabulary_path.resolve().parent != temporal_manifest_path.resolve().parent:
        raise IngestionError("Vocabulary and temporal manifest must share a directory.")
    try:
        manifest_value = json.loads(temporal_manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IngestionError("Cannot read the temporal split manifest.") from error
    manifest = _mapping(manifest_value, "Temporal split manifest")
    if manifest.get("manifest_schema_version") != MANIFEST_SCHEMA:
        raise IngestionError("Unsupported temporal split manifest schema.")
    if manifest.get("mode") != "trusted-pre-split":
        raise IngestionError("Metadata matching requires trusted pre-split membership.")

    configuration = _mapping(manifest.get("configuration"), "Temporal configuration")
    if (
        configuration.get("candidate_policy")
        != "unique item keys observed in train only"
    ):
        raise IngestionError(
            "Temporal manifest does not declare a train-only item pool."
        )
    if (
        configuration.get("input_record_schema")
        != "recfusion.interaction-preprocessing.v1"
    ):
        raise IngestionError("Temporal manifest has an unsupported input schema.")
    counts = _mapping(manifest.get("counts"), "Temporal counts")
    candidate_pool = _mapping(counts.get("candidate_pool"), "Candidate pool")
    train_vocabulary = _mapping(counts.get("train_vocabulary"), "Train vocabulary")
    if (
        candidate_pool.get("source_split") != "train"
        or candidate_pool.get("uses_validation_or_test") is not False
        or train_vocabulary.get("fit_split") != "train"
    ):
        raise IngestionError("Temporal item vocabulary is not train-only.")
    integrity = _mapping(manifest.get("integrity_status"), "Temporal integrity")
    if (
        integrity.get("evaluation_eligible") is not True
        or integrity.get("source_split_membership_changed") != 0
    ):
        raise IngestionError(
            "Temporal split integrity does not permit metadata joining."
        )

    expected_items = _integer(candidate_pool.get("items"), "Candidate item count")
    if expected_items != _integer(
        train_vocabulary.get("items"), "Train vocabulary item count"
    ):
        raise IngestionError("Temporal candidate and vocabulary counts disagree.")
    outputs_value = manifest.get("outputs")
    if not isinstance(outputs_value, list):
        raise IngestionError("Temporal manifest does not list its outputs.")
    vocabulary_output = next(
        (
            _mapping(value, "Temporal output")
            for value in outputs_value
            if isinstance(value, dict) and value.get("file") == vocabulary_path.name
        ),
        None,
    )
    if vocabulary_output is None:
        raise IngestionError("Temporal manifest does not attest the item vocabulary.")
    expected_hash = vocabulary_output.get("sha256")
    checksum, size = sha256_file(vocabulary_path)
    if checksum != expected_hash or size != _integer(
        vocabulary_output.get("size_bytes"), "Vocabulary size"
    ):
        raise IngestionError("Item vocabulary checksum does not match its manifest.")
    manifest_checksum, _ = sha256_file(temporal_manifest_path)
    return checksum, size, manifest_checksum, expected_items


def _load_vocabulary_index(path: Path, database: sqlite3.Connection) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as source:
        first = source.readline()
        try:
            unknown = _mapping(json.loads(first), "Unknown vocabulary row")
        except (json.JSONDecodeError, ValueError) as error:
            raise IngestionError(
                "Item vocabulary has an invalid unknown row."
            ) from error
        if (
            unknown.get("schema_version") != VOCABULARY_SCHEMA
            or unknown.get("entity_type") != "item"
            or unknown.get("index") != 0
            or unknown.get("is_unknown") is not True
            or "source_key" in unknown
        ):
            raise IngestionError("Item vocabulary unknown row is invalid.")

        for expected_index, line in enumerate(source, start=1):
            try:
                row = _mapping(json.loads(line), "Item vocabulary row")
            except (json.JSONDecodeError, ValueError) as error:
                raise IngestionError(
                    "Item vocabulary contains invalid JSON."
                ) from error
            source_key = row.get("source_key")
            index = row.get("index")
            if (
                row.get("schema_version") != VOCABULARY_SCHEMA
                or row.get("entity_type") != "item"
                or isinstance(index, bool)
                or not isinstance(index, int)
                or index != expected_index
                or row.get("is_unknown") is not False
                or not isinstance(source_key, str)
                or not source_key.startswith(_ITEM_KEY_PREFIX)
                or not source_key[len(_ITEM_KEY_PREFIX) :].strip()
            ):
                raise IngestionError("Item vocabulary row violates its contract.")
            try:
                database.execute(
                    "INSERT INTO target_items(item_key) VALUES (?)", (source_key,)
                )
            except sqlite3.IntegrityError as error:
                raise IngestionError(
                    "Item vocabulary contains duplicate keys."
                ) from error
            count += 1
    return count


def _iter_gzip_lines(
    path: Path, max_record_bytes: int
) -> Iterator[tuple[int, bytes | None, str | None, int]]:
    try:
        with gzip.open(path, "rb") as source:
            row_number = 0
            while True:
                line = source.readline(max_record_bytes + 1)
                if not line:
                    break
                row_number += 1
                consumed = len(line)
                if len(line) > max_record_bytes:
                    while not line.endswith(b"\n"):
                        line = source.readline(64 * 1024)
                        consumed += len(line)
                        if not line:
                            break
                    yield row_number, None, "record_too_large", consumed
                    continue
                yield row_number, line, None, consumed
    except (gzip.BadGzipFile, EOFError, OSError, zlib.error) as error:
        raise IngestionError(
            "Metadata input is not a valid complete gzip stream."
        ) from error


def _product_record(product: ProductMetadata) -> dict[str, object]:
    price: dict[str, str] | None = None
    if product.price is not None:
        price = {
            "amount": str(product.price.amount),
            "currency": product.price.currency,
        }
    return {
        "attributes": product.attributes,
        "average_rating": None,
        "categories": product.categories,
        "category": product.category,
        "description": product.description,
        "features": product.features,
        "images": None,
        "item_key": product.item_key,
        "price": price,
        "rating_count": None,
        "source_record_fingerprint": product.source_record_fingerprint,
        "title": product.title,
        "videos": None,
    }


def _open_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute(f"PRAGMA cache_size=-{_SQLITE_CACHE_KIB}")
    connection.executescript(
        """
        CREATE TABLE target_items (
            item_key TEXT PRIMARY KEY
        ) WITHOUT ROWID;
        CREATE TABLE source_records (
            item_key TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            is_matched INTEGER NOT NULL,
            occurrences INTEGER NOT NULL,
            PRIMARY KEY (item_key, fingerprint)
        ) WITHOUT ROWID;
        CREATE TABLE matched_products (
            item_key TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            product_json TEXT NOT NULL,
            PRIMARY KEY (item_key, fingerprint)
        ) WITHOUT ROWID;
        """
    )
    return connection


def _metadata_line(line: bytes, row_number: int) -> Mapping[str, object]:
    del row_number
    try:
        value = json.loads(line.decode("utf-8"), parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise ValueError("malformed_json") from None
    if not isinstance(value, dict):
        raise ValueError("record_not_object")
    return cast(Mapping[str, object], value)


def _validate_paths(
    *,
    metadata_path: Path,
    vocabulary_path: Path,
    temporal_manifest_path: Path,
    output_dir: Path,
    temp_dir: Path | None,
) -> Path:
    input_paths = (metadata_path, vocabulary_path, temporal_manifest_path)
    resolved_inputs = tuple(path.resolve() for path in input_paths)
    if len(set(resolved_inputs)) != len(resolved_inputs):
        raise IngestionError(
            "Metadata, vocabulary, and manifest paths must be distinct."
        )
    for label, path in zip(
        ("Metadata", "Vocabulary", "Temporal manifest"), input_paths, strict=True
    ):
        if not path.is_file():
            raise IngestionError(f"{label} input is not a local file.")

    requested = (
        output_dir if output_dir.is_absolute() else _REPOSITORY_ROOT / output_dir
    )
    if requested.is_symlink():
        raise IngestionError("Output directory cannot be a symbolic link.")
    resolved_output = requested.resolve()
    try:
        relative = resolved_output.relative_to(_PROCESSED_ROOT)
    except ValueError:
        raise IngestionError("Output must be inside ignored data/processed.") from None
    if not relative.parts or resolved_output.exists() or resolved_output.is_symlink():
        raise IngestionError("Output must name a new, non-existing child directory.")
    if resolved_output in resolved_inputs:
        raise IngestionError("Output directory cannot replace an input file.")
    if temp_dir is not None and not temp_dir.is_dir():
        raise IngestionError("Temporary directory must already exist.")
    return resolved_output


def ingest_amazon_electronics_metadata(
    *,
    metadata_path: Path,
    train_vocabulary_path: Path,
    temporal_manifest_path: Path,
    output_dir: Path,
    source_id: str,
    source_version: str,
    temp_dir: Path | None = None,
    max_record_bytes: int = _DEFAULT_MAX_RECORD_BYTES,
) -> AmazonMetadataIngestionResult:
    """Stream, match, normalize and atomically publish only train-known products."""
    if not all(_SOURCE_TOKEN.fullmatch(value) for value in (source_id, source_version)):
        raise IngestionError(
            "Source identity and version must be safe non-empty tokens."
        )
    if max_record_bytes < 1:
        raise IngestionError("max_record_bytes must be positive.")
    final_output = _validate_paths(
        metadata_path=metadata_path,
        vocabulary_path=train_vocabulary_path,
        temporal_manifest_path=temporal_manifest_path,
        output_dir=output_dir,
        temp_dir=temp_dir,
    )
    (
        vocabulary_checksum,
        vocabulary_size,
        temporal_manifest_checksum,
        expected_target_count,
    ) = _verified_train_vocabulary(train_vocabulary_path, temporal_manifest_path)
    input_checksum, input_size = sha256_file(metadata_path)
    final_output.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{final_output.name}.tmp-", dir=final_output.parent)
    )
    counts: Counter[str] = Counter()
    rejected: Counter[str] = Counter()
    field_issues: Counter[str] = Counter()
    unknown_fields = 0
    uncompressed_bytes = 0
    exact_duplicate_source_occurrences = 0
    exact_duplicate_matched_occurrences = 0
    sink: _JsonlSink | None = None
    normalized_sink: _JsonlSink | None = None
    try:
        with tempfile.TemporaryDirectory(
            prefix="recfusion-amazon-metadata-", dir=temp_dir
        ) as temporary_dir:
            database = _open_database(Path(temporary_dir) / "metadata-index.sqlite3")
            try:
                target_count = _load_vocabulary_index(train_vocabulary_path, database)
                if target_count != expected_target_count:
                    raise IngestionError(
                        "Item vocabulary rows do not match the temporal manifest."
                    )
                for row_number, line, line_error, byte_count in _iter_gzip_lines(
                    metadata_path, max_record_bytes
                ):
                    del row_number
                    counts["source_records_read"] += 1
                    uncompressed_bytes += byte_count
                    if line_error is not None:
                        rejected[line_error] += 1
                        continue
                    if line is None:
                        rejected["malformed_json"] += 1
                        continue
                    try:
                        source_record = _metadata_line(
                            line, counts["source_records_read"]
                        )
                    except ValueError as error:
                        rejected[str(error)] += 1
                        continue

                    parent_asin = source_record.get("parent_asin")
                    if not isinstance(parent_asin, str) or not parent_asin.strip():
                        rejected["invalid_source_identifier"] += 1
                        continue
                    item_key = amazon_electronics_item_key(parent_asin)
                    is_matched = (
                        database.execute(
                            "SELECT 1 FROM target_items WHERE item_key = ?", (item_key,)
                        ).fetchone()
                        is not None
                    )
                    fingerprint = source_record_fingerprint(
                        source_record,
                        source_id=source_id,
                        source_version=source_version,
                    )
                    counts["valid_source_records"] += 1
                    table_row = database.execute(
                        "SELECT occurrences FROM source_records "
                        "WHERE item_key = ? AND fingerprint = ?",
                        (item_key, fingerprint),
                    ).fetchone()
                    if table_row is None:
                        database.execute(
                            "INSERT INTO source_records VALUES (?, ?, ?, 1)",
                            (item_key, fingerprint, int(is_matched)),
                        )
                    else:
                        database.execute(
                            "UPDATE source_records SET occurrences = occurrences + 1 "
                            "WHERE item_key = ? AND fingerprint = ?",
                            (item_key, fingerprint),
                        )
                        exact_duplicate_source_occurrences += 1
                        if is_matched:
                            exact_duplicate_matched_occurrences += 1

                    if not is_matched:
                        counts["unmatched_source_records"] += 1
                        continue
                    counts["matched_source_records"] += 1
                    mapped: MappedAmazonMetadata = adapt_amazon_metadata_record(
                        source_record,
                        source_id=source_id,
                        source_version=source_version,
                    )
                    field_issues.update(mapped.field_issues)
                    unknown_fields += len(mapped.unknown_fields)
                    if mapped.product.title is None:
                        counts["missing_titles"] += 1
                    if (
                        "images" in source_record
                        and source_record["images"] is not None
                    ):
                        counts["records_with_images_excluded"] += 1
                    if (
                        "videos" in source_record
                        and source_record["videos"] is not None
                    ):
                        counts["records_with_videos_excluded"] += 1
                    product_record = _product_record(mapped.product)
                    product_json = json.dumps(
                        product_record,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                    inserted = database.execute(
                        "INSERT OR IGNORE INTO matched_products VALUES (?, ?, ?)",
                        (item_key, fingerprint, product_json),
                    ).rowcount
                    if inserted:
                        counts["unique_matched_source_records"] += 1
                    if counts["source_records_read"] % 10_000 == 0:
                        database.commit()

                database.commit()
                counts["unique_valid_source_records"] = database.execute(
                    "SELECT COUNT(*) FROM source_records"
                ).fetchone()[0]
                counts["source_conflicting_item_keys"] = database.execute(
                    "SELECT COUNT(*) FROM (SELECT item_key FROM source_records "
                    "GROUP BY item_key HAVING COUNT(*) > 1)"
                ).fetchone()[0]
                counts["matched_conflicting_item_keys"] = database.execute(
                    "SELECT COUNT(*) FROM (SELECT item_key FROM matched_products "
                    "GROUP BY item_key HAVING COUNT(*) > 1)"
                ).fetchone()[0]
                counts["matched_unique_products"] = database.execute(
                    "SELECT COUNT(DISTINCT item_key) FROM matched_products"
                ).fetchone()[0]
                counts["missing_target_products"] = database.execute(
                    "SELECT COUNT(*) FROM target_items AS target WHERE NOT EXISTS "
                    "(SELECT 1 FROM matched_products WHERE item_key = target.item_key)"
                ).fetchone()[0]
                counts["canonical_output_records"] = database.execute(
                    "SELECT COUNT(*) FROM matched_products"
                ).fetchone()[0]
                if (
                    counts["source_records_read"]
                    != counts["valid_source_records"] + sum(rejected.values())
                    or counts["valid_source_records"]
                    != counts["matched_source_records"]
                    + counts["unmatched_source_records"]
                    or counts["matched_source_records"]
                    != counts["unique_matched_source_records"]
                    + exact_duplicate_matched_occurrences
                    or target_count
                    != counts["matched_unique_products"]
                    + counts["missing_target_products"]
                ):
                    raise IngestionError(
                        "Metadata row and join counts do not reconcile."
                    )

                sink = _JsonlSink(staging_dir / "products.jsonl")
                normalized_sink = _JsonlSink(staging_dir / "products.normalized.jsonl")
                for _item_key, fingerprint, product_json, conflict in database.execute(
                    """
                    SELECT product.item_key, product.fingerprint, product.product_json,
                           item_counts.record_count > 1
                    FROM matched_products AS product
                    JOIN (
                        SELECT item_key, COUNT(*) AS record_count
                        FROM matched_products GROUP BY item_key
                    ) AS item_counts USING (item_key)
                    ORDER BY product.item_key COLLATE BINARY,
                             product.fingerprint COLLATE BINARY
                    """
                ):
                    record = cast(dict[str, object], json.loads(product_json))
                    product, _ = validate_product(record, fingerprint)
                    product_output = _product_record(product)
                    sink.write(product_output)
                    attributes = product.attributes
                    raw_price = attributes.get("source_price_raw")
                    invalid_price = attributes.get("source_price_status") == "invalid"
                    normalized = normalize_product_metadata(
                        product,
                        raw_price=raw_price,
                        invalid_price=invalid_price,
                        raw_price_present="source_price_raw" in attributes,
                    )
                    normalized_sink.write(
                        normalized.as_record(
                            product_output,
                            conflict_retained=bool(conflict),
                        )
                    )
                database.close()
            except BaseException:
                database.close()
                raise

        checksum_after, size_after = sha256_file(metadata_path)
        if checksum_after != input_checksum or size_after != input_size:
            raise IngestionError("Metadata source changed during ingestion.")
        vocabulary_checksum_after, vocabulary_size_after = sha256_file(
            train_vocabulary_path
        )
        manifest_checksum_after, _ = sha256_file(temporal_manifest_path)
        if (
            vocabulary_checksum_after != vocabulary_checksum
            or vocabulary_size_after != vocabulary_size
            or manifest_checksum_after != temporal_manifest_checksum
        ):
            raise IngestionError(
                "Train vocabulary or manifest changed during ingestion."
            )
        assert sink is not None
        assert normalized_sink is not None
        outputs = [sink.manifest_record(), normalized_sink.manifest_record()]
        sink.close()
        normalized_sink.close()
        sink = None
        normalized_sink = None
        counts["exact_duplicate_source_occurrences"] = (
            exact_duplicate_source_occurrences
        )
        counts["exact_duplicate_matched_occurrences"] = (
            exact_duplicate_matched_occurrences
        )
        manifest: dict[str, object] = {
            "manifest_schema_version": AMAZON_METADATA_MANIFEST_SCHEMA,
            "source": {
                "id": source_id,
                "version": source_version,
                "format": "amazon-reviews-2023-electronics-metadata-jsonl-gzip",
                "schema_version": "amazon-reviews-2023-metadata-v1",
                "input": {"sha256": input_checksum, "size_bytes": input_size},
            },
            "target_vocabulary": {
                "schema_version": VOCABULARY_SCHEMA,
                "file_sha256": vocabulary_checksum,
                "size_bytes": vocabulary_size,
                "temporal_manifest_sha256": temporal_manifest_checksum,
                "fit_split": "train",
                "item_count": target_count,
                "validation_or_test_used_for_matching": False,
            },
            "configuration": {
                "adapter": "amazon-reviews-2023-electronics-metadata",
                "max_record_bytes": max_record_bytes,
                "sqlite_cache_kib": _SQLITE_CACHE_KIB,
                "item_key_policy": "ar23:Electronics:item:{exact parent_asin}",
                "join_policy": (
                    "exact parent_asin key membership in train-only vocabulary"
                ),
                "duplicate_policy": (
                    "skip exact duplicate source-record fingerprints and count them; "
                    "retain distinct conflicting records for an item key"
                ),
                "snapshot_effective_time": None,
                "average_rating_and_rating_number_features": "excluded",
                "images_and_videos": "excluded from canonical outputs; never fetched",
            },
            "counts": {
                **dict(sorted(counts.items())),
                "rejected_records": sum(rejected.values()),
                "rejected_by_reason": dict(sorted(rejected.items())),
                "field_issues": dict(sorted(field_issues.items())),
                "unknown_source_fields": unknown_fields,
                "uncompressed_bytes_read": uncompressed_bytes,
            },
            "outputs": outputs,
        }
        write_manifest(staging_dir / "manifest.json", manifest)
        if final_output.exists() or final_output.is_symlink():
            raise IngestionError(
                "Output appeared during processing; refusing overwrite."
            )
        os.replace(staging_dir, final_output)
        return AmazonMetadataIngestionResult(final_output, manifest)
    except (OSError, sqlite3.Error, ValueError, zlib.error) as error:
        raise IngestionError(
            "Metadata ingestion failed; no output was published."
        ) from error
    finally:
        if sink is not None:
            sink.close()
        if normalized_sink is not None:
            normalized_sink.close()
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
