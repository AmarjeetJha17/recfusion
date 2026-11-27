from __future__ import annotations

import hashlib
import json

import pytest

from recfusion_api.services.synthetic_catalog import build_synthetic_catalog
from recfusion_ml.inference.artifacts import (
    ArtifactLoadError,
    ArtifactValidationCode,
    load_recommendation_artifact,
    prepare_synthetic_recommendation_artifact,
)


def _artifact():
    catalog = build_synthetic_catalog()
    return catalog, prepare_synthetic_recommendation_artifact(catalog)


def test_synthetic_artifact_preparation_and_loading_are_versioned() -> None:
    catalog, prepared = _artifact()
    loaded = load_recommendation_artifact(
        prepared.payload,
        expected_sha256=prepared.sha256,
        expected_catalog_id=catalog.catalog_id,
        expected_catalog_fingerprint=catalog.catalog_fingerprint,
    )

    assert loaded.artifact_id == prepared.artifact_id
    assert loaded.catalog_fingerprint == catalog.catalog_fingerprint
    assert loaded.artifact_fingerprint == prepared.sha256
    assert loaded.content_index.vocabulary_sha256
    assert len(loaded.content_index.candidate_keys) == 7


def test_missing_and_corrupted_artifacts_fail_closed() -> None:
    with pytest.raises(ArtifactLoadError) as missing:
        load_recommendation_artifact(
            None,
            expected_sha256="0" * 64,
            expected_catalog_id="synthetic-electronics-v1",
            expected_catalog_fingerprint="0" * 64,
        )
    assert missing.value.code is ArtifactValidationCode.MISSING

    catalog, prepared = _artifact()
    with pytest.raises(ArtifactLoadError) as corrupted:
        load_recommendation_artifact(
            prepared.payload + b" ",
            expected_sha256=prepared.sha256,
            expected_catalog_id=catalog.catalog_id,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
    assert corrupted.value.code is ArtifactValidationCode.CHECKSUM_INVALID


def test_schema_catalog_and_algorithm_compatibility_are_checked() -> None:
    catalog, prepared = _artifact()
    envelope = json.loads(prepared.payload)
    envelope["schema_version"] = "recfusion.offline-recommendation-artifact.v99"
    payload = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()

    with pytest.raises(ArtifactLoadError) as schema_error:
        load_recommendation_artifact(
            payload,
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_catalog_id=catalog.catalog_id,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
    assert schema_error.value.code is ArtifactValidationCode.SCHEMA_INCOMPATIBLE

    with pytest.raises(ArtifactLoadError) as catalog_error:
        load_recommendation_artifact(
            prepared.payload,
            expected_sha256=prepared.sha256,
            expected_catalog_id=catalog.catalog_id,
            expected_catalog_fingerprint="0" * 64,
        )
    assert catalog_error.value.code is ArtifactValidationCode.CATALOG_MISMATCH

    envelope = json.loads(prepared.payload)
    envelope["supported_algorithms"]["tfidf_content"] = "99"
    payload = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ArtifactLoadError) as algorithm_error:
        load_recommendation_artifact(
            payload,
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_catalog_id=catalog.catalog_id,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
    assert algorithm_error.value.code is ArtifactValidationCode.SCHEMA_INCOMPATIBLE
