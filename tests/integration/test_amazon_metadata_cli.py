from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from recfusion_data.ingestion import amazon_metadata_pipeline
from recfusion_data.metadata_cli import main
from recfusion_data.splitting.temporal import process_trusted_pre_split

pytestmark = pytest.mark.integration

_REPOSITORY_ROOT = Path(__file__).parents[2]
_PROCESSED_ROOT = _REPOSITORY_ROOT / "data" / "processed"
_INTERACTION_SCHEMA = "recfusion.interaction-preprocessing.v1"


def _interaction(
    *, fingerprint: str, user: str, item: str, timestamp: int, split: str
) -> dict[str, object]:
    return {
        "schema_version": _INTERACTION_SCHEMA,
        "user_key": f"synthetic-user-{user}",
        "item_key": f"ar23:Electronics:item:{item}",
        "event_time_ms": timestamp,
        "event_time_utc": (
            f"1970-01-01T00:00:{timestamp // 1000:02d}.{timestamp % 1000:03d}Z"
        ),
        "source_timestamp_value": timestamp,
        "source_timestamp_unit": "unix_ms",
        "rating": "5",
        "source_rating_value": 5,
        "rating_label": "observed_positive_signal",
        "event_type": None,
        "event_type_present": False,
        "source_event_id": None,
        "source_event_id_present": False,
        "source_event_fingerprint": fingerprint,
        "split": split,
    }


def _write_interactions(path: Path, rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _metadata_rows() -> list[bytes]:
    rows: list[bytes | dict[str, object]] = [
        {
            "parent_asin": "SYNTH_A",
            "title": "Synthetic A",
            "main_category": "Electronics",
            "categories": ["Computers", "Laptops"],
            "description": ["Invented description"],
            "features": ["Invented feature"],
            "details": {"RAM": "16 GB", "Brand": "Synthetic Brand"},
            "store": "Synthetic Store",
            "average_rating": 4.9,
            "rating_number": 99,
            "price": 123.45,
            "images": [{"hi_res": "https://example.invalid/image"}],
            "videos": [{"title": "Synthetic video"}],
        },
        {
            "parent_asin": "SYNTH_B",
            "categories": [],
            "details": "{'not': 'JSON'}",
        },
        {"parent_asin": "SYNTH_C", "title": "Held-out-only item"},
        {
            "parent_asin": "SYNTH_A",
            "title": "Synthetic A",
            "main_category": "Electronics",
            "categories": ["Computers", "Laptops"],
            "description": ["Invented description"],
            "features": ["Invented feature"],
            "details": {"RAM": "16 GB", "Brand": "Synthetic Brand"},
            "store": "Synthetic Store",
            "average_rating": 4.9,
            "rating_number": 99,
            "price": 123.45,
            "images": [{"hi_res": "https://example.invalid/image"}],
            "videos": [{"title": "Synthetic video"}],
        },
        {"parent_asin": "SYNTH_A", "title": "Conflicting synthetic title"},
        {"asin": "SYNTH_CHILD_ONLY", "title": "Child key cannot join"},
        b"{invalid-json\n",
        b"[]\n",
    ]
    return [
        row
        if isinstance(row, bytes)
        else json.dumps(row, sort_keys=True).encode() + b"\n"
        for row in rows
    ]


def _write_gzip(path: Path, lines: list[bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(b"".join(lines), mtime=0))
    return path


def _write_jsonl(path: Path, lines: list[bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(lines))
    return path


@pytest.fixture
def run_root(tmp_path: Path) -> Path:
    path = _PROCESSED_ROOT / f"amazon-metadata-synthetic-{tmp_path.name}"
    shutil.rmtree(path, ignore_errors=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _prepare_temporal_inputs(root: Path) -> tuple[Path, Path, Path]:
    train = _write_interactions(
        root / "inputs" / "train.jsonl",
        [
            _interaction(
                fingerprint="a" * 64,
                user="1",
                item="SYNTH_A",
                timestamp=1_000,
                split="train",
            ),
            _interaction(
                fingerprint="b" * 64,
                user="1",
                item="SYNTH_B",
                timestamp=1_500,
                split="train",
            ),
            _interaction(
                fingerprint="c" * 64,
                user="2",
                item="SYNTH_MISSING",
                timestamp=1_800,
                split="train",
            ),
        ],
    )
    validation = _write_interactions(
        root / "inputs" / "validation.jsonl",
        [
            _interaction(
                fingerprint="d" * 64,
                user="1",
                item="SYNTH_C",
                timestamp=2_000,
                split="validation",
            )
        ],
    )
    test = _write_interactions(
        root / "inputs" / "test.jsonl",
        [
            _interaction(
                fingerprint="e" * 64,
                user="1",
                item="SYNTH_C",
                timestamp=3_000,
                split="test",
            )
        ],
    )
    process_trusted_pre_split(
        train_path=train,
        validation_path=validation,
        test_path=test,
        output_dir=root / "temporal",
        source_id="synthetic-metadata-join",
        source_version="fixture-v1",
    )
    return (
        root / "temporal" / "vocabulary.items.jsonl",
        root / "temporal" / "manifest.json",
        train,
    )


def _run_cli(
    *,
    source: Path,
    vocabulary: Path,
    temporal_manifest: Path,
    output: Path,
    temp_dir: Path,
    capsys: pytest.CaptureFixture[str],
    source_url: str | None = None,
    retrieved_at: str | None = None,
    retrieval_method: str | None = None,
    publisher_sha256: str | None = None,
) -> dict[str, object]:
    arguments = [
        "--adapter",
        "amazon-reviews-2023-electronics-metadata",
        "--metadata",
        str(source),
        "--train-vocabulary",
        str(vocabulary),
        "--temporal-manifest",
        str(temporal_manifest),
        "--source-id",
        "synthetic-amazon-electronics",
        "--source-version",
        "fixture-v1",
        "--output-dir",
        str(output),
        "--temp-dir",
        str(temp_dir),
    ]
    for flag, value in (
        ("--source-url", source_url),
        ("--retrieved-at", retrieved_at),
        ("--retrieval-method", retrieval_method),
        ("--publisher-sha256", publisher_sha256),
    ):
        if value is not None:
            arguments.extend((flag, value))
    result = main(arguments)
    assert result == 0
    return cast(dict[str, object], json.loads(capsys.readouterr().out))


def test_synthetic_cli_join_reconciles_and_is_order_independent(
    run_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vocabulary, temporal_manifest, _ = _prepare_temporal_inputs(run_root)
    temp_dir = tmp_path / "sqlite-temp"
    temp_dir.mkdir()
    lines = _metadata_rows()
    first_source = _write_gzip(tmp_path / "metadata-a.jsonl.gz", lines)
    second_source = _write_gzip(tmp_path / "metadata-b.jsonl.gz", list(reversed(lines)))

    first = _run_cli(
        source=first_source,
        vocabulary=vocabulary,
        temporal_manifest=temporal_manifest,
        output=run_root / "run-a",
        temp_dir=temp_dir,
        capsys=capsys,
    )
    second = _run_cli(
        source=second_source,
        vocabulary=vocabulary,
        temporal_manifest=temporal_manifest,
        output=run_root / "run-b",
        temp_dir=temp_dir,
        capsys=capsys,
    )

    assert first["outputs"] == second["outputs"]
    assert first["source_records_read"] == 8
    assert first["matched_source_records"] == 4
    assert first["matched_unique_products"] == 2
    assert first["missing_target_products"] == 1
    assert first["rejected_records"] == 3
    assert first["canonical_output_records"] == 3
    first_manifest = json.loads((run_root / "run-a" / "manifest.json").read_text())
    second_manifest = json.loads((run_root / "run-b" / "manifest.json").read_text())
    first_counts = first_manifest["counts"]
    assert first_counts["valid_source_records"] == 5
    assert first_counts["unmatched_source_records"] == 1
    assert first_counts["unique_matched_source_records"] == 3
    assert first_counts["exact_duplicate_matched_occurrences"] == 1
    assert first_counts["matched_conflicting_item_keys"] == 1
    assert first_counts["missing_titles"] == 1
    assert first_counts["rejected_by_reason"] == {
        "invalid_source_identifier": 1,
        "malformed_json": 1,
        "record_not_object": 1,
    }
    assert first_counts["field_issues"]["malformed_details"] == 1
    assert (
        first_manifest["target_vocabulary"]["validation_or_test_used_for_matching"]
        is False
    )
    output_hashes = [entry["sha256"] for entry in first_manifest["outputs"]]
    reordered_hashes = [entry["sha256"] for entry in second_manifest["outputs"]]
    assert output_hashes == reordered_hashes
    assert (
        first_manifest["source"]["input"]["sha256"]
        != second_manifest["source"]["input"]["sha256"]
    )

    products = [
        json.loads(line)
        for line in (run_root / "run-a" / "products.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [record["item_key"] for record in products] == [
        "ar23:Electronics:item:SYNTH_A",
        "ar23:Electronics:item:SYNTH_A",
        "ar23:Electronics:item:SYNTH_B",
    ]
    assert all(
        record["images"] is None and record["videos"] is None for record in products
    )
    assert all("example.invalid" not in json.dumps(record) for record in products)
    assert all("SYNTH_C" not in json.dumps(record) for record in products)
    normalized = [
        json.loads(line)
        for line in (run_root / "run-a" / "products.normalized.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [record["normalization"]["product_decision"] for record in normalized] == [
        "conflict_retained",
        "conflict_retained",
        "unique_retained",
    ]
    assert all(
        record["normalization"]["source_record_fingerprint"]
        == record["product"]["source_record_fingerprint"]
        for record in normalized
    )
    assert list(temp_dir.iterdir()) == []


def test_plain_jsonl_matches_gzip_and_reports_split_join_coverage(
    run_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vocabulary, temporal_manifest, _ = _prepare_temporal_inputs(run_root)
    temp_dir = tmp_path / "sqlite-temp-formats"
    temp_dir.mkdir()
    lines = _metadata_rows()
    plain = _write_jsonl(tmp_path / "metadata.jsonl", lines)
    compressed = _write_gzip(tmp_path / "metadata.jsonl.gz", lines)
    publisher_hash = hashlib.sha256(plain.read_bytes()).hexdigest()
    declared_provenance = {
        "source_url": "https://example.invalid/synthetic-metadata.jsonl",
        "retrieved_at": "2026-11-26T00:00:00Z",
        "retrieval_method": "synthetic_fixture",
        "publisher_sha256": publisher_hash,
    }

    _run_cli(
        source=plain,
        vocabulary=vocabulary,
        temporal_manifest=temporal_manifest,
        output=run_root / "plain-run",
        temp_dir=temp_dir,
        capsys=capsys,
        **declared_provenance,
    )
    _run_cli(
        source=compressed,
        vocabulary=vocabulary,
        temporal_manifest=temporal_manifest,
        output=run_root / "gzip-run",
        temp_dir=temp_dir,
        capsys=capsys,
    )
    _run_cli(
        source=plain,
        vocabulary=vocabulary,
        temporal_manifest=temporal_manifest,
        output=run_root / "plain-repeat",
        temp_dir=temp_dir,
        capsys=capsys,
        **declared_provenance,
    )

    plain_manifest = json.loads((run_root / "plain-run" / "manifest.json").read_text())
    gzip_manifest = json.loads((run_root / "gzip-run" / "manifest.json").read_text())
    repeated_manifest = json.loads(
        (run_root / "plain-repeat" / "manifest.json").read_text()
    )
    assert plain_manifest == repeated_manifest
    assert [output["sha256"] for output in plain_manifest["outputs"]] == [
        output["sha256"] for output in gzip_manifest["outputs"]
    ]
    assert plain_manifest["source"]["representation"] == "jsonl"
    assert gzip_manifest["source"]["representation"] == "jsonl.gz"
    assert plain_manifest["source"]["declared_provenance"] == {
        **declared_provenance,
        "verification_status": "declared values are not independently verified",
    }
    assert (
        plain_manifest["source"]["locally_verified"]["publisher_sha256_match"] is True
    )
    assert hashlib.sha256(plain.read_bytes()).hexdigest() == publisher_hash
    assert gzip_manifest["source"]["declared_provenance"]["source_url"] is None
    assert plain_manifest["source"]["locally_verified"]["sha256"]
    assert plain_manifest["provenance"]["snapshot_only"] is True
    assert plain_manifest["provenance"]["normalization_schema_version"] == (
        "recfusion.product-normalization.v1"
    )

    coverage = plain_manifest["interaction_join_coverage"]
    assert coverage["candidate_pool_changed"] is False
    assert coverage["heldout_labels_used"] is False
    assert coverage["splits"]["train"] == {
        "interaction_rows": 3,
        "unique_items": 3,
        "train_known_interaction_rows": 3,
        "train_known_unique_items": 3,
        "train_cold_interaction_rows": 0,
        "train_cold_unique_items": 0,
        "metadata_matched_interaction_rows": 2,
        "metadata_matched_unique_items": 2,
        "feature_ready_interaction_rows": 1,
        "feature_ready_unique_items": 1,
        "conflict_excluded_interaction_rows": 1,
        "conflict_excluded_unique_items": 1,
        "missing_train_known_interaction_rows": 1,
        "missing_train_known_unique_items": 1,
        "coverage_denominators": {
            "all_interaction_rows": 3,
            "all_unique_items": 3,
            "train_known_interaction_rows": 3,
            "train_known_unique_items": 3,
        },
    }
    assert coverage["splits"]["validation"]["train_cold_interaction_rows"] == 1
    assert coverage["splits"]["test"]["train_cold_interaction_rows"] == 1


def test_corrupt_gzip_does_not_publish_or_leave_temp_files(
    run_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vocabulary, temporal_manifest, _ = _prepare_temporal_inputs(run_root)
    temp_dir = tmp_path / "sqlite-temp-corrupt"
    temp_dir.mkdir()
    source = tmp_path / "corrupt.jsonl.gz"
    source.write_bytes(b"not a gzip file")
    output = run_root / "corrupt-run"

    result = main(
        [
            "--adapter",
            "amazon-reviews-2023-electronics-metadata",
            "--metadata",
            str(source),
            "--train-vocabulary",
            str(vocabulary),
            "--temporal-manifest",
            str(temporal_manifest),
            "--source-id",
            "synthetic-amazon-electronics",
            "--source-version",
            "fixture-v1",
            "--output-dir",
            str(output),
            "--temp-dir",
            str(temp_dir),
        ]
    )

    assert result == 2
    assert "valid complete gzip" in capsys.readouterr().err
    assert not output.exists()
    assert list(temp_dir.iterdir()) == []


def test_cli_requires_an_explicit_sqlite_temp_directory(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "--adapter",
                "amazon-reviews-2023-electronics-metadata",
                "--metadata",
                "missing.jsonl",
                "--train-vocabulary",
                "vocabulary.items.jsonl",
                "--temporal-manifest",
                "manifest.json",
                "--source-id",
                "synthetic-source",
                "--source-version",
                "fixture-v1",
                "--output-dir",
                "data/processed/synthetic-metadata-output",
            ]
        )

    assert error.value.code == 2
    assert "--temp-dir" in capsys.readouterr().err


def test_vocabulary_manifest_checksum_is_required(
    run_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vocabulary, temporal_manifest, _ = _prepare_temporal_inputs(run_root)
    vocabulary.write_text(
        vocabulary.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    temp_dir = tmp_path / "sqlite-temp-checksum"
    temp_dir.mkdir()
    source = _write_gzip(tmp_path / "empty-valid.jsonl.gz", [])
    output = run_root / "checksum-run"

    result = main(
        [
            "--adapter",
            "amazon-reviews-2023-electronics-metadata",
            "--metadata",
            str(source),
            "--train-vocabulary",
            str(vocabulary),
            "--temporal-manifest",
            str(temporal_manifest),
            "--source-id",
            "synthetic-amazon-electronics",
            "--source-version",
            "fixture-v1",
            "--output-dir",
            str(output),
            "--temp-dir",
            str(temp_dir),
        ]
    )

    assert result == 2
    assert "checksum" in capsys.readouterr().err
    assert not output.exists()


def test_existing_output_is_never_overwritten(
    run_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vocabulary, temporal_manifest, _ = _prepare_temporal_inputs(run_root)
    source = _write_gzip(tmp_path / "synthetic-metadata.jsonl.gz", _metadata_rows())
    temp_dir = tmp_path / "sqlite-temp-overwrite"
    temp_dir.mkdir()
    output = run_root / "existing-run"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("preserve existing output", encoding="utf-8")

    result = main(
        [
            "--adapter",
            "amazon-reviews-2023-electronics-metadata",
            "--metadata",
            str(source),
            "--train-vocabulary",
            str(vocabulary),
            "--temporal-manifest",
            str(temporal_manifest),
            "--source-id",
            "synthetic-amazon-electronics",
            "--source-version",
            "fixture-v1",
            "--output-dir",
            str(output),
            "--temp-dir",
            str(temp_dir),
        ]
    )

    assert result == 2
    assert "new, non-existing child directory" in capsys.readouterr().err
    assert sentinel.read_text(encoding="utf-8") == "preserve existing output"
    assert list(temp_dir.iterdir()) == []


def test_publisher_checksum_mismatch_rejects_before_publication(
    run_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vocabulary, temporal_manifest, _ = _prepare_temporal_inputs(run_root)
    complete_content = b"".join(_metadata_rows())
    source = _write_jsonl(tmp_path / "metadata.jsonl", _metadata_rows())
    source.write_bytes(complete_content[:-12])
    temp_dir = tmp_path / "sqlite-temp-publisher-checksum"
    temp_dir.mkdir()
    output = run_root / "publisher-checksum-run"

    result = main(
        [
            "--adapter",
            "amazon-reviews-2023-electronics-metadata",
            "--metadata",
            str(source),
            "--train-vocabulary",
            str(vocabulary),
            "--temporal-manifest",
            str(temporal_manifest),
            "--source-id",
            "synthetic-amazon-electronics",
            "--source-version",
            "fixture-v1",
            "--publisher-sha256",
            hashlib.sha256(complete_content).hexdigest(),
            "--output-dir",
            str(output),
            "--temp-dir",
            str(temp_dir),
        ]
    )

    assert result == 2
    assert "publisher SHA-256 mismatch" in capsys.readouterr().err
    assert not output.exists()
    assert list(temp_dir.iterdir()) == []


def test_failed_manifest_write_cleans_staging_and_retry_is_deterministic(
    run_root: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vocabulary, temporal_manifest, _ = _prepare_temporal_inputs(run_root)
    source = _write_gzip(tmp_path / "retry-metadata.jsonl.gz", _metadata_rows())
    temp_dir = tmp_path / "sqlite-temp-retry"
    temp_dir.mkdir()
    expected = _run_cli(
        source=source,
        vocabulary=vocabulary,
        temporal_manifest=temporal_manifest,
        output=run_root / "expected-run",
        temp_dir=temp_dir,
        capsys=capsys,
    )
    expected_manifest = (run_root / "expected-run" / "manifest.json").read_bytes()
    failed_output = run_root / "retry-run"
    original_write_manifest = amazon_metadata_pipeline.write_manifest

    def fail_after_manifest_write(path: Path, manifest: Mapping[str, object]) -> bytes:
        original_write_manifest(path, manifest)
        raise OSError("synthetic interruption before publication")

    monkeypatch.setattr(
        amazon_metadata_pipeline, "write_manifest", fail_after_manifest_write
    )
    result = main(
        [
            "--adapter",
            "amazon-reviews-2023-electronics-metadata",
            "--metadata",
            str(source),
            "--train-vocabulary",
            str(vocabulary),
            "--temporal-manifest",
            str(temporal_manifest),
            "--source-id",
            "synthetic-amazon-electronics",
            "--source-version",
            "fixture-v1",
            "--output-dir",
            str(failed_output),
            "--temp-dir",
            str(temp_dir),
        ]
    )

    assert result == 2
    assert "no output was published" in capsys.readouterr().err
    assert not failed_output.exists()
    assert not list(run_root.glob(".retry-run.tmp-*"))
    assert list(temp_dir.iterdir()) == []

    monkeypatch.setattr(
        amazon_metadata_pipeline, "write_manifest", original_write_manifest
    )
    retried = _run_cli(
        source=source,
        vocabulary=vocabulary,
        temporal_manifest=temporal_manifest,
        output=failed_output,
        temp_dir=temp_dir,
        capsys=capsys,
    )
    assert retried["outputs"] == expected["outputs"]
    assert (failed_output / "manifest.json").read_bytes() == expected_manifest
    assert list(temp_dir.iterdir()) == []
