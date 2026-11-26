"""Synthetic contract tests for the aggregate-only item-CF comparison."""

import hashlib
import json
from pathlib import Path

import pytest

from recfusion_ml.evaluation import item_cf_pilot, pilot


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
    return {
        "split": split,
        "source_split": split,
        "integrity_flags": [],
        "interaction": {
            "user_key": user,
            "item_key": item,
            "rating": rating,
            "split": split,
            "event_time_utc": "2023-01-01T00:00:00.000Z",
            "source_event_fingerprint": fingerprint,
        },
    }


def _make_artifacts(processed: Path) -> tuple[Path, Path]:
    preprocessing_dir = processed / "preprocessed"
    temporal_dir = processed / "temporal"
    preprocessing_dir.mkdir(parents=True)
    temporal_dir.mkdir()
    source = {"source_id": "synthetic", "source_version": "v1"}
    preprocessing_outputs = [
        _write(
            preprocessing_dir / f"interactions.{split}.processed.jsonl",
            "synthetic\n",
        )
        for split in ("train", "validation", "test")
    ]
    (preprocessing_dir / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_schema_version": "recfusion.interaction-manifest.v1",
                "source": source,
                "outputs": preprocessing_outputs,
            }
        ),
        encoding="utf-8",
    )
    train = [
        _record("user-a", "history", "5", "train", "a" * 64),
        _record("user-b", "history", "5", "train", "b" * 64),
        _record("user-a", "item-a", "5", "train", "c" * 64),
        _record("user-b", "item-a", "5", "train", "d" * 64),
        _record("user-c", "item-b", "5", "train", "f" * 64),
    ]
    validation = [_record("user-a", "item-b", "5", "validation", "e" * 64)]
    temporal_outputs = [
        _write(temporal_dir / "interactions.train.jsonl", _jsonl(train)),
        _write(temporal_dir / "interactions.validation.jsonl", _jsonl(validation)),
        # Invalid JSON proves the evaluator verifies test bytes without parsing rows.
        _write(temporal_dir / "interactions.test.jsonl", "private test payload\n"),
        _write(temporal_dir / "evaluation.jsonl", "{}\n"),
        _write(temporal_dir / "vocabulary.users.jsonl", "{}\n"),
        _write(temporal_dir / "vocabulary.items.jsonl", "{}\n"),
        _write(
            temporal_dir / "candidate-pool.items.jsonl",
            _jsonl([{"item_key": item} for item in ("history", "item-a", "item-b")]),
        ),
    ]
    by_name = {output["file"]: output for output in preprocessing_outputs}
    (temporal_dir / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_schema_version": "recfusion.temporal-split-manifest.v1",
                "mode": "trusted-pre-split",
                "source": source,
                "inputs": {
                    split: by_name[f"interactions.{split}.processed.jsonl"]
                    for split in ("train", "validation", "test")
                },
                "outputs": temporal_outputs,
                "integrity_status": {
                    "evaluation_eligible": True,
                    "source_split_membership_changed": 0,
                    "blocking_violations": {},
                },
                "counts": {"rejected_records": 0, "integrity": {}},
            }
        ),
        encoding="utf-8",
    )
    return preprocessing_dir, temporal_dir


def test_item_cf_compares_same_verified_validation_cohort_aggregate_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repo"
    processed = repository / "data" / "processed"
    processed.mkdir(parents=True)
    preprocessing_dir, temporal_dir = _make_artifacts(processed)
    monkeypatch.setattr(pilot, "_repository_root", lambda: repository)
    monkeypatch.setattr(item_cf_pilot, "_repository_root", lambda: repository)

    baseline_dir = processed / "popularity"
    baseline = pilot.evaluate_pilot(
        preprocessing_dir=preprocessing_dir,
        temporal_dir=temporal_dir,
        output_dir=baseline_dir,
        ks=(1, 2),
    )
    report = item_cf_pilot.evaluate_item_cf_pilot(
        preprocessing_dir=preprocessing_dir,
        temporal_dir=temporal_dir,
        popularity_report_path=baseline_dir / "aggregate-report.json",
        output_dir=processed / "item-cf",
        ks=(1, 2),
    )

    assert report["counts"]["evaluated_users"] == baseline["counts"]["evaluated_users"]
    assert (
        report["counts"]["eligible_positive_target_pairs"]
        == baseline["counts"]["eligible_positive_target_pairs"]
    )
    assert report["protocol"]["test_rows_parsed_or_evaluated"] is False
    assert report["counts"]["fallback_users"] == 0
    assert report["counts"]["users_without_generated_candidates"] == 1
    output = (processed / "item-cf" / "item-cf-report.json").read_text()
    assert "user-a" not in output
    assert "item-a" not in output
    assert "item-b" not in output


def test_item_cf_rejects_popularity_report_for_different_cohort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repo"
    processed = repository / "data" / "processed"
    processed.mkdir(parents=True)
    preprocessing_dir, temporal_dir = _make_artifacts(processed)
    monkeypatch.setattr(pilot, "_repository_root", lambda: repository)
    monkeypatch.setattr(item_cf_pilot, "_repository_root", lambda: repository)
    baseline_dir = processed / "popularity"
    pilot.evaluate_pilot(
        preprocessing_dir=preprocessing_dir,
        temporal_dir=temporal_dir,
        output_dir=baseline_dir,
        ks=(1, 2),
    )
    report_path = baseline_dir / "aggregate-report.json"
    baseline = json.loads(report_path.read_text(encoding="utf-8"))
    baseline["counts"]["evaluated_users"] += 1
    report_path.write_text(json.dumps(baseline), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match"):
        item_cf_pilot.evaluate_item_cf_pilot(
            preprocessing_dir=preprocessing_dir,
            temporal_dir=temporal_dir,
            popularity_report_path=report_path,
            output_dir=processed / "item-cf",
            ks=(1, 2),
        )

    assert not (processed / "item-cf").exists()
