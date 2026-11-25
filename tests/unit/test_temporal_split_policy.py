import pytest

from recfusion_core.contracts import DataSplit
from recfusion_data.splitting.temporal import (
    TemporalCutoffs,
    parse_utc_cutoff_ms,
)


def test_cutoffs_use_half_open_boundaries_and_keep_equal_timestamps_together() -> None:
    cutoffs = TemporalCutoffs(train_end_ms=2_000, test_start_ms=4_000)

    assert cutoffs.assign(1_999) is DataSplit.TRAIN
    assert cutoffs.assign(2_000) is DataSplit.VALIDATION
    assert cutoffs.assign(3_999) is DataSplit.VALIDATION
    assert cutoffs.assign(4_000) is DataSplit.TEST
    assert cutoffs.assign(2_000) is cutoffs.assign(2_000)


@pytest.mark.parametrize(
    "value",
    [
        "1970-01-01T00:00:02Z",
        "1970-01-01T00:00:02+00:00",
    ],
)
def test_cutoff_parser_requires_explicit_millisecond_precision_utc(
    value: str,
) -> None:
    assert parse_utc_cutoff_ms(value) == 2_000


@pytest.mark.parametrize(
    "value",
    [
        "1970-01-01T00:00:02",
        "1970-01-01T01:00:02+01:00",
        "1970-01-01T00:00:02.000001Z",
        "1969-12-31T23:59:59Z",
    ],
)
def test_cutoff_parser_rejects_non_utc_or_unsupported_cutoffs(value: str) -> None:
    with pytest.raises(ValueError, match=r"UTC|precision|epoch"):
        parse_utc_cutoff_ms(value)


def test_cutoffs_require_increasing_nonnegative_values() -> None:
    with pytest.raises(ValueError, match="Cutoffs"):
        TemporalCutoffs(train_end_ms=4_000, test_start_ms=4_000)
