import hashlib
import json
import shutil
from pathlib import Path
from typing import cast

import pytest

from recfusion_data.splitting.temporal import (
    TemporalCutoffs,
    process_trusted_pre_split,
    process_unsplit_with_cutoffs,
)

pytestmark = pytest.mark.integration

_REPOSITORY_ROOT = Path(__file__).parents[2]
_SCHEMA = "recfusion.interaction-preprocessing.v1"


@pytest.fixture
def output_root(tmp_path: Path) -> Path:
    path = _REPOSITORY_ROOT / "data" / "processed" / f"temporal-{tmp_path.name}"
    try:
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path)


def _record(
    fingerprint: str,
    user: str,
    item: str,
    timestamp: int,
    rating: int,
    *,
    split: str | None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_version": _SCHEMA,
        "user_key": user,
        "item_key": item,
        "event_time_ms": timestamp,
        "event_time_utc": (
            f"1970-01-01T00:00:{timestamp // 1000:02d}.{timestamp % 1000:03d}Z"
        ),
        "source_timestamp_value": timestamp,
        "source_timestamp_unit": "unix_ms",
        "rating": str(rating),
        "source_rating_value": rating,
        "rating_label": (
            "observed_positive_signal"
            if rating >= 4
            else "neutral"
            if rating == 3
            else "observed_low_rating"
        ),
        "event_type": None,
        "event_type_present": False,
        "source_event_id": None,
        "source_event_id_present": False,
        "source_event_fingerprint": fingerprint,
    }
    if split is not None:
        record["split"] = split
    return record


def _write(path: Path, records: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _trusted_inputs(root: Path) -> tuple[Path, Path, Path]:
    train = [
        _record("a" * 64, "user_a", "item_a", 1_000, 5, split="train"),
        _record("b" * 64, "user_a", "item_b", 1_500, 4, split="train"),
        _record("c" * 64, "user_b", "item_b", 1_999, 3, split="train"),
    ]
    validation = [
        _record("d" * 64, "user_a", "item_a", 2_000, 5, split="validation"),
        _record("e" * 64, "user_c", "item_a", 2_100, 5, split="validation"),
        _record("f" * 64, "user_a", "item_c", 2_200, 5, split="validation"),
        _record("1" * 64, "user_d", "item_d", 2_300, 5, split="validation"),
        _record("2" * 64, "user_b", "item_b", 2_400, 3, split="validation"),
    ]
    test = [
        _record("3" * 64, "user_a", "item_b", 4_000, 4, split="test"),
        _record("4" * 64, "user_e", "item_e", 4_100, 5, split="test"),
    ]
    return (
        _write(root / "train.jsonl", train),
        _write(root / "validation.jsonl", validation),
        _write(root / "test.jsonl", test),
    )


def _process_trusted(
    output_dir: Path,
    inputs: tuple[Path, Path, Path],
    *,
    cutoffs: TemporalCutoffs | None = None,
) -> dict[str, object]:
    result = process_trusted_pre_split(
        train_path=inputs[0],
        validation_path=inputs[1],
        test_path=inputs[2],
        output_dir=output_dir,
        source_id="synthetic-temporal",
        source_version="v1",
        cutoffs=cutoffs,
    )
    return dict(result.manifest)


def test_trusted_splits_preserve_membership_and_fit_vocab_from_train_only(
    output_root: Path,
    tmp_path: Path,
) -> None:
    manifest = _process_trusted(
        output_root / "clean",
        _trusted_inputs(tmp_path / "input"),
        cutoffs=TemporalCutoffs(2_000, 4_000),
    )

    assert manifest["integrity_status"]["evaluation_eligible"] is True
    assert manifest["integrity_status"]["source_split_membership_changed"] == 0
    assert manifest["counts"]["split_counts"]["train"]["input_accepted_records"] == 3
    assert (
        manifest["counts"]["split_counts"]["validation"]["input_accepted_records"] == 5
    )

    train_rows = _records(output_root / "clean" / "interactions.train.jsonl")
    validation_rows = _records(output_root / "clean" / "interactions.validation.jsonl")
    test_rows = _records(output_root / "clean" / "interactions.test.jsonl")
    assert {row["split"] for row in train_rows} == {"train"}
    assert {row["split"] for row in validation_rows} == {"validation"}
    assert {row["split"] for row in test_rows} == {"test"}
    assert all(row["source_split"] == row["split"] for row in train_rows)

    user_vocab = _records(output_root / "clean" / "vocabulary.users.jsonl")
    item_vocab = _records(output_root / "clean" / "vocabulary.items.jsonl")
    candidates = _records(output_root / "clean" / "candidate-pool.items.jsonl")
    assert user_vocab[0]["index"] == item_vocab[0]["index"] == 0
    assert [row["source_key"] for row in user_vocab[1:]] == ["user_a", "user_b"]
    assert [row["source_key"] for row in item_vocab[1:]] == ["item_a", "item_b"]
    assert [row["item_key"] for row in candidates] == ["item_a", "item_b"]
    assert all(
        row["item_key"] not in {"item_c", "item_d", "item_e"} for row in candidates
    )

    evaluation = _records(output_root / "clean" / "evaluation.jsonl")
    cohorts = [row["evaluation_eligibility"]["cohort"] for row in evaluation]
    assert cohorts == [
        "warm_user_and_item",
        "cold_user",
        "cold_item",
        "both_user_and_item_cold",
        "warm_user_and_item",
        "warm_user_and_item",
        "both_user_and_item_cold",
    ]
    assert (
        sum(
            bool(row["evaluation_eligibility"]["warm_metric_eligible"])
            for row in evaluation
        )
        == 2
    )
    assert all(
        row["evaluation_eligibility"]["exclusion_reasons"]
        for row in evaluation
        if not row["evaluation_eligibility"]["warm_metric_eligible"]
    )


def test_absolute_cutoffs_assign_half_open_boundaries_and_equal_times(
    output_root: Path,
    tmp_path: Path,
) -> None:
    unsplit = _write(
        tmp_path / "unsplit.jsonl",
        [
            _record("a" * 64, "user_a", "item_a", 1_999, 5, split=None),
            _record("b" * 64, "user_a", "item_b", 2_000, 5, split=None),
            _record("c" * 64, "user_b", "item_b", 2_000, 3, split=None),
            _record("d" * 64, "user_b", "item_a", 3_999, 4, split=None),
            _record("e" * 64, "user_a", "item_a", 4_000, 4, split=None),
        ],
    )
    result = process_unsplit_with_cutoffs(
        input_path=unsplit,
        output_dir=output_root / "absolute",
        source_id="synthetic-temporal",
        source_version="v1",
        cutoffs=TemporalCutoffs(2_000, 4_000),
    )

    assert result.manifest["integrity_status"]["evaluation_eligible"] is True
    assert len(_records(output_root / "absolute" / "interactions.train.jsonl")) == 1
    validation = _records(output_root / "absolute" / "interactions.validation.jsonl")
    test = _records(output_root / "absolute" / "interactions.test.jsonl")
    assert len(validation) == 3
    assert {row["interaction"]["event_time_ms"] for row in validation} == {2_000, 3_999}
    assert len(test) == 1
    assert test[0]["interaction"]["event_time_ms"] == 4_000
    assert all(row["source_split"] is None for row in validation + test)
    assert all(
        row["split_origin"] == "absolute_utc_cutoffs" for row in validation + test
    )


def test_duplicate_and_conflicting_fingerprints_are_retained_and_block_evaluation(
    output_root: Path,
    tmp_path: Path,
) -> None:
    shared = _record("a" * 64, "user_a", "item_a", 1_000, 5, split="train")
    conflict_train = _record("b" * 64, "user_b", "item_b", 1_500, 4, split="train")
    conflict_test = _record("b" * 64, "user_b", "item_b", 1_500, 2, split="test")
    inputs = (
        _write(tmp_path / "duplicates" / "train.jsonl", [shared, conflict_train]),
        _write(
            tmp_path / "duplicates" / "validation.jsonl",
            [
                {**shared, "split": "validation"},
                {**shared, "split": "validation"},
            ],
        ),
        _write(tmp_path / "duplicates" / "test.jsonl", [conflict_test]),
    )

    manifest = _process_trusted(output_root / "duplicates", inputs)
    counts = manifest["counts"]["integrity"]
    assert counts["exact_cross_split_duplicate_groups"] == 1
    assert counts["within_split_exact_duplicate_occurrences"] == 1
    assert counts["fingerprint_conflict_groups"] == 1
    assert manifest["integrity_status"]["evaluation_eligible"] is False
    assert (
        "exact_cross_split_duplicate"
        in manifest["integrity_status"]["blocking_violations"]
    )
    assert (
        "conflicting_source_event_fingerprint"
        in manifest["integrity_status"]["blocking_violations"]
    )
    assert len(_records(output_root / "duplicates" / "interactions.train.jsonl")) == 2
    assert (
        len(_records(output_root / "duplicates" / "interactions.validation.jsonl")) == 2
    )
    evaluation = _records(output_root / "duplicates" / "evaluation.jsonl")
    assert len(evaluation) == 3
    assert all(
        not row["evaluation_eligibility"]["warm_metric_eligible"] for row in evaluation
    )
    assert any(
        "repeated_exact_record_within_split" in row["integrity_flags"]
        for row in _records(
            output_root / "duplicates" / "interactions.validation.jsonl"
        )
    )


def test_invalid_split_and_temporal_contradictions_are_audited_not_reassigned(
    output_root: Path,
    tmp_path: Path,
) -> None:
    inputs = (
        _write(
            tmp_path / "invalid" / "train.jsonl",
            [_record("a" * 64, "user_a", "item_a", 2_000, 5, split="train")],
        ),
        _write(
            tmp_path / "invalid" / "validation.jsonl",
            [
                _record("b" * 64, "user_b", "item_b", 1_999, 4, split="validation"),
                _record("c" * 64, "user_c", "item_c", 2_100, 4, split="not-a-split"),
            ],
        ),
        _write(
            tmp_path / "invalid" / "test.jsonl",
            [_record("d" * 64, "user_d", "item_d", 4_000, 4, split="test")],
        ),
    )
    manifest = _process_trusted(
        output_root / "invalid",
        inputs,
        cutoffs=TemporalCutoffs(2_000, 4_000),
    )

    assert manifest["counts"]["rejected_by_reason"] == {"invalid_split_label": 1}
    assert (
        manifest["integrity_status"]["blocking_violations"][
            "temporal_boundary_mismatch"
        ]
        == 2
    )
    assert manifest["integrity_status"]["evaluation_eligible"] is False
    train_rows = _records(output_root / "invalid" / "interactions.train.jsonl")
    validation_rows = _records(
        output_root / "invalid" / "interactions.validation.jsonl"
    )
    assert train_rows[0]["split"] == "train"
    assert train_rows[0]["integrity_flags"] == ["temporal_boundary_mismatch"]
    assert validation_rows[0]["split"] == "validation"
    assert validation_rows[0]["integrity_flags"] == ["temporal_boundary_mismatch"]


def test_trusted_chronological_overlap_blocks_without_cutoff_reassignment(
    output_root: Path,
    tmp_path: Path,
) -> None:
    inputs = (
        _write(
            tmp_path / "overlap" / "train.jsonl",
            [_record("a" * 64, "user_a", "item_a", 3_000, 5, split="train")],
        ),
        _write(
            tmp_path / "overlap" / "validation.jsonl",
            [_record("b" * 64, "user_b", "item_b", 2_000, 4, split="validation")],
        ),
        _write(
            tmp_path / "overlap" / "test.jsonl",
            [_record("c" * 64, "user_c", "item_c", 4_000, 4, split="test")],
        ),
    )
    manifest = _process_trusted(output_root / "overlap", inputs)

    assert manifest["integrity_status"]["chronological_overlap_records"] == 2
    assert (
        manifest["integrity_status"]["blocking_violations"]["chronological_overlap"]
        == 2
    )
    assert manifest["integrity_status"]["evaluation_eligible"] is False
    assert len(_records(output_root / "overlap" / "interactions.train.jsonl")) == 1
    assert len(_records(output_root / "overlap" / "interactions.validation.jsonl")) == 1


def test_empty_heldout_splits_are_reported_without_changing_training_membership(
    output_root: Path,
    tmp_path: Path,
) -> None:
    inputs = (
        _write(
            tmp_path / "sparse" / "train.jsonl",
            [_record("a" * 64, "user_a", "item_a", 1_000, 5, split="train")],
        ),
        _write(tmp_path / "sparse" / "validation.jsonl", []),
        _write(tmp_path / "sparse" / "test.jsonl", []),
    )
    manifest = _process_trusted(output_root / "sparse", inputs)

    assert manifest["integrity_status"]["evaluation_eligible"] is True
    assert manifest["integrity_status"]["report_only_warnings"] == {
        "empty_test_split": 1,
        "empty_validation_split": 1,
        "no_warm_positive_evaluation_targets": 1,
    }
    assert len(_records(output_root / "sparse" / "interactions.train.jsonl")) == 1
    assert _records(output_root / "sparse" / "evaluation.jsonl") == []


def test_preassigned_membership_is_rejected_by_absolute_cutoff_mode(
    output_root: Path,
    tmp_path: Path,
) -> None:
    assigned = _write(
        tmp_path / "assigned.jsonl",
        [_record("a" * 64, "user_a", "item_a", 1_000, 5, split="train")],
    )
    result = process_unsplit_with_cutoffs(
        input_path=assigned,
        output_dir=output_root / "reject-assigned",
        source_id="synthetic-temporal",
        source_version="v1",
        cutoffs=TemporalCutoffs(2_000, 4_000),
    )

    assert result.manifest["counts"]["rejected_by_reason"] == {
        "preassigned_split_in_unsplit_input": 1
    }
    assert result.manifest["integrity_status"]["evaluation_eligible"] is False
    assert _records(output_root / "reject-assigned" / "interactions.train.jsonl") == []


def test_noncanonical_derived_field_types_are_counted_as_rejections(
    output_root: Path,
    tmp_path: Path,
) -> None:
    invalid_timestamp = _record("b" * 64, "user_b", "item_b", 1_500, 4, split="train")
    invalid_timestamp["event_time_ms"] = "1500"
    invalid_label = _record("c" * 64, "user_c", "item_c", 1_600, 4, split="train")
    invalid_label["rating_label"] = []
    inputs = (
        _write(
            tmp_path / "types" / "train.jsonl",
            [
                _record("a" * 64, "user_a", "item_a", 1_000, 5, split="train"),
                invalid_timestamp,
                invalid_label,
            ],
        ),
        _write(tmp_path / "types" / "validation.jsonl", []),
        _write(tmp_path / "types" / "test.jsonl", []),
    )

    manifest = _process_trusted(output_root / "types", inputs)

    assert manifest["counts"]["rejected_by_reason"] == {
        "invalid_derived_timestamp_type": 1,
        "invalid_rating_label": 1,
    }
    assert manifest["counts"]["split_counts"]["train"]["input_accepted_records"] == 1


def test_outputs_are_order_independent_and_heldout_data_cannot_change_vocab(
    output_root: Path,
    tmp_path: Path,
) -> None:
    inputs = _trusted_inputs(tmp_path / "stable-input")
    first_manifest = _process_trusted(output_root / "first", inputs)
    repeated_manifest = _process_trusted(output_root / "repeat", inputs)
    assert first_manifest == repeated_manifest
    encoded_manifest = json.dumps(first_manifest)
    assert '"user_a"' not in encoded_manifest
    assert '"item_a"' not in encoded_manifest

    reordered = (
        inputs[0],
        _write(
            tmp_path / "reordered-validation.jsonl",
            list(reversed(_records(inputs[1]))),
        ),
        _write(
            tmp_path / "reordered-test.jsonl",
            list(reversed(_records(inputs[2]))),
        ),
    )
    _process_trusted(output_root / "reordered", reordered)
    for filename in (
        "vocabulary.users.jsonl",
        "vocabulary.items.jsonl",
        "candidate-pool.items.jsonl",
        "interactions.validation.jsonl",
        "interactions.test.jsonl",
        "evaluation.jsonl",
    ):
        first = (output_root / "first" / filename).read_bytes()
        second = (output_root / "reordered" / filename).read_bytes()
        assert hashlib.sha256(first).digest() == hashlib.sha256(second).digest()

    changed_heldout = (
        inputs[0],
        inputs[1],
        _write(
            tmp_path / "changed-test.jsonl",
            [
                _record("5" * 64, "new_user", "new_item", 4_200, 5, split="test"),
            ],
        ),
    )
    _process_trusted(output_root / "heldout-changed", changed_heldout)
    for filename in (
        "vocabulary.users.jsonl",
        "vocabulary.items.jsonl",
        "candidate-pool.items.jsonl",
    ):
        assert (output_root / "first" / filename).read_bytes() == (
            output_root / "heldout-changed" / filename
        ).read_bytes()

    outputs = cast(list[dict[str, object]], first_manifest["outputs"])
    for output in outputs:
        filename = cast(str, output["file"])
        content = (output_root / "first" / filename).read_bytes()
        assert output["sha256"] == hashlib.sha256(content).hexdigest()
        assert output["size_bytes"] == len(content)
