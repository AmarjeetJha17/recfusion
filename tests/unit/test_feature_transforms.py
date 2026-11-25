import pytest

from recfusion_data.features.generation import encode_categorical_value

pytestmark = pytest.mark.unit


def test_category_transform_distinguishes_missing_unknown_and_unavailable() -> None:
    vocabulary = {"known brand": 1}

    assert encode_categorical_value(None, "missing", vocabulary).missing

    unknown = encode_categorical_value("new brand", "normalized", vocabulary)
    assert unknown.index == 0
    assert unknown.unknown
    assert not unknown.missing

    unavailable = encode_categorical_value(None, "ambiguous", vocabulary)
    assert unavailable.index == 0
    assert unavailable.unavailable
    assert not unavailable.missing

    known = encode_categorical_value("known brand", "normalized", vocabulary)
    assert known.index == 1
    assert not known.unknown
    assert not known.missing
