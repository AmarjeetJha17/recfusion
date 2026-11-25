"""Reproducible synthetic-only Phase 2 pipeline and release audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import tracemalloc
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import cast

from recfusion_data.features.generation import (
    FEATURE_INTERACTION_SCHEMA,
    FEATURE_ITEM_SCHEMA,
    FEATURE_MANIFEST_SCHEMA,
    FEATURE_SCHEMA_VERSION,
    TRANSFORMERS_SCHEMA_VERSION,
    generate_features,
)
from recfusion_data.ingestion.errors import IngestionError
from recfusion_data.ingestion.manifest import sha256_file, write_manifest
from recfusion_data.ingestion.pipeline import ingest_local_files
from recfusion_data.ingestion.readers import InputFormat
from recfusion_data.preprocessing.interactions import (
    DERIVED_SCHEMA_VERSION,
    preprocess_interaction_files,
)
from recfusion_data.splitting.temporal import (
    MANIFEST_SCHEMA,
    TemporalCutoffs,
    process_trusted_pre_split,
)

RELEASE_SCHEMA_VERSION = "recfusion.synthetic-data-release.v1"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_PROCESSED_ROOT = (_REPOSITORY_ROOT / "data" / "processed").resolve()
_FIXTURE_ROOT = _REPOSITORY_ROOT / "tests" / "fixtures" / "phase2_release"
_FIXTURE_FILES = ("train.jsonl", "validation.jsonl", "test.jsonl", "products.jsonl")
_SOURCE_ID = "synthetic-phase2-release"
_SOURCE_VERSION = "v1"
_SEED = "recfusion-phase2-synthetic-release-v1"
_MAX_USERS = 10
_CUTOFFS = TemporalCutoffs(5_000, 10_000)


class ReleaseValidationError(IngestionError):
    """Raised when the synthetic release does not meet its validation gate."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseValidationError(f"Cannot read manifest {path.name}.") from error
    if not isinstance(value, dict):
        raise ReleaseValidationError(f"Manifest {path.name} must be a JSON object.")
    return cast(dict[str, object], value)


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ReleaseValidationError(f"Malformed {label} contract.")
    return cast(dict[str, object], value)


def _jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    try:
        with path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ReleaseValidationError(
                        f"Invalid JSONL in {path.name} at row {line_number}."
                    ) from error
                if not isinstance(value, dict):
                    raise ReleaseValidationError(
                        f"Non-object JSONL row in {path.name} at row {line_number}."
                    )
                records.append(cast(dict[str, object], value))
    except OSError as error:
        raise ReleaseValidationError(f"Cannot read output {path.name}.") from error
    return records


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseValidationError(message)


def _verify_stage_outputs(
    directory: Path, manifest: Mapping[str, object]
) -> list[dict[str, object]]:
    raw_outputs = manifest.get("outputs")
    _require(isinstance(raw_outputs, list), f"{directory.name} has no output list.")
    verified: list[dict[str, object]] = []
    names: set[str] = set()
    for raw in cast(list[object], raw_outputs):
        output = _mapping(raw, f"{directory.name} output")
        name = output.get("file")
        expected_hash = output.get("sha256")
        _require(
            isinstance(name, str)
            and Path(name).name == name
            and "/" not in name
            and "\\" not in name,
            f"{directory.name} has an unsafe output name.",
        )
        _require(
            isinstance(expected_hash, str), f"{directory.name} has no output hash."
        )
        if name in names:
            raise ReleaseValidationError(f"{directory.name} repeats output {name}.")
        names.add(cast(str, name))
        path = directory / cast(str, name)
        try:
            actual_hash, actual_size = sha256_file(path)
        except ValueError as error:
            raise ReleaseValidationError(
                f"Cannot checksum {directory.name}/{name}."
            ) from error
        _require(
            actual_hash == expected_hash,
            f"Checksum mismatch for {directory.name}/{name}.",
        )
        expected_size = output.get("size_bytes")
        _require(
            not isinstance(expected_size, int)
            or isinstance(expected_size, bool)
            or actual_size == expected_size,
            f"Size mismatch for {directory.name}/{name}.",
        )
        verified.append(
            {
                "file": str(Path(directory.name) / cast(str, name)).replace("\\", "/"),
                "sha256": actual_hash,
                "size_bytes": actual_size,
                "records": output.get("records"),
            }
        )
    return verified


def _output_manifest(
    directory: Path, expected_schema: str | int
) -> tuple[dict[str, object], list[dict[str, object]]]:
    manifest = _read_json(directory / "manifest.json")
    _require(
        manifest.get("manifest_schema_version") == expected_schema,
        f"Unexpected manifest version in {directory.name}.",
    )
    return manifest, _verify_stage_outputs(directory, manifest)


def _walk_output_hashes(root: Path) -> list[dict[str, object]]:
    outputs: list[dict[str, object]] = []
    for path in sorted(
        root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()
    ):
        if path.is_symlink():
            raise ReleaseValidationError("Release artifacts cannot contain symlinks.")
        if not path.is_file() or path.name == "release-manifest.json":
            continue
        digest, size = sha256_file(path)
        outputs.append(
            {
                "file": path.relative_to(root).as_posix(),
                "sha256": digest,
                "size_bytes": size,
            }
        )
    return outputs


def _tree_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _input_provenance(fixture_root: Path) -> dict[str, dict[str, object]]:
    provenance: dict[str, dict[str, object]] = {}
    for name in _FIXTURE_FILES:
        path = fixture_root / name
        if not path.is_file():
            raise ReleaseValidationError(
                f"Required synthetic fixture is missing: {name}."
            )
        digest, size = sha256_file(path)
        provenance[name] = {"sha256": digest, "size_bytes": size}
    return provenance


def _assert_schema_records(
    records: Sequence[Mapping[str, object]], schema_version: str, label: str
) -> None:
    _require(
        all(record.get("schema_version") == schema_version for record in records),
        f"{label} contains an unexpected record schema.",
    )


def _validate_pipeline(
    *,
    root: Path,
    input_hashes: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    ingestion_dir = root / "ingestion"
    preprocessing_dir = root / "preprocessing"
    temporal_dir = root / "temporal"
    features_dir = root / "features"

    ingestion, ingestion_outputs = _output_manifest(ingestion_dir, 1)
    preprocessing, preprocessing_outputs = _output_manifest(
        preprocessing_dir, "recfusion.interaction-manifest.v1"
    )
    temporal, temporal_outputs = _output_manifest(temporal_dir, MANIFEST_SCHEMA)
    features, feature_outputs = _output_manifest(features_dir, FEATURE_MANIFEST_SCHEMA)

    _require(
        ingestion.get("canonical_schema_version") == "recfusion.canonical.v1",
        "Unexpected canonical schema.",
    )
    ingestion_config = _mapping(ingestion.get("configuration"), "ingestion config")
    _require(
        ingestion_config.get("normalize_products") is True,
        "Product normalization must remain opt-in and explicitly enabled.",
    )
    ingestion_counts = _mapping(ingestion.get("counts"), "ingestion counts")
    source_info = _mapping(ingestion.get("source"), "ingestion source")
    source_files = _mapping(source_info.get("files"), "ingestion source files")
    expected_source_roles = {
        "train": "train.jsonl",
        "validation": "validation.jsonl",
        "test": "test.jsonl",
        "products": "products.jsonl",
    }
    for role, filename in expected_source_roles.items():
        source_record = _mapping(source_files.get(role), f"input {role} checksum")
        input_record = _mapping(input_hashes.get(filename), f"fixture {filename}")
        _require(
            source_record.get("sha256") == input_record.get("sha256")
            and source_record.get("size_bytes") == input_record.get("size_bytes"),
            f"Ingestion manifest input provenance mismatch for {filename}.",
        )
    ingestion_splits = _mapping(
        ingestion_counts.get("interactions_by_split"), "ingestion split counts"
    )
    _require(
        ingestion_counts.get("cross_split_duplicate_interactions") == 0,
        "Cross-split duplicate interactions block synthetic release.",
    )

    preprocessing_quality = _mapping(
        preprocessing.get("quality_report"), "preprocessing quality report"
    )
    descriptive = _mapping(
        preprocessing_quality.get("descriptive_all_splits"),
        "whole-dataset preprocessing report",
    )
    temporal_integrity = _mapping(
        temporal.get("integrity_status"), "temporal integrity status"
    )
    temporal_counts = _mapping(temporal.get("counts"), "temporal counts")
    temporal_split_counts = _mapping(
        temporal_counts.get("split_counts"), "temporal per-split counts"
    )
    feature_counts = _mapping(features.get("counts"), "feature counts")
    feature_integrity = _mapping(features.get("integrity"), "feature integrity")
    feature_configuration = _mapping(
        features.get("configuration"), "feature configuration"
    )

    _require(
        temporal_integrity.get("evaluation_eligible") is True,
        "Temporal integrity blocks release.",
    )
    _require(
        features.get("feature_schema_version") == FEATURE_SCHEMA_VERSION,
        "Unexpected feature schema.",
    )
    _require(
        feature_integrity.get("training_only_vocabulary_fit") is True,
        "Feature vocabulary was not fit on train only.",
    )
    _require(
        feature_integrity.get("training_only_history") is True,
        "Feature history was not train-only.",
    )
    _require(
        feature_integrity.get("simultaneous_events_excluded") is True,
        "Simultaneous events were not excluded.",
    )
    _require(
        feature_configuration.get("history_time_rule")
        == "event_time_ms strictly less than target timestamp",
        "Feature history boundary policy changed.",
    )
    _require(
        feature_configuration.get("validation_test_history")
        == "training interactions only",
        "Held-out history policy changed.",
    )
    _require(
        feature_integrity.get("held_out_records_preserved") is True,
        "Held-out records were not preserved.",
    )
    _require(
        feature_integrity.get("conflicting_product_metadata_merged") is False,
        "Conflicting product records were merged.",
    )
    _require(
        feature_integrity.get("historical_metadata_availability_proven") is False,
        "Snapshot metadata was misrepresented as historical.",
    )

    feature_interactions = _jsonl(features_dir / "interactions.features.jsonl")
    feature_items = _jsonl(features_dir / "items.features.jsonl")
    _assert_schema_records(
        feature_interactions, FEATURE_INTERACTION_SCHEMA, "Feature interactions"
    )
    _assert_schema_records(feature_items, FEATURE_ITEM_SCHEMA, "Feature items")
    _require(
        all(
            "user_key" not in row and "item_key" not in row
            for row in feature_interactions
        ),
        "Feature interactions expose raw user or item keys.",
    )
    _require(
        all("user_key" not in row and "item_key" not in row for row in feature_items),
        "Item feature artifact contains raw identity keys.",
    )

    vocabulary_users = _jsonl(temporal_dir / "vocabulary.users.jsonl")
    vocabulary_items = _jsonl(temporal_dir / "vocabulary.items.jsonl")
    candidates = _jsonl(temporal_dir / "candidate-pool.items.jsonl")
    _require(
        vocabulary_users[0].get("index") == 0
        and vocabulary_users[0].get("is_unknown") is True
        and vocabulary_items[0].get("index") == 0
        and vocabulary_items[0].get("is_unknown") is True,
        "Train vocabularies do not reserve unknown index 0.",
    )
    train_keys = {
        str(row.get("source_key"))
        for row in vocabulary_users[1:] + vocabulary_items[1:]
    }
    _require(
        all(
            str(row.get("source_key")) not in train_keys
            for row in vocabulary_users[:1] + vocabulary_items[:1]
        ),
        "Unknown vocabulary entries unexpectedly contain source IDs.",
    )
    train_item_indices = {
        cast(int, row["index"])
        for row in vocabulary_items[1:]
        if isinstance(row.get("index"), int)
    }
    candidate_indices = {
        cast(int, row["item_index"])
        for row in candidates
        if isinstance(row.get("item_index"), int)
    }
    _require(
        candidate_indices == train_item_indices,
        "Candidate pool is not exactly the train-fitted item vocabulary.",
    )
    feature_item_indices = {
        cast(int, row["item_index"])
        for row in feature_items
        if isinstance(row.get("item_index"), int)
    }
    _require(
        feature_item_indices == train_item_indices | {0},
        "Item features include held-out catalog items or omit train items.",
    )
    interaction_splits = {
        split: [row for row in feature_interactions if row.get("split") == split]
        for split in ("train", "validation", "test")
    }
    _require(
        all(
            len(interaction_splits[split])
            == cast(
                int,
                _mapping(temporal_split_counts.get(split), split).get(
                    "input_accepted_records", -1
                ),
            )
            for split in interaction_splits
        ),
        "Final feature row counts disagree with temporal outputs.",
    )
    _require(
        all(row.get("user_index") != 0 for row in interaction_splits["train"]),
        "Training interactions unexpectedly map to the unknown user index.",
    )
    _require(
        all(row.get("item_index") != 0 for row in interaction_splits["train"]),
        "Training interactions unexpectedly map to the unknown item index.",
    )
    _require(
        any(
            row.get("item_index") == 0
            for row in feature_interactions
            if row.get("split") != "train"
        ),
        "Synthetic held-out cold-item case did not map to unknown index 0.",
    )

    temporal_records = {
        split: _jsonl(temporal_dir / f"interactions.{split}.jsonl")
        for split in ("train", "validation", "test")
    }
    boundary_events: dict[int, object] = {}
    for records in temporal_records.values():
        for row in records:
            interaction = row.get("interaction")
            if isinstance(interaction, dict):
                timestamp = interaction.get("event_time_ms")
                if isinstance(timestamp, int) and not isinstance(timestamp, bool):
                    boundary_events[timestamp] = row.get("split")
    _require(
        boundary_events.get(5_000) == "validation",
        "Inclusive validation cutoff is incorrect.",
    )
    _require(
        boundary_events.get(10_000) == "test", "Inclusive test cutoff is incorrect."
    )
    same_time_test = [
        row for row in interaction_splits["test"] if row.get("event_time_ms") == 10_000
    ]
    _require(
        len(same_time_test) == 2,
        "Equal-timestamp synthetic test events were not retained.",
    )
    same_time_histories = [
        _mapping(row.get("history"), "same-time history") for row in same_time_test
    ]
    _require(
        all(
            history.get("policy") == "training_only_strictly_prior"
            for history in same_time_histories
        ),
        "Same-time history policy is not recorded on output rows.",
    )
    _require(
        [history.get("user_prior_interaction_count") for history in same_time_histories]
        == [2, 2],
        "Expected training-only history counts at test cutoff are incorrect.",
    )
    train_events = [row for row in feature_interactions if row.get("split") == "train"]
    for target in feature_interactions:
        target_time_value = target.get("event_time_ms")
        _require(
            isinstance(target_time_value, int)
            and not isinstance(target_time_value, bool),
            "Feature event has an invalid timestamp.",
        )
        target_time = cast(int, target_time_value)
        history = _mapping(target.get("history"), "feature history")
        eligible_prior = [
            row
            for row in train_events
            if row.get("training_eligible") is True
            and cast(int, row.get("event_time_ms", target_time)) < target_time
        ]
        user_prior = [
            row
            for row in eligible_prior
            if row.get("user_index") == target.get("user_index")
            and target.get("user_index") != 0
        ]
        item_prior = [
            row
            for row in eligible_prior
            if row.get("item_index") == target.get("item_index")
            and target.get("item_index") != 0
        ]
        _require(
            history.get("user_prior_interaction_count") == len(user_prior)
            and history.get("item_prior_interaction_count") == len(item_prior),
            "As-of history counts include held-out or non-prior events.",
        )
        for rows, mean_field in (
            (user_prior, "user_prior_mean_rating"),
            (item_prior, "item_prior_mean_rating"),
        ):
            expected_mean: str | None = None
            if rows:
                mean = sum(
                    (Decimal(str(row["observed_rating"])) for row in rows),
                    Decimal(0),
                ) / len(rows)
                expected_mean = format(mean.normalize(), "f")
            _require(
                history.get(mean_field) == expected_mean,
                f"As-of aggregate {mean_field} includes an incorrect rating value.",
            )

    for filename in ("feature-schema.json", "transformers.json"):
        _require(
            (features_dir / filename).is_file(),
            f"Feature output missing {filename}.",
        )
    feature_schema = _read_json(features_dir / "feature-schema.json")
    transformers = _read_json(features_dir / "transformers.json")
    _require(
        feature_schema.get("schema_version") == FEATURE_SCHEMA_VERSION,
        "Feature schema file version mismatch.",
    )
    _require(
        transformers.get("schema_version") == TRANSFORMERS_SCHEMA_VERSION,
        "Transformer file version mismatch.",
    )
    encoder_records = _mapping(
        transformers.get("categorical_encoders"), "categorical encoders"
    )
    _require(
        all(
            _mapping(record, "categorical encoder").get("fit_split") == "train"
            for record in encoder_records.values()
        ),
        "Categorical encoders were not fitted exclusively on train.",
    )
    numeric_records = _mapping(
        transformers.get("numeric_standardizers"), "numeric standardizers"
    )
    _require(
        all(
            _mapping(record, "numeric standardizer").get("fit_split") == "train"
            for record in numeric_records.values()
        ),
        "Numeric transformers were not fitted exclusively on train.",
    )
    feature_manifest_schemas = _mapping(features.get("schemas"), "feature schemas")
    _require(
        feature_manifest_schemas.get("feature_interaction")
        == FEATURE_INTERACTION_SCHEMA
        and feature_manifest_schemas.get("feature_item") == FEATURE_ITEM_SCHEMA,
        "Feature manifest schema references are inconsistent.",
    )
    product_field_statuses = _mapping(
        _mapping(
            ingestion_counts.get("product_normalization"),
            "product normalization counts",
        ).get("field_statuses"),
        "normalized product field status counts",
    )
    _require(
        any(
            str(key).endswith(".ambiguous") and count
            for key, count in product_field_statuses.items()
        )
        and any(
            str(key).endswith(".unsupported") and cast(int, count) > 0
            for key, count in product_field_statuses.items()
        ),
        "Synthetic normalized product ambiguity/unknown-unit cases were not accounted.",
    )
    product_counts = _mapping(
        ingestion_counts.get("products"), "product ingestion counts"
    )
    _require(
        cast(int, product_counts.get("conflicting_item_rows", 0)) > 0
        and cast(int, product_counts.get("duplicate_rows_skipped", 0)) > 0
        and cast(int, product_counts.get("rejected_records", 0)) > 0,
        "Synthetic product duplicate, conflict and rejection cases were not accounted.",
    )
    _require(
        any(
            cast(
                int,
                _mapping(value, f"ingestion {split} counts").get(
                    "duplicate_rows_skipped", 0
                ),
            )
            > 0
            and split == "train"
            for split, value in ingestion_splits.items()
        )
        and any(
            cast(
                int,
                _mapping(value, f"ingestion {split} counts").get("rejected_records", 0),
            )
            > 0
            and split == "train"
            for split, value in ingestion_splits.items()
        ),
        "Synthetic interaction duplicates and invalid records were not accounted.",
    )

    outputs = (
        ingestion_outputs + preprocessing_outputs + temporal_outputs + feature_outputs
    )
    validation = {
        "stage_manifests_and_output_checksums": {
            "passed": True,
            "verified_output_files": len(outputs),
        },
        "step_schema_and_manifest_references": {"passed": True},
        "train_only_vocabularies_and_candidate_pool": {
            "passed": True,
            "train_users": len(vocabulary_users) - 1,
            "train_items": len(vocabulary_items) - 1,
            "candidate_items": len(candidates),
            "unknown_index": 0,
        },
        "final_schema_and_split_counts": {
            "passed": True,
            "train": len(interaction_splits["train"]),
            "validation": len(interaction_splits["validation"]),
            "test": len(interaction_splits["test"]),
        },
        "timestamp_boundaries_and_simultaneous_events": {
            "passed": True,
            "validation_boundary_ms": 5_000,
            "test_boundary_ms": 10_000,
            "same_timestamp_test_events": len(same_time_test),
        },
        "raw_user_item_keys_absent_from_feature_artifacts": {"passed": True},
        "metadata_conflicts_not_merged": {
            "passed": True,
            "conflicting_training_items": feature_counts.get(
                "training_catalog_items_with_conflicting_metadata"
            ),
        },
        "snapshot_metadata_not_claimed_historical": {
            "passed": feature_integrity.get("historical_metadata_availability_proven")
            is False
        },
        "no_validation_test_feature_fitting": {
            "passed": True,
            "vocabulary_fit_split": "train",
            "metadata_fit_scope": feature_configuration.get("item_metadata_fit_scope"),
            "history_policy": feature_configuration.get("validation_test_history"),
        },
        "cross_split_event_integrity": {
            "passed": True,
            "cross_split_duplicates": ingestion_counts.get(
                "cross_split_duplicate_interactions"
            ),
            "evaluation_eligible": temporal_integrity.get("evaluation_eligible"),
        },
        "invalid_duplicates_and_ambiguous_products_accounted": {
            "passed": True,
            "training_duplicates": _mapping(
                ingestion_splits["train"], "train counts"
            ).get("duplicate_rows_skipped"),
            "invalid_training_records": _mapping(
                ingestion_splits["train"], "train counts"
            ).get("rejected_records"),
            "conflicting_product_rows": product_counts.get("conflicting_item_rows"),
            "product_duplicates": product_counts.get("duplicate_rows_skipped"),
            "normalized_ambiguous_or_unsupported_fields": True,
        },
    }
    _require(
        all(
            _mapping(result, name).get("passed") is True
            for name, result in validation.items()
        ),
        "One or more end-to-end release validations failed.",
    )

    counts = {
        "ingestion": {
            "input_by_split": {
                split: _mapping(value, f"ingestion {split}").get("input_records")
                for split, value in ingestion_splits.items()
            },
            "valid_and_output_by_split": {
                split: {
                    "output_records": _mapping(value, f"ingestion {split}").get(
                        "output_records"
                    ),
                    "duplicate_rows_skipped": _mapping(value, f"ingestion {split}").get(
                        "duplicate_rows_skipped"
                    ),
                    "rejected_records": _mapping(value, f"ingestion {split}").get(
                        "rejected_records"
                    ),
                }
                for split, value in ingestion_splits.items()
            },
            "product": ingestion_counts.get("products"),
            "cross_split_duplicates": ingestion_counts.get(
                "cross_split_duplicate_interactions"
            ),
        },
        "preprocessing": {
            "input_records": descriptive.get("input_records"),
            "retained_unique_records": descriptive.get("retained_unique_records"),
            "rejected_records": descriptive.get("rejected_records"),
            "duplicate_occurrences": descriptive.get("exact_duplicate_occurrences"),
            "cross_split_duplicate_groups": descriptive.get(
                "cross_split_duplicate_fingerprint_groups"
            ),
        },
        "temporal": temporal_counts,
        "features": feature_counts,
    }
    return {
        "validation_results": validation,
        "counts": counts,
        "feature_configuration": feature_configuration,
        "stage_manifests": {
            "ingestion": "ingestion/manifest.json",
            "preprocessing": "preprocessing/manifest.json",
            "temporal": "temporal/manifest.json",
            "features": "features/manifest.json",
        },
        "verified_outputs": sorted(outputs, key=lambda item: str(item["file"])),
        "manifest_schemas": {
            "canonical": ingestion.get("canonical_schema_version"),
            "interaction_preprocessing": DERIVED_SCHEMA_VERSION,
            "temporal_split": temporal.get("split_policy_version"),
            "temporal_manifest": MANIFEST_SCHEMA,
            "feature": FEATURE_SCHEMA_VERSION,
            "feature_interaction": FEATURE_INTERACTION_SCHEMA,
            "feature_item": FEATURE_ITEM_SCHEMA,
            "feature_manifest": FEATURE_MANIFEST_SCHEMA,
            "transformers": TRANSFORMERS_SCHEMA_VERSION,
        },
    }


def _output_directory(output_dir: Path) -> Path:
    requested = (
        output_dir if output_dir.is_absolute() else _REPOSITORY_ROOT / output_dir
    )
    if requested.is_symlink():
        raise ReleaseValidationError("Release output cannot be a symbolic link.")
    resolved = requested.resolve()
    try:
        relative = resolved.relative_to(_PROCESSED_ROOT)
    except ValueError:
        raise ReleaseValidationError(
            "Synthetic releases must be published under ignored data/processed."
        ) from None
    if not relative.parts:
        raise ReleaseValidationError("Release output must name a new child directory.")
    if resolved.exists() or resolved.is_symlink():
        raise ReleaseValidationError("Release output exists; refusing to overwrite.")
    return resolved


def run_synthetic_release(
    output_dir: Path,
    *,
    fixture_dir: Path = _FIXTURE_ROOT,
) -> dict[str, object]:
    """Run all Phase 2 stages and atomically publish a validated synthetic release."""
    fixture_dir = fixture_dir.resolve()
    final_output = _output_directory(output_dir)
    if not fixture_dir.is_relative_to(_REPOSITORY_ROOT):
        raise ReleaseValidationError("Release fixtures must be inside the repository.")
    input_hashes = _input_provenance(fixture_dir)
    final_output.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{final_output.name}.staging-", dir=final_output.parent
        )
    )
    stage_durations: dict[str, float] = {}
    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start()
    tracemalloc.reset_peak()
    started = time.perf_counter()
    try:
        stage_started = time.perf_counter()
        ingestion = ingest_local_files(
            train_path=fixture_dir / "train.jsonl",
            validation_path=fixture_dir / "validation.jsonl",
            test_path=fixture_dir / "test.jsonl",
            product_path=fixture_dir / "products.jsonl",
            input_format=InputFormat.JSONL,
            product_format=InputFormat.JSONL,
            output_dir=staging_dir / "ingestion",
            source_id=_SOURCE_ID,
            source_version=_SOURCE_VERSION,
            seed=_SEED,
            max_users=_MAX_USERS,
            normalize_products=True,
        )
        stage_durations["ingestion_seconds"] = time.perf_counter() - stage_started

        stage_started = time.perf_counter()
        preprocessing = preprocess_interaction_files(
            train_path=ingestion.output_dir / "interactions.train.jsonl",
            validation_path=ingestion.output_dir / "interactions.validation.jsonl",
            test_path=ingestion.output_dir / "interactions.test.jsonl",
            output_dir=staging_dir / "preprocessing",
            source_id=_SOURCE_ID,
            source_version=_SOURCE_VERSION,
        )
        stage_durations["preprocessing_seconds"] = time.perf_counter() - stage_started

        stage_started = time.perf_counter()
        temporal = process_trusted_pre_split(
            train_path=preprocessing.output_dir / "interactions.train.processed.jsonl",
            validation_path=preprocessing.output_dir
            / "interactions.validation.processed.jsonl",
            test_path=preprocessing.output_dir / "interactions.test.processed.jsonl",
            output_dir=staging_dir / "temporal",
            source_id=_SOURCE_ID,
            source_version=_SOURCE_VERSION,
            cutoffs=_CUTOFFS,
        )
        stage_durations["temporal_split_seconds"] = time.perf_counter() - stage_started

        stage_started = time.perf_counter()
        generate_features(
            temporal_dir=temporal.output_dir,
            product_ingestion_dir=ingestion.output_dir,
            output_dir=staging_dir / "features",
        )
        stage_durations["feature_generation_seconds"] = (
            time.perf_counter() - stage_started
        )

        stage_durations["pipeline_seconds"] = time.perf_counter() - started
        validation = _validate_pipeline(
            root=staging_dir,
            input_hashes=input_hashes,
        )
        artifact_outputs = _walk_output_hashes(staging_dir)
        total_bytes = sum(
            cast(int, output["size_bytes"]) for output in artifact_outputs
        )
        _, peak_traced_bytes = tracemalloc.get_traced_memory()
        performance = {
            "timings_seconds": {
                name: round(value, 6) for name, value in sorted(stage_durations.items())
            },
            "peak_traced_python_memory_bytes": peak_traced_bytes,
            "measurement_note": (
                "tracemalloc peak; excludes native allocator and child-process RSS"
            ),
            "artifact_bytes_excluding_release_manifest": total_bytes,
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
        }
        configuration: dict[str, object] = {
            "seed": _SEED,
            "max_users": _MAX_USERS,
            "normalization_opt_in": True,
            "split_mode": "trusted-pre-split-with-utc-boundary-validation",
            "cutoffs": _CUTOFFS.as_record(),
            "feature_generation": validation["feature_configuration"],
        }
        run_manifest: dict[str, object] = {
            "manifest_schema_version": RELEASE_SCHEMA_VERSION,
            "release_type": "synthetic_only",
            "external_data_used": False,
            "real_data_validation": (
                "BLOCKED_PENDING_USAGE_RIGHTS_REVIEW_AND_AUTHORIZED_PILOT"
            ),
            "phase3_training_readiness": "NOT_ESTABLISHED_BY_SYNTHETIC_VALIDATION",
            "source_restrictions": {
                "dataset_rights_gate": (
                    "unresolved; no third-party data may be downloaded or processed"
                ),
                "fixture_scope": "committed synthetic canonical JSONL only",
                "raw_user_identifiers": (
                    "synthetic internal intermediates only; absent from "
                    "final feature artifacts"
                ),
                "model_training": "not run",
            },
            "source": {
                "source_id": _SOURCE_ID,
                "source_version": _SOURCE_VERSION,
                "fixture_checksums": input_hashes,
            },
            "configuration": configuration,
            "configuration_sha256": hashlib.sha256(
                _canonical_json(configuration).encode("utf-8")
            ).hexdigest(),
            "schema_versions": validation["manifest_schemas"],
            "stage_manifests": validation["stage_manifests"],
            "counts": validation["counts"],
            "validation_results": validation["validation_results"],
            "outputs": artifact_outputs,
        }
        _require(
            all(
                _mapping(result, label).get("passed") is True
                for label, result in _mapping(
                    run_manifest["validation_results"], "release validations"
                ).items()
            ),
            "Release validations failed; publication is blocked.",
        )
        write_manifest(staging_dir / "release-manifest.json", run_manifest)
        if final_output.exists():
            raise ReleaseValidationError("Release output appeared during processing.")
        os.rename(staging_dir, final_output)
        return {
            **run_manifest,
            "published_output_dir": str(final_output),
            "published_directory_bytes": _tree_size(final_output),
            "performance": performance,
        }
    except (OSError, ValueError) as error:
        if isinstance(error, IngestionError):
            raise
        raise ReleaseValidationError(
            "Synthetic release failed; no release directory was published."
        ) from error
    finally:
        if not was_tracing:
            tracemalloc.stop()
        if staging_dir.exists():
            shutil.rmtree(staging_dir)


def _arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the committed synthetic-only Phase 2 pipeline and publish a "
            "validated release under data/processed."
        )
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments().parse_args(argv)
    try:
        manifest = run_synthetic_release(args.output_dir)
    except (IngestionError, OSError, ValueError) as error:
        print(f"Synthetic release failed: {error}", file=sys.stderr)
        return 2
    counts = _mapping(manifest["counts"], "release counts")
    print(
        json.dumps(
            {
                "output_dir": manifest["published_output_dir"],
                "release_type": manifest["release_type"],
                "validation_passed": all(
                    _mapping(result, label).get("passed") is True
                    for label, result in _mapping(
                        manifest["validation_results"], "release validations"
                    ).items()
                ),
                "counts": counts,
                "performance": manifest["performance"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
