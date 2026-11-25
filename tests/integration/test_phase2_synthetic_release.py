import hashlib
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

import recfusion_data.release as release
from recfusion_data.ingestion.errors import IngestionError

pytestmark = pytest.mark.integration
_ROOT = Path(__file__).parents[2]


@pytest.fixture
def output_root(tmp_path: Path) -> Iterator[Path]:
    path = _ROOT / "data" / "processed" / f"phase2-release-{tmp_path.name}"
    try:
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path)


def _read_manifest(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_synthetic_release_is_complete_auditable_and_reproducible(
    output_root: Path,
) -> None:
    first = release.run_synthetic_release(output_root / "first")
    second = release.run_synthetic_release(output_root / "second")

    assert first["release_type"] == second["release_type"] == "synthetic_only"
    assert first["external_data_used"] is False
    assert first["real_data_validation"] == (
        "BLOCKED_PENDING_USAGE_RIGHTS_REVIEW_AND_AUTHORIZED_PILOT"
    )
    assert first["phase3_training_readiness"] == (
        "NOT_ESTABLISHED_BY_SYNTHETIC_VALIDATION"
    )
    assert first["outputs"] == second["outputs"]
    assert first["schema_versions"] == second["schema_versions"]
    assert first["counts"] == second["counts"]
    assert first["validation_results"] == second["validation_results"]

    first_dir = Path(cast(str, first["published_output_dir"]))
    second_dir = Path(cast(str, second["published_output_dir"]))
    assert first_dir.is_dir()
    assert second_dir.is_dir()
    first_manifest = _read_manifest(first_dir / "release-manifest.json")
    second_dir = Path(cast(str, second["published_output_dir"]))
    assert _hash(first_dir / "release-manifest.json") == _hash(
        second_dir / "release-manifest.json"
    )
    assert first_manifest["manifest_schema_version"] == (
        "recfusion.synthetic-data-release.v1"
    )
    assert first_manifest["validation_results"] == first["validation_results"]
    assert len(cast(list[object], first["outputs"])) > 20
    for output in cast(list[dict[str, object]], first["outputs"]):
        relative = Path(cast(str, output["file"]))
        assert _hash(first_dir / relative) == output["sha256"]
        assert _hash(first_dir / relative) == _hash(second_dir / relative)

    counts = cast(dict[str, object], first["counts"])
    preprocessing = cast(dict[str, object], counts["preprocessing"])
    assert preprocessing["retained_unique_records"] == 11
    assert preprocessing["rejected_records"] == 0
    ingestion = cast(dict[str, object], counts["ingestion"])
    assert ingestion["cross_split_duplicates"] == 0
    temporal = cast(dict[str, object], counts["temporal"])
    split_counts = cast(dict[str, object], temporal["split_counts"])
    assert {
        split: cast(dict[str, object], values)["input_accepted_records"]
        for split, values in split_counts.items()
    } == {"train": 4, "validation": 4, "test": 3}

    performance = cast(dict[str, object], first["performance"])
    assert cast(int, performance["peak_traced_python_memory_bytes"]) > 0
    assert cast(int, first["published_directory_bytes"]) > 0
    assert cast(int, performance["artifact_bytes_excluding_release_manifest"]) > 0
    assert all(
        cast(float, value) >= 0
        for value in cast(dict[str, object], performance["timings_seconds"]).values()
    )


def test_failed_stage_never_publishes_a_release_directory(
    output_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = output_root / "failed-release"

    def fail_ingestion(**kwargs: object) -> object:
        raise IngestionError("injected synthetic ingestion failure")

    monkeypatch.setattr(release, "ingest_local_files", fail_ingestion)
    with pytest.raises(IngestionError, match="injected synthetic ingestion failure"):
        release.run_synthetic_release(target)

    assert not target.exists()
    assert not list(output_root.glob(".failed-release.staging-*"))


def test_existing_release_directory_is_never_overwritten(output_root: Path) -> None:
    target = output_root / "existing-release"
    target.mkdir(parents=True)
    sentinel = target / "keep.txt"
    sentinel.write_text("existing output", encoding="utf-8")

    with pytest.raises(release.ReleaseValidationError, match="refusing to overwrite"):
        release.run_synthetic_release(target)

    assert sentinel.read_text(encoding="utf-8") == "existing output"
