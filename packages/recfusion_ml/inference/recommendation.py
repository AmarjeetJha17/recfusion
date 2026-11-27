"""Adapters from validated synthetic artifacts to core inference ports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from recfusion_core.contracts import (
    HybridInferenceConfig,
    Interaction,
    RankedCandidate,
    SyntheticProduct,
    SyntheticUserContext,
)
from recfusion_ml.inference.artifacts import LoadedRecommendationArtifact
from recfusion_ml.ranking.rrf import RRFConfig
from recfusion_ml.retrieval.content import ContentIndex, ContentItem
from recfusion_ml.retrieval.hybrid import (
    HybridCandidatePolicy,
    HybridConfig,
    HybridUserContext,
    retrieve_hybrid,
)

_CONTENT_SOURCE_NAME = "tfidf_content"


def _content_item(product: SyntheticProduct) -> ContentItem:
    return ContentItem(
        item_key=product.item_key,
        fields=product.content_fields,
        source_record_fingerprint=product.source_record_fingerprint,
        catalog_eligible=product.catalog_eligible and product.visible,
    )


@dataclass(frozen=True, slots=True)
class SyntheticRecommendationSource:
    """A loaded synthetic artifact; request calls never fit or reload it."""

    artifact: LoadedRecommendationArtifact

    @property
    def artifact_id(self) -> str:
        return self.artifact.artifact_id

    @property
    def catalog_id(self) -> str:
        return self.artifact.catalog_id

    @property
    def catalog_fingerprint(self) -> str:
        return self.artifact.catalog_fingerprint

    @property
    def artifact_fingerprint(self) -> str:
        return self.artifact.artifact_fingerprint

    @property
    def supported_algorithms(self) -> Mapping[str, str]:
        return self.artifact.supported_algorithms

    @property
    def supported_candidate_policies(self) -> frozenset[str]:
        return self.artifact.supported_candidate_policies

    @property
    def content_index(self) -> ContentIndex:
        return self.artifact.content_index

    def recommend_product_to_product(
        self,
        query_product: SyntheticProduct,
        *,
        eligible_item_keys: frozenset[str],
        excluded_item_keys: frozenset[str],
        k: int,
    ) -> tuple[RankedCandidate, ...]:
        allowed = eligible_item_keys - excluded_item_keys
        result = self.content_index.recommend_similar(
            _content_item(query_product),
            eligible_item_keys=allowed,
            k=k,
        )
        return tuple(
            RankedCandidate(
                item_key=match.item_key,
                score=match.score,
                source_names=(_CONTENT_SOURCE_NAME,),
                reason_codes=("content_similarity",),
            )
            for match in result.items
        )

    def recommend_synthetic_user(
        self,
        context: SyntheticUserContext,
        *,
        target_item_key: str | None,
        excluded_item_keys: frozenset[str],
        k: int,
    ) -> tuple[RankedCandidate, ...]:
        profile = self.content_index.profile_from_training_history(
            context.training_history,
            user_key=context.user_key,
            prediction_time_ms=context.prediction_time_ms,
            target_item_key=target_item_key,
            positive_min_rating=Decimal("4"),
        )
        allowed = frozenset(self.content_index.candidate_keys) - excluded_item_keys
        result = self.content_index.recommend_for_profile(
            profile,
            eligible_item_keys=allowed,
            k=k,
        )
        return tuple(
            RankedCandidate(
                item_key=match.item_key,
                score=match.score,
                source_names=(_CONTENT_SOURCE_NAME,),
                reason_codes=("content_similarity",),
            )
            for match in result.items
        )

    def recommend_hybrid(
        self,
        context: SyntheticUserContext,
        *,
        target_item_key: str | None,
        all_training_interactions: Sequence[Interaction],
        collaborative_rankings: Mapping[str, Sequence[str]],
        train_known_item_keys: frozenset[str],
        candidate_policy: str,
        config: HybridInferenceConfig,
        k: int,
    ) -> tuple[RankedCandidate, ...]:
        try:
            policy = HybridCandidatePolicy(candidate_policy)
        except ValueError as error:
            raise ValueError("Unsupported hybrid candidate policy.") from error
        hybrid_config = HybridConfig(
            rrf=RRFConfig(
                rank_constant=config.rank_constant,
                source_weights=dict(config.source_weights),
                source_depths=dict(config.source_depths),
            ),
            content_source_name=_CONTENT_SOURCE_NAME,
        )
        result = retrieve_hybrid(
            context=HybridUserContext(
                user_key=context.user_key,
                training_interactions=all_training_interactions,
                prediction_time_ms=context.prediction_time_ms,
                target_item_key=target_item_key,
            ),
            content_index=self.content_index,
            collaborative_rankings=collaborative_rankings,
            train_known_item_keys=train_known_item_keys,
            candidate_policy=policy,
            config=hybrid_config,
            k=k,
        )
        return tuple(
            RankedCandidate(
                item_key=item_key,
                score=result.fusion.scores[item_key],
                source_names=result.fusion.source_provenance.get(item_key, ()),
                reason_codes=("hybrid_rrf",),
            )
            for item_key in result.fusion.recommended_items
        )
