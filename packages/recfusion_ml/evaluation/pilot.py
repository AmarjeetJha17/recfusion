"""Run an aggregate-only popularity evaluation on trusted Step 2.5 artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import tracemalloc
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from recfusion_ml.baselines.popularity import PopularityRecommender
from recfusion_ml.evaluation.metrics import build_validation_cohort, evaluate_rankings
from recfusion_ml.types import RatingEvent

_PREPROCESS_SCHEMA = "recfusion.interaction-manifest.v1"
_TEMPORAL_SCHEMA = "recfusion.temporal-split-manifest.v1"
_TEMPORAL_OUTPUTS = (
    "interactions.train.jsonl",
    "interactions.validation.jsonl",
    "interactions.test.jsonl",
    "evaluation.jsonl",
    "vocabulary.users.jsonl",
    "vocabulary.items.jsonl",
    "candidate-pool.items.jsonl",
)
_CHUNK_SIZE = 1024 * 1024


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _read_manifest(path: Path, schema: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read input manifest {path.name}.") from error
    if not isinstance(value, dict) or value.get("manifest_schema_version") != schema:
        raise ValueError(f"Unsupported or malformed manifest {path.name}.")
    return cast(dict[str, object], value)


def _verified_outputs(
    directory: Path, manifest: Mapping[str, object], expected_files: Sequence[str]
) -> dict[str, dict[str, object]]:
    raw_outputs = manifest.get("outputs")
    if not isinstance(raw_outputs, list):
        raise ValueError(f"{directory.name} manifest has no outputs list.")
    outputs: dict[str, dict[str, object]] = {}
    for raw in raw_outputs:
        if not isinstance(raw, dict):
            raise ValueError(f"{directory.name} contains a malformed output entry.")
        file_name = raw.get("file")
        if not isinstance(file_name, str) or Path(file_name).name != file_name:
            raise ValueError(f"{directory.name} contains an unsafe output name.")
        if file_name in outputs:
            raise ValueError(f"{directory.name} repeats output {file_name}.")
        path = directory / file_name
        if not path.is_file():
            raise ValueError(f"Required artifact {file_name} is missing.")
        checksum, size = _sha256_file(path)
        if raw.get("sha256") != checksum or raw.get("size_bytes") != size:
            raise ValueError(f"Artifact integrity check failed for {file_name}.")
        outputs[file_name] = cast(dict[str, object], raw)
    if set(outputs) != set(expected_files):
        raise ValueError(f"{directory.name} outputs do not match the expected set.")
    return outputs


def _validate_input_lineage(
    preprocessing: Mapping[str, object], temporal: Mapping[str, object]
) -> None:
    source = preprocessing.get("source")
    if not isinstance(source, dict) or temporal.get("source") != source:
        raise ValueError("Preprocessing and temporal source identities differ.")
    temporal_inputs = temporal.get("inputs")
    preprocessing_outputs = preprocessing.get("outputs")
    if not isinstance(temporal_inputs, dict) or not isinstance(
        preprocessing_outputs, list
    ):
        raise ValueError("Input lineage is unavailable in the manifests.")
    output_by_file = {
        record.get("file"): record
        for record in preprocessing_outputs
        if isinstance(record, dict)
    }
    for split in ("train", "validation", "test"):
        input_record = temporal_inputs.get(split)
        if not isinstance(input_record, dict):
            raise ValueError(f"Temporal manifest is missing the {split} input.")
        parent = output_by_file.get(input_record.get("file"))
        if not isinstance(parent, dict) or any(
            input_record.get(field) != parent.get(field)
            for field in ("sha256", "size_bytes")
        ):
            raise ValueError(f"Temporal {split} input does not match preprocessing.")


def _jsonl_records(path: Path, *, split: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"Malformed JSON in {path.name} at line {line_number}."
                    ) from error
                if not isinstance(value, dict):
                    raise ValueError(f"Invalid record in {path.name}.")
                interaction = value.get("interaction")
                if not isinstance(interaction, dict):
                    raise ValueError(f"Missing interaction in {path.name}.")
                if value.get("split") != split or value.get("source_split") != split:
                    raise ValueError(f"Split membership mismatch in {path.name}.")
                if interaction.get("split") != split:
                    raise ValueError(f"Interaction split mismatch in {path.name}.")
                if value.get("integrity_flags") != []:
                    raise ValueError(
                        f"Integrity flags block evaluation in {path.name}."
                    )
                records.append(value)
    except OSError as error:
        raise ValueError(f"Cannot read artifact {path.name}.") from error
    return records


def _event(record: Mapping[str, object], split: str) -> RatingEvent:
    interaction = record["interaction"]
    if not isinstance(interaction, dict):
        raise ValueError("Interaction record is malformed.")
    user_key = interaction.get("user_key")
    item_key = interaction.get("item_key")
    rating_value = interaction.get("rating")
    if not isinstance(user_key, str) or not isinstance(item_key, str):
        raise ValueError("Interaction identifiers are malformed.")
    if not isinstance(rating_value, str):
        raise ValueError("Interaction rating is malformed.")
    try:
        rating = Decimal(rating_value)
    except InvalidOperation as error:
        raise ValueError("Interaction rating is invalid.") from error
    return RatingEvent(user_key, item_key, rating, split)


def _fingerprint(record: Mapping[str, object]) -> str:
    interaction = record.get("interaction")
    value = (
        interaction.get("source_event_fingerprint")
        if isinstance(interaction, dict)
        else None
    )
    if not isinstance(value, str):
        raise ValueError("Source event fingerprint is missing or malformed.")
    return value


def _candidate_pool(path: Path) -> set[str]:
    items: set[str] = set()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            value = json.loads(line)
            item_key = value.get("item_key") if isinstance(value, dict) else None
            if not isinstance(item_key, str) or item_key in items:
                raise ValueError("Candidate pool contains malformed or duplicate IDs.")
            items.add(item_key)
    return items


def _timestamp_range(
    events: Sequence[RatingEvent], records: Sequence[dict[str, object]]
) -> dict[str, str | None]:
    del events
    timestamps: list[str] = []
    for record in records:
        interaction = record.get("interaction")
        value = (
            interaction.get("event_time_utc") if isinstance(interaction, dict) else None
        )
        if not isinstance(value, str):
            raise ValueError("Canonical timestamp is missing or malformed.")
        timestamps.append(value)
    return {
        "minimum_utc": min(timestamps) if timestamps else None,
        "maximum_utc": max(timestamps) if timestamps else None,
    }


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class TrustedPilotData:
    preprocessing_dir: Path
    temporal_dir: Path
    preprocessing: dict[str, object]
    temporal: dict[str, object]
    temporal_outputs: dict[str, dict[str, object]]
    train_records: list[dict[str, object]]
    validation_records: list[dict[str, object]]
    train_events: tuple[RatingEvent, ...]
    validation_events: tuple[RatingEvent, ...]
    candidate_items: frozenset[str]


def load_trusted_pilot_data(
    preprocessing_dir: Path, temporal_dir: Path
) -> TrustedPilotData:
    """Verify Step 2.4/2.5 artifacts; parse train and validation rows only."""
    preprocessing_dir = preprocessing_dir.resolve()
    temporal_dir = temporal_dir.resolve()
    if not preprocessing_dir.is_dir() or not temporal_dir.is_dir():
        raise ValueError(
            "Both preprocessing and trusted temporal directories are required."
        )
    preprocessing = _read_manifest(
        preprocessing_dir / "manifest.json", _PREPROCESS_SCHEMA
    )
    temporal = _read_manifest(temporal_dir / "manifest.json", _TEMPORAL_SCHEMA)
    if temporal.get("mode") != "trusted-pre-split":
        raise ValueError("Only trusted-pre-split temporal artifacts are accepted.")
    integrity = temporal.get("integrity_status")
    if (
        not isinstance(integrity, dict)
        or integrity.get("evaluation_eligible") is not True
    ):
        raise ValueError("Temporal integrity status does not permit evaluation.")
    blocking_violations = integrity.get("blocking_violations")
    if not isinstance(blocking_violations, dict) or blocking_violations:
        raise ValueError("Temporal manifest reports blocking integrity violations.")
    if integrity.get("source_split_membership_changed") != 0:
        raise ValueError("Temporal stage changed official split membership.")
    _validate_input_lineage(preprocessing, temporal)
    temporal_outputs = _verified_outputs(temporal_dir, temporal, _TEMPORAL_OUTPUTS)
    preprocessing_outputs = preprocessing.get("outputs")
    if not isinstance(preprocessing_outputs, list):
        raise ValueError("Preprocessing manifest is missing outputs.")
    preprocessing_names: list[str] = []
    for value in preprocessing_outputs:
        if not isinstance(value, dict) or not isinstance(value.get("file"), str):
            raise ValueError("Preprocessing manifest has a malformed output entry.")
        preprocessing_names.append(cast(str, value["file"]))
    _verified_outputs(preprocessing_dir, preprocessing, preprocessing_names)

    train_records = _jsonl_records(
        temporal_dir / "interactions.train.jsonl", split="train"
    )
    validation_records = _jsonl_records(
        temporal_dir / "interactions.validation.jsonl", split="validation"
    )
    train_declared = temporal_outputs["interactions.train.jsonl"].get("records")
    validation_declared = temporal_outputs["interactions.validation.jsonl"].get(
        "records"
    )
    if train_declared != len(train_records) or validation_declared != len(
        validation_records
    ):
        raise ValueError("Parsed train/validation counts disagree with their manifest.")
    train_events = tuple(_event(record, "train") for record in train_records)
    validation_events = tuple(
        _event(record, "validation") for record in validation_records
    )
    candidate_items = frozenset(
        _candidate_pool(temporal_dir / "candidate-pool.items.jsonl")
    )
    return TrustedPilotData(
        preprocessing_dir=preprocessing_dir,
        temporal_dir=temporal_dir,
        preprocessing=preprocessing,
        temporal=temporal,
        temporal_outputs=temporal_outputs,
        train_records=train_records,
        validation_records=validation_records,
        train_events=train_events,
        validation_events=validation_events,
        candidate_items=candidate_items,
    )


def evaluate_pilot(
    *,
    preprocessing_dir: Path,
    temporal_dir: Path,
    output_dir: Path,
    ks: Sequence[int] = (5, 10, 20),
) -> dict[str, object]:
    """Validate pilot artifacts and write aggregate-only validation results."""
    started = time.perf_counter()
    tracemalloc.start()
    output_dir = output_dir.resolve()
    repository_root = _repository_root()
    processed_root = (repository_root / "data" / "processed").resolve()
    for input_dir in (preprocessing_dir.resolve(), temporal_dir.resolve()):
        if input_dir == output_dir or input_dir in output_dir.parents:
            raise ValueError("Output directory cannot overwrite or contain an input.")
    if processed_root not in output_dir.parents:
        raise ValueError("Output directory must be under ignored data/processed.")
    if output_dir.exists():
        raise ValueError("Output directory already exists; refusing to overwrite it.")

    data = load_trusted_pilot_data(preprocessing_dir, temporal_dir)
    preprocessing = data.preprocessing
    temporal = data.temporal
    temporal_outputs = data.temporal_outputs
    train_records = data.train_records
    validation_records = data.validation_records
    train = data.train_events
    validation = data.validation_events
    pool = data.candidate_items
    model = PopularityRecommender.fit(train, pool)
    cohort = build_validation_cohort(train, validation, pool)
    recommendations = {
        user: model.recommend(seen_items=cohort.seen_items_by_user[user], k=max(ks))
        for user in sorted(cohort.targets_by_user)
    }
    evaluated = evaluate_rankings(cohort, recommendations, candidate_items=pool, ks=ks)

    train_ratings = Counter(str(event.rating) for event in train)
    validation_ratings = Counter(str(event.rating) for event in validation)
    train_fingerprints = Counter(_fingerprint(record) for record in train_records)
    validation_fingerprints = Counter(
        _fingerprint(record) for record in validation_records
    )
    peak_allocated_bytes = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    runtime_seconds = time.perf_counter() - started
    metrics = {
        str(k): {
            "recall": metric.recall,
            "ndcg": metric.ndcg,
            "hit_rate": metric.hit_rate,
            "mrr": metric.mrr,
            "candidate_coverage": metric.candidate_coverage,
            "unique_recommended_items": metric.unique_recommended_items,
            "recommendation_count": metric.recommendation_count,
        }
        for k, metric in evaluated.metrics_by_k.items()
    }
    preprocessing_quality = preprocessing.get("quality_report")
    descriptive_quality = (
        preprocessing_quality.get("descriptive_all_splits")
        if isinstance(preprocessing_quality, dict)
        else None
    )
    per_split_quality = (
        descriptive_quality.get("per_split")
        if isinstance(descriptive_quality, dict)
        else None
    )
    preprocessing_split_quality: dict[str, object] = {}
    if isinstance(per_split_quality, dict):
        for split in ("train", "validation"):
            value = per_split_quality.get(split)
            if isinstance(value, dict):
                preprocessing_split_quality[split] = {
                    field: value.get(field)
                    for field in (
                        "input_records",
                        "valid_records_before_deduplication",
                        "rejected_records",
                        "rejection_counts_by_reason",
                        "exact_duplicate_occurrences",
                    )
                }
    temporal_counts_value = temporal.get("counts")
    temporal_counts = (
        cast(dict[str, object], temporal_counts_value)
        if isinstance(temporal_counts_value, dict)
        else {}
    )
    integrity_counts_value = temporal_counts.get("integrity")
    integrity_counts = (
        cast(dict[str, object], integrity_counts_value)
        if isinstance(integrity_counts_value, dict)
        else {}
    )
    integrity_status = temporal.get("integrity_status")
    integrity_status = (
        cast(dict[str, object], integrity_status)
        if isinstance(integrity_status, dict)
        else {}
    )
    integrity_summary = {
        key: integrity_status.get(key)
        for key in (
            "evaluation_eligible",
            "blocking_violations",
            "source_split_membership_changed",
            "chronological_overlap_records",
            "report_only_warnings",
        )
    }
    report: dict[str, object] = {
        "report_schema_version": "recfusion.popularity-evaluation-report.v1",
        "experiment": "amazon-electronics-10k-validation-popularity-v1",
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": temporal.get("source"),
        "protocol": {
            "baseline": "positive-training-review-count popularity",
            "positive_min_rating": "4",
            "seed": None,
            "seed_policy": "not_applicable; deterministic ranking",
            "candidate_universe": "train-known items from Step 2.5 candidate pool",
            "catalog_size": len(pool),
            "seen_train_items_excluded": True,
            "evaluation_split": "validation only",
            "test_rows_parsed_or_evaluated": False,
            "metadata_features": "unavailable; no product metadata joined",
            "ks": list(ks),
        },
        "provenance": {
            "preprocessing_manifest_sha256": _sha256_file(
                preprocessing_dir / "manifest.json"
            )[0],
            "temporal_manifest_sha256": _sha256_file(temporal_dir / "manifest.json")[0],
            "train_sha256": temporal_outputs["interactions.train.jsonl"]["sha256"],
            "validation_sha256": temporal_outputs["interactions.validation.jsonl"][
                "sha256"
            ],
            "test_sha256_verified_without_parsing": temporal_outputs[
                "interactions.test.jsonl"
            ]["sha256"],
        },
        "integrity": {
            "temporal_status": integrity_summary,
            "temporal_counts": integrity_counts,
        },
        "counts": {
            "source_split_records": {
                split: temporal_outputs[f"interactions.{split}.jsonl"]["records"]
                for split in ("train", "validation", "test")
            },
            "parsed_records": {"train": len(train), "validation": len(validation)},
            "rejected_records": temporal_counts.get("rejected_records", 0),
            "unique_train_users": len({event.user_key for event in train}),
            "unique_train_items": len({event.item_key for event in train}),
            "unique_validation_items": len({event.item_key for event in validation}),
            "train_users_with_positive_ratings": len(
                {event.user_key for event in train if event.rating >= Decimal("4")}
            ),
            "candidate_pool_items": len(pool),
            "unique_validation_users": cohort.validation_user_count,
            "users_with_observed_positives": cohort.users_with_observed_positives,
            "users_with_warm_positive_targets": cohort.users_with_warm_positive_targets,
            "users_with_evaluable_targets": cohort.users_with_evaluable_targets,
            "evaluated_users": evaluated.evaluated_user_count,
            "validation_positive_observations": cohort.positive_observation_count,
            "validation_positive_target_pairs": cohort.positive_target_pair_count,
            "warm_positive_observations": cohort.warm_positive_observation_count,
            "eligible_positive_target_pairs": cohort.eligible_positive_target_count,
            "cold_user_positive_observations": (
                cohort.cold_user_positive_observation_count
            ),
            "cold_item_positive_observations": (
                cohort.cold_item_positive_observation_count
            ),
            "seen_positive_observations": cohort.seen_positive_observation_count,
            "non_positive_validation_observations": (
                cohort.non_positive_observation_count
            ),
            "low_rating_validation_observations": sum(
                event.rating <= Decimal("2") for event in validation
            ),
            "neutral_validation_observations": sum(
                event.rating == Decimal("3") for event in validation
            ),
            "unclassified_non_positive_validation_observations": sum(
                Decimal("3") < event.rating < Decimal("4") for event in validation
            ),
            "duplicate_positive_observations": (
                cohort.duplicate_positive_observation_count
            ),
            "excluded_positive_target_pairs": dict(cohort.excluded_target_counts),
            "step_2_4_quality_train_and_validation_only": preprocessing_split_quality,
            "exact_duplicate_fingerprint_occurrences": {
                "train": sum(
                    count - 1 for count in train_fingerprints.values() if count > 1
                ),
                "validation": sum(
                    count - 1 for count in validation_fingerprints.values() if count > 1
                ),
            },
        },
        "ratings": {
            "train": dict(sorted(train_ratings.items())),
            "validation": dict(sorted(validation_ratings.items())),
        },
        "timestamps": {
            "train": _timestamp_range(train, train_records),
            "validation": _timestamp_range(validation, validation_records),
        },
        "metrics": metrics,
        "resources": {
            "wall_time_seconds": round(runtime_seconds, 3),
            "peak_tracemalloc_bytes": peak_allocated_bytes,
            "process_peak_rss": "not measured by this runner",
        },
    }
    output_dir.mkdir(parents=True)
    try:
        report_path = output_dir / "aggregate-report.json"
        report_path.write_text(
            json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except OSError:
        report_path.unlink(missing_ok=True)
        output_dir.rmdir()
        raise
    return report


def _arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate train-only popularity on a verified trusted Step 2.5 split; "
            "writes aggregate metrics only."
        )
    )
    parser.add_argument("--preprocessing-dir", type=Path, required=True)
    parser.add_argument("--temporal-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ks", type=int, nargs="+", default=(5, 10, 20))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments().parse_args(argv)
    try:
        result = evaluate_pilot(
            preprocessing_dir=args.preprocessing_dir,
            temporal_dir=args.temporal_dir,
            output_dir=args.output_dir,
            ks=args.ks,
        )
    except (OSError, ValueError) as error:
        print(f"Popularity evaluation failed: {error}", file=sys.stderr)
        return 2
    counts = cast(dict[str, object], result["counts"])
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir.resolve()),
                "evaluated_users": counts["evaluated_users"],
                "metrics": result["metrics"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
