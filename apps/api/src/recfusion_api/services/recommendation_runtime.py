"""Construction of the explicitly enabled synthetic recommendation runtime."""

from typing import cast

from recfusion_api.services.recommendation import (
    InMemoryRecommendationArtifactRegistry,
    RecommendationService,
)
from recfusion_api.services.synthetic_catalog import build_synthetic_catalog
from recfusion_core.contracts import RecommendationInferenceSource, SyntheticCatalog
from recfusion_ml.inference.artifacts import (
    load_recommendation_artifact,
    prepare_synthetic_recommendation_artifact,
)
from recfusion_ml.inference.recommendation import SyntheticRecommendationSource


def build_synthetic_recommendation_service() -> RecommendationService:
    """Build and validate the deterministic synthetic service once per app."""
    catalog = build_synthetic_catalog()
    catalog_contract = cast(SyntheticCatalog, catalog)
    prepared = prepare_synthetic_recommendation_artifact(catalog_contract)
    loaded = load_recommendation_artifact(
        prepared.payload,
        expected_sha256=prepared.sha256,
        expected_catalog_id=catalog.catalog_id,
        expected_catalog_fingerprint=catalog.catalog_fingerprint,
        expected_compatibility_fingerprint=catalog.compatibility_fingerprint,
        expected_bundle_fingerprint=catalog.bundle_fingerprint,
    )
    source = cast(RecommendationInferenceSource, SyntheticRecommendationSource(loaded))
    return RecommendationService(
        catalog=catalog_contract,
        artifacts=InMemoryRecommendationArtifactRegistry((source,)),
    )
