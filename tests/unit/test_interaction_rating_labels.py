from decimal import Decimal

import pytest

from recfusion_data.preprocessing.interactions import (
    RatingLabel,
    RatingLabelConfig,
)


def test_provisional_rating_labels_preserve_unclassified_gaps() -> None:
    labels = RatingLabelConfig()

    assert labels.label(Decimal("5")) is RatingLabel.OBSERVED_POSITIVE
    assert labels.label(Decimal("4")) is RatingLabel.OBSERVED_POSITIVE
    assert labels.label(Decimal("3")) is RatingLabel.NEUTRAL
    assert labels.label(Decimal("2")) is RatingLabel.OBSERVED_LOW
    assert labels.label(Decimal("1")) is RatingLabel.OBSERVED_LOW
    assert labels.label(Decimal("3.5")) is RatingLabel.UNCLASSIFIED


def test_custom_rating_thresholds_are_validated() -> None:
    labels = RatingLabelConfig(
        positive_min=Decimal("4.5"),
        neutral_rating=Decimal("3"),
        low_max=Decimal("1.5"),
    )

    assert labels.label(Decimal("4.5")) is RatingLabel.OBSERVED_POSITIVE
    with pytest.raises(ValueError, match="thresholds"):
        RatingLabelConfig(
            positive_min=Decimal("3"),
            neutral_rating=Decimal("3"),
            low_max=Decimal("2"),
        )
