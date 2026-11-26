"""Synthetic artifact contract tests for the local popularity pilot runner."""

import hashlib
import json
from pathlib import Path

from recfusion_ml.evaluation import pilot


def _write(path: Path, content: str) -> dict[str, object]:
    encoded = content.encode("utf-8")
    path.write_bytes(encoded)
    return {
        "file": path.name,
        "records": len(content.splitlines()) if content else 0,
        "size_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _jsonl(records: list[dict[str, object]]) -> str:
    return "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)


def _record(
    user: str, item: str, rating: str, split: str, fingerprint: str
) -> dict[str, object]:
    interaction = {
        "user_key": user,
        "item_key": item,
        "rating": rating,
        "split": split,
        "event_time_utc": "2023-01-01T00:00:00.000Z",
        "source_event_fingerprint": fingerprint,
    }
    return {
        "split": split,
        "source_split": split,
        "integrity_flags": [],
        "interaction": interaction,
    }


def test_synthetic_pilot_validates_artifacts_and_writes_aggregate_only_report(
    tmp_path: Path, monkeypatch
) -> None:
    repository = tmp_path / "repo"
    processed = repository / "data" / "processed"
    preprocessing_dir = processed / "preprocessed"
    temporal_dir = processed / "temporal"
    preprocessing_dir.mkdir(parents=True)
    temporal_dir.mkdir()
    source = {"source_id": "synthetic", "source_version": "v1"}

    preprocessing_outputs = []
    for split in ("train", "validation", "test"):
        name = f"interactions.{split}.processed.jsonl"
        preprocessing_outputs.append(_write(preprocessing_dir / name, "synthetic\n"))
    preprocessing_manifest = {
        "manifest_schema_version": "recfusion.interaction-manifest.v1",
        "source": source,
        "outputs": preprocessing_outputs,
        "quality_report": {"descriptive_all_splits": {"rejected_records": 0}},
    }
    (preprocessing_dir / "manifest.json").write_text(
        json.dumps(preprocessing_manifest), encoding="utf-8"
    )

    train_records = [
        _record("user-a", "history", "3", "train", "a" * 64),
        _record("user-b", "item-a", "5", "train", "b" * 64),
        _record("user-c", "item-b", "4", "train", "c" * 64),
    ]
    validation_records = [
        _record("user-a", "item-a", "5", "validation", "d" * 64),
        _record("user-a", "item-b", "5", "validation", "e" * 64),
        _record("user-a", "history", "3", "validation", "f" * 64),
        _record("user-a", "item-a", "2", "validation", "g" * 64),
    ]
    temporal_outputs = [
        _write(temporal_dir / "interactions.train.jsonl", _jsonl(train_records)),
        _write(
            temporal_dir / "interactions.validation.jsonl",
            _jsonl(validation_records),
        ),
        # Deliberately not valid JSONL: the runner must hash, never parse, test rows.
        _write(temporal_dir / "interactions.test.jsonl", "private test payload\n"),
        _write(temporal_dir / "evaluation.jsonl", "{}\n"),
        _write(temporal_dir / "vocabulary.users.jsonl", "{}\n"),
        _write(temporal_dir / "vocabulary.items.jsonl", "{}\n"),
        _write(
            temporal_dir / "candidate-pool.items.jsonl",
            _jsonl(
                [
                    {"item_key": "history"},
                    {"item_key": "item-a"},
                    {"item_key": "item-b"},
                ]
            ),
        ),
    ]
    preprocessing_by_file = {item["file"]: item for item in preprocessing_outputs}
    temporal_inputs = {
        split: preprocessing_by_file[f"interactions.{split}.processed.jsonl"]
        for split in ("train", "validation", "test")
    }
    temporal_manifest = {
        "manifest_schema_version": "recfusion.temporal-split-manifest.v1",
        "mode": "trusted-pre-split",
        "source": source,
        "inputs": temporal_inputs,
        "outputs": temporal_outputs,
        "integrity_status": {
            "evaluation_eligible": True,
            "source_split_membership_changed": 0,
            "blocking_violations": {},
            "chronological_overlap_records": 0,
            "report_only_warnings": {},
        },
        "counts": {"rejected_records": 0, "integrity": {}},
    }
    (temporal_dir / "manifest.json").write_text(
        json.dumps(temporal_manifest), encoding="utf-8"
    )
    monkeypatch.setattr(pilot, "_repository_root", lambda: repository)

    report = pilot.evaluate_pilot(
        preprocessing_dir=preprocessing_dir,
        temporal_dir=temporal_dir,
        output_dir=processed / "popularity-report",
        ks=(1, 2),
    )

    assert report["counts"]["parsed_records"] == {"train": 3, "validation": 4}
    assert report["counts"]["evaluated_users"] == 1
    assert report["counts"]["low_rating_validation_observations"] == 1
    assert report["counts"]["neutral_validation_observations"] == 1
    assert report["integrity"]["temporal_status"]["blocking_violations"] == {}
    assert report["protocol"]["test_rows_parsed_or_evaluated"] is False
    assert report["metrics"]["1"]["recall"] == 0.5
    serialized = (processed / "popularity-report" / "aggregate-report.json").read_text()
    assert "user-a" not in serialized
    assert "item-a" not in serialized
