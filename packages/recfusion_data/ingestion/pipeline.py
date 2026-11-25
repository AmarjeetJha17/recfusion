"""Streaming ingestion orchestration with train-only sampling and atomic output."""

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
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from recfusion_core.contracts import DataSplit, Interaction, ProductMetadata
from recfusion_data.ingestion.adapters import CanonicalSourceAdapter, SourceAdapter
from recfusion_data.ingestion.errors import (
    AdapterError,
    IngestionError,
    RecordValidationError,
    SourceReadError,
    ValidationIssue,
)
from recfusion_data.ingestion.manifest import (
    sha256_file,
    source_record_fingerprint,
    write_manifest,
)
from recfusion_data.ingestion.readers import InputFormat, SourceRow, read_records
from recfusion_data.normalization import normalize_product_metadata
from recfusion_data.splitting.sampling import select_train_users
from recfusion_data.validation import validate_interaction, validate_product

SCHEMA_VERSION = "recfusion.canonical.v1"
_SPLITS = (DataSplit.TRAIN, DataSplit.VALIDATION, DataSplit.TEST)
_SAFE_SOURCE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_PROCESSED_ROOT = (_REPOSITORY_ROOT / "data" / "processed").resolve()


@dataclass(frozen=True, slots=True)
class IngestionResult:
    output_dir: Path
    manifest: Mapping[str, object]
    selected_user_count: int | None


class _JsonlSink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.file: TextIO = path.open("w", encoding="utf-8", newline="\n")
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

    def output_manifest(self) -> dict[str, object]:
        return {
            "file": self.path.name,
            "records": self.record_count,
            "sha256": self.digest.hexdigest(),
        }


class _DuplicateIndex:
    """Disk-backed exact-duplicate index so event rows are not retained in RAM."""

    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=OFF")
        self.connection.execute("PRAGMA synchronous=OFF")
        self.connection.execute("PRAGMA temp_store=FILE")
        self.connection.execute("PRAGMA cache_size=-8192")
        self.connection.executescript(
            """
            CREATE TABLE interaction_rows (
                fingerprint TEXT NOT NULL,
                split TEXT NOT NULL,
                PRIMARY KEY (fingerprint, split)
            ) WITHOUT ROWID;
            CREATE TABLE first_interaction_split (
                fingerprint TEXT PRIMARY KEY,
                split TEXT NOT NULL
            ) WITHOUT ROWID;
            CREATE TABLE product_rows (
                item_key TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                PRIMARY KEY (item_key, fingerprint)
            ) WITHOUT ROWID;
            CREATE TABLE first_product_fingerprint (
                item_key TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL
            ) WITHOUT ROWID;
            CREATE TABLE normalized_products (
                item_key TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (item_key, fingerprint)
            ) WITHOUT ROWID;
            CREATE TABLE interaction_payloads (
                payload_id INTEGER PRIMARY KEY,
                split TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX interaction_payload_order
            ON interaction_payloads (split, fingerprint, payload);
            """
        )

    def interaction_status(self, fingerprint: str, split: DataSplit) -> str:
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO interaction_rows VALUES (?, ?)",
            (fingerprint, split.value),
        )
        if cursor.rowcount == 0:
            return "duplicate"
        row = self.connection.execute(
            "SELECT split FROM first_interaction_split WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if row is None:
            self.connection.execute(
                "INSERT INTO first_interaction_split VALUES (?, ?)",
                (fingerprint, split.value),
            )
            return "new"
        return "cross_split" if row[0] != split.value else "new"

    def product_status(self, item_key: str, fingerprint: str) -> str:
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO product_rows VALUES (?, ?)",
            (item_key, fingerprint),
        )
        if cursor.rowcount == 0:
            return "duplicate"
        row = self.connection.execute(
            "SELECT fingerprint FROM first_product_fingerprint WHERE item_key = ?",
            (item_key,),
        ).fetchone()
        if row is None:
            self.connection.execute(
                "INSERT INTO first_product_fingerprint VALUES (?, ?)",
                (item_key, fingerprint),
            )
            return "new"
        return "conflict" if row[0] != fingerprint else "new"

    def add_normalized_product(
        self, item_key: str, fingerprint: str, record: Mapping[str, object]
    ) -> None:
        payload = json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        self.connection.execute(
            "INSERT INTO normalized_products VALUES (?, ?, ?)",
            (item_key, fingerprint, payload),
        )

    def add_interaction_payload(
        self, split: DataSplit, fingerprint: str, record: Mapping[str, object]
    ) -> None:
        payload = json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        self.connection.execute(
            "INSERT INTO interaction_payloads (split, fingerprint, payload) "
            "VALUES (?, ?, ?)",
            (split.value, fingerprint, payload),
        )

    def iter_interaction_payloads(
        self, split: DataSplit
    ) -> Iterator[dict[str, object]]:
        cursor = self.connection.execute(
            "SELECT payload FROM interaction_payloads WHERE split = ? "
            "ORDER BY fingerprint, payload",
            (split.value,),
        )
        for (payload,) in cursor:
            yield json.loads(payload)

    def iter_normalized_products(self) -> Iterator[dict[str, object]]:
        cursor = self.connection.execute(
            """
            SELECT item_key, payload, COUNT(*) OVER (PARTITION BY item_key)
            FROM normalized_products
            ORDER BY item_key, fingerprint
            """
        )
        for _item_key, payload, item_count in cursor:
            record: dict[str, object] = json.loads(payload)
            normalization = record["normalization"]
            if not isinstance(normalization, dict):
                raise IngestionError("Invalid normalized product spool record.")
            normalization["product_decision"] = (
                "conflict_retained" if item_count > 1 else "unique_retained"
            )
            yield record

    def close(self) -> None:
        self.connection.commit()
        self.connection.close()


def _issue_counts(issues: tuple[ValidationIssue, ...], failures: Counter[str]) -> None:
    failures.update(issue.code for issue in issues)


def _fingerprint(
    record: Mapping[str, object], source_id: str, source_version: str
) -> str:
    try:
        return source_record_fingerprint(
            record, source_id=source_id, source_version=source_version
        )
    except (TypeError, ValueError):
        raise AdapterError("unfingerprintable_record") from None


def _normalize_interaction(
    row: SourceRow,
    *,
    split: DataSplit,
    source_id: str,
    source_version: str,
    adapter: SourceAdapter,
) -> tuple[Interaction | None, tuple[ValidationIssue, ...]]:
    if row.error_code is not None:
        return None, (ValidationIssue(row.error_code),)
    if row.values is None:
        return None, (ValidationIssue("empty_record"),)
    try:
        values = adapter.interaction_fields(row.values, split)
        fingerprint = _fingerprint(row.values, source_id, source_version)
        return (
            validate_interaction(values, split, fingerprint),
            (),
        )
    except AdapterError as error:
        return None, (ValidationIssue(error.code, error.field),)
    except RecordValidationError as error:
        return None, error.issues


def _normalize_product(
    row: SourceRow,
    *,
    source_id: str,
    source_version: str,
    adapter: SourceAdapter,
) -> tuple[
    ProductMetadata | None, tuple[ValidationIssue, ...], tuple[ValidationIssue, ...]
]:
    if row.error_code is not None:
        return None, (ValidationIssue(row.error_code),), ()
    if row.values is None:
        return None, (ValidationIssue("empty_record"),), ()
    try:
        values = adapter.product_fields(row.values)
        fingerprint = _fingerprint(row.values, source_id, source_version)
        product, warnings = validate_product(values, fingerprint)
        return product, (), warnings
    except AdapterError as error:
        return None, (ValidationIssue(error.code, error.field),), ()
    except RecordValidationError as error:
        return None, error.issues, ()


def _interaction_record(interaction: Interaction) -> dict[str, object]:
    return {
        "event_time_ms": interaction.event_time_ms,
        "item_key": interaction.item_key,
        "rating": str(interaction.rating),
        "source_event_fingerprint": interaction.source_event_fingerprint,
        "split": interaction.split.value,
        "user_key": interaction.user_key,
    }


def _product_record(product: ProductMetadata) -> dict[str, object]:
    price: dict[str, str] | None = None
    if product.price is not None:
        price = {
            "amount": str(product.price.amount),
            "currency": product.price.currency,
        }
    return {
        "attributes": product.attributes,
        "average_rating": (
            str(product.average_rating) if product.average_rating is not None else None
        ),
        "categories": product.categories,
        "category": product.category,
        "description": product.description,
        "features": product.features,
        "images": product.images,
        "item_key": product.item_key,
        "price": price,
        "rating_count": product.rating_count,
        "source_record_fingerprint": product.source_record_fingerprint,
        "title": product.title,
        "videos": product.videos,
    }


def _new_split_counts() -> dict[str, int]:
    return {
        "input_records": 0,
        "valid_records": 0,
        "rejected_records": 0,
        "duplicate_rows_skipped": 0,
        "filtered_unselected_users": 0,
        "output_records": 0,
    }


def _validate_inputs(
    files: Mapping[str, Path],
    *,
    source_id: str,
    source_version: str,
    max_users: int,
    seed: str,
    output_dir: Path,
) -> tuple[Path, dict[str, dict[str, object]]]:
    if not all(
        _SAFE_SOURCE_TOKEN.fullmatch(value)
        for value in (source_id, source_version, seed)
    ):
        raise IngestionError(
            "Source identity, version, and seed must be non-empty safe tokens."
        )
    if max_users < 1:
        raise IngestionError("max_users must be positive.")
    resolved_inputs: set[Path] = set()
    for role, path in files.items():
        resolved = path.resolve()
        if resolved in resolved_inputs:
            raise IngestionError(
                "Each split and product input must be a distinct file."
            )
        resolved_inputs.add(resolved)
        if not path.is_file():
            raise IngestionError(f"Required {role} input is not a local file.")

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

    file_manifest: dict[str, dict[str, object]] = {}
    for role, path in files.items():
        try:
            checksum, size = sha256_file(path)
        except ValueError as error:
            raise IngestionError(f"Cannot read {role} input checksum.") from error
        file_manifest[role] = {
            "file": path.name,
            "sha256": checksum,
            "size_bytes": size,
        }
    return resolved_output, file_manifest


def _eligible_train_users(
    path: Path,
    *,
    input_format: InputFormat,
    source_id: str,
    source_version: str,
    adapter: SourceAdapter,
) -> set[str]:
    eligible: set[str] = set()
    for row in read_records(
        path,
        input_format,
        expected_csv_headers=getattr(adapter, "csv_headers", None),
    ):
        interaction, _ = _normalize_interaction(
            row,
            split=DataSplit.TRAIN,
            source_id=source_id,
            source_version=source_version,
            adapter=adapter,
        )
        if interaction is not None:
            eligible.add(interaction.user_key)
    return eligible


def _process_split(
    *,
    split: DataSplit,
    path: Path,
    input_format: InputFormat,
    selected_users: frozenset[str] | None,
    source_id: str,
    source_version: str,
    adapter: SourceAdapter,
    sink: _JsonlSink,
    duplicate_index: _DuplicateIndex,
    counts: dict[str, int],
    failures: Counter[str],
    cross_split_duplicates: Counter[str],
    selected_train_items: set[str],
    rejection_sink: _JsonlSink | None = None,
) -> None:
    for row in read_records(
        path,
        input_format,
        expected_csv_headers=getattr(adapter, "csv_headers", None),
    ):
        counts["input_records"] += 1
        interaction, issues = _normalize_interaction(
            row,
            split=split,
            source_id=source_id,
            source_version=source_version,
            adapter=adapter,
        )
        if interaction is None:
            counts["rejected_records"] += 1
            _issue_counts(issues, failures)
            if rejection_sink is not None:
                rejection_sink.write(
                    _rejection_record(
                        split=split,
                        row_number=row.row_number,
                        values=row.values,
                        issues=issues,
                        source_id=source_id,
                        source_version=source_version,
                    )
                )
                counts["rejection_audit_records"] += 1
            continue

        counts["valid_records"] += 1
        if (
            selected_users is not None
            and split is DataSplit.TRAIN
            and interaction.user_key in selected_users
        ):
            selected_train_items.add(interaction.item_key)

        duplicate_status = duplicate_index.interaction_status(
            interaction.source_event_fingerprint, split
        )
        if duplicate_status == "duplicate":
            if getattr(adapter, "retain_exact_duplicates", False):
                counts["exact_duplicate_occurrences"] += 1
                counts["duplicate_rows_retained"] += 1
            else:
                counts["duplicate_rows_skipped"] += 1
                if rejection_sink is not None:
                    rejection_sink.write(
                        {
                            "reason": "exact_duplicate",
                            "source_event_fingerprint": (
                                interaction.source_event_fingerprint
                            ),
                            "source_row_number": row.row_number,
                            "split": split.value,
                        }
                    )
                    counts["rejection_audit_records"] += 1
                continue
        if duplicate_status == "cross_split":
            cross_split_duplicates["interaction"] += 1
        if selected_users is not None and interaction.user_key not in selected_users:
            counts["filtered_unselected_users"] += 1
            continue
        interaction_record = _interaction_record(interaction)
        if getattr(adapter, "deterministic_interaction_order", False):
            duplicate_index.add_interaction_payload(
                split, interaction.source_event_fingerprint, interaction_record
            )
        else:
            sink.write(interaction_record)
        counts["output_records"] += 1


def _rejection_record(
    *,
    split: DataSplit,
    row_number: int,
    values: Mapping[str, object] | None,
    issues: tuple[ValidationIssue, ...],
    source_id: str,
    source_version: str,
) -> dict[str, object]:
    fingerprint: str | None = None
    if values is not None:
        with suppress(AdapterError):
            fingerprint = _fingerprint(values, source_id, source_version)
    return {
        "reasons": [{"code": issue.code, "field": issue.field} for issue in issues],
        "source_event_fingerprint": fingerprint,
        "source_row_number": row_number,
        "split": split.value,
    }


def _process_products(
    *,
    path: Path | None,
    input_format: InputFormat,
    selected_train_items: set[str],
    source_id: str,
    source_version: str,
    adapter: SourceAdapter,
    sink: _JsonlSink,
    duplicate_index: _DuplicateIndex,
    failures: Counter[str],
    warnings: Counter[str],
    normalized_products: bool,
    normalization_counts: Counter[str],
) -> dict[str, int]:
    counts = {
        "input_records": 0,
        "valid_records": 0,
        "rejected_records": 0,
        "duplicate_rows_skipped": 0,
        "conflicting_item_rows": 0,
        "filtered_not_in_selected_train": 0,
        "output_records": 0,
    }
    if path is None:
        return counts

    for row in read_records(path, input_format):
        counts["input_records"] += 1
        product, issues, record_warnings = _normalize_product(
            row,
            source_id=source_id,
            source_version=source_version,
            adapter=adapter,
        )
        _issue_counts(record_warnings, warnings)
        if product is None:
            counts["rejected_records"] += 1
            _issue_counts(issues, failures)
            continue

        counts["valid_records"] += 1
        duplicate_status = duplicate_index.product_status(
            product.item_key, product.source_record_fingerprint
        )
        if duplicate_status == "duplicate":
            counts["duplicate_rows_skipped"] += 1
            continue
        if duplicate_status == "conflict":
            counts["conflicting_item_rows"] += 1
        if product.item_key not in selected_train_items:
            counts["filtered_not_in_selected_train"] += 1
            continue
        sink.write(_product_record(product))
        if normalized_products:
            normalized = normalize_product_metadata(
                product,
                raw_price=(row.values.get("price") if row.values is not None else None),
                invalid_price=any(issue.field == "price" for issue in record_warnings),
                raw_price_present=(row.values is not None and "price" in row.values),
            )
            record = normalized.as_record(
                _product_record(product), conflict_retained=None
            )
            duplicate_index.add_normalized_product(
                product.item_key, product.source_record_fingerprint, record
            )
            fields = {
                "brand": normalized.brand,
                "category": normalized.category,
                "price": normalized.price,
                **normalized.specifications,
            }
            for name, value in fields.items():
                normalization_counts[f"{name}.{value.status.value}"] += 1
        counts["output_records"] += 1
    return counts


def ingest_local_files(
    *,
    train_path: Path,
    validation_path: Path,
    test_path: Path,
    product_path: Path | None,
    input_format: InputFormat,
    product_format: InputFormat,
    output_dir: Path,
    source_id: str,
    source_version: str,
    seed: str,
    max_users: int,
    adapter: SourceAdapter | None = None,
    normalize_products: bool = False,
) -> IngestionResult:
    """Ingest canonical local files and atomically publish a new output directory."""
    source_adapter = adapter or CanonicalSourceAdapter()
    if product_path is not None and not getattr(
        source_adapter, "supports_products", True
    ):
        raise IngestionError("The selected source adapter does not accept products.")
    files = {
        "train": train_path,
        "validation": validation_path,
        "test": test_path,
    }
    if product_path is not None:
        files["products"] = product_path
    final_output, source_manifest = _validate_inputs(
        files,
        source_id=source_id,
        source_version=source_version,
        max_users=max_users,
        seed=seed,
        output_dir=output_dir,
    )
    preserve_all_users = getattr(source_adapter, "preserve_all_users", False)
    if preserve_all_users:
        eligible_users = None
        selected_users = None
        selected_user_count = None
    else:
        eligible_users = _eligible_train_users(
            train_path,
            input_format=input_format,
            source_id=source_id,
            source_version=source_version,
            adapter=source_adapter,
        )
        selected_users = select_train_users(
            eligible_users,
            max_users=max_users,
            seed=seed,
            source_id=source_id,
        )
        selected_user_count = len(selected_users)

    final_output.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{final_output.name}.tmp-", dir=final_output.parent)
    )
    split_counts = {split.value: _new_split_counts() for split in _SPLITS}
    if getattr(source_adapter, "retain_exact_duplicates", False):
        for split_record_counts in split_counts.values():
            split_record_counts["exact_duplicate_occurrences"] = 0
            split_record_counts["duplicate_rows_retained"] = 0
    failures: Counter[str] = Counter()
    warnings: Counter[str] = Counter()
    cross_split_duplicates: Counter[str] = Counter()
    selected_train_items: set[str] = set()
    output_manifests: list[dict[str, object]] = []
    normalization_counts: Counter[str] = Counter()
    normalized_sink: _JsonlSink | None = None
    rejection_sinks: dict[DataSplit, _JsonlSink] = {}

    try:
        with tempfile.TemporaryDirectory(prefix="recfusion-ingest-index-") as scratch:
            duplicate_index = _DuplicateIndex(Path(scratch) / "duplicates.sqlite3")
            split_sinks: dict[DataSplit, _JsonlSink] = {}
            product_sink: _JsonlSink | None = None
            try:
                for split in _SPLITS:
                    sink = _JsonlSink(staging_dir / f"interactions.{split.value}.jsonl")
                    split_sinks[split] = sink
                    rejection_sink = None
                    if getattr(source_adapter, "record_rejections", False):
                        rejection_sink = _JsonlSink(
                            staging_dir / f"rejections.{split.value}.jsonl"
                        )
                        rejection_sinks[split] = rejection_sink
                        split_counts[split.value]["rejection_audit_records"] = 0
                    _process_split(
                        split=split,
                        path=files[split.value],
                        input_format=input_format,
                        selected_users=selected_users,
                        source_id=source_id,
                        source_version=source_version,
                        adapter=source_adapter,
                        sink=sink,
                        duplicate_index=duplicate_index,
                        counts=split_counts[split.value],
                        failures=failures,
                        cross_split_duplicates=cross_split_duplicates,
                        selected_train_items=selected_train_items,
                        rejection_sink=rejection_sink,
                    )
                product_sink = _JsonlSink(staging_dir / "products.jsonl")
                product_counts = _process_products(
                    path=product_path,
                    input_format=product_format,
                    selected_train_items=selected_train_items,
                    source_id=source_id,
                    source_version=source_version,
                    adapter=source_adapter,
                    sink=product_sink,
                    duplicate_index=duplicate_index,
                    failures=failures,
                    warnings=warnings,
                    normalized_products=normalize_products,
                    normalization_counts=normalization_counts,
                )
                if normalize_products:
                    normalized_sink = _JsonlSink(
                        staging_dir / "products.normalized.jsonl"
                    )
                    for record in duplicate_index.iter_normalized_products():
                        normalized_sink.write(record)
                if getattr(source_adapter, "deterministic_interaction_order", False):
                    for split in _SPLITS:
                        for record in duplicate_index.iter_interaction_payloads(split):
                            split_sinks[split].write(record)
            finally:
                for sink in split_sinks.values():
                    sink.close()
                if product_sink is not None:
                    product_sink.close()
                if normalized_sink is not None:
                    normalized_sink.close()
                for sink in rejection_sinks.values():
                    sink.close()
                duplicate_index.close()

        if product_sink is None:
            raise IngestionError("Product output sink was not initialized.")
        output_manifests = (
            [split_sinks[split].output_manifest() for split in _SPLITS]
            + [product_sink.output_manifest()]
            + [
                rejection_sinks[split].output_manifest()
                for split in _SPLITS
                if split in rejection_sinks
            ]
        )
        if normalized_sink is not None:
            output_manifests.append(normalized_sink.output_manifest())
        configuration: dict[str, object] = {
            "interaction_format": input_format.value,
            "product_format": product_format.value,
            "duplicate_policy": (
                "retain and count exact source duplicates for Step 2.4 "
                "preprocessing; do not assign unique event IDs"
                if getattr(source_adapter, "retain_exact_duplicates", False)
                else "skip exact duplicates within a split; retain and count "
                "identical fingerprints appearing in different splits"
            ),
            "product_conflict_policy": (
                "skip exact duplicate rows; retain and count differing rows "
                "for the same item key"
            ),
            "product_filter": (
                "items in selected users' training interactions only"
                if selected_users is not None
                else "not applicable; source adapter disables product input"
            ),
        }
        adapter_configuration = getattr(source_adapter, "manifest_configuration", None)
        if adapter_configuration is not None:
            configuration.update(adapter_configuration)
        counts: dict[str, object] = {
            "interactions_by_split": split_counts,
            "products": product_counts,
            "cross_split_duplicate_interactions": cross_split_duplicates["interaction"],
            "validation_failures": dict(sorted(failures.items())),
            "warnings": dict(sorted(warnings.items())),
        }
        if normalize_products:
            configuration["normalize_products"] = True
            configuration["product_normalization_schema_version"] = (
                "recfusion.product-normalization.v1"
            )
            counts["product_normalization"] = {
                "records": product_counts["output_records"],
                "field_statuses": dict(sorted(normalization_counts.items())),
            }

        manifest: dict[str, object] = {
            "manifest_schema_version": 1,
            "canonical_schema_version": SCHEMA_VERSION,
            "source": {
                "id": source_id,
                "version": source_version,
                "files": source_manifest,
            },
            "sampling": (
                {
                    "eligibility": "all valid source records",
                    "max_users": None,
                    "seed": seed,
                    "selected_users": None,
                    "train_eligible_users": None,
                    "policy": "preserve all records and assigned source splits",
                }
                if selected_users is None
                else {
                    "eligibility": "at least one valid training interaction",
                    "max_users": max_users,
                    "seed": seed,
                    "selected_users": len(selected_users),
                    "train_eligible_users": len(eligible_users or ()),
                    "policy": (
                        "SHA-256 rank of eligible training users; order-independent"
                    ),
                }
            ),
            "configuration": configuration,
            "counts": counts,
            "outputs": output_manifests,
        }
        write_manifest(staging_dir / "manifest.json", manifest)
        os.rename(staging_dir, final_output)
        return IngestionResult(
            output_dir=final_output,
            manifest=manifest,
            selected_user_count=selected_user_count,
        )
    except (OSError, sqlite3.Error, SourceReadError, ValueError) as error:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        if isinstance(error, IngestionError):
            raise
        raise IngestionError("Ingestion failed; no output was published.") from error
