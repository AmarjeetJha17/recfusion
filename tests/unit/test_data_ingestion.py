import csv
import inspect
from pathlib import Path

import pytest

from recfusion_core.contracts import DataSplit
from recfusion_data.ingestion.adapters import CanonicalSourceAdapter
from recfusion_data.ingestion.errors import AdapterError, RecordValidationError
from recfusion_data.ingestion.readers import InputFormat, read_records
from recfusion_data.splitting.sampling import (
    select_train_users,
    select_train_users_disk_backed,
)
from recfusion_data.validation import validate_interaction, validate_product

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "ingestion"
_FINGERPRINT = "a" * 64


def test_jsonl_reader_is_lazy_and_reports_malformed_rows() -> None:
    rows = read_records(_FIXTURES / "train.jsonl", InputFormat.JSONL)

    assert inspect.isgenerator(rows)
    assert next(rows).values == {
        "user_key": "synthetic_user_a",
        "item_key": "synthetic_item_a",
        "event_time_ms": 1000,
        "rating": 5,
    }
    remaining = list(rows)
    assert any(row.error_code == "malformed_json" for row in remaining)


def test_csv_reader_reports_rows_with_wrong_column_count(tmp_path: Path) -> None:
    path = tmp_path / "source.csv"
    path.write_text(
        "user_key,item_key,event_time_ms,rating\n"
        "synthetic_user,synthetic_item,1000,5\n"
        "synthetic_user,synthetic_item_short,2000\n",
        encoding="utf-8",
    )

    rows = list(read_records(path, InputFormat.CSV))

    assert len(rows) == 2
    assert rows[0].values is not None
    assert rows[1].error_code == "malformed_csv_row"


def test_validation_rejects_bad_timestamp_and_rating() -> None:
    with pytest.raises(RecordValidationError, match="invalid_timestamp"):
        validate_interaction(
            {
                "user_key": "synthetic_user",
                "item_key": "synthetic_item",
                "event_time_ms": "not-a-time",
                "rating": 5,
            },
            DataSplit.TRAIN,
            _FINGERPRINT,
        )

    with pytest.raises(RecordValidationError, match="invalid_rating"):
        validate_interaction(
            {
                "user_key": "synthetic_user",
                "item_key": "synthetic_item",
                "event_time_ms": 1000,
                "rating": 6,
            },
            DataSplit.TRAIN,
            _FINGERPRINT,
        )


def test_missing_optional_product_fields_remain_unknown() -> None:
    product, warnings = validate_product({"item_key": "synthetic_item"}, _FINGERPRINT)

    assert warnings == ()
    assert product.title is None
    assert product.price is None
    assert product.images is None
    assert product.attributes == {}


def test_malformed_optional_price_is_a_warning_not_a_fabricated_value() -> None:
    product, warnings = validate_product(
        {
            "item_key": "synthetic_item",
            "price": {"amount": "unknown", "currency": "USD"},
        },
        _FINGERPRINT,
    )

    assert product.price is None
    assert [warning.code for warning in warnings] == ["invalid_optional_price"]


def test_canonical_adapter_rejects_unexpected_source_fields() -> None:
    with pytest.raises(AdapterError, match="unexpected_field"):
        CanonicalSourceAdapter().interaction_fields(
            {
                "user_key": "synthetic_user",
                "item_key": "synthetic_item",
                "event_time_ms": 1000,
                "rating": 5,
                "raw_review_text": "synthetic only",
            },
            DataSplit.TRAIN,
        )


def test_user_selection_is_stable_under_input_reordering() -> None:
    eligible = [
        "synthetic_user_c",
        "synthetic_user_a",
        "synthetic_user_b",
        "synthetic_user_a",
    ]
    first = select_train_users(
        eligible, max_users=2, seed="fixed-test-seed", source_id="synthetic-source"
    )
    second = select_train_users(
        reversed(eligible),
        max_users=2,
        seed="fixed-test-seed",
        source_id="synthetic-source",
    )

    assert first == second


def test_disk_backed_user_selection_is_stable_nested_and_fails_when_too_small(
    tmp_path: Path,
) -> None:
    eligible = [f"synthetic_user_{index:02}" for index in range(12)]
    duplicate_rich = [*eligible, *eligible[:4]]
    small, small_count = select_train_users_disk_backed(
        duplicate_rich,
        max_users=3,
        seed="fixed-test-seed",
        source_id="synthetic-source",
        database_path=tmp_path / "small.sqlite3",
    )
    larger, larger_count = select_train_users_disk_backed(
        reversed(duplicate_rich),
        max_users=8,
        seed="fixed-test-seed",
        source_id="synthetic-source",
        database_path=tmp_path / "larger.sqlite3",
    )

    assert small == select_train_users(
        eligible,
        max_users=3,
        seed="fixed-test-seed",
        source_id="synthetic-source",
    )
    assert small < larger
    assert small_count == larger_count == 12
    with pytest.raises(ValueError, match="only 12 eligible train users"):
        select_train_users_disk_backed(
            eligible,
            max_users=13,
            seed="fixed-test-seed",
            source_id="synthetic-source",
            database_path=tmp_path / "insufficient.sqlite3",
        )


def test_csv_fixture_contains_only_synthetic_records() -> None:
    with (_FIXTURES / "interactions.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))

    assert rows[0]["user_key"] == "synthetic_user_csv"
    assert all(row["user_key"].startswith("synthetic_") for row in rows)
