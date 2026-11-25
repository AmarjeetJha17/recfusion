"""CLI for source-independent canonical interaction preprocessing."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from recfusion_data.ingestion.errors import IngestionError
from recfusion_data.preprocessing.interactions import (
    RatingLabelConfig,
    preprocess_interaction_files,
)


def _decimal_argument(value: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError("threshold must be a decimal number") from None
    if not result.is_finite():
        raise argparse.ArgumentTypeError("threshold must be finite")
    return result


def _arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and preprocess local canonical per-split JSONL interaction "
            "outputs into ignored derived files."
        )
    )
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument(
        "--positive-min-rating", type=_decimal_argument, default=Decimal("4")
    )
    parser.add_argument(
        "--neutral-rating", type=_decimal_argument, default=Decimal("3")
    )
    parser.add_argument(
        "--low-max-rating", type=_decimal_argument, default=Decimal("2")
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data") / "processed" / "synthetic-interactions-v1",
        help=(
            "New directory under data/processed; existing directories "
            "are never overwritten."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments().parse_args(argv)
    try:
        labels = RatingLabelConfig(
            positive_min=args.positive_min_rating,
            neutral_rating=args.neutral_rating,
            low_max=args.low_max_rating,
        )
        result = preprocess_interaction_files(
            train_path=args.train,
            validation_path=args.validation,
            test_path=args.test,
            output_dir=args.output_dir,
            source_id=args.source_id,
            source_version=args.source_version,
            label_config=labels,
        )
    except (IngestionError, ValueError) as error:
        print(f"Interaction preprocessing failed: {error}", file=sys.stderr)
        return 2

    report = cast(dict[str, object], result.manifest["quality_report"])
    descriptive = cast(dict[str, object], report["descriptive_all_splits"])
    summary = {
        "output_dir": str(result.output_dir),
        "retained_records": descriptive["retained_unique_records"],
        "rejected_records": descriptive["rejected_records"],
        "exact_duplicate_occurrences": descriptive["exact_duplicate_occurrences"],
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
