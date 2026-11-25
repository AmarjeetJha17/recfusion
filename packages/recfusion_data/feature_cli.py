"""CLI for generating versioned, leakage-aware feature artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from recfusion_data.features.generation import generate_features
from recfusion_data.ingestion.errors import IngestionError


def _arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate train-only transforms, strictly as-of interaction features, "
            "and separately labeled snapshot product features."
        )
    )
    parser.add_argument("--temporal-dir", type=Path, required=True)
    parser.add_argument("--product-ingestion-dir", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="new directory under data/processed; existing output is never replaced",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments().parse_args(argv)
    try:
        result = generate_features(
            temporal_dir=args.temporal_dir,
            product_ingestion_dir=args.product_ingestion_dir,
            output_dir=args.output_dir,
        )
    except (IngestionError, ValueError) as error:
        print(f"Feature generation failed: {error}", file=sys.stderr)
        return 2
    counts = cast(dict[str, object], result.manifest["counts"])
    print(
        json.dumps(
            {
                "output_dir": str(result.output_dir),
                "feature_dataset_id": result.manifest["feature_dataset_id"],
                "interaction_records": counts["interaction_records"],
                "training_eligible_interactions": counts[
                    "training_eligible_interactions"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
