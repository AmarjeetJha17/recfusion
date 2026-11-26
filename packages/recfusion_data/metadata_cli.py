"""Explicit local CLI for synthetic-tested Amazon Electronics metadata ingest."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from recfusion_data.ingestion.amazon_metadata_pipeline import (
    _DEFAULT_MAX_RECORD_BYTES,
    ingest_amazon_electronics_metadata,
)
from recfusion_data.ingestion.errors import IngestionError


def _arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stream an explicit Amazon Electronics metadata JSONL or JSONL.GZ file and "
            "join it to a checksummed Step 2.5 train-only item vocabulary."
        )
    )
    parser.add_argument(
        "--adapter",
        required=True,
        choices=("amazon-reviews-2023-electronics-metadata",),
        help=(
            "Explicitly opt into the Amazon Reviews 2023 Electronics metadata adapter."
        ),
    )
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--train-vocabulary", type=Path, required=True)
    parser.add_argument("--temporal-manifest", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument(
        "--source-url", help="Declared source URL; not independently verified."
    )
    parser.add_argument(
        "--retrieved-at", help="Declared retrieval timestamp, if known."
    )
    parser.add_argument(
        "--retrieval-method", help="Declared retrieval method, if known."
    )
    parser.add_argument(
        "--publisher-sha256",
        help="Publisher-listed SHA-256 for comparison with the local input checksum.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="New output directory under ignored data/processed; never overwritten.",
    )
    parser.add_argument(
        "--temp-dir",
        type=Path,
        help="Existing directory for the temporary SQLite target and metadata indexes.",
    )
    parser.add_argument(
        "--max-record-bytes",
        type=int,
        default=_DEFAULT_MAX_RECORD_BYTES,
        help="Maximum JSONL record bytes (default: 8 MiB).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments().parse_args(argv)
    try:
        result = ingest_amazon_electronics_metadata(
            metadata_path=args.metadata,
            train_vocabulary_path=args.train_vocabulary,
            temporal_manifest_path=args.temporal_manifest,
            output_dir=args.output_dir,
            source_id=args.source_id,
            source_version=args.source_version,
            source_url=args.source_url,
            retrieved_at=args.retrieved_at,
            retrieval_method=args.retrieval_method,
            publisher_sha256=args.publisher_sha256,
            temp_dir=args.temp_dir,
            max_record_bytes=args.max_record_bytes,
        )
    except (IngestionError, OSError, ValueError) as error:
        print(f"Amazon metadata ingestion failed: {error}", file=sys.stderr)
        return 2

    counts = cast(dict[str, object], result.manifest["counts"])
    print(
        json.dumps(
            {
                "output_dir": str(result.output_dir),
                "source_records_read": counts["source_records_read"],
                "matched_source_records": counts["matched_source_records"],
                "matched_unique_products": counts["matched_unique_products"],
                "missing_target_products": counts["missing_target_products"],
                "rejected_records": counts["rejected_records"],
                "canonical_output_records": counts["canonical_output_records"],
                "outputs": result.manifest["outputs"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
