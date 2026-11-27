from __future__ import annotations

import json
from pathlib import Path

from recfusion_api.schemas.recommendation import RecommendationRequest
from recfusion_api.services.recommendation import (
    InMemoryRecommendationArtifactRegistry,
    RecommendationService,
)
from recfusion_api.services.synthetic_catalog import build_synthetic_catalog
from recfusion_ml.inference.artifacts import (
    load_recommendation_artifact,
    prepare_synthetic_recommendation_artifact,
)
from recfusion_ml.inference.recommendation import SyntheticRecommendationSource

BASELINE = json.loads(
    Path(__file__)
    .parents[1]
    .joinpath("fixtures", "phase_7_1b_v1_baseline.json")
    .read_text(encoding="utf-8")
)


def _service() -> RecommendationService:
    catalog = build_synthetic_catalog()
    artifact = prepare_synthetic_recommendation_artifact(catalog)
    loaded = load_recommendation_artifact(
        artifact.payload,
        expected_sha256=artifact.sha256,
        expected_catalog_id=catalog.catalog_id,
        expected_catalog_fingerprint=catalog.catalog_fingerprint,
        expected_compatibility_fingerprint=catalog.compatibility_fingerprint,
        expected_bundle_fingerprint=catalog.bundle_fingerprint,
    )
    return RecommendationService(
        catalog=catalog,
        artifacts=InMemoryRecommendationArtifactRegistry(
            (SyntheticRecommendationSource(loaded),)
        ),
    )


def _request(
    mode: str, policy: str, candidate_policy: str, query: dict[str, str]
) -> RecommendationRequest:
    algorithm = "weighted_rrf" if mode == "hybrid" else "tfidf_content"
    return RecommendationRequest.model_validate(
        {
            "schema_version": "recfusion.recommendation-request.v1",
            "mode": mode,
            "catalog_id": BASELINE["catalog_id"],
            "algorithm_id": algorithm,
            "algorithm_version": "1",
            "policy_id": policy,
            "candidate_policy": candidate_policy,
            "k": 5,
            "query": query,
            "excluded_product_ids": [],
            "constraints": {},
        }
    )


def test_phase_7_1b_baseline_recommendation_order_is_captured() -> None:
    service = _service()
    cases = {
        "product_to_product:000001": _request(
            "product_to_product",
            "content-similarity-v1",
            "content_catalog",
            {
                "kind": "product_to_product",
                "product_id": f"{BASELINE['catalog_id']}:item:000001",
            },
        ),
        "synthetic_user:000001": _request(
            "synthetic_user",
            "synthetic-user-content-v1",
            "content_catalog",
            {
                "kind": "synthetic_user",
                "user_id": f"{BASELINE['catalog_id']}:user:000001",
            },
        ),
        "hybrid_warm:000001": _request(
            "hybrid",
            "synthetic-hybrid-warm-v1",
            "warm_hybrid",
            {"kind": "hybrid", "user_id": f"{BASELINE['catalog_id']}:user:000001"},
        ),
        "hybrid_content:000001": _request(
            "hybrid",
            "synthetic-hybrid-content-v1",
            "content_eligible_hybrid",
            {"kind": "hybrid", "user_id": f"{BASELINE['catalog_id']}:user:000001"},
        ),
        "synthetic_user:000003": _request(
            "synthetic_user",
            "synthetic-user-content-v1",
            "content_catalog",
            {
                "kind": "synthetic_user",
                "user_id": f"{BASELINE['catalog_id']}:user:000003",
            },
        ),
    }

    for case, request in cases.items():
        result = service.recommend(request)
        suffixes = [row.product_id.rsplit(":", 1)[-1] for row in result.recommendations]
        assert suffixes == BASELINE["recommendation_ids"][case]
