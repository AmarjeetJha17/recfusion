"""Bounded JSON artifact preparation and integrity validation."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, cast

from recfusion_core.contracts import SyntheticCatalog, SyntheticProduct
from recfusion_ml.retrieval.content import (
    CONTENT_FEATURE_SCHEMA,
    CONTENT_INDEX_ARTIFACT_SCHEMA,
    ContentConfig,
    ContentIndex,
    ContentItem,
)

SERVING_ARTIFACT_SCHEMA = "recfusion.offline-recommendation-artifact.v1"
SERVING_ARTIFACT_ID = "synthetic-electronics-content-v1"
CONTENT_ALGORITHM_ID = "tfidf_content"
HYBRID_ALGORITHM_ID = "weighted_rrf"
ALGORITHM_VERSIONS = {
    CONTENT_ALGORITHM_ID: "1",
    HYBRID_ALGORITHM_ID: "1",
}
CANDIDATE_POLICIES = frozenset(
    {"content_catalog", "warm_hybrid", "content_eligible_hybrid"}
)
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_ARTIFACT_CATALOG_ITEMS = 50_000
_CODE_REVISION = "recfusion-phase-6-1b-synthetic-artifact-v1"


class ArtifactValidationCode(StrEnum):
    MISSING = "artifact_missing"
    CHECKSUM_INVALID = "artifact_checksum_invalid"
    SCHEMA_INCOMPATIBLE = "artifact_schema_incompatible"
    CATALOG_MISMATCH = "catalog_mismatch"
    SIZE_LIMIT = "artifact_size_limit"


class ArtifactLoadError(ValueError):
    def __init__(self, code: ArtifactValidationCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PreparedRecommendationArtifact:
    artifact_id: str
    payload: bytes
    sha256: str
    catalog_id: str
    catalog_fingerprint: str
    bundle_fingerprint: str


@dataclass(frozen=True, slots=True)
class LoadedRecommendationArtifact:
    artifact_id: str
    catalog_id: str
    catalog_fingerprint: str
    bundle_fingerprint: str
    artifact_fingerprint: str
    supported_algorithms: Mapping[str, str]
    supported_candidate_policies: frozenset[str]
    content_index: ContentIndex


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _to_content_item(product: SyntheticProduct) -> ContentItem:
    fields = product.content_fields
    return ContentItem(
        item_key=product.item_key,
        fields=fields,
        source_record_fingerprint=product.source_record_fingerprint,
        catalog_eligible=product.catalog_eligible and product.visible,
    )


def prepare_synthetic_recommendation_artifact(
    catalog: SyntheticCatalog,
) -> PreparedRecommendationArtifact:
    """Fit once from synthetic warm references and package a JSON index."""
    products = catalog.list_products()
    if len(products) > MAX_ARTIFACT_CATALOG_ITEMS:
        raise ArtifactLoadError(
            ArtifactValidationCode.SIZE_LIMIT,
            "Synthetic catalog exceeds the inference artifact limit.",
        )
    items = tuple(_to_content_item(product) for product in products)
    by_key = {item.item_key: item for item in items}
    reference_keys = catalog.train_known_item_keys
    reference_items = tuple(
        by_key[key]
        for key in sorted(reference_keys)
        if key in by_key and by_key[key].catalog_eligible and by_key[key].fields
    )
    if not reference_items:
        raise ArtifactLoadError(
            ArtifactValidationCode.SCHEMA_INCOMPATIBLE,
            "Synthetic artifact has no eligible reference content.",
        )
    index = ContentIndex.fit(
        reference_items,
        items,
        code_revision=_CODE_REVISION,
        config=ContentConfig(),
    )
    index_payload = index.to_artifact_bytes()
    envelope: dict[str, object] = {
        "schema_version": SERVING_ARTIFACT_SCHEMA,
        "artifact_id": SERVING_ARTIFACT_ID,
        "catalog_id": catalog.catalog_id,
        "catalog_version": catalog.version,
        "catalog_fingerprint": catalog.catalog_fingerprint,
        "bundle_fingerprint": catalog.bundle_fingerprint,
        "generator_schema": catalog.generator_schema,
        "generator_seed": catalog.seed,
        "supported_algorithms": ALGORITHM_VERSIONS,
        "supported_candidate_policies": sorted(CANDIDATE_POLICIES),
        "content_feature_schema": CONTENT_FEATURE_SCHEMA,
        "content_index_schema": CONTENT_INDEX_ARTIFACT_SCHEMA,
        "vectorizer_configuration": index.vectorizer.config.__dict__
        if hasattr(index.vectorizer.config, "__dict__")
        else {
            field: getattr(index.vectorizer.config, field)
            for field in ContentConfig.__dataclass_fields__
        },
        "vocabulary_fingerprint": index.vocabulary_sha256,
        "content_index_sha256": _sha256(index_payload),
        "content_index_base64": base64.b64encode(index_payload).decode("ascii"),
    }
    payload = _canonical_json(envelope)
    if len(payload) > MAX_ARTIFACT_BYTES:
        raise ArtifactLoadError(
            ArtifactValidationCode.SIZE_LIMIT,
            "Synthetic inference artifact exceeds the configured byte limit.",
        )
    return PreparedRecommendationArtifact(
        artifact_id=SERVING_ARTIFACT_ID,
        payload=payload,
        sha256=_sha256(payload),
        catalog_id=catalog.catalog_id,
        catalog_fingerprint=catalog.catalog_fingerprint,
        bundle_fingerprint=catalog.bundle_fingerprint,
    )


def load_recommendation_artifact(
    payload: bytes | None,
    *,
    expected_sha256: str,
    expected_catalog_id: str,
    expected_catalog_fingerprint: str,
) -> LoadedRecommendationArtifact:
    """Load only the declared JSON/TF-IDF artifact; never load Python objects."""
    if payload is None:
        raise ArtifactLoadError(
            ArtifactValidationCode.MISSING,
            "The requested recommendation artifact is unavailable.",
        )
    if len(payload) > MAX_ARTIFACT_BYTES:
        raise ArtifactLoadError(
            ArtifactValidationCode.SIZE_LIMIT,
            "Recommendation artifact exceeds the configured byte limit.",
        )
    if not isinstance(expected_sha256, str) or _sha256(payload) != expected_sha256:
        raise ArtifactLoadError(
            ArtifactValidationCode.CHECKSUM_INVALID,
            "Recommendation artifact checksum validation failed.",
        )
    try:
        record: Any = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as error:
        raise ArtifactLoadError(
            ArtifactValidationCode.SCHEMA_INCOMPATIBLE,
            "Recommendation artifact is not valid JSON.",
        ) from error
    if not isinstance(record, dict):
        raise ArtifactLoadError(
            ArtifactValidationCode.SCHEMA_INCOMPATIBLE,
            "Recommendation artifact envelope is invalid.",
        )
    if (
        record.get("schema_version") != SERVING_ARTIFACT_SCHEMA
        or record.get("artifact_id") != SERVING_ARTIFACT_ID
        or record.get("content_feature_schema") != CONTENT_FEATURE_SCHEMA
        or record.get("content_index_schema") != CONTENT_INDEX_ARTIFACT_SCHEMA
        or record.get("supported_algorithms") != ALGORITHM_VERSIONS
        or record.get("supported_candidate_policies") != sorted(CANDIDATE_POLICIES)
        or record.get("vectorizer_configuration")
        != {
            field: getattr(ContentConfig(), field)
            for field in ContentConfig.__dataclass_fields__
        }
    ):
        raise ArtifactLoadError(
            ArtifactValidationCode.SCHEMA_INCOMPATIBLE,
            "Recommendation artifact schema or algorithm configuration "
            "is incompatible.",
        )
    if (
        record.get("catalog_id") != expected_catalog_id
        or record.get("catalog_fingerprint") != expected_catalog_fingerprint
    ):
        raise ArtifactLoadError(
            ArtifactValidationCode.CATALOG_MISMATCH,
            "Recommendation artifact does not match the active synthetic catalog.",
        )
    encoded_index = record.get("content_index_base64")
    index_digest = record.get("content_index_sha256")
    vocabulary_digest = record.get("vocabulary_fingerprint")
    if not isinstance(encoded_index, str):
        raise ArtifactLoadError(
            ArtifactValidationCode.SCHEMA_INCOMPATIBLE,
            "Recommendation artifact index payload is invalid.",
        )
    try:
        index_payload = base64.b64decode(encoded_index, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ArtifactLoadError(
            ArtifactValidationCode.SCHEMA_INCOMPATIBLE,
            "Recommendation artifact index encoding is invalid.",
        ) from error
    if not isinstance(index_digest, str) or _sha256(index_payload) != index_digest:
        raise ArtifactLoadError(
            ArtifactValidationCode.CHECKSUM_INVALID,
            "Recommendation content index checksum validation failed.",
        )
    try:
        content_index = ContentIndex.from_artifact_bytes(index_payload)
    except (TypeError, ValueError) as error:
        raise ArtifactLoadError(
            ArtifactValidationCode.SCHEMA_INCOMPATIBLE,
            "Recommendation content index failed schema validation.",
        ) from error
    if (
        content_index.vocabulary_sha256 != vocabulary_digest
        or content_index.vectorizer.config != ContentConfig()
        or content_index.total_candidate_count > MAX_ARTIFACT_CATALOG_ITEMS
        or len(content_index.candidate_keys) > MAX_ARTIFACT_CATALOG_ITEMS
    ):
        raise ArtifactLoadError(
            ArtifactValidationCode.SCHEMA_INCOMPATIBLE,
            "Recommendation content index configuration is incompatible.",
        )
    catalog_id = record.get("catalog_id")
    catalog_fingerprint = record.get("catalog_fingerprint")
    bundle_fingerprint = record.get("bundle_fingerprint")
    if not all(
        isinstance(value, str) and value
        for value in (catalog_id, catalog_fingerprint, bundle_fingerprint)
    ):
        raise ArtifactLoadError(
            ArtifactValidationCode.SCHEMA_INCOMPATIBLE,
            "Recommendation artifact provenance is incomplete.",
        )
    catalog_id = cast(str, catalog_id)
    catalog_fingerprint = cast(str, catalog_fingerprint)
    bundle_fingerprint = cast(str, bundle_fingerprint)
    return LoadedRecommendationArtifact(
        artifact_id=SERVING_ARTIFACT_ID,
        catalog_id=catalog_id,
        catalog_fingerprint=catalog_fingerprint,
        bundle_fingerprint=bundle_fingerprint,
        artifact_fingerprint=expected_sha256,
        supported_algorithms=MappingProxyType(dict(ALGORITHM_VERSIONS)),
        supported_candidate_policies=CANDIDATE_POLICIES,
        content_index=content_index,
    )
