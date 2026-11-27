"""Offline application-layer recommendation orchestration; no HTTP handlers."""

from __future__ import annotations

import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from recfusion_api.schemas.recommendation import (
    ProductToProductQuery,
    RecommendationDiagnostics,
    RecommendationError,
    RecommendationErrorCode,
    RecommendationErrorResponse,
    RecommendationItem,
    RecommendationMode,
    RecommendationRequest,
    RecommendationResponse,
    RecommendationStatus,
    UserRecommendationQuery,
)
from recfusion_core.contracts import (
    HybridInferenceConfig,
    RankedCandidate,
    RecommendationArtifactRegistry,
    RecommendationInferenceSource,
    SyntheticCatalog,
    SyntheticProduct,
    SyntheticUserContext,
)

_ARTIFACT_ID = "synthetic-electronics-content-v1"
_CONTENT_ALGORITHM = "tfidf_content"
_HYBRID_ALGORITHM = "weighted_rrf"
_CONTENT_POLICY = "content_catalog"
_CONTENT_SOURCE = "tfidf_content"
_COLLABORATIVE_SOURCES = frozenset({"synthetic_item_cf", "synthetic_bpr_control"})
_ALLOWED_SOURCES = _COLLABORATIVE_SOURCES | {_CONTENT_SOURCE}
_ALLOWED_REASONS = {"content_similarity", "hybrid_rrf"}


class RecommendationServiceError(Exception):
    """A typed failure containing only a safe public message."""

    def __init__(self, code: RecommendationErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_response(self, request_id: str | None = None) -> RecommendationErrorResponse:
        return RecommendationErrorResponse(
            request_id=request_id or secrets.token_hex(12),
            error=RecommendationError(code=self.code, message=self.message),
        )


@dataclass(frozen=True, slots=True)
class _Policy:
    policy_id: str
    mode: RecommendationMode
    algorithm_id: str
    algorithm_version: str
    candidate_policy: str
    artifact_id: str = _ARTIFACT_ID
    hybrid_config: HybridInferenceConfig | None = None


def _hybrid_config() -> HybridInferenceConfig:
    return HybridInferenceConfig(
        rank_constant=60,
        source_weights={
            "synthetic_item_cf": 1.0,
            "synthetic_bpr_control": 1.0,
            _CONTENT_SOURCE: 1.0,
        },
        source_depths={
            "synthetic_item_cf": 20,
            "synthetic_bpr_control": 20,
            _CONTENT_SOURCE: 20,
        },
    )


_HYBRID_CONFIG = _hybrid_config()
_POLICIES: Mapping[str, _Policy] = MappingProxyType(
    {
        "content-similarity-v1": _Policy(
            "content-similarity-v1",
            RecommendationMode.PRODUCT_TO_PRODUCT,
            _CONTENT_ALGORITHM,
            "1",
            _CONTENT_POLICY,
        ),
        "synthetic-user-content-v1": _Policy(
            "synthetic-user-content-v1",
            RecommendationMode.SYNTHETIC_USER,
            _CONTENT_ALGORITHM,
            "1",
            _CONTENT_POLICY,
        ),
        "synthetic-hybrid-warm-v1": _Policy(
            "synthetic-hybrid-warm-v1",
            RecommendationMode.HYBRID,
            _HYBRID_ALGORITHM,
            "1",
            "warm_hybrid",
            hybrid_config=_HYBRID_CONFIG,
        ),
        "synthetic-hybrid-content-v1": _Policy(
            "synthetic-hybrid-content-v1",
            RecommendationMode.HYBRID,
            _HYBRID_ALGORITHM,
            "1",
            "content_eligible_hybrid",
            hybrid_config=_HYBRID_CONFIG,
        ),
    }
)


class InMemoryRecommendationArtifactRegistry:
    """Read-only allowlist of already validated artifacts; accepts no paths."""

    def __init__(self, sources: Iterable[RecommendationInferenceSource]) -> None:
        source_map: dict[str, RecommendationInferenceSource] = {}
        for source in sources:
            if source.artifact_id in source_map:
                raise ValueError("Duplicate recommendation artifact ID.")
            source_map[source.artifact_id] = source
        self._sources = MappingProxyType(source_map)

    def get(self, artifact_id: str) -> RecommendationInferenceSource | None:
        return self._sources.get(artifact_id)


class RecommendationService:
    """Validate policy/artifact compatibility and return safe ranked IDs."""

    def __init__(
        self,
        *,
        catalog: SyntheticCatalog,
        artifacts: RecommendationArtifactRegistry,
    ) -> None:
        self._catalog = catalog
        self._artifacts = artifacts

    def _resolve(
        self, request: RecommendationRequest
    ) -> tuple[_Policy, RecommendationInferenceSource]:
        policy = _POLICIES.get(request.policy_id)
        if policy is None:
            raise RecommendationServiceError(
                RecommendationErrorCode.UNSUPPORTED_ALGORITHM,
                "The requested recommendation algorithm is unsupported.",
            )
        if (
            request.mode is not policy.mode
            or request.algorithm_id != policy.algorithm_id
        ):
            raise RecommendationServiceError(
                RecommendationErrorCode.UNSUPPORTED_ALGORITHM,
                "The requested algorithm is not available for this mode.",
            )
        if request.algorithm_version != policy.algorithm_version:
            raise RecommendationServiceError(
                RecommendationErrorCode.UNSUPPORTED_ALGORITHM,
                "The requested algorithm version is unsupported.",
            )
        if request.candidate_policy != policy.candidate_policy:
            raise RecommendationServiceError(
                RecommendationErrorCode.UNSUPPORTED_CANDIDATE_POLICY,
                "The requested candidate policy is unsupported for this algorithm.",
            )
        source = self._artifacts.get(policy.artifact_id)
        if source is None:
            raise RecommendationServiceError(
                RecommendationErrorCode.ARTIFACT_MISSING,
                "The requested recommendation artifact is unavailable.",
            )
        if (
            source.catalog_id != self._catalog.catalog_id
            or source.catalog_fingerprint != self._catalog.catalog_fingerprint
        ):
            raise RecommendationServiceError(
                RecommendationErrorCode.CATALOG_MISMATCH,
                "The recommendation artifact does not match the active catalog.",
            )
        if (
            source.supported_algorithms.get(policy.algorithm_id)
            != policy.algorithm_version
        ):
            raise RecommendationServiceError(
                RecommendationErrorCode.UNSUPPORTED_ALGORITHM,
                "The requested algorithm is not supported by the loaded artifact.",
            )
        if request.candidate_policy not in source.supported_candidate_policies:
            raise RecommendationServiceError(
                RecommendationErrorCode.UNSUPPORTED_CANDIDATE_POLICY,
                "The loaded artifact does not support this candidate policy.",
            )
        return policy, source

    def recommend(self, request: RecommendationRequest) -> RecommendationResponse:
        try:
            return self._recommend(request)
        except RecommendationServiceError:
            raise
        except Exception as error:
            raise RecommendationServiceError(
                RecommendationErrorCode.EXECUTION_FAILED,
                "The recommendation request could not be completed.",
            ) from error

    def _recommend(self, request: RecommendationRequest) -> RecommendationResponse:
        policy, source = self._resolve(request)
        context: SyntheticUserContext | None = None
        target_item_key: str | None = None
        requested_exclusions = set(request.excluded_product_ids)

        if request.mode is RecommendationMode.PRODUCT_TO_PRODUCT:
            if not isinstance(request.query, ProductToProductQuery):
                raise RecommendationServiceError(
                    RecommendationErrorCode.INVALID_REQUEST,
                    "The request query does not match its recommendation mode.",
                )
            product = self._catalog.get_product(request.query.product_id)
            if product is None:
                raise RecommendationServiceError(
                    RecommendationErrorCode.UNKNOWN_SYNTHETIC_PRODUCT,
                    "The requested synthetic product is unknown.",
                )
            self._require_query_product(product)
            requested_exclusions.add(product.item_key)
            method = getattr(source, "recommend_product_to_product", None)
            if not callable(method):
                raise RecommendationServiceError(
                    RecommendationErrorCode.MISSING_CONTENT_SOURCE,
                    "The requested content source is unavailable.",
                )
            candidate_pool = frozenset(
                row.item_key
                for row in self._catalog.list_products()
                if row.visible and row.catalog_eligible
            )
            raw_candidates = method(
                product,
                eligible_item_keys=candidate_pool,
                excluded_item_keys=frozenset(requested_exclusions),
                k=request.k,
            )
        elif request.mode in {
            RecommendationMode.SYNTHETIC_USER,
            RecommendationMode.HYBRID,
        }:
            query = request.query
            if not isinstance(query, UserRecommendationQuery):
                raise RecommendationServiceError(
                    RecommendationErrorCode.INVALID_REQUEST,
                    "The request query does not match its recommendation mode.",
                )
            try:
                context = self._catalog.get_user_context(query.user_id)
            except KeyError as error:
                raise RecommendationServiceError(
                    RecommendationErrorCode.UNKNOWN_SYNTHETIC_USER,
                    "The requested synthetic user is unknown.",
                ) from error
            if query.target_product_id is not None:
                target = self._catalog.get_product(query.target_product_id)
                if target is None:
                    raise RecommendationServiceError(
                        RecommendationErrorCode.UNKNOWN_SYNTHETIC_PRODUCT,
                        "The requested synthetic product is unknown.",
                    )
                self._require_query_product(target)
                target_item_key = target.item_key
                requested_exclusions.add(target.item_key)
            prior_events = tuple(
                event
                for event in context.training_history
                if event.event_time_ms < context.prediction_time_ms
            )
            seen_items = frozenset(event.item_key for event in prior_events)
            requested_exclusions.update(seen_items)
            if request.mode is RecommendationMode.SYNTHETIC_USER:
                method = getattr(source, "recommend_synthetic_user", None)
                if not callable(method):
                    raise RecommendationServiceError(
                        RecommendationErrorCode.MISSING_CONTENT_SOURCE,
                        "The requested content source is unavailable.",
                    )
                raw_candidates = method(
                    context,
                    target_item_key=target_item_key,
                    excluded_item_keys=frozenset(requested_exclusions),
                    k=request.k,
                )
            else:
                method = getattr(source, "recommend_hybrid", None)
                if not callable(method):
                    raise RecommendationServiceError(
                        RecommendationErrorCode.MISSING_COLLABORATIVE_SOURCE,
                        "The requested hybrid sources are unavailable.",
                    )
                assert policy.hybrid_config is not None
                try:
                    rankings = self._catalog.get_collaborative_rankings(
                        context.user_key
                    )
                except KeyError as error:
                    raise RecommendationServiceError(
                        RecommendationErrorCode.MISSING_COLLABORATIVE_SOURCE,
                        "A required synthetic collaborative source is unavailable.",
                    ) from error
                required_sources = set(policy.hybrid_config.source_weights) - {
                    _CONTENT_SOURCE
                }
                if not required_sources <= set(rankings):
                    raise RecommendationServiceError(
                        RecommendationErrorCode.MISSING_COLLABORATIVE_SOURCE,
                        "A required synthetic collaborative source is unavailable.",
                    )
                if set(rankings) - required_sources:
                    raise RecommendationServiceError(
                        RecommendationErrorCode.UNSUPPORTED_ALGORITHM,
                        "The synthetic source configuration is incompatible.",
                    )
                raw_candidates = method(
                    context,
                    target_item_key=target_item_key,
                    all_training_interactions=self._catalog.get_training_interactions(),
                    collaborative_rankings=rankings,
                    train_known_item_keys=self._catalog.train_known_item_keys,
                    candidate_policy=request.candidate_policy,
                    config=policy.hybrid_config,
                    k=request.k,
                )
        else:
            raise RecommendationServiceError(
                RecommendationErrorCode.INVALID_REQUEST,
                "The requested recommendation mode is invalid.",
            )

        if len(raw_candidates) > request.k:
            raw_candidates = tuple(raw_candidates[: request.k])
        visible_products = {
            product.item_key: product
            for product in self._catalog.list_products()
            if product.visible and product.catalog_eligible
        }
        accepted: list[tuple[RankedCandidate, SyntheticProduct]] = []
        seen_candidate_ids: set[str] = set()
        for candidate in raw_candidates:
            if candidate.item_key in seen_candidate_ids:
                continue
            seen_candidate_ids.add(candidate.item_key)
            if candidate.item_key in requested_exclusions:
                continue
            product = visible_products.get(candidate.item_key)
            if product is None or not self._passes_constraints(product, request):
                continue
            if not set(candidate.source_names) <= _ALLOWED_SOURCES:
                raise RecommendationServiceError(
                    RecommendationErrorCode.EXECUTION_FAILED,
                    "A recommendation source returned invalid provenance.",
                )
            if not set(candidate.reason_codes) <= _ALLOWED_REASONS:
                raise RecommendationServiceError(
                    RecommendationErrorCode.EXECUTION_FAILED,
                    "A recommendation source returned invalid reason codes.",
                )
            accepted.append((candidate, product))

        result_rows = tuple(
            RecommendationItem(
                product_id=candidate.item_key,
                rank=rank,
                source_names=candidate.source_names,
                reason_codes=candidate.reason_codes,
            )
            for rank, (candidate, _product) in enumerate(accepted[: request.k], start=1)
        )
        history_events = (
            tuple(
                event
                for event in context.training_history
                if event.event_time_ms < context.prediction_time_ms
            )
            if context is not None
            else ()
        )
        request_id = secrets.token_hex(12)
        return RecommendationResponse(
            schema_version="recfusion.recommendation-response.v1",
            request_id=request_id,
            mode=request.mode,
            algorithm_id=policy.algorithm_id,
            algorithm_version=policy.algorithm_version,
            candidate_policy=policy.candidate_policy,
            policy_id=policy.policy_id,
            catalog_id="synthetic-electronics-v1",
            catalog_fingerprint=self._catalog.catalog_fingerprint,
            artifact_fingerprint=source.artifact_fingerprint,
            status=(
                RecommendationStatus.OK
                if result_rows
                else RecommendationStatus.NO_RESULTS
            ),
            result_count=len(result_rows),
            diagnostics=RecommendationDiagnostics(
                candidate_count=len(raw_candidates),
                eligible_count=len(accepted),
                returned_count=len(result_rows),
                history_event_count=len(history_events),
                seen_exclusion_count=len({event.item_key for event in history_events}),
            ),
            recommendations=result_rows,
            warnings=() if result_rows else ("no_eligible_results",),
        )

    @staticmethod
    def _require_query_product(product: SyntheticProduct) -> None:
        if not product.visible or not product.catalog_eligible:
            raise RecommendationServiceError(
                RecommendationErrorCode.QUERY_PRODUCT_INELIGIBLE,
                "The requested synthetic product is not eligible for recommendations.",
            )

    @staticmethod
    def _passes_constraints(
        product: SyntheticProduct, request: RecommendationRequest
    ) -> bool:
        if request.constraints.category is not None and (
            product.category is None
            or product.category.casefold() != request.constraints.category.casefold()
        ):
            return False
        price_cap = request.constraints.max_price
        if price_cap is not None:
            if product.price is None or product.price.currency != price_cap.currency:
                return False
            if product.price.amount > price_cap.amount:
                return False
        return True
