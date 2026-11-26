"""Reproducible synthetic benchmark for sparse content retrieval.

This module generates all records in memory. It has no path or dataset I/O and
does not use the Phase 3 warm-only evaluator, whose candidate contract is
intentionally different from this cold-item benchmark.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from math import log2

from recfusion_core.contracts import DataSplit, Interaction
from recfusion_ml.retrieval.content import (
    CONTENT_FEATURE_SCHEMA,
    ContentConfig,
    ContentIndex,
    ContentItem,
)

BENCHMARK_SCHEMA = "recfusion.content-benchmark.v1"
GENERATOR_SCHEMA = "recfusion.synthetic-content-generator.v1"
BENCHMARK_VERSION = "4.3B"
DEFAULT_SEED = 43031
EVALUATION_KS = (5, 10, 20)
POSITIVE_MIN_RATING = Decimal("4")

type Rankings = Mapping[str, Sequence[str]]
type Relevance = Mapping[str, Set[str]]

_NORMALIZATION_SCHEMA = "recfusion.product-normalization.v1"
_TOKENIZER_SCHEMA = "recfusion.electronics-tokenizer.v1"
_CATEGORY_PROFILES: tuple[tuple[str, str, tuple[tuple[str, str, str], ...]], ...] = (
    (
        "laptop",
        "Computers/Laptops",
        (
            (
                "gaming",
                "gaming laptop RTX graphics high refresh",
                "16GB RAM 1TB NVMe SSD USB-C Wi-Fi 6",
            ),
            (
                "portable",
                "ultraportable laptop OLED long battery",
                "16GB RAM 512GB SSD USB-C Wi-Fi 6",
            ),
        ),
    ),
    (
        "audio",
        "Audio/Headphones",
        (
            (
                "studio",
                "studio headphones wired reference audio",
                "40mm drivers USB-C high resolution audio",
            ),
            (
                "travel",
                "wireless noise cancelling headphones travel",
                "Bluetooth 5.3 USB-C 30 hour battery",
            ),
        ),
    ),
    (
        "camera",
        "Cameras/Mirrorless",
        (
            (
                "photo",
                "mirrorless camera APS-C image sensor",
                "24MP 4K video USB-C stabilization",
            ),
            (
                "video",
                "compact camera video creator autofocus",
                "4K 60fps image stabilization USB-C",
            ),
        ),
    ),
    (
        "network",
        "Networking/Routers",
        (
            (
                "mesh",
                "mesh Wi-Fi router whole home coverage",
                "Wi-Fi 6 tri-band 2.5GbE WPA3",
            ),
            (
                "gaming",
                "gaming router low latency network",
                "Wi-Fi 6E 2.5GbE QoS WPA3",
            ),
        ),
    ),
)


class CandidatePolicy(StrEnum):
    """Frozen benchmark candidate universes."""

    WARM_ONLY = "warm_only"
    CONTENT_ELIGIBLE = "content_eligible"


@dataclass(frozen=True, slots=True)
class SyntheticContentBenchmark:
    """Invented source partitions retained in memory for one benchmark run."""

    seed: int
    generator_schema: str
    generator_config: Mapping[str, object]
    products: tuple[ContentItem, ...]
    reference_item_keys: frozenset[str]
    warm_item_keys: frozenset[str]
    cold_item_keys: frozenset[str]
    training_interactions: tuple[Interaction, ...]
    evaluation_events: tuple[Interaction, ...]
    source_checksums: Mapping[str, str]
    metadata_source_record_count: int
    duplicate_metadata_occurrences: int
    conflicting_metadata_occurrences: int
    manifest: Mapping[str, object]
    manifest_bytes: bytes

    @property
    def evaluation_users(self) -> tuple[str, ...]:
        return tuple(sorted({event.user_key for event in self.evaluation_events}))

    @property
    def products_by_key(self) -> Mapping[str, ContentItem]:
        return {product.item_key: product for product in self.products}


@dataclass(frozen=True, slots=True)
class ContentBenchmarkRun:
    """Aggregate-only report and its deterministic serialized manifest."""

    aggregate: Mapping[str, object]
    manifest_bytes: bytes
    manifest_sha256: str


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _jsonl_bytes(records: Sequence[Mapping[str, object]]) -> bytes:
    return b"".join(_canonical_bytes(record) + b"\n" for record in records)


def _event_fingerprint(
    user_key: str,
    item_key: str,
    event_time_ms: int,
    rating: Decimal,
    split: DataSplit,
) -> str:
    return _sha256(
        _canonical_bytes(
            {
                "user_key": user_key,
                "item_key": item_key,
                "event_time_ms": event_time_ms,
                "rating": str(rating),
                "split": split.value,
            }
        )
    )


def _interaction(
    user_key: str,
    item_key: str,
    event_time_ms: int,
    rating: str,
    split: DataSplit,
) -> Interaction:
    decimal_rating = Decimal(rating)
    return Interaction(
        user_key=user_key,
        item_key=item_key,
        event_time_ms=event_time_ms,
        rating=decimal_rating,
        split=split,
        source_event_fingerprint=_event_fingerprint(
            user_key, item_key, event_time_ms, decimal_rating, split
        ),
    )


def _interaction_record(event: Interaction) -> dict[str, object]:
    return {
        "user_key": event.user_key,
        "item_key": event.item_key,
        "event_time_ms": event.event_time_ms,
        "rating": str(event.rating),
        "split": event.split.value,
        "source_event_fingerprint": event.source_event_fingerprint,
    }


def _product_mapping(record: Mapping[str, object]) -> Mapping[str, object]:
    product = record.get("product")
    if not isinstance(product, Mapping):
        raise ValueError("Synthetic product record is malformed.")
    return product


def _product_item_key(record: Mapping[str, object]) -> str:
    item_key = _product_mapping(record).get("item_key")
    if not isinstance(item_key, str):
        raise ValueError("Synthetic product record is missing its item key.")
    return item_key


def _normalized_field(value: object) -> dict[str, object]:
    return {
        "value": value,
        "status": "normalized" if value is not None else "missing",
        "source_keys": ["synthetic specification"],
    }


def _make_product_record(
    item_key: str,
    *,
    category: str,
    profile_terms: str,
    model: str,
    variant: int,
    cold: bool,
    empty: bool = False,
    conflict: bool = False,
    malformed: bool = False,
    rare_token: bool = False,
) -> dict[str, object]:
    title = (
        None
        if empty
        else f"Synthetic {category.split('/')[-1]} {profile_terms} {model} {variant}"
    )
    if cold and profile_terms:
        title = f"Synthetic cold {category.split('/')[-1]} {profile_terms} {model}"
    if cold and not profile_terms:
        title = f"UnseenOnly{model}"

    description = (
        "Synthetic graphics workstation with rare QX-7000 accelerator "
        "and shared laptop terms."
        if rare_token
        else f"Synthetic electronics item for {profile_terms}; variant {variant}."
    )
    product: dict[str, object] = {
        "item_key": item_key,
        "title": title,
        "category": None if empty else category,
        "categories": [] if empty else category.split("/"),
        "description": None if empty else [description],
        "features": 19
        if malformed
        else []
        if empty
        else [profile_terms, f"model {model}"],
        "rating_count": 10000,
        "average_rating": "5.0",
        "price": {"amount": "1.00", "currency": "USD"},
        "images": ["synthetic-image-only"],
        "attributes": {
            "brand": "Synthetic Lab",
            "store": "Synthetic store text is excluded",
        },
    }
    fingerprint = _sha256(_canonical_bytes(product))
    product["source_record_fingerprint"] = fingerprint

    normalized = {
        "schema_version": _NORMALIZATION_SCHEMA,
        "brand": _normalized_field("synthetic lab"),
        "specifications": {
            "ram_capacity_bytes": _normalized_field(16_000_000_000),
            "storage_capacity_bytes": _normalized_field(512_000_000_000),
            "storage_type": _normalized_field("ssd"),
            "processor_name": _normalized_field(f"Synthetic CPU {model}"),
            "gpu_name": _normalized_field("Synthetic GPU"),
        },
        "product_decision": "conflict_retained" if conflict else "unique_retained",
        "source_record_fingerprint": fingerprint,
    }
    return {"product": product, "normalization": normalized}


def _make_unknown_cold_record(item_key: str, token: str) -> dict[str, object]:
    product: dict[str, object] = {
        "item_key": item_key,
        "title": token,
        "category": None,
        "categories": [],
        "description": None,
        "features": [],
    }
    fingerprint = _sha256(_canonical_bytes(product))
    product["source_record_fingerprint"] = fingerprint
    return {
        "product": product,
        "normalization": {
            "schema_version": _NORMALIZATION_SCHEMA,
            "brand": _normalized_field(None),
            "specifications": {},
            "product_decision": "unique_retained",
            "source_record_fingerprint": fingerprint,
        },
    }


def _make_missing_record(item_key: str) -> dict[str, object]:
    product: dict[str, object] = {
        "item_key": item_key,
        "title": None,
        "category": None,
        "categories": None,
        "description": None,
        "features": None,
    }
    product["source_record_fingerprint"] = _sha256(_canonical_bytes(product))
    return {"product": product}


def generate_synthetic_benchmark(
    *, seed: int = DEFAULT_SEED
) -> SyntheticContentBenchmark:
    """Generate deterministic, invented product and interaction partitions."""
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("Benchmark seed must be a non-negative integer.")

    rng = random.Random(seed)
    generator_config: dict[str, object] = {
        "seed": seed,
        "category_count": len(_CATEGORY_PROFILES),
        "warm_products_per_category": 6,
        "cold_content_products_per_category": 2,
        "cold_unseen_vocabulary_products_per_category": 1,
        "cold_missing_product_count": 1,
        "cold_conflict_product_count": 1,
        "item_variants_per_interest_profile": 3,
        "evaluation_users": 16,
        "empty_history_users": 2,
        "positive_rating_threshold": "4",
        "evaluation_timestamp_ms": 10_000,
        "interest_categories": [category[0] for category in _CATEGORY_PROFILES],
        "history_positive_event_rule": (
            "0-2 unique positives per user with one optional repeated positive record"
        ),
        "low_rating_event_rule": "rating 2 for half of non-empty histories",
        "popularity_control_signal": (
            "distinct synthetic users add positives to a subset of warm items"
        ),
        "content_schema": CONTENT_FEATURE_SCHEMA,
        "normalization_schema": _NORMALIZATION_SCHEMA,
        "duplicate_metadata_policy": (
            "one exact repeated record and one conflicting record"
        ),
        "history_generation": (
            "seeded interest assignments; 0-2 unique positives and optional "
            "repeated positive/low rating"
        ),
    }

    record_rows: list[dict[str, object]] = []
    products: list[ContentItem] = []
    warm_keys: set[str] = set()
    cold_keys: set[str] = set()
    reference_keys: set[str] = set()
    profile_user_groups: list[tuple[str, str, str, tuple[str, ...], str]] = []

    for category_name, category_label, profiles in _CATEGORY_PROFILES:
        for profile_name, profile_text, specifications in profiles:
            warm_keys_for_profile: list[str] = []
            for variant in range(3):
                item_key = f"synthetic_warm_{category_name}_{profile_name}_{variant}"
                model = (
                    f"M{category_name[:2].upper()}-{profile_name[:2].upper()}-{variant}"
                )
                row = _make_product_record(
                    item_key,
                    category=category_label,
                    profile_terms=f"{profile_text} {specifications}",
                    model=model,
                    variant=variant,
                    cold=False,
                    malformed=(
                        category_name == "audio"
                        and profile_name == "studio"
                        and variant == 2
                    ),
                    rare_token=(
                        category_name == "laptop"
                        and profile_name == "gaming"
                        and variant == 0
                    ),
                )
                record_rows.append(row)
                products.append(
                    ContentItem.from_records(
                        _product_mapping(row),
                        row if "normalization" in row else None,
                    )
                )
                warm_keys.add(item_key)
                reference_keys.add(item_key)
                warm_keys_for_profile.append(item_key)
            eligible_cold_key = (
                f"synthetic_cold_{category_name}_{profile_name}_matching"
            )
            eligible_cold = _make_product_record(
                eligible_cold_key,
                category=category_label,
                profile_terms=f"{profile_text} {specifications}",
                model=f"COLD-{category_name[:2].upper()}-{profile_name[:2].upper()}",
                variant=0,
                cold=True,
            )
            record_rows.append(eligible_cold)
            products.append(
                ContentItem.from_records(_product_mapping(eligible_cold), eligible_cold)
            )
            cold_keys.add(eligible_cold_key)

            unknown_key = f"synthetic_cold_{category_name}_{profile_name}_unseen"
            unknown_row = _make_unknown_cold_record(
                unknown_key, f"UnseenOnlyZQ{category_name}{profile_name}"
            )
            record_rows.append(unknown_row)
            products.append(
                ContentItem.from_records(_product_mapping(unknown_row), unknown_row)
            )
            cold_keys.add(unknown_key)

            profile_user_groups.append(
                (
                    category_name,
                    profile_name,
                    category_label,
                    tuple(warm_keys_for_profile),
                    eligible_cold_key,
                )
            )

    missing_key = "synthetic_cold_missing_metadata"
    missing_row = _make_missing_record(missing_key)
    record_rows.append(missing_row)
    products.append(ContentItem.from_records(_product_mapping(missing_row)))
    cold_keys.add(missing_key)

    conflict_key = "synthetic_cold_conflicted_metadata"
    _, category_label, conflict_profiles = _CATEGORY_PROFILES[0]
    _, profile_text, specifications = conflict_profiles[0]
    conflict_row = _make_product_record(
        conflict_key,
        category=category_label,
        profile_terms=f"{profile_text} {specifications}",
        model="CONFLICT-X1",
        variant=0,
        cold=True,
        conflict=True,
    )
    record_rows.append(conflict_row)
    products.append(
        ContentItem.from_records(_product_mapping(conflict_row), conflict_row)
    )
    cold_keys.add(conflict_key)
    conflicting_row = json.loads(_canonical_bytes(conflict_row))
    conflicting_row["product"]["title"] = "Synthetic conflicting alternate title"
    conflicting_row["product"].pop("source_record_fingerprint")
    alternate_fingerprint = _sha256(_canonical_bytes(conflicting_row["product"]))
    conflicting_row["product"]["source_record_fingerprint"] = alternate_fingerprint
    conflicting_row["normalization"]["source_record_fingerprint"] = (
        alternate_fingerprint
    )
    record_rows.append(conflicting_row)

    exact_duplicate_row = next(
        row
        for row in record_rows
        if _product_item_key(row) == "synthetic_warm_laptop_gaming_0"
    )
    record_rows.append(json.loads(_canonical_bytes(exact_duplicate_row)))

    # Every warm catalog item is train-known independently of held-out labels.
    training: list[Interaction] = []
    for item_key in sorted(warm_keys):
        training.append(
            _interaction(
                "synthetic_catalog_coverage_user",
                item_key,
                500,
                "5",
                DataSplit.TRAIN,
            )
        )

    # Seeded assignments vary the user-to-interest mapping, never item splits.
    assignments = [group for group in profile_user_groups for _ in range(2)]
    rng.shuffle(assignments)
    empty_user_indices = set(rng.sample(range(len(assignments)), 2))
    evaluation_user_profiles: dict[str, tuple[str, str, tuple[str, ...], str]] = {}
    evaluation_users_by_group: dict[tuple[str, str], list[str]] = defaultdict(list)
    for index, (
        category_name,
        profile_name,
        _category_label,
        warm_keys_for_group,
        cold_key,
    ) in enumerate(assignments):
        user_key = f"synthetic_user_{index:03d}"
        evaluation_user_profiles[user_key] = (
            category_name,
            profile_name,
            warm_keys_for_group,
            cold_key,
        )
        evaluation_users_by_group[(category_name, profile_name)].append(user_key)
        if index in empty_user_indices:
            continue
        history_count = 1 + (index % 3)
        positive_history = warm_keys_for_group[: min(history_count, 2)]
        for event_offset, item_key in enumerate(positive_history):
            training.append(
                _interaction(
                    user_key,
                    item_key,
                    1_000 + event_offset * 500,
                    "5",
                    DataSplit.TRAIN,
                )
            )
        if index % 4 == 0 and positive_history:
            training.append(
                _interaction(
                    user_key,
                    positive_history[0],
                    1_750,
                    "5",
                    DataSplit.TRAIN,
                )
            )
        if index % 2 == 0:
            other = next(
                group for group in profile_user_groups if group[0] != category_name
            )
            training.append(
                _interaction(
                    user_key,
                    other[3][0],
                    2_500,
                    "2",
                    DataSplit.TRAIN,
                )
            )

    # Add limited synthetic popularity signal using distinct non-evaluation users.
    for category_name, _, _, warm_keys_for_group, _ in profile_user_groups:
        for popularity_user in range(1 + (len(category_name) % 3)):
            training.append(
                _interaction(
                    f"synthetic_popularity_user_{popularity_user}",
                    warm_keys_for_group[0],
                    750 + popularity_user,
                    "5",
                    DataSplit.TRAIN,
                )
            )

    evaluation: list[Interaction] = []
    for user_key, (_, _, warm_keys_for_group, _) in sorted(
        evaluation_user_profiles.items()
    ):
        evaluation.append(
            _interaction(
                user_key,
                warm_keys_for_group[2],
                10_000,
                "5",
                DataSplit.VALIDATION,
            )
        )

    for _, users in sorted(evaluation_users_by_group.items()):
        evaluation.append(
            _interaction(
                users[0],
                evaluation_user_profiles[users[0]][3],
                10_000,
                "5",
                DataSplit.VALIDATION,
            )
        )

    cold_special_users = tuple(sorted(evaluation_user_profiles))[:3]
    for user_key, cold_key in zip(
        cold_special_users,
        (missing_key, conflict_key, "synthetic_cold_laptop_gaming_unseen"),
        strict=True,
    ):
        evaluation.append(
            _interaction(
                user_key,
                cold_key,
                10_000,
                "5",
                DataSplit.VALIDATION,
            )
        )

    training.sort(
        key=lambda event: (
            event.event_time_ms,
            event.user_key,
            event.item_key,
            event.rating,
        )
    )
    evaluation.sort(
        key=lambda event: (event.event_time_ms, event.user_key, event.item_key)
    )

    training_records = [_interaction_record(event) for event in training]
    evaluation_records = [_interaction_record(event) for event in evaluation]
    source_checksums = {
        "metadata_source_sha256": _sha256(_jsonl_bytes(record_rows)),
        "training_interactions_sha256": _sha256(_jsonl_bytes(training_records)),
        "evaluation_labels_sha256": _sha256(_jsonl_bytes(evaluation_records)),
    }
    generator_manifest: dict[str, object] = {
        "schema_version": BENCHMARK_SCHEMA,
        "benchmark_version": BENCHMARK_VERSION,
        "generator_schema": GENERATOR_SCHEMA,
        "generator_config": generator_config,
        "partition_sizes": {
            "reference_catalog_items": len(reference_keys),
            "warm_catalog_items": len(warm_keys),
            "cold_catalog_items": len(cold_keys),
            "evaluation_users": len({event.user_key for event in evaluation}),
            "training_interactions": len(training),
            "evaluation_events": len(evaluation),
            "metadata_source_records": len(record_rows),
        },
        "source_checksums": source_checksums,
        "partition_policy": {
            "reference": "all synthetic warm items; selected without held-out labels",
            "warm": "all train-known synthetic items",
            "cold": "synthetic items absent from every training interaction",
            "heldout": (
                "synthetic relevance events at one fixed UTC-millisecond instant"
            ),
        },
        "duplicate_metadata_occurrences": 1,
        "conflicting_metadata_occurrences": 1,
    }
    manifest_bytes = _canonical_bytes(generator_manifest) + b"\n"
    return SyntheticContentBenchmark(
        seed=seed,
        generator_schema=GENERATOR_SCHEMA,
        generator_config=generator_config,
        products=tuple(sorted(products, key=lambda product: product.item_key)),
        reference_item_keys=frozenset(reference_keys),
        warm_item_keys=frozenset(warm_keys),
        cold_item_keys=frozenset(cold_keys),
        training_interactions=tuple(training),
        evaluation_events=tuple(evaluation),
        source_checksums=source_checksums,
        metadata_source_record_count=len(record_rows),
        duplicate_metadata_occurrences=1,
        conflicting_metadata_occurrences=1,
        manifest=generator_manifest,
        manifest_bytes=manifest_bytes,
    )


def evaluate_macro_rankings(
    *,
    relevant_by_user: Relevance,
    rankings_by_user: Rankings,
    eligible_candidate_count: int,
    ks: Sequence[int] = EVALUATION_KS,
) -> dict[str, object]:
    """Compute macro binary ranking metrics over a fixed user denominator."""
    if isinstance(eligible_candidate_count, bool) or eligible_candidate_count < 0:
        raise ValueError("Eligible candidate count must be non-negative.")
    users = set(relevant_by_user)
    if set(rankings_by_user) != users:
        raise ValueError("Rankings must be provided for every evaluated user.")
    k_values = tuple(ks)
    if not k_values or any(
        isinstance(k, bool) or not isinstance(k, int) or k <= 0 for k in k_values
    ):
        raise ValueError("K values must be positive integers.")
    if len(set(k_values)) != len(k_values):
        raise ValueError("K values must be unique.")
    for user in users:
        if not relevant_by_user[user]:
            raise ValueError("Every evaluated user must have an eligible target.")
        ranking = tuple(rankings_by_user[user])
        if len(ranking) != len(set(ranking)):
            raise ValueError("Recommendation lists must contain unique items.")

    output: dict[str, object] = {
        "evaluated_user_count": len(users),
        "eligible_target_count": sum(
            len(targets) for targets in relevant_by_user.values()
        ),
        "metrics_by_k": {},
    }
    metrics_by_k: dict[str, object] = {}
    for k in k_values:
        recall_values: list[float] = []
        ndcg_values: list[float] = []
        hit_values: list[float] = []
        reciprocal_ranks: list[float] = []
        unique_products: set[str] = set()
        total_recommendations = 0
        short_users = 0
        for user in sorted(users):
            ranked = tuple(rankings_by_user[user])[:k]
            relevant = set(relevant_by_user[user])
            unique_products.update(ranked)
            total_recommendations += len(ranked)
            short_users += int(len(ranked) < k)
            gains = [float(item in relevant) for item in ranked]
            hits = sum(gains)
            recall_values.append(hits / len(relevant))
            dcg = sum(gain / log2(rank + 2) for rank, gain in enumerate(gains))
            ideal_count = min(len(relevant), k)
            idcg = sum(1.0 / log2(rank + 2) for rank in range(ideal_count))
            ndcg_values.append(dcg / idcg if idcg else 0.0)
            hit_values.append(float(hits > 0))
            first_hit = next(
                (rank for rank, gain in enumerate(gains, start=1) if gain), None
            )
            reciprocal_ranks.append(1 / first_hit if first_hit else 0.0)
        user_count = len(users)
        metrics_by_k[str(k)] = {
            "recall": sum(recall_values) / user_count if user_count else None,
            "ndcg": sum(ndcg_values) / user_count if user_count else None,
            "hit_rate": sum(hit_values) / user_count if user_count else None,
            "mrr": sum(reciprocal_ranks) / user_count if user_count else None,
            "unique_recommended_products": len(unique_products),
            "recommendation_count": total_recommendations,
            "catalog_coverage": (
                len(unique_products) / eligible_candidate_count
                if eligible_candidate_count
                else None
            ),
            "users_with_short_lists": short_users,
            "mean_list_length": total_recommendations / user_count
            if user_count
            else 0.0,
            "macro_user_denominator": user_count,
        }
    output["metrics_by_k"] = metrics_by_k
    return output


def _profile_targets(
    benchmark: SyntheticContentBenchmark,
    candidates: frozenset[str],
) -> dict[str, frozenset[str]]:
    seen_by_user: dict[str, set[str]] = defaultdict(set)
    for event in benchmark.training_interactions:
        if event.event_time_ms < 10_000:
            seen_by_user[event.user_key].add(event.item_key)
    targets: dict[str, set[str]] = {user: set() for user in benchmark.evaluation_users}
    for event in benchmark.evaluation_events:
        if (
            event.rating >= POSITIVE_MIN_RATING
            and event.item_key in candidates
            and event.item_key not in seen_by_user.get(event.user_key, set())
        ):
            targets[event.user_key].add(event.item_key)
    return {user: frozenset(items) for user, items in targets.items()}


def _ranked_by_policy(
    index: ContentIndex,
    benchmark: SyntheticContentBenchmark,
    candidate_keys: frozenset[str],
    model: str,
) -> dict[str, tuple[str, ...]]:
    rankings: dict[str, tuple[str, ...]] = {}
    positive_pairs = {
        (event.user_key, event.item_key)
        for event in benchmark.training_interactions
        if event.rating >= POSITIVE_MIN_RATING
    }
    positive_counts: Counter[str] = Counter(item for _, item in positive_pairs)
    if model == "popularity":
        ordered = tuple(
            sorted(candidate_keys, key=lambda item: (-positive_counts[item], item))
        )
    else:
        ordered = ()

    for user in benchmark.evaluation_users:
        profile = index.profile_from_training_history(
            benchmark.training_interactions,
            user_key=user,
            prediction_time_ms=10_000,
        )
        eligible = candidate_keys - profile.seen_item_keys
        if model == "tfidf_user_profile":
            recommendation = index.recommend_for_profile(
                profile, k=20, eligible_item_keys=eligible
            )
            rankings[user] = tuple(result.item_key for result in recommendation.items)
        elif model == "item_content_nearest_neighbor":
            prior_positive = [
                event
                for event in benchmark.training_interactions
                if event.user_key == user
                and event.rating >= POSITIVE_MIN_RATING
                and event.event_time_ms < 10_000
                and event.item_key in index.content_vectors
            ]
            if not prior_positive:
                rankings[user] = ()
                continue
            query = max(
                prior_positive,
                key=lambda event: (event.event_time_ms, event.item_key),
            )
            recommendation = index.recommend_similar(
                benchmark.products_by_key[query.item_key],
                k=20,
                eligible_item_keys=eligible,
            )
            rankings[user] = tuple(result.item_key for result in recommendation.items)
        elif model == "popularity":
            rankings[user] = tuple(
                item for item in ordered if item not in profile.seen_item_keys
            )
        elif model == "deterministic_random":
            rankings[user] = tuple(
                sorted(
                    eligible,
                    key=lambda item: (
                        _sha256(f"{benchmark.seed}|{user}|{item}".encode()),
                        item,
                    ),
                )
            )
        else:
            raise ValueError(f"Unknown synthetic benchmark model: {model}.")
    return rankings


def _cold_item_metrics(
    *,
    benchmark: SyntheticContentBenchmark,
    candidates: frozenset[str],
    rankings: Rankings,
    eligible_targets: Relevance,
    k_values: Sequence[int] = EVALUATION_KS,
) -> dict[str, object]:
    cold_targets = {
        user: frozenset(item for item in targets if item in benchmark.cold_item_keys)
        for user, targets in eligible_targets.items()
    }
    cold_users = {user for user, targets in cold_targets.items() if targets}
    target_count = sum(len(targets) for targets in cold_targets.values())
    recall_by_k: dict[str, object] = {}
    for k in k_values:
        per_user = [
            len(set(rankings[user][:k]) & set(cold_targets[user]))
            / len(cold_targets[user])
            for user in sorted(cold_users)
        ]
        recall_by_k[str(k)] = sum(per_user) / len(per_user) if per_user else None

    seen: dict[str, set[str]] = defaultdict(set)
    for event in benchmark.training_interactions:
        seen[event.user_key].add(event.item_key)
    ineligible_positive_count = sum(
        1
        for event in benchmark.evaluation_events
        if event.rating >= POSITIVE_MIN_RATING
        and event.item_key in benchmark.cold_item_keys
        and (
            event.item_key not in candidates
            or event.item_key in seen.get(event.user_key, set())
        )
    )
    return {
        "averaging": "macro over users with at least one eligible cold positive",
        "eligible_user_denominator": len(cold_users),
        "eligible_target_denominator": target_count,
        "users_without_eligible_cold_positive": len(eligible_targets) - len(cold_users),
        "ineligible_cold_positive_count": ineligible_positive_count,
        "eligible_cold_candidate_count": sum(
            item in candidates for item in benchmark.cold_item_keys
        ),
        "unique_cold_candidate_count": sum(
            item in candidates for item in benchmark.cold_item_keys
        ),
        "recall_by_k": recall_by_k,
    }


def _policy_report(
    *,
    benchmark: SyntheticContentBenchmark,
    index: ContentIndex,
    candidate_keys: frozenset[str],
    warm_candidates: frozenset[str],
    models: Sequence[str],
) -> tuple[dict[str, object], dict[str, dict[str, tuple[str, ...]]]]:
    targets = _profile_targets(benchmark, candidate_keys)
    model_reports: dict[str, object] = {}
    rankings_by_model: dict[str, dict[str, tuple[str, ...]]] = {}
    for model in models:
        rankings = _ranked_by_policy(index, benchmark, candidate_keys, model)
        rankings_by_model[model] = rankings
        model_reports[model] = evaluate_macro_rankings(
            relevant_by_user=targets,
            rankings_by_user=rankings,
            eligible_candidate_count=len(candidate_keys),
        )

    cold = _cold_item_metrics(
        benchmark=benchmark,
        candidates=candidate_keys,
        rankings=rankings_by_model["tfidf_user_profile"],
        eligible_targets=targets,
    )
    result: dict[str, object] = {
        "eligible_candidate_count": len(candidate_keys),
        "eligible_warm_candidate_count": len(warm_candidates & candidate_keys),
        "cold_eligible_candidate_count": len(candidate_keys & benchmark.cold_item_keys),
        "evaluated_user_count": len(targets),
        "eligible_target_count": sum(len(items) for items in targets.values()),
        "cold_item_recall": cold,
        "metrics_by_model": model_reports,
    }
    return result, rankings_by_model


def _variant_items(
    products: Sequence[ContentItem], variant: str
) -> tuple[ContentItem, ...]:
    if variant == "normal":
        return tuple(products)
    if variant == "title_only":
        return tuple(
            replace(
                item,
                fields=tuple(field for field in item.fields if field[0] == "title"),
            )
            for item in products
        )
    if variant == "no_usable_text":
        return tuple(replace(item, fields=()) for item in products)
    raise ValueError(f"Unknown content diagnostic variant: {variant}.")


def _metadata_diagnostics(
    benchmark: SyntheticContentBenchmark,
    index: ContentIndex,
) -> dict[str, object]:
    product_by_key = benchmark.products_by_key
    vectorized = {
        item.item_key
        for item in benchmark.products
        if item.catalog_eligible and index.vectorizer.transform(item)
    }
    conflict_keys = {
        item.item_key for item in benchmark.products if not item.catalog_eligible
    }
    metadata_matched = {
        item.item_key
        for item in benchmark.products
        if item.normalization_schema == _NORMALIZATION_SCHEMA
    }
    malformed = {
        item.item_key
        for item in benchmark.products
        if any(status == "invalid" for _, status in item.field_statuses)
    }
    zero_vector = {
        item.item_key
        for item in benchmark.products
        if item.catalog_eligible
        and item.fields
        and not index.vectorizer.transform(item)
    }
    categories = Counter(
        dict(item.fields).get("category", "unavailable") for item in benchmark.products
    )
    return {
        "synthetic_product_count": len(benchmark.products),
        "metadata_source_record_count": benchmark.metadata_source_record_count,
        "duplicate_metadata_occurrences": benchmark.duplicate_metadata_occurrences,
        "conflicting_metadata_occurrences": benchmark.conflicting_metadata_occurrences,
        "metadata_matched_product_count": len(metadata_matched),
        "metadata_unmatched_product_count": len(product_by_key) - len(metadata_matched),
        "category_product_counts": dict(sorted(categories.items())),
        "feature_ready_product_count": len(vectorized),
        "conflict_excluded_product_count": len(conflict_keys),
        "zero_vector_product_count": len(zero_vector),
        "cold_zero_vector_product_count": len(zero_vector & benchmark.cold_item_keys),
        "warm_zero_vector_product_count": len(zero_vector & benchmark.warm_item_keys),
        "malformed_metadata_product_count": len(malformed),
        "missing_metadata_product_count": sum(
            item.normalization_schema is None for item in benchmark.products
        ),
        "eligible_cold_item_count": len(vectorized & benchmark.cold_item_keys),
        "ineligible_cold_conflict_count": len(conflict_keys & benchmark.cold_item_keys),
        "ineligible_cold_missing_or_zero_count": len(
            set(benchmark.cold_item_keys) - vectorized - conflict_keys
        ),
    }


def _history_diagnostics(benchmark: SyntheticContentBenchmark) -> dict[str, object]:
    event_counts: Counter[str] = Counter(
        event.user_key
        for event in benchmark.training_interactions
        if event.user_key in benchmark.evaluation_users and event.event_time_ms < 10_000
    )
    histogram = Counter(
        event_counts.get(user, 0) for user in benchmark.evaluation_users
    )
    return {
        "evaluation_user_count": len(benchmark.evaluation_users),
        "history_event_count_by_user_histogram": {
            str(count): histogram[count] for count in sorted(histogram)
        },
        "empty_history_user_count": histogram.get(0, 0),
        "training_interaction_count": len(benchmark.training_interactions),
        "evaluation_event_count": len(benchmark.evaluation_events),
        "training_rating_distribution": dict(
            sorted(
                Counter(
                    str(event.rating) for event in benchmark.training_interactions
                ).items()
            )
        ),
        "evaluation_rating_distribution": dict(
            sorted(
                Counter(
                    str(event.rating) for event in benchmark.evaluation_events
                ).items()
            )
        ),
    }


def run_content_benchmark(
    benchmark: SyntheticContentBenchmark,
    *,
    code_revision: str,
    working_tree_dirty: bool = False,
) -> ContentBenchmarkRun:
    """Fit and evaluate fixed synthetic protocols; return aggregates only."""
    if not isinstance(code_revision, str) or not code_revision.strip():
        raise ValueError("A source code revision is required for reproducibility.")
    if not isinstance(working_tree_dirty, bool):
        raise ValueError("Working-tree dirty state must be a boolean.")

    items_by_key = benchmark.products_by_key
    reference_products = tuple(
        items_by_key[item_key] for item_key in sorted(benchmark.reference_item_keys)
    )
    config = ContentConfig()
    index = ContentIndex.fit(
        reference_products,
        benchmark.products,
        code_revision=code_revision,
        config=config,
    )
    all_content_candidates = frozenset(index.candidate_keys)
    warm_candidates = frozenset(all_content_candidates & benchmark.warm_item_keys)
    policy_candidates = {
        CandidatePolicy.WARM_ONLY.value: warm_candidates,
        CandidatePolicy.CONTENT_ELIGIBLE.value: all_content_candidates,
    }
    models = (
        "tfidf_user_profile",
        "item_content_nearest_neighbor",
        "popularity",
        "deterministic_random",
    )
    policy_results: dict[str, object] = {}
    rankings_by_policy: dict[str, dict[str, dict[str, tuple[str, ...]]]] = {}
    for policy_name, candidates in policy_candidates.items():
        report, rankings = _policy_report(
            benchmark=benchmark,
            index=index,
            candidate_keys=candidates,
            warm_candidates=warm_candidates,
            models=models,
        )
        policy_results[policy_name] = report
        rankings_by_policy[policy_name] = rankings

    ablations: dict[str, object] = {}
    title_items = _variant_items(benchmark.products, "title_only")
    title_by_key = {item.item_key: item for item in title_items}
    title_index = ContentIndex.fit(
        tuple(title_by_key[key] for key in sorted(benchmark.reference_item_keys)),
        title_items,
        code_revision=code_revision,
        config=config,
    )
    title_results: dict[str, object] = {}
    for policy_name, candidates in policy_candidates.items():
        targets = _profile_targets(benchmark, candidates)
        title_rankings = _ranked_by_policy(
            title_index, benchmark, candidates, "tfidf_user_profile"
        )
        title_results[policy_name] = evaluate_macro_rankings(
            relevant_by_user=targets,
            rankings_by_user=title_rankings,
            eligible_candidate_count=len(candidates),
        )
    ablations["title_only"] = {
        "description": (
            "Only canonical title text is used; candidate policies and "
            "evaluation users stay fixed."
        ),
        "vocabulary_sha256": title_index.vocabulary_sha256,
        "metrics_by_policy": title_results,
    }

    no_text_items = _variant_items(benchmark.products, "no_usable_text")
    no_text_by_key = {item.item_key: item for item in no_text_items}
    try:
        ContentIndex.fit(
            tuple(no_text_by_key[key] for key in sorted(benchmark.reference_item_keys)),
            no_text_items,
            code_revision=code_revision,
            config=config,
        )
    except ValueError as error:
        if "no usable content documents" not in str(error):
            raise
        no_text_metrics: dict[str, object] = {}
        for policy_name, candidates in policy_candidates.items():
            targets = _profile_targets(benchmark, candidates)
            no_text_metrics[policy_name] = evaluate_macro_rankings(
                relevant_by_user=targets,
                rankings_by_user={user: () for user in targets},
                eligible_candidate_count=len(candidates),
            )
        ablations["no_usable_text"] = {
            "status": "no_usable_reference_content",
            "recommendation_count": 0,
            "metrics_by_policy": no_text_metrics,
        }
    else:
        raise AssertionError("The no-text ablation unexpectedly fitted a vectorizer.")

    empty_rankings_by_policy: dict[str, object] = {}
    for policy_name, candidates in policy_candidates.items():
        targets = _profile_targets(benchmark, candidates)
        empty_rankings_by_policy[policy_name] = evaluate_macro_rankings(
            relevant_by_user=targets,
            rankings_by_user={user: () for user in targets},
            eligible_candidate_count=len(candidates),
        )
    ablations["empty_history"] = {
        "description": (
            "All users use an empty training history; candidate and target "
            "cohorts are unchanged."
        ),
        "metrics_by_policy": empty_rankings_by_policy,
    }

    base_vocabulary = index.vocabulary_sha256
    cold_products = tuple(items_by_key[key] for key in sorted(benchmark.cold_item_keys))
    transformed_cold = {
        item.item_key: index.vectorizer.transform(item) for item in cold_products
    }
    unseen_count = sum(
        bool(items_by_key[item_key].fields) and not vector
        for item_key, vector in transformed_cold.items()
    )
    ablations["unseen_vocabulary_cold"] = {
        "description": (
            "Transform cold candidate text with the frozen reference vocabulary."
        ),
        "vocabulary_sha256_before": base_vocabulary,
        "vocabulary_sha256_after": index.vocabulary_sha256,
        "vocabulary_unchanged": base_vocabulary == index.vocabulary_sha256,
        "unseen_vocabulary_cold_item_count": unseen_count,
        "cold_item_count": len(cold_products),
    }

    metadata = _metadata_diagnostics(benchmark, index)
    profile_zero_count = sum(
        not index.profile_from_training_history(
            benchmark.training_interactions,
            user_key=user,
            prediction_time_ms=10_000,
        ).vector
        for user in benchmark.evaluation_users
    )
    standard_rankings = rankings_by_policy[CandidatePolicy.CONTENT_ELIGIBLE.value][
        "tfidf_user_profile"
    ]
    cold_targets = {
        event.user_key: event.item_key
        for event in benchmark.evaluation_events
        if event.item_key in benchmark.cold_item_keys
        and event.item_key in all_content_candidates
    }
    retrieved_cold_positive_count = sum(
        item in standard_rankings.get(user, ())[:20]
        for user, item in cold_targets.items()
    )
    ineligible_zero_cold_positive_count = sum(
        event.item_key in benchmark.cold_item_keys
        and event.item_key not in all_content_candidates
        and event.item_key
        not in {
            key
            for key in benchmark.cold_item_keys
            if not items_by_key[key].catalog_eligible
        }
        for event in benchmark.evaluation_events
        if event.rating >= POSITIVE_MIN_RATING
    )
    ineligible_missing_cold_positive_count = sum(
        event.item_key == "synthetic_cold_missing_metadata"
        and event.rating >= POSITIVE_MIN_RATING
        for event in benchmark.evaluation_events
    )
    ineligible_conflict_cold_positive_count = sum(
        event.item_key == "synthetic_cold_conflicted_metadata"
        and event.rating >= POSITIVE_MIN_RATING
        for event in benchmark.evaluation_events
    )
    ineligible_unseen_vocab_cold_positive_count = sum(
        event.item_key in benchmark.cold_item_keys
        and event.item_key not in all_content_candidates
        and bool(items_by_key[event.item_key].fields)
        and items_by_key[event.item_key].catalog_eligible
        and event.rating >= POSITIVE_MIN_RATING
        for event in benchmark.evaluation_events
    )
    policy_warm_positive_count = sum(
        event.rating >= POSITIVE_MIN_RATING
        and event.item_key in benchmark.warm_item_keys
        for event in benchmark.evaluation_events
    )
    policy_cold_positive_count = sum(
        event.rating >= POSITIVE_MIN_RATING
        and event.item_key in benchmark.cold_item_keys
        for event in benchmark.evaluation_events
    )
    partition_policy = benchmark.manifest.get("partition_policy")
    if not isinstance(partition_policy, Mapping):
        raise ValueError("Synthetic benchmark partition policy is missing.")

    aggregate: dict[str, object] = {
        "schema_version": BENCHMARK_SCHEMA,
        "benchmark_version": BENCHMARK_VERSION,
        "generator_schema": benchmark.generator_schema,
        "generator_config": dict(benchmark.generator_config),
        "source_checksums": dict(benchmark.source_checksums),
        "code_revision": code_revision,
        "working_tree_dirty": working_tree_dirty,
        "partition_sizes": {
            "reference_catalog_items": len(benchmark.reference_item_keys),
            "warm_catalog_items": len(benchmark.warm_item_keys),
            "cold_catalog_items": len(benchmark.cold_item_keys),
            "synthetic_products": len(benchmark.products),
            "evaluation_users": len(benchmark.evaluation_users),
            "training_interactions": len(benchmark.training_interactions),
            "evaluation_events": len(benchmark.evaluation_events),
        },
        "partition_policy": dict(partition_policy),
        "history_diagnostics": _history_diagnostics(benchmark),
        "evaluation_targets": {
            "positive_rating_threshold": str(POSITIVE_MIN_RATING),
            "warm_positive_event_count": policy_warm_positive_count,
            "cold_positive_event_count": policy_cold_positive_count,
            "evaluation_timestamp_ms": 10_000,
            "all_evaluation_users_retained_even_with_empty_history": True,
        },
        "tfidf": {
            "feature_schema": CONTENT_FEATURE_SCHEMA,
            "tokenizer_schema": _TOKENIZER_SCHEMA,
            "configuration": {
                "max_vocabulary_size": config.max_vocabulary_size,
                "max_distinct_terms": config.max_distinct_terms,
                "max_characters_per_field": config.max_characters_per_field,
                "max_tokens_per_document": config.max_tokens_per_document,
            },
            "reference_item_count": len(reference_products),
            "fitted_document_count": index.vectorizer.document_count,
            "vocabulary_size": len(index.vectorizer.vocabulary),
            "vocabulary_sha256": index.vocabulary_sha256,
            "cold_items_refit_vocabulary": False,
            "unseen_vocabulary_cold_item_count": unseen_count,
            "index_artifact_sha256": _sha256(index.to_artifact_bytes()),
            "artifact_schema": "recfusion.content-tfidf-index.v1",
        },
        "candidate_policy_definitions": {
            CandidatePolicy.WARM_ONLY.value: (
                "Train-known warm products with a nonzero fitted-vocabulary "
                "vector; remove each user's prior train-seen products."
            ),
            CandidatePolicy.CONTENT_ELIGIBLE.value: (
                "Eligible warm products plus eligible cold products with a "
                "nonzero vector under the frozen reference vocabulary; "
                "remove each user's prior train-seen products."
            ),
        },
        "candidate_policies": policy_results,
        "model_controls": {
            "tfidf_user_profile": (
                "Equal-weight mean of unique positive training-item vectors, "
                "normalized; held-out and future interactions are absent."
            ),
            "item_content_nearest_neighbor": (
                "Most recent prior positive train item as query; same policy "
                "candidate pool and seen-item filter."
            ),
            "popularity": (
                "Unique positive train user/item pairs counted, descending "
                "count then item key; not a Phase 3 implementation claim."
            ),
            "deterministic_random": (
                "Per-user SHA-256 ordering over fixed seed, synthetic user "
                "key, and candidate key."
            ),
        },
        "metric_definitions": {
            "relevance": (
                "Synthetic rating >= 4, deduplicated by user/item for target sets."
            ),
            "recall": (
                "Macro user mean of relevant items in top K divided by that "
                "user's eligible target count."
            ),
            "ndcg": (
                "Macro binary-gain NDCG; gain 1; discount 1/log2(rank+1); "
                "IDCG uses min(K, eligible targets)."
            ),
            "hit_rate": "Macro user mean of any eligible target in top K.",
            "mrr": (
                "Macro user mean reciprocal rank of first eligible target; "
                "zero when absent."
            ),
            "catalog_coverage": (
                "Unique products returned at K divided by the frozen policy "
                "eligible-candidate count before user-specific seen filtering."
            ),
            "short_list": (
                "All evaluated users receiving fewer than K candidates; "
                "zero-prediction users remain in metric denominators."
            ),
        },
        "metadata_diagnostics": metadata,
        "zero_vector_query_profile_count": profile_zero_count,
        "examples": {
            "retrieved_eligible_cold_positive_count": retrieved_cold_positive_count,
            "unretrievable_zero_content_cold_positive_count": (
                ineligible_zero_cold_positive_count
            ),
            "unretrievable_missing_metadata_cold_positive_count": (
                ineligible_missing_cold_positive_count
            ),
            "unretrievable_unseen_vocabulary_cold_positive_count": (
                ineligible_unseen_vocab_cold_positive_count
            ),
            "ineligible_conflicted_cold_positive_count": (
                ineligible_conflict_cold_positive_count
            ),
            "missing_or_conflicted_cold_positives_are_excluded_from_candidates": True,
        },
        "ablations": ablations,
        "reproducibility": {
            "aggregate_only": True,
            "source_rows_persisted": False,
            "per_user_rankings_persisted": False,
            "seed_controls_interest_assignment_and_random_control": True,
            "checksummed_manifest_excludes_runtime_and_absolute_paths": True,
        },
        "phase_boundary": (
            "Phase 4.2C remains ON HOLD; this benchmark uses invented data only."
        ),
    }
    manifest_bytes = _canonical_bytes(aggregate) + b"\n"
    return ContentBenchmarkRun(
        aggregate=aggregate,
        manifest_bytes=manifest_bytes,
        manifest_sha256=_sha256(manifest_bytes),
    )
