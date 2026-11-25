"""Source-independent normalizers for canonical product data."""

from recfusion_data.normalization.products import (
    NormalizationStatus,
    NormalizedField,
    NormalizedProductMetadata,
    normalize_product_metadata,
)

__all__ = [
    "NormalizationStatus",
    "NormalizedField",
    "NormalizedProductMetadata",
    "normalize_product_metadata",
]
