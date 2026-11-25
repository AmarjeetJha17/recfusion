import json
import shutil
from pathlib import Path

import pytest

from recfusion_data.preprocessing.interactions import preprocess_interaction_files

pytestmark = pytest.mark.contract

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "preprocessing"
_REPOSITORY_ROOT = Path(__file__).parents[2]


def test_derived_record_preserves_provenance_split_and_schema(tmp_path: Path) -> None:
    output_dir = _REPOSITORY_ROOT / "data" / "processed" / f"contract-{tmp_path.name}"
    try:
        preprocess_interaction_files(
            train_path=_FIXTURES / "train.jsonl",
            validation_path=_FIXTURES / "validation.jsonl",
            test_path=_FIXTURES / "test.jsonl",
            output_dir=output_dir,
            source_id="synthetic-preprocessing",
            source_version="v1",
        )
        records = [
            json.loads(line)
            for line in (output_dir / "interactions.train.processed.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
    finally:
        if output_dir.exists():
            shutil.rmtree(output_dir)

    assert records[0]["schema_version"] == "recfusion.interaction-preprocessing.v1"
    assert records[0]["split"] == "train"
    assert records[0]["source_event_fingerprint"] == "a" * 64
    assert records[0]["source_rating_value"] == 5
    assert records[0]["source_timestamp_value"] == 1000
    assert records[0]["source_timestamp_unit"] == "unix_ms"
    assert records[0]["event_time_utc"] == "1970-01-01T00:00:01.000Z"
    assert records[0]["event_type"] is None
    assert records[0]["event_type_present"] is False
    assert "internal_user_id" not in records[0]
    assert records[-2]["event_type"] == "review_feedback"
    assert records[-2]["source_event_id"] == "synthetic_event_d"
    assert records[-2]["source_event_id_present"] is True
    assert records[-1]["source_timestamp_value"] == "3000"
