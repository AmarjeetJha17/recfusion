import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_REPOSITORY_ROOT = Path(__file__).parents[2]
_FIXTURES = Path(__file__).parents[1] / "fixtures" / "amazon_electronics"
_PROCESSED_ROOT = _REPOSITORY_ROOT / "data" / "processed"
_T1_UTC = "2021-08-11T00:56:54.042Z"
_T2_UTC = "2022-07-16T20:18:49.837Z"


@pytest.fixture
def output_root(tmp_path: Path) -> Path:
    output = _PROCESSED_ROOT / f"amazon-adapter-test-{tmp_path.name}"
    try:
        yield output
    finally:
        if output.exists():
            shutil.rmtree(output)


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            str(_REPOSITORY_ROOT / "packages"),
            str(_REPOSITORY_ROOT / "apps" / "api" / "src"),
            environment.get("PYTHONPATH", ""),
        ]
    )
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "recfusion_data.cli",
            "--input-format",
            "csv",
            *args,
        ],
        cwd=_REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _ingest(
    output: Path, *, train: Path = _FIXTURES / "train.csv"
) -> dict[str, object]:
    result = _run_cli(
        "--adapter",
        "amazon-reviews-2023-electronics",
        "--train",
        str(train),
        "--validation",
        str(_FIXTURES / "validation.csv"),
        "--test",
        str(_FIXTURES / "test.csv"),
        "--source-id",
        "amazon-reviews-2023-electronics",
        "--source-version",
        "synthetic-fixture-v1",
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_cli_preserves_splits_and_reports_counts_deterministically(
    output_root: Path,
) -> None:
    first_dir = output_root / "first"
    second_dir = output_root / "second"

    first_summary = _ingest(first_dir)
    second_summary = _ingest(second_dir)
    first_manifest = json.loads((first_dir / "manifest.json").read_text())
    second_manifest = json.loads((second_dir / "manifest.json").read_text())

    assert first_manifest == second_manifest
    assert first_summary["counts"] == second_summary["counts"]
    counts = first_manifest["counts"]
    assert isinstance(counts, dict)
    split_counts = counts["interactions_by_split"]
    assert isinstance(split_counts, dict)
    assert split_counts["train"]["input_records"] == 11
    assert split_counts["train"]["valid_records"] == 4
    assert split_counts["train"]["rejected_records"] == 7
    assert split_counts["train"]["input_records"] == (
        split_counts["train"]["valid_records"]
        + split_counts["train"]["rejected_records"]
    )
    assert split_counts["train"]["duplicate_rows_skipped"] == 0
    assert split_counts["train"]["exact_duplicate_occurrences"] == 1
    assert split_counts["train"]["duplicate_rows_retained"] == 1
    assert split_counts["train"]["output_records"] == 4
    assert (
        split_counts["train"]["output_records"]
        == split_counts["train"]["valid_records"]
    )
    assert split_counts["validation"]["output_records"] == 1
    assert split_counts["test"]["output_records"] == 1

    train = _records(first_dir / "interactions.train.jsonl")
    validation = _records(first_dir / "interactions.validation.jsonl")
    test = _records(first_dir / "interactions.test.jsonl")
    assert all(record["split"] == "train" for record in train)
    assert len(train) == 4
    train_fingerprints = Counter(record["source_event_fingerprint"] for record in train)
    assert sorted(train_fingerprints.values()) == [1, 1, 2]
    assert all(record["split"] == "validation" for record in validation)
    assert all(record["split"] == "test" for record in test)
    assert set(train[0]) == {
        "user_key",
        "item_key",
        "event_time_ms",
        "rating",
        "source_event_fingerprint",
        "split",
    }
    assert validation[0]["event_time_ms"] == 1628643414042
    assert test[0]["event_time_ms"] == 1658002729837
    assert "synthetic_validation_only_user" not in json.dumps(validation)
    assert "source_event_id" not in validation[0]

    rejection_records = _records(first_dir / "rejections.train.jsonl")
    assert len(rejection_records) == 7
    assert all("synthetic_user_" not in json.dumps(row) for row in rejection_records)
    assert all("source_event_fingerprint" in row for row in rejection_records)
    assert all("exact_duplicate" not in json.dumps(row) for row in rejection_records)

    source_manifest = first_manifest["source"]
    assert source_manifest["id"] == "amazon-reviews-2023-electronics"
    assert source_manifest["version"] == "synthetic-fixture-v1"
    assert {entry["file"] for entry in source_manifest["files"].values()} == {
        "train.csv",
        "validation.csv",
        "test.csv",
    }
    assert "split_mapping" in first_manifest["configuration"]
    assert first_manifest["configuration"]["timestamp_unit"] == "unix_ms"

    outputs = first_manifest["outputs"]
    assert isinstance(outputs, list)
    for entry in outputs:
        artifact = first_dir / entry["file"]
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == entry["sha256"]


def test_cli_output_is_independent_of_train_row_order(
    output_root: Path, tmp_path: Path
) -> None:
    source_rows = (_FIXTURES / "train.csv").read_text().splitlines()
    reordered = tmp_path / "train.csv"
    reordered.write_text("\n".join([source_rows[0], *reversed(source_rows[1:])]) + "\n")

    original_dir = output_root / "original"
    reordered_dir = output_root / "reordered"
    _ingest(original_dir)
    _ingest(reordered_dir, train=reordered)

    assert (original_dir / "interactions.train.jsonl").read_bytes() == (
        reordered_dir / "interactions.train.jsonl"
    ).read_bytes()
    original_manifest = json.loads((original_dir / "manifest.json").read_text())
    reordered_manifest = json.loads((reordered_dir / "manifest.json").read_text())
    original_interaction_hashes = {
        entry["file"]: entry["sha256"]
        for entry in original_manifest["outputs"]
        if entry["file"].startswith("interactions.")
    }
    reordered_interaction_hashes = {
        entry["file"]: entry["sha256"]
        for entry in reordered_manifest["outputs"]
        if entry["file"].startswith("interactions.")
    }
    assert original_interaction_hashes == reordered_interaction_hashes
    assert original_manifest["counts"] == reordered_manifest["counts"]
    assert (
        original_manifest["source"]["files"]["train"]["sha256"]
        != (reordered_manifest["source"]["files"]["train"]["sha256"])
    )
    assert (original_dir / "rejections.train.jsonl").read_bytes() != (
        reordered_dir / "rejections.train.jsonl"
    ).read_bytes()


def test_cli_outputs_compatibility_with_preprocessor_and_trusted_splitter(
    output_root: Path,
) -> None:
    ingested = output_root / "ingested"
    _ingest(ingested)
    preprocessed = output_root / "preprocessed"
    preprocess = subprocess.run(
        [
            sys.executable,
            "-m",
            "recfusion_data.interaction_cli",
            "--train",
            str(ingested / "interactions.train.jsonl"),
            "--validation",
            str(ingested / "interactions.validation.jsonl"),
            "--test",
            str(ingested / "interactions.test.jsonl"),
            "--source-id",
            "amazon-reviews-2023-electronics",
            "--source-version",
            "synthetic-fixture-v1",
            "--output-dir",
            str(preprocessed),
        ],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert preprocess.returncode == 0, preprocess.stderr
    preprocessed_manifest = json.loads(
        (preprocessed / "manifest.json").read_text(encoding="utf-8")
    )
    quality = preprocessed_manifest["quality_report"]["descriptive_all_splits"]
    assert quality["valid_records_before_deduplication"] == 6
    assert quality["exact_duplicate_occurrences"] == 1
    assert quality["exact_duplicate_rows_skipped"] == 1
    assert quality["retained_unique_records"] == 5
    assert len(_records(preprocessed / "interactions.train.processed.jsonl")) == 3

    temporal = subprocess.run(
        [
            sys.executable,
            "-m",
            "recfusion_data.temporal_split_cli",
            "trusted-pre-split",
            "--train",
            str(preprocessed / "interactions.train.processed.jsonl"),
            "--validation",
            str(preprocessed / "interactions.validation.processed.jsonl"),
            "--test",
            str(preprocessed / "interactions.test.processed.jsonl"),
            "--train-end-utc",
            _T1_UTC,
            "--test-start-utc",
            _T2_UTC,
            "--source-id",
            "amazon-reviews-2023-electronics",
            "--source-version",
            "synthetic-fixture-v1",
            "--output-dir",
            str(output_root / "temporal"),
        ],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert temporal.returncode == 0, temporal.stderr
    result = json.loads(temporal.stdout)
    assert result["evaluation_eligible"] is True

    processed_test = _records(preprocessed / "interactions.test.processed.jsonl")
    assert processed_test[0]["event_time_utc"] == "2022-07-16T20:18:49.837Z"
    assert processed_test[0]["source_timestamp_value"] == 1658002729837


@pytest.mark.parametrize(
    "contents",
    [
        "",
        "user_id,parent_asin,rating\nsynthetic_user,synthetic_item,5\n",
        "user_id,parent_asin,rating,timestamp,extra\n",
        "user_id,user_id,rating,timestamp\n",
    ],
)
def test_cli_rejects_empty_or_mismatched_headers_atomically(
    output_root: Path, tmp_path: Path, contents: str
) -> None:
    bad_train = tmp_path / "train.csv"
    bad_train.write_text(contents, encoding="utf-8")
    output = output_root / "invalid-header"

    result = _run_cli(
        "--adapter",
        "amazon-reviews-2023-electronics",
        "--train",
        str(bad_train),
        "--validation",
        str(_FIXTURES / "validation.csv"),
        "--test",
        str(_FIXTURES / "test.csv"),
        "--source-id",
        "amazon-reviews-2023-electronics",
        "--source-version",
        "synthetic-fixture-v1",
        "--output-dir",
        str(output),
    )

    assert result.returncode == 2
    assert not output.exists()
    assert not list(output_root.glob(".invalid-header.tmp-*"))


def test_cli_rejects_invalid_utf8_without_publishing(
    output_root: Path, tmp_path: Path
) -> None:
    invalid_utf8 = tmp_path / "train.csv"
    invalid_utf8.write_bytes(
        b"user_id,parent_asin,rating,timestamp\n"
        b"synthetic_user,synthetic_item,5,1628643414041\n\xff\n"
    )
    output = output_root / "invalid-utf8"

    result = _run_cli(
        "--adapter",
        "amazon-reviews-2023-electronics",
        "--train",
        str(invalid_utf8),
        "--validation",
        str(_FIXTURES / "validation.csv"),
        "--test",
        str(_FIXTURES / "test.csv"),
        "--source-id",
        "amazon-reviews-2023-electronics",
        "--source-version",
        "synthetic-fixture-v1",
        "--output-dir",
        str(output),
    )

    assert result.returncode == 2
    assert not output.exists()


def test_amazon_adapter_rejects_products_option_through_cli(
    output_root: Path,
) -> None:
    result = _run_cli(
        "--adapter",
        "amazon-reviews-2023-electronics",
        "--train",
        str(_FIXTURES / "train.csv"),
        "--validation",
        str(_FIXTURES / "validation.csv"),
        "--test",
        str(_FIXTURES / "test.csv"),
        "--products",
        str(_FIXTURES / "train.csv"),
        "--source-id",
        "amazon-reviews-2023-electronics",
        "--source-version",
        "synthetic-fixture-v1",
        "--output-dir",
        str(output_root / "products-not-supported"),
    )

    assert result.returncode == 2
