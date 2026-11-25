import hashlib
import json
import shutil
from pathlib import Path

import pytest

from recfusion_data.ingestion.errors import IngestionError
from recfusion_data.ingestion.pipeline import ingest_local_files
from recfusion_data.ingestion.readers import InputFormat

pytestmark = pytest.mark.integration

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "ingestion"
_REPOSITORY_ROOT = Path(__file__).parents[2]


@pytest.fixture
def output_root(tmp_path: Path) -> Path:
    path = _REPOSITORY_ROOT / "data" / "processed" / f"test-{tmp_path.name}"
    try:
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path)


def _ingest(
    output_dir: Path, train_path: Path = _FIXTURES / "train.jsonl"
) -> dict[str, object]:
    result = ingest_local_files(
        train_path=train_path,
        validation_path=_FIXTURES / "validation.jsonl",
        test_path=_FIXTURES / "test.jsonl",
        product_path=_FIXTURES / "products.jsonl",
        input_format=InputFormat.JSONL,
        product_format=InputFormat.JSONL,
        output_dir=output_dir,
        source_id="synthetic-fixtures",
        source_version="v1",
        seed="recfusion-phase2-pilot-v1",
        max_users=2,
    )
    return dict(result.manifest)


def _jsonl_records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_synthetic_ingestion_is_repeatable_and_auditable(output_root: Path) -> None:
    first_dir = output_root / "first"
    second_dir = output_root / "second"

    first_manifest = _ingest(first_dir)
    second_manifest = _ingest(second_dir)

    assert first_manifest == second_manifest
    assert first_manifest["outputs"] == second_manifest["outputs"]
    assert _jsonl_records(first_dir / "interactions.train.jsonl") == _jsonl_records(
        second_dir / "interactions.train.jsonl"
    )
    output_entries = first_manifest["outputs"]
    assert isinstance(output_entries, list)
    for entry in output_entries:
        assert isinstance(entry, dict)
        output_path = first_dir / str(entry["file"])
        assert entry["sha256"] == hashlib.sha256(output_path.read_bytes()).hexdigest()

    counts = first_manifest["counts"]
    assert isinstance(counts, dict)
    split_counts = counts["interactions_by_split"]
    assert isinstance(split_counts, dict)
    train_counts = split_counts["train"]
    assert isinstance(train_counts, dict)
    assert train_counts["input_records"] == 8
    assert train_counts["rejected_records"] == 4
    assert train_counts["duplicate_rows_skipped"] == 1
    assert train_counts["output_records"] == 3
    assert counts["cross_split_duplicate_interactions"] == 1
    products = counts["products"]
    assert isinstance(products, dict)
    assert products["duplicate_rows_skipped"] == 1
    assert products["conflicting_item_rows"] == 1
    assert products["rejected_records"] == 1
    assert products["output_records"] == 4
    assert counts["validation_failures"] == {
        "invalid_rating": 1,
        "invalid_timestamp": 1,
        "malformed_json": 2,
        "missing_or_invalid_identifier": 1,
    }


def test_validation_and_test_only_users_do_not_enter_sample(
    output_root: Path,
) -> None:
    output_dir = output_root / "sample"
    manifest = _ingest(output_dir)
    sampling = manifest["sampling"]
    assert isinstance(sampling, dict)
    assert sampling["selected_users"] == 2

    all_users = {
        record["user_key"]
        for split in ("train", "validation", "test")
        for record in _jsonl_records(output_dir / f"interactions.{split}.jsonl")
    }
    assert "synthetic_user_validation_only" not in all_users
    assert "synthetic_user_test_only" not in all_users


def test_pipeline_user_sample_is_stable_when_train_rows_are_reordered(
    output_root: Path, tmp_path: Path
) -> None:
    source_lines = (_FIXTURES / "train.jsonl").read_text(encoding="utf-8").splitlines()
    reordered_train = tmp_path / "reordered-train.jsonl"
    reordered_train.write_text(
        "\n".join(reversed(source_lines)) + "\n", encoding="utf-8"
    )
    original_dir = output_root / "original"
    reordered_dir = output_root / "reordered"

    _ingest(original_dir)
    _ingest(reordered_dir, train_path=reordered_train)

    def selected_training_users(output_dir: Path) -> set[str]:
        return {
            str(record["user_key"])
            for record in _jsonl_records(output_dir / "interactions.train.jsonl")
        }

    assert selected_training_users(original_dir) == selected_training_users(
        reordered_dir
    )


def test_csv_pipeline_counts_invalid_rows(tmp_path: Path, output_root: Path) -> None:
    header = "user_key,item_key,event_time_ms,rating\n"
    empty_validation = tmp_path / "validation.csv"
    empty_test = tmp_path / "test.csv"
    empty_validation.write_text(header, encoding="utf-8")
    empty_test.write_text(header, encoding="utf-8")
    output_dir = output_root / "csv-run"

    result = ingest_local_files(
        train_path=_FIXTURES / "interactions.csv",
        validation_path=empty_validation,
        test_path=empty_test,
        product_path=None,
        input_format=InputFormat.CSV,
        product_format=InputFormat.JSONL,
        output_dir=output_dir,
        source_id="synthetic-csv",
        source_version="v1",
        seed="csv-test",
        max_users=1,
    )

    counts = result.manifest["counts"]
    assert isinstance(counts, dict)
    split_counts = counts["interactions_by_split"]
    assert isinstance(split_counts, dict)
    train_counts = split_counts["train"]
    assert isinstance(train_counts, dict)
    assert train_counts["input_records"] == 4
    assert train_counts["rejected_records"] == 2
    assert train_counts["output_records"] == 2
    assert counts["validation_failures"] == {
        "invalid_timestamp": 1,
        "malformed_csv_row": 1,
    }


def test_output_refuses_to_overwrite_existing_directory(output_root: Path) -> None:
    output_dir = output_root / "existing"
    output_dir.mkdir(parents=True)
    sentinel = output_dir / "keep.txt"
    sentinel.write_text("unchanged", encoding="utf-8")

    with pytest.raises(IngestionError, match="refusing to overwrite"):
        _ingest(output_dir)

    assert sentinel.read_text(encoding="utf-8") == "unchanged"


def test_fatal_product_header_error_does_not_publish_partial_output(
    tmp_path: Path, output_root: Path
) -> None:
    invalid_products = tmp_path / "invalid-products.csv"
    invalid_products.write_text("\n", encoding="utf-8")
    output_dir = output_root / "failed-run"

    with pytest.raises(IngestionError, match="no header"):
        ingest_local_files(
            train_path=_FIXTURES / "train.jsonl",
            validation_path=_FIXTURES / "validation.jsonl",
            test_path=_FIXTURES / "test.jsonl",
            product_path=invalid_products,
            input_format=InputFormat.JSONL,
            product_format=InputFormat.CSV,
            output_dir=output_dir,
            source_id="synthetic-failure",
            source_version="v1",
            seed="failure-test",
            max_users=2,
        )

    assert not output_dir.exists()
    assert list(output_root.iterdir()) == []


def test_input_files_are_not_modified(output_root: Path) -> None:
    source = _FIXTURES / "train.jsonl"
    original = source.read_bytes()

    _ingest(output_root / "output")

    assert source.read_bytes() == original


def test_output_outside_gitignored_processed_path_is_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(IngestionError, match="ignored data/processed"):
        _ingest(tmp_path / "outside")
