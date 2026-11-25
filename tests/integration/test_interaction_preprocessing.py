import hashlib
import json
import shutil
from pathlib import Path

import pytest

from recfusion_data.ingestion.errors import IngestionError
from recfusion_data.preprocessing.interactions import preprocess_interaction_files

pytestmark = pytest.mark.integration

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "preprocessing"
_REPOSITORY_ROOT = Path(__file__).parents[2]


@pytest.fixture
def output_root(tmp_path: Path) -> Path:
    path = _REPOSITORY_ROOT / "data" / "processed" / f"preprocess-{tmp_path.name}"
    try:
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path)


def _process(
    output_dir: Path,
    *,
    train: Path = _FIXTURES / "train.jsonl",
    validation: Path = _FIXTURES / "validation.jsonl",
    test: Path = _FIXTURES / "test.jsonl",
) -> dict[str, object]:
    result = preprocess_interaction_files(
        train_path=train,
        validation_path=validation,
        test_path=test,
        output_dir=output_dir,
        source_id="synthetic-preprocessing",
        source_version="v1",
    )
    return dict(result.manifest)


def _records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_preprocessing_reports_duplicates_rejections_and_split_diagnostics(
    output_root: Path,
) -> None:
    manifest = _process(output_root / "first")
    report = manifest["quality_report"]
    descriptive = report["descriptive_all_splits"]
    splits = descriptive["per_split"]

    assert descriptive["input_records"] == 16
    assert descriptive["valid_records_before_deduplication"] == 11
    assert descriptive["retained_unique_records"] == 10
    assert descriptive["rejected_records"] == 5
    assert descriptive["exact_duplicate_occurrences"] == 1
    assert descriptive["exact_duplicate_rows_skipped"] == 1
    assert descriptive["cross_split_duplicate_fingerprint_groups"] == 1
    assert descriptive["rejection_counts_by_reason"] == {
        "impossible_timestamp": 1,
        "invalid_rating": 1,
        "invalid_timestamp": 1,
        "malformed_json": 1,
        "missing_or_invalid_identifier": 1,
    }

    train = splits["train"]
    assert train["retained_unique_records"] == 5
    assert train["rating_label_distribution"] == {
        "neutral": 1,
        "observed_low_rating": 2,
        "observed_positive_signal": 2,
    }
    assert train["timestamp_range_ms"] == {"min": 1000, "max": 3000}
    assert splits["validation"]["retained_unique_records"] == 3
    assert splits["test"]["retained_unique_records"] == 2
    assert descriptive["cold_start_diagnostics"]["validation"] == {
        "users_unseen_in_train": 1,
        "items_unseen_in_train": 2,
    }
    assert descriptive["cold_start_diagnostics"]["test"] == {
        "users_unseen_in_train": 1,
        "items_unseen_in_train": 1,
    }
    train_only = report["training_only"]
    assert train_only["source_split"] == "train"
    assert train_only["statistics"] == train

    train_records = _records(
        output_root / "first" / "interactions.train.processed.jsonl"
    )
    assert len(train_records) == 5
    assert [record["source_event_fingerprint"] for record in train_records] == [
        "a" * 64,
        "b" * 64,
        "c" * 64,
        "d" * 64,
        "e" * 64,
    ]
    assert all(record["split"] == "train" for record in train_records)

    validation_records = _records(
        output_root / "first" / "interactions.validation.processed.jsonl"
    )
    assert validation_records[0]["source_event_fingerprint"] == "a" * 64


def test_repeat_runs_are_reproducible_and_outputs_ignore_input_order(
    output_root: Path,
    tmp_path: Path,
) -> None:
    first = _process(output_root / "first")
    second = _process(output_root / "second")
    assert first == second

    reversed_files: dict[str, Path] = {}
    for split in ("train", "validation", "test"):
        original = (
            (_FIXTURES / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()
        )
        reversed_path = tmp_path / f"{split}-reversed.jsonl"
        reversed_path.write_text("\n".join(reversed(original)) + "\n", encoding="utf-8")
        reversed_files[split] = reversed_path

    reordered = _process(
        output_root / "reordered",
        train=reversed_files["train"],
        validation=reversed_files["validation"],
        test=reversed_files["test"],
    )
    for split in ("train", "validation", "test"):
        file_name = f"interactions.{split}.processed.jsonl"
        assert (output_root / "first" / file_name).read_bytes() == (
            output_root / "reordered" / file_name
        ).read_bytes()
    for output in first["outputs"]:
        output_path = output_root / "first" / output["file"]
        assert output["sha256"] == hashlib.sha256(output_path.read_bytes()).hexdigest()
    assert (
        first["quality_report"]["descriptive_all_splits"]
        == reordered["quality_report"]["descriptive_all_splits"]
    )


def test_held_out_changes_do_not_change_train_output_or_train_statistics(
    output_root: Path,
    tmp_path: Path,
) -> None:
    first = _process(output_root / "first")
    validation_rows = [
        json.loads(line)
        for line in (_FIXTURES / "validation.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    validation_rows[1]["user_key"] = "synthetic_changed_heldout_user"
    validation_rows[1]["item_key"] = "synthetic_changed_heldout_item"
    validation_rows[1]["rating"] = 1
    changed_validation = tmp_path / "changed-validation.jsonl"
    changed_validation.write_text(
        "\n".join(json.dumps(row) for row in validation_rows) + "\n",
        encoding="utf-8",
    )
    second = _process(
        output_root / "second",
        validation=changed_validation,
    )

    train_file = "interactions.train.processed.jsonl"
    assert (output_root / "first" / train_file).read_bytes() == (
        output_root / "second" / train_file
    ).read_bytes()
    assert (
        first["quality_report"]["training_only"]
        == second["quality_report"]["training_only"]
    )


def test_conflicting_fingerprint_rejects_all_variants_independent_of_order(
    output_root: Path,
    tmp_path: Path,
) -> None:
    fingerprint = "f" * 64
    train_rows = [
        {
            "user_key": "synthetic_user_one",
            "item_key": "synthetic_item_one",
            "event_time_ms": 1000,
            "rating": 4,
            "source_event_fingerprint": fingerprint,
            "split": "train",
        },
        {
            "user_key": "synthetic_user_two",
            "item_key": "synthetic_item_two",
            "event_time_ms": 2000,
            "rating": 2,
            "source_event_fingerprint": fingerprint,
            "split": "train",
        },
    ]
    train_path = tmp_path / "conflict.jsonl"
    train_path.write_text(
        "\n".join(json.dumps(row) for row in train_rows) + "\n", encoding="utf-8"
    )
    reversed_path = tmp_path / "conflict-reversed.jsonl"
    reversed_path.write_text(
        "\n".join(json.dumps(row) for row in reversed(train_rows)) + "\n",
        encoding="utf-8",
    )
    empty_validation = tmp_path / "validation.jsonl"
    empty_test = tmp_path / "test.jsonl"
    empty_validation.write_text("", encoding="utf-8")
    empty_test.write_text("", encoding="utf-8")

    first = _process(
        output_root / "conflict-first",
        train=train_path,
        validation=empty_validation,
        test=empty_test,
    )
    second = _process(
        output_root / "conflict-second",
        train=reversed_path,
        validation=empty_validation,
        test=empty_test,
    )

    for name in ("train", "validation", "test"):
        file_name = f"interactions.{name}.processed.jsonl"
        assert (output_root / "conflict-first" / file_name).read_bytes() == (
            output_root / "conflict-second" / file_name
        ).read_bytes()
    report = first["quality_report"]["descriptive_all_splits"]
    assert report == second["quality_report"]["descriptive_all_splits"]
    assert report["fingerprint_conflict_groups"] == 1
    assert report["fingerprint_conflict_records"] == 2
    assert report["rejection_counts_by_reason"]["fingerprint_conflict"] == 2
    assert report["retained_unique_records"] == 0


def test_cross_split_fingerprint_conflict_does_not_change_train_data(
    output_root: Path,
    tmp_path: Path,
) -> None:
    fingerprint = "e" * 64
    train_row = {
        "user_key": "synthetic_train_user",
        "item_key": "synthetic_train_item",
        "event_time_ms": 1000,
        "rating": 5,
        "source_event_fingerprint": fingerprint,
        "split": "train",
    }
    validation_row = {
        "user_key": "synthetic_heldout_user",
        "item_key": "synthetic_heldout_item",
        "event_time_ms": 2000,
        "rating": 1,
        "source_event_fingerprint": fingerprint,
        "split": "validation",
    }
    train_path = tmp_path / "train.jsonl"
    train_path.write_text(json.dumps(train_row) + "\n", encoding="utf-8")
    validation_path = tmp_path / "validation.jsonl"
    validation_path.write_text(json.dumps(validation_row) + "\n", encoding="utf-8")
    empty_validation = tmp_path / "empty-validation.jsonl"
    empty_validation.write_text("", encoding="utf-8")
    empty_test = tmp_path / "test.jsonl"
    empty_test.write_text("", encoding="utf-8")

    baseline = _process(
        output_root / "baseline",
        train=train_path,
        validation=empty_validation,
        test=empty_test,
    )
    with_cross_split_conflict = _process(
        output_root / "with-conflict",
        train=train_path,
        validation=validation_path,
        test=empty_test,
    )

    train_file = "interactions.train.processed.jsonl"
    assert (output_root / "baseline" / train_file).read_bytes() == (
        output_root / "with-conflict" / train_file
    ).read_bytes()
    assert (
        baseline["quality_report"]["training_only"]
        == with_cross_split_conflict["quality_report"]["training_only"]
    )
    report = with_cross_split_conflict["quality_report"]["descriptive_all_splits"]
    assert report["cross_split_fingerprint_conflict_groups"] == 1
    assert report["fingerprint_conflict_records"] == 0
    assert report["retained_unique_records"] == 2


def test_split_mismatch_and_invalid_event_type_are_counted(
    output_root: Path,
    tmp_path: Path,
) -> None:
    mismatch = {
        "user_key": "synthetic_user",
        "item_key": "synthetic_item",
        "event_time_ms": 1000,
        "rating": 4,
        "source_event_fingerprint": "8" * 64,
        "split": "validation",
    }
    bad_event_type = {
        "user_key": "synthetic_user",
        "item_key": "synthetic_item",
        "event_time_ms": 1000,
        "rating": 4,
        "source_event_fingerprint": "9" * 64,
        "split": "train",
        "event_type": 7,
    }
    train_path = tmp_path / "invalid-train.jsonl"
    train_path.write_text(
        json.dumps(mismatch) + "\n" + json.dumps(bad_event_type) + "\n",
        encoding="utf-8",
    )
    empty_validation = tmp_path / "empty-validation.jsonl"
    empty_test = tmp_path / "empty-test.jsonl"
    empty_validation.write_text("", encoding="utf-8")
    empty_test.write_text("", encoding="utf-8")

    manifest = _process(
        output_root / "invalid",
        train=train_path,
        validation=empty_validation,
        test=empty_test,
    )

    report = manifest["quality_report"]["descriptive_all_splits"]
    assert report["rejection_counts_by_reason"] == {
        "invalid_event_type": 1,
        "split_mismatch": 1,
    }
    assert report["retained_unique_records"] == 0


def test_existing_output_is_never_overwritten(output_root: Path) -> None:
    destination = output_root / "existing"
    destination.mkdir(parents=True)
    sentinel = destination / "sentinel.txt"
    sentinel.write_text("unchanged", encoding="utf-8")

    with pytest.raises(IngestionError, match="refusing to overwrite"):
        _process(destination)

    assert sentinel.read_text(encoding="utf-8") == "unchanged"
