from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path
from typing import cast

import pytest

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
        {"title": "Missing parent identifier"},
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
) -> dict[str, object]:
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
