import hashlib
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from recfusion_data.feature_cli import main as feature_cli_main
from recfusion_data.features.generation import generate_features
from recfusion_data.ingestion.pipeline import ingest_local_files
from recfusion_data.ingestion.readers import InputFormat
from recfusion_data.preprocessing.interactions import preprocess_interaction_files
from recfusion_data.splitting.temporal import process_trusted_pre_split

pytestmark = pytest.mark.integration

_REPOSITORY_ROOT = Path(__file__).parents[2]
_FIXTURES = Path(__file__).parents[1] / "fixtures" / "features"
_PRODUCT_FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "ingestion"
    / ("products-normalization.jsonl")
)


@pytest.fixture
def output_root(tmp_path: Path) -> Iterator[Path]:
    path = (
        _REPOSITORY_ROOT / "data" / "processed" / f"feature-generation-{tmp_path.name}"
    )
    try:
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        cast(dict[str, object], json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    return path


def _raw_catalog_interactions(root: Path) -> tuple[Path, Path, Path]:
    train = [
        {
            "user_key": "catalog_user",
            "item_key": item,
            "event_time_ms": 1000 + index,
            "rating": 5,
        }
        for index, item in enumerate(
            (
                "synthetic_laptop",
                "synthetic_phone",
                "synthetic_headphones",
                "synthetic_conflict_product",
            )
        )
    ]
    return (
        _write_jsonl(root / "catalog-train.jsonl", train),
        _write_jsonl(root / "catalog-validation.jsonl", []),
        _write_jsonl(root / "catalog-test.jsonl", []),
    )


def _run_pipeline(
    output_root: Path,
    *,
    source_root: Path = _FIXTURES,
    reverse_inputs: bool = False,
    heldout_rating_override: int | None = None,
) -> tuple[Path, Path, Path]:
    ingestion_inputs = _raw_catalog_interactions(output_root / "catalog-input")
    ingestion = ingest_local_files(
        train_path=ingestion_inputs[0],
        validation_path=ingestion_inputs[1],
        test_path=ingestion_inputs[2],
        product_path=_PRODUCT_FIXTURE,
        input_format=InputFormat.JSONL,
        product_format=InputFormat.JSONL,
        output_dir=output_root / "ingestion",
        source_id="synthetic-feature-products",
        source_version="v1",
        seed="feature-test",
        max_users=1,
        normalize_products=True,
    )

    split_paths: dict[str, Path] = {}
    for split in ("train", "validation", "test"):
        source_path = source_root / f"{split}.jsonl"
        records = _read_jsonl(source_path)
        if reverse_inputs:
            records.reverse()
        if split != "train" and heldout_rating_override is not None and records:
            records[0]["rating"] = heldout_rating_override
        split_paths[split] = _write_jsonl(
            output_root / "canonical" / f"{split}.jsonl", records
        )
    preprocessed = preprocess_interaction_files(
        train_path=split_paths["train"],
        validation_path=split_paths["validation"],
        test_path=split_paths["test"],
        output_dir=output_root / "preprocessed",
        source_id="synthetic-feature-events",
        source_version="v1",
    )
    temporal = process_trusted_pre_split(
        train_path=preprocessed.output_dir / "interactions.train.processed.jsonl",
        validation_path=(
            preprocessed.output_dir / "interactions.validation.processed.jsonl"
        ),
        test_path=preprocessed.output_dir / "interactions.test.processed.jsonl",
        output_dir=output_root / "temporal",
        source_id="synthetic-feature-events",
        source_version="v1",
    )
    return temporal.output_dir, ingestion.output_dir, output_root / "features"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def test_feature_generation_preserves_asof_boundaries_and_train_only_fit(
    output_root: Path,
) -> None:
    temporal_dir, product_dir, features_dir = _run_pipeline(output_root)
    result = generate_features(
        temporal_dir=temporal_dir,
        product_ingestion_dir=product_dir,
        output_dir=features_dir,
    )
    integrity = _mapping(result.manifest["integrity"])
    counts = _mapping(result.manifest["counts"])
    assert integrity["training_only_vocabulary_fit"] is True
    assert integrity["training_only_history"] is True
    assert integrity["simultaneous_events_excluded"] is True
    assert counts["interaction_records"] == 11
    assert counts["training_eligible_interactions"] == 5
    assert counts["held_out_interactions_retained"] == 6
    assert counts["training_catalog_items_with_conflicting_metadata"] == 1
    split_metrics = _mapping(
        _mapping(counts["unknown_id_and_history_counts_by_split"])["validation"]
    )
    assert split_metrics["unknown_user_records"] == 1
    assert split_metrics["unknown_user_rate"] == "0.25"

    interactions = _read_jsonl(features_dir / "interactions.features.jsonl")
    assert all(
        "user_key" not in record and "item_key" not in record for record in interactions
    )
    by_fingerprint = {
        record["source_event_fingerprint"]: record for record in interactions
    }
    simultaneous_a = _mapping(by_fingerprint["b" * 64]["history"])
    simultaneous_b = _mapping(by_fingerprint["c" * 64]["history"])
    assert simultaneous_a["user_prior_interaction_count"] == 1
    assert simultaneous_a["item_prior_interaction_count"] == 0
    assert simultaneous_b["user_prior_interaction_count"] == 0
    assert simultaneous_b["item_prior_interaction_count"] == 0

    validation_later = by_fingerprint["1" * 64]
    assert _mapping(validation_later["history"])["user_prior_interaction_count"] == 3
    cold_user = by_fingerprint["2" * 64]
    assert cold_user["user_index"] == 0
    assert _mapping(cold_user["history"])["user_prior_interaction_count"] == 0
    cold_item = by_fingerprint["3" * 64]
    assert cold_item["item_index"] == 0
    assert _mapping(cold_item["history"])["item_prior_interaction_count"] == 0
    test_event = by_fingerprint["4" * 64]
    assert _mapping(test_event["history"])["user_prior_interaction_count"] == 3

    vocab = _read_jsonl(temporal_dir / "vocabulary.items.jsonl")
    key_to_index = {
        record["source_key"]: record["index"]
        for record in vocab
        if record.get("source_key") is not None
    }
    item_features = {
        record["item_index"]: record
        for record in _read_jsonl(features_dir / "items.features.jsonl")
    }
    assert item_features[0]["metadata_status"] == "unknown_item"
    assert "item_key" not in item_features[0]
    laptop = item_features[key_to_index["synthetic_laptop"]]
    phone = item_features[key_to_index["synthetic_phone"]]
    headphones = item_features[key_to_index["synthetic_headphones"]]
    conflict = item_features[key_to_index["synthetic_conflict_product"]]
    laptop_numeric = _mapping(laptop["numeric"])
    phone_numeric = _mapping(phone["numeric"])
    headphone_numeric = _mapping(headphones["numeric"])
    assert _mapping(laptop_numeric["ram_capacity_bytes"])["missing"] is False
    assert _mapping(headphone_numeric["storage_capacity_bytes"])["missing"] is True
    assert _mapping(phone_numeric["battery_energy_wh"])["not_applicable"] is True
    assert _mapping(phone_numeric["battery_charge_mah"])["value"] == "0"
    laptop_categories = _mapping(laptop["categorical"])
    assert _mapping(laptop_categories["brand"])["raw_values"] == ["  ACME   Systems "]
    assert conflict["metadata_status"] == "conflict_excluded"
    assert conflict["source_record_fingerprint"] is None
    assert (
        _mapping(_mapping(conflict["numeric"])["ram_capacity_bytes"])["unavailable"]
        is True
    )

    transformers = json.loads((features_dir / "transformers.json").read_text())
    ram_fit = _mapping(_mapping(transformers)["numeric_standardizers"])
    ram_fit = _mapping(ram_fit["ram_capacity_bytes"])
    assert ram_fit["fit_split"] == "train"
    assert ram_fit["observation_count"] == 2
    assert ram_fit["mean"] == "12294967296"
    field_missingness = _mapping(
        _mapping(result.manifest["feature_statistics"])["item_missingness_counts"]
    )
    assert _mapping(field_missingness["storage_capacity_bytes"])["missing"] == 1
    assert (
        _hash(features_dir / "interactions.features.jsonl")
        == _mapping(cast(list[object], result.manifest["outputs"])[0])["sha256"]
    )
    assert not any(
        "price" in name or "rating_count" in name or "average_rating" in name
        for name in json.loads((features_dir / "feature-schema.json").read_text())
    )


def test_outputs_are_order_independent_and_heldout_labels_do_not_fit_features(
    output_root: Path,
) -> None:
    temporal_a, products_a, features_a = _run_pipeline(output_root / "first")
    result_a = generate_features(
        temporal_dir=temporal_a,
        product_ingestion_dir=products_a,
        output_dir=features_a,
    )

    temporal_b, products_b, features_b = _run_pipeline(
        output_root / "reordered",
        reverse_inputs=True,
    )
    result_b = generate_features(
        temporal_dir=temporal_b,
        product_ingestion_dir=products_b,
        output_dir=features_b,
    )
    for filename in (
        "interactions.features.jsonl",
        "items.features.jsonl",
        "feature-schema.json",
        "transformers.json",
    ):
        assert _hash(features_a / filename) == _hash(features_b / filename)

    repeated = generate_features(
        temporal_dir=temporal_a,
        product_ingestion_dir=products_a,
        output_dir=output_root / "repeated",
    )
    assert result_a.manifest == repeated.manifest

    temporal_c, products_c, features_c = _run_pipeline(
        output_root / "heldout-changed",
        heldout_rating_override=1,
    )
    result_c = generate_features(
        temporal_dir=temporal_c,
        product_ingestion_dir=products_c,
        output_dir=features_c,
    )
    assert _hash(features_a / "transformers.json") == _hash(
        features_c / "transformers.json"
    )
    assert _hash(features_a / "items.features.jsonl") == _hash(
        features_c / "items.features.jsonl"
    )
    train_a = [
        record
        for record in _read_jsonl(features_a / "interactions.features.jsonl")
        if record["split"] == "train"
    ]
    train_c = [
        record
        for record in _read_jsonl(features_c / "interactions.features.jsonl")
        if record["split"] == "train"
    ]
    assert train_a == train_c
    heldout_a = {
        record["source_event_fingerprint"]: record["history"]
        for record in _read_jsonl(features_a / "interactions.features.jsonl")
        if record["split"] != "train"
    }
    heldout_c = {
        record["source_event_fingerprint"]: record["history"]
        for record in _read_jsonl(features_c / "interactions.features.jsonl")
        if record["split"] != "train"
    }
    assert heldout_a == heldout_c

    # The CLI exercises the same public path without introducing a second framework.
    temporal_d, products_d, _ = _run_pipeline(output_root / "cli")
    assert (
        feature_cli_main(
            [
                "--temporal-dir",
                str(temporal_d),
                "--product-ingestion-dir",
                str(products_d),
                "--output-dir",
                str(output_root / "cli-features"),
            ]
        )
        == 0
    )
    assert (
        result_a.manifest["configuration_sha256"]
        == result_b.manifest["configuration_sha256"]
    )
    assert (
        _mapping(result_c.manifest["integrity"])["held_out_records_preserved"] is True
    )
