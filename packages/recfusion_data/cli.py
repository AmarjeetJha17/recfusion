"""Command-line entry point for local, canonical-format ingestion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from recfusion_data.ingestion.errors import IngestionError
from recfusion_data.ingestion.pipeline import ingest_local_files
from recfusion_data.ingestion.readers import InputFormat


def _arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream local canonical CSV or JSONL files into ignored outputs."
    )
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--products", type=Path)
    parser.add_argument(
        "--input-format", choices=[item.value for item in InputFormat], default="jsonl"
    )
    parser.add_argument(
        "--product-format",
        choices=[item.value for item in InputFormat],
        default="jsonl",
    )
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--seed", default="recfusion-phase2-pilot-v1")
    parser.add_argument("--max-users", type=int, default=10_000)
    parser.add_argument(
        "--normalize-products",
        action="store_true",
        help="Write an additional deterministic normalized product metadata file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data") / "processed" / "synthetic-pilot-v1",
        help=(
            "New directory under data/processed; existing directories "
            "are never overwritten."
        ),
    )
    return parser


def main() -> int:
    parser = _arguments()
    args = parser.parse_args()
    try:
        result = ingest_local_files(
            train_path=args.train,
            validation_path=args.validation,
            test_path=args.test,
            product_path=args.products,
            input_format=InputFormat(args.input_format),
            product_format=InputFormat(args.product_format),
            output_dir=args.output_dir,
            source_id=args.source_id,
            source_version=args.source_version,
            seed=args.seed,
            max_users=args.max_users,
            normalize_products=args.normalize_products,
        )
    except (IngestionError, OSError, ValueError) as error:
        print(f"Ingestion failed: {error}", file=sys.stderr)
        return 2

    counts = result.manifest["counts"]
    summary = {
        "output_dir": str(result.output_dir),
        "selected_users": result.selected_user_count,
        "counts": counts,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
