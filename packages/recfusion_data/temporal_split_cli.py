"""CLI for validating trusted splits or applying explicit UTC time cutoffs."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from recfusion_data.ingestion.errors import IngestionError
from recfusion_data.splitting.temporal import (
    TemporalCutoffs,
    parse_utc_cutoff_ms,
    process_trusted_pre_split,
    process_unsplit_with_cutoffs,
)


def _cutoff_argument(value: str) -> int:
    try:
        return parse_utc_cutoff_ms(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def _arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate trusted Step 2.4 splits or partition an explicitly unsplit "
            "canonical JSONL file by absolute UTC cutoffs."
        )
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    trusted = subparsers.add_parser(
        "trusted-pre-split",
        help="preserve membership from the three supplied canonical split files",
    )
    trusted.add_argument("--train", type=Path, required=True)
    trusted.add_argument("--validation", type=Path, required=True)
    trusted.add_argument("--test", type=Path, required=True)
    trusted.add_argument("--train-end-utc", type=_cutoff_argument)
    trusted.add_argument("--test-start-utc", type=_cutoff_argument)

    absolute = subparsers.add_parser(
        "absolute-cutoffs",
        help="assign an unpartitioned canonical file to UTC time intervals",
    )
    absolute.add_argument("--input", type=Path, required=True)
    absolute.add_argument("--train-end-utc", type=_cutoff_argument, required=True)
    absolute.add_argument("--test-start-utc", type=_cutoff_argument, required=True)

    for subparser in (trusted, absolute):
        subparser.add_argument("--source-id", required=True)
        subparser.add_argument("--source-version", required=True)
        subparser.add_argument(
            "--output-dir",
            type=Path,
            required=True,
            help=(
                "new directory under data/processed; existing output is never replaced"
            ),
        )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments().parse_args(argv)
    if (args.train_end_utc is None) != (args.test_start_utc is None):
        print(
            "Temporal splitting failed: both cutoffs must be supplied together.",
            file=sys.stderr,
        )
        return 2
    try:
        cutoffs = (
            TemporalCutoffs(args.train_end_utc, args.test_start_utc)
            if args.train_end_utc is not None
            else None
        )
        if args.mode == "trusted-pre-split":
            result = process_trusted_pre_split(
                train_path=args.train,
                validation_path=args.validation,
                test_path=args.test,
                output_dir=args.output_dir,
                source_id=args.source_id,
                source_version=args.source_version,
                cutoffs=cutoffs,
            )
        else:
            if cutoffs is None:
                raise IngestionError("Absolute-cutoff mode requires both UTC cutoffs.")
            result = process_unsplit_with_cutoffs(
                input_path=args.input,
                output_dir=args.output_dir,
                source_id=args.source_id,
                source_version=args.source_version,
                cutoffs=cutoffs,
            )
    except (IngestionError, ValueError) as error:
        print(f"Temporal splitting failed: {error}", file=sys.stderr)
        return 2

    counts = cast(dict[str, object], result.manifest["counts"])
    integrity = cast(dict[str, object], result.manifest["integrity_status"])
    summary = {
        "output_dir": str(result.output_dir),
        "input_records": counts["input_records"],
        "rejected_records": counts["rejected_records"],
        "evaluation_eligible": integrity["evaluation_eligible"],
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
