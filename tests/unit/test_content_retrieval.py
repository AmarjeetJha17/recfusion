"""Synthetic-only contracts for content-based TF-IDF retrieval."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

import pytest

from recfusion_core.contracts import DataSplit, Interaction
from recfusion_ml.retrieval.content import (
    CONTENT_FEATURE_SCHEMA,
    CONTENT_INDEX_ARTIFACT_SCHEMA,
    NORMALIZATION_SCHEMA,
    ContentConfig,
    ContentIndex,
    ContentItem,
    tokenize_electronics_text,
)

pytestmark = pytest.mark.unit

_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "content"
_CODE_REVISION = "synthetic-phase-4-3a"


def _catalog() -> tuple[ContentItem, ...]:
    result: list[ContentItem] = []
    for line in (
        (_FIXTURE_DIR / "products.jsonl").read_text(encoding="utf-8").splitlines()
    ):
        wrapper = json.loads(line)
        result.append(
            ContentItem.from_records(
                wrapper["product"],
                wrapper if "normalization" in wrapper else None,
            )
        )
    return tuple(result)


def _history() -> tuple[Interaction, ...]:
    result: list[Interaction] = []
    for line in (
        (_FIXTURE_DIR / "interactions.jsonl").read_text(encoding="utf-8").splitlines()
    ):
        row = json.loads(line)
        result.append(
            Interaction(
                user_key=row["user_key"],
                item_key=row["item_key"],
                event_time_ms=row["event_time_ms"],
                rating=Decimal(row["rating"]),
                split=DataSplit(row["split"]),
                source_event_fingerprint=row["source_event_fingerprint"],
            )
        )
    return tuple(result)


def _index(
    *,
    references: Iterable[ContentItem] | None = None,
    candidates: Iterable[ContentItem] | None = None,
    config: ContentConfig | None = None,
) -> ContentIndex:
    products = _catalog()
    reference_items = tuple(references) if references is not None else products[:2]
    candidate_items = tuple(candidates) if candidates is not None else products
    return ContentIndex.fit(
        reference_items,
        candidate_items,
        config=config or ContentConfig(),
        code_revision=_CODE_REVISION,
    )


def test_content_item_uses_only_approved_fields_and_provenance() -> None:
    product = _catalog()[0]

    assert product.item_key == "synthetic_laptop_train"
    assert [name for name, _ in product.fields] == [
        "title",
        "category",
        "categories",
        "description",
        "features",
        "brand",
        "ram_capacity_bytes",
        "storage_capacity_bytes",
        "storage_type",
        "processor_name",
        "gpu_name",
    ]
    joined = " ".join(value for _, value in product.fields)
    for forbidden in ("999", "1.00", "store", "secret_note", "synthetic-image"):
        assert forbidden not in joined
    assert product.source_record_fingerprint == "a" * 64
    assert product.normalization_schema == NORMALIZATION_SCHEMA


def test_missing_and_malformed_optional_fields_are_preserved_as_statuses() -> None:
    incomplete, malformed = _catalog()[3:5]
    incomplete_statuses = dict(incomplete.field_statuses)
    malformed_statuses = dict(malformed.field_statuses)

    assert incomplete_statuses["title"] == "missing"
    assert incomplete.fields == ()
    assert malformed_statuses["title"] == "invalid"
    assert malformed_statuses["categories"] == "invalid"
    assert malformed.fields == ()


def test_conflict_marker_makes_product_ineligible() -> None:
    conflicted = _catalog()[-1]

    assert not conflicted.catalog_eligible


def test_incompatible_normalization_schema_is_rejected() -> None:
    wrapper = json.loads((_FIXTURE_DIR / "products.jsonl").read_text().splitlines()[0])
    wrapper["normalization"]["schema_version"] = "recfusion.product-normalization.v99"

    with pytest.raises(ValueError, match="normalization schema"):
        ContentItem.from_records(wrapper["product"], wrapper)


def test_mismatched_normalized_product_identity_is_rejected() -> None:
    wrapper = json.loads((_FIXTURE_DIR / "products.jsonl").read_text().splitlines()[0])
    product = dict(wrapper["product"])
    normalized = json.loads(json.dumps(wrapper))
    normalized["product"]["item_key"] = "synthetic_other_id"

    with pytest.raises(ValueError, match="identity"):
        ContentItem.from_records(product, normalized)


def test_normalized_record_without_product_identity_is_rejected() -> None:
    wrapper = json.loads((_FIXTURE_DIR / "products.jsonl").read_text().splitlines()[0])
    normalized = {"normalization": wrapper["normalization"]}

    with pytest.raises(ValueError, match="identity"):
        ContentItem.from_records(wrapper["product"], normalized)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "16GB 512GB USB-C Wi-Fi 6 RTX 4060 144Hz",
            ("16gb", "512gb", "usb-c", "wi-fi", "6", "rtx", "4060", "144hz"),
        ),
        ("M.2 NVMe 2.4GHz", ("m.2", "nvme", "2.4ghz")),
        ("USB-C!!! Wi-Fi, 6", ("usb-c", "wi-fi", "6")),
    ],
)
def test_tokenizer_preserves_electronics_terms_and_punctuation(
    text: str, expected: tuple[str, ...]
) -> None:
    assert tokenize_electronics_text(text) == expected


def test_tokenizer_normalizes_unicode_and_case_deterministically() -> None:
    assert tokenize_electronics_text(
        "\uff26\uff29 16\uff27\uff22 \u00c9cran USB-C"
    ) == (
        "fi",
        "16gb",
        "écran",
        "usb-c",
    )
    assert tokenize_electronics_text("USB-C") == tokenize_electronics_text("usb-c")


def test_vectorizer_uses_deterministic_bounded_vocabulary() -> None:
    products = _catalog()
    forward = _index(references=products[:3], candidates=products)
    shuffled = _index(
        references=(products[2], products[0], products[1]), candidates=products
    )

    assert forward.vectorizer.vocabulary == shuffled.vectorizer.vocabulary
    assert forward.vocabulary_sha256 == shuffled.vocabulary_sha256

    bounded = _index(
        references=products[:3],
        candidates=products,
        config=ContentConfig(max_vocabulary_size=3),
    )
    assert len(bounded.vectorizer.vocabulary) <= 3


def test_tfidf_idf_uses_smoothed_document_frequency() -> None:
    products = _catalog()
    index = _index(references=products[:2], candidates=products)
    token = "synthetic"

    assert index.vectorizer.document_count == 2
    assert math.isclose(
        index.vectorizer.idf[token],
        math.log((1 + 2) / (1 + 2)) + 1,
        rel_tol=0,
        abs_tol=1e-12,
    )


def test_similarity_is_cosine_and_zero_scores_are_not_recommended() -> None:
    products = _catalog()
    index = _index(references=products[:2], candidates=products)

    exact = index.recommend_similar(products[0], k=5)
    assert exact.items[0].item_key == "synthetic_cold_laptop"
    assert math.isclose(exact.items[0].score, 1.0, abs_tol=1e-12)
    assert all(result.score > 0 for result in exact.items)


def test_self_item_is_excluded_and_k_is_bounded() -> None:
    products = _catalog()
    index = _index(references=products[:2], candidates=products)
    results = index.recommend_similar(products[0], k=1)

    assert len(results.items) == 1
    assert all(item.item_key != products[0].item_key for item in results.items)
    with pytest.raises(ValueError, match="maximum"):
        index.recommend_similar(products[0], k=101)


def test_unseen_query_uses_fitted_vectorizer_without_refitting() -> None:
    products = _catalog()
    index = _index(references=products[:2], candidates=products)
    before = index.vocabulary_sha256
    unseen = ContentItem(
        item_key="synthetic_unseen_query",
        fields=(("title", "Synthetic Laptop USB-C 16GB"),),
        source_record_fingerprint="9" * 64,
    )

    result = index.recommend_similar(unseen, k=3)

    assert result.items
    assert index.vocabulary_sha256 == before


def test_empty_or_unknown_query_returns_no_fallback() -> None:
    products = _catalog()
    index = _index(references=products[:2], candidates=products)
    empty = ContentItem("synthetic_empty_query", (), "8" * 64)
    unknown = ContentItem(
        "synthetic_unknown_query", (("title", "unseenwordzz"),), "7" * 64
    )

    assert index.recommend_similar(empty, k=5).reason == "empty_query_content"
    assert index.recommend_similar(unknown, k=5).reason == "empty_query_content"


def test_candidate_allowlist_and_conflict_policy_are_applied() -> None:
    products = _catalog()
    index = _index(references=products[:2], candidates=products)
    allowed = {"synthetic_cold_laptop", "synthetic_conflicted_product"}

    result = index.recommend_similar(products[0], k=5, eligible_item_keys=allowed)

    assert [item.item_key for item in result.items] == ["synthetic_cold_laptop"]


def test_duplicate_candidate_identity_is_rejected() -> None:
    products = _catalog()

    with pytest.raises(ValueError, match="Duplicate item identity"):
        _index(references=products[:2], candidates=(products[0], products[0]))


def test_batch_results_match_single_queries_and_obey_batch_bound() -> None:
    products = _catalog()
    index = _index(references=products[:2], candidates=products)
    queries = products[:2]

    batch = index.recommend_many(queries, k=3)
    singles = tuple(index.recommend_similar(query, k=3) for query in queries)
    assert batch == singles

    with pytest.raises(ValueError, match="batch limit"):
        index.recommend_many(queries * 17, k=3)


def test_user_profile_uses_prior_positive_unique_items_and_tracks_seen_items() -> None:
    index = _index()
    profile = index.profile_from_training_history(
        _history(),
        user_key="synthetic_user_1",
        prediction_time_ms=3000,
        target_item_key="synthetic_cold_laptop",
    )

    assert profile.prior_positive_item_count == 1
    assert profile.seen_item_keys == frozenset(
        {"synthetic_laptop_train", "synthetic_headphones_train"}
    )
    assert profile.vector
    assert not hasattr(profile, "user_key")


def test_history_profile_excludes_nonpositive_items_from_content_average() -> None:
    index = _index()
    profile = index.profile_from_training_history(
        _history(),
        user_key="synthetic_user_1",
        prediction_time_ms=3000,
    )
    positive_vector = index.vectorizer.transform(_catalog()[0])

    assert profile.vector == positive_vector
    assert "synthetic_headphones_train" in profile.seen_item_keys


def test_target_product_is_masked_from_its_own_profile() -> None:
    profile = _index().profile_from_training_history(
        _history(),
        user_key="synthetic_user_1",
        prediction_time_ms=3000,
        target_item_key="synthetic_laptop_train",
    )

    assert profile.prior_positive_item_count == 0
    assert profile.vector == ()


def test_equal_timestamp_and_future_events_do_not_enter_profile_or_seen_set() -> None:
    profile = _index().profile_from_training_history(
        _history(), user_key="synthetic_user_1", prediction_time_ms=3000
    )

    assert "synthetic_equal_time_item" not in profile.seen_item_keys
    assert "synthetic_future_item" not in profile.seen_item_keys


def test_heldout_history_events_are_rejected() -> None:
    heldout = Interaction(
        "synthetic_user_1",
        "synthetic_cold_laptop",
        1500,
        Decimal("5"),
        DataSplit.VALIDATION,
        hashlib.sha256(b"synthetic heldout").hexdigest(),
    )

    with pytest.raises(ValueError, match="training-only"):
        _index().profile_from_training_history(
            (*_history(), heldout),
            user_key="synthetic_user_1",
            prediction_time_ms=3000,
        )


def test_user_retrieval_excludes_all_prior_seen_products_and_returns_cold_item() -> (
    None
):
    index = _index()
    profile = index.profile_from_training_history(
        _history(), user_key="synthetic_user_1", prediction_time_ms=3000
    )

    result = index.recommend_for_profile(profile, k=5)

    keys = [item.item_key for item in result.items]
    assert "synthetic_cold_laptop" in keys
    assert "synthetic_laptop_train" not in keys
    assert "synthetic_headphones_train" not in keys


def test_empty_user_profile_returns_no_recommendations() -> None:
    index = _index()
    profile = index.profile_from_training_history(
        (), user_key="synthetic_user_1", prediction_time_ms=3000
    )

    assert index.recommend_for_profile(profile, k=5).reason == "empty_user_profile"


def test_profile_reports_positive_history_without_metadata() -> None:
    products = _catalog()
    index = _index(references=products[:2], candidates=products)
    event = Interaction(
        "synthetic_user_2",
        "synthetic_incomplete_product",
        1000,
        Decimal("5"),
        DataSplit.TRAIN,
        "6" * 64,
    )
    profile = index.profile_from_training_history(
        (event,), user_key="synthetic_user_2", prediction_time_ms=2000
    )

    assert profile.prior_positive_item_count == 1
    assert profile.missing_content_item_count == 1
    assert not profile.vector


def test_profile_rejects_history_input_over_configured_event_bound() -> None:
    index = _index(config=ContentConfig(max_history_events=1))

    with pytest.raises(ValueError, match="event limit"):
        index.profile_from_training_history(
            _history()[:2], user_key="synthetic_user_1", prediction_time_ms=3000
        )


def test_vectorizer_rejects_corpus_above_distinct_term_bound() -> None:
    products = _catalog()

    with pytest.raises(ValueError, match="distinct-term limit"):
        _index(
            references=products[:2],
            candidates=products,
            config=ContentConfig(max_distinct_terms=2),
        )


def test_artifact_is_deterministic_and_records_checksums_and_policy() -> None:
    products = _catalog()
    first = _index(references=products[:2], candidates=products)
    second = _index(
        references=(products[1], products[0]), candidates=reversed(products)
    )
    artifact = first.to_artifact_bytes()
    record = json.loads(artifact)

    assert artifact == second.to_artifact_bytes()
    assert record["artifact_schema"] == CONTENT_INDEX_ARTIFACT_SCHEMA
    assert record["feature_schema"] == CONTENT_FEATURE_SCHEMA
    assert record["vocabulary_sha256"] == first.vocabulary_sha256
    assert len(record["catalog_manifest_sha256"]) == 64
    assert record["code_revision"] == _CODE_REVISION
    assert record["candidate_eligibility_policy"]


def test_artifact_round_trip_preserves_rankings_and_rejects_wrong_schema() -> None:
    products = _catalog()
    index = _index(references=products[:2], candidates=products)
    artifact = index.to_artifact_bytes()
    restored = ContentIndex.from_artifact_bytes(artifact)

    assert restored.to_artifact_bytes() == artifact
    assert restored.recommend_similar(products[0], k=3) == index.recommend_similar(
        products[0], k=3
    )
    wrong_version = json.loads(artifact)
    wrong_version["feature_schema"] = "recfusion.content-feature.v99"
    with pytest.raises(ValueError, match="feature schema"):
        ContentIndex.from_artifact_bytes(json.dumps(wrong_version).encode())


def test_artifact_rejects_invalid_json_without_loading_python_objects() -> None:
    with pytest.raises(ValueError, match="JSON"):
        ContentIndex.from_artifact_bytes(b"cos\npython/object/apply:os.system")


def test_config_rejects_unbounded_resource_limits() -> None:
    with pytest.raises(ValueError, match="maximum vocabulary"):
        ContentConfig(max_vocabulary_size=100_001)
    with pytest.raises(ValueError, match="catalog item"):
        ContentConfig(max_catalog_items=100_001)
    with pytest.raises(ValueError, match="distinct term"):
        ContentConfig(max_distinct_terms=1_000_001)
