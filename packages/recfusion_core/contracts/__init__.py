"""Typed contracts shared across RecFusion packages."""

from recfusion_core.contracts.data import (
    DataSplit,
    Interaction,
    JSONValue,
    Money,
    ProductMetadata,
)
from recfusion_core.contracts.recommendation import (
    HybridInferenceConfig,
    RankedCandidate,
    RecommendationArtifactRegistry,
    RecommendationInferenceSource,
    SyntheticCatalog,
    SyntheticProduct,
    SyntheticUserContext,
)

__all__ = [
    "DataSplit",
    "HybridInferenceConfig",
    "Interaction",
    "JSONValue",
    "Money",
    "ProductMetadata",
    "RankedCandidate",
    "RecommendationArtifactRegistry",
    "RecommendationInferenceSource",
    "SyntheticCatalog",
    "SyntheticProduct",
    "SyntheticUserContext",
]
