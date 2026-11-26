"""Deterministic sparse TF-IDF retrieval over product content.

This module consumes explicit canonical/normalized product records. It does not
read datasets, infer product facts, or fit from interaction labels.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import asdict, dataclass
from decimal import Decimal

from recfusion_core.contracts import DataSplit, Interaction

CONTENT_FEATURE_SCHEMA = "recfusion.content-feature.v1"
CONTENT_INDEX_ARTIFACT_SCHEMA = "recfusion.content-tfidf-index.v1"
NORMALIZATION_SCHEMA = "recfusion.product-normalization.v1"
TOKENIZER_SCHEMA = "recfusion.electronics-tokenizer.v1"
_CANDIDATE_POLICY = (
    "explicit catalog eligibility and non-empty fitted-vocabulary content"
)
_ITEM_KEY_PATTERN = re.compile(r"^[^\s\x00]+$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_PATTERN = re.compile(r"[^\W_]+(?:[-+.#/][^\W_]+)*", re.UNICODE)
_DASHES = str.maketrans(
    {
        chr(codepoint): "-"
        for codepoint in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015)
    }
)
_BASE_FIELDS = ("title", "category", "categories", "description", "features")
_NORMALIZED_FIELDS = (
    "brand",
    "ram_capacity_bytes",
    "storage_capacity_bytes",
    "storage_type",
    "display_size_mm",
    "weight_g",
    "battery_capacity",
    "processor_name",
    "gpu_name",
)
_MAX_VOCABULARY_SIZE = 100_000
_MAX_DISTINCT_TERMS = 1_000_000
_MAX_FIELD_CHARACTERS = 100_000
_MAX_TOKENS_PER_DOCUMENT = 4_096
_MAX_CATALOG_ITEMS = 100_000
_MAX_TOTAL_NONZERO = 5_000_000
_MAX_QUERY_BATCH_SIZE = 128
_MAX_RECOMMENDATIONS = 100
_MAX_HISTORY_EVENTS = 100_000

type SparseVector = tuple[tuple[int, float], ...]


@dataclass(frozen=True, slots=True)
class ContentConfig:
    """Hard bounds and deterministic TF-IDF settings for one content index."""

    max_vocabulary_size: int = 4096
    max_distinct_terms: int = 100_000
    max_characters_per_field: int = 4096
    max_tokens_per_document: int = 512
    max_catalog_items: int = 50_000
    max_total_nonzero: int = 2_000_000
    max_query_batch_size: int = 16
    max_recommendations: int = 100
    max_history_events: int = 100_000

    def __post_init__(self) -> None:
        limits = (
            ("maximum vocabulary size", self.max_vocabulary_size, _MAX_VOCABULARY_SIZE),
            (
                "maximum distinct term count",
                self.max_distinct_terms,
                _MAX_DISTINCT_TERMS,
            ),
            (
                "maximum characters per field",
                self.max_characters_per_field,
                _MAX_FIELD_CHARACTERS,
            ),
            (
                "maximum tokens per document",
                self.max_tokens_per_document,
                _MAX_TOKENS_PER_DOCUMENT,
            ),
            ("maximum catalog item count", self.max_catalog_items, _MAX_CATALOG_ITEMS),
            (
                "maximum sparse nonzero count",
                self.max_total_nonzero,
                _MAX_TOTAL_NONZERO,
            ),
            (
                "maximum query batch size",
                self.max_query_batch_size,
                _MAX_QUERY_BATCH_SIZE,
            ),
            (
                "maximum recommendation count",
                self.max_recommendations,
                _MAX_RECOMMENDATIONS,
            ),
            (
                "maximum history event count",
                self.max_history_events,
                _MAX_HISTORY_EVENTS,
            ),
        )
        for label, value, maximum in limits:
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= maximum
            ):
                raise ValueError(f"{label} must be between 1 and {maximum}.")


@dataclass(frozen=True, slots=True)
class ContentItem:
    """Approved product text and provenance, with identity kept out of text."""

    item_key: str
    fields: tuple[tuple[str, str], ...]
    source_record_fingerprint: str
    normalization_schema: str | None = None
    field_statuses: tuple[tuple[str, str], ...] = ()
    catalog_eligible: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.item_key, str) or not _ITEM_KEY_PATTERN.fullmatch(
            self.item_key
        ):
            raise ValueError("Content item identity must be a non-empty token.")
        if not _FINGERPRINT_PATTERN.fullmatch(self.source_record_fingerprint):
            raise ValueError("Content source fingerprint must be a SHA-256 digest.")
        if self.normalization_schema not in {None, NORMALIZATION_SCHEMA}:
            raise ValueError("Unsupported product normalization schema.")
        allowed_fields = set(_BASE_FIELDS) | set(_NORMALIZED_FIELDS)
        if any(
            name not in allowed_fields or not isinstance(value, str)
            for name, value in self.fields
        ):
            raise ValueError(
                "Content item contains an unsupported field representation."
            )
        if len({name for name, _ in self.fields}) != len(self.fields):
            raise ValueError("Content item fields must have unique names.")

    @classmethod
    def from_records(
        cls,
        product_record: Mapping[str, object],
        normalized_record: Mapping[str, object] | None = None,
    ) -> ContentItem:
        """Select contract-backed content, ignoring unsupported/malformed fields."""
        item_key = product_record.get("item_key")
        fingerprint = product_record.get("source_record_fingerprint")
        if not isinstance(item_key, str) or not isinstance(fingerprint, str):
            raise ValueError("Product identity and source fingerprint are required.")

        fields: list[tuple[str, str]] = []
        statuses: dict[str, str] = {}
        for name in _BASE_FIELDS:
            value = product_record.get(name)
            text, status = _canonical_text(value)
            statuses[name] = status
            if text:
                fields.append((name, text))

        normalization_schema: str | None = None
        catalog_eligible = True
        if normalized_record is not None:
            normalized_product = normalized_record.get("product")
            if not isinstance(normalized_product, Mapping):
                raise ValueError("Normalized product identity is missing.")
            normalized_item_key = normalized_product.get("item_key")
            normalized_fingerprint = normalized_product.get("source_record_fingerprint")
            if normalized_item_key != item_key or normalized_fingerprint != fingerprint:
                raise ValueError("Canonical and normalized product identity mismatch.")
            normalization = normalized_record.get("normalization")
            if not isinstance(normalization, Mapping):
                raise ValueError("Product normalization record is malformed.")
            schema = normalization.get("schema_version")
            if schema != NORMALIZATION_SCHEMA:
                raise ValueError("Unsupported product normalization schema version.")
            normalization_schema = NORMALIZATION_SCHEMA
            catalog_eligible = (
                normalization.get("product_decision") != "conflict_retained"
            )
            _append_normalized_field(
                fields,
                statuses,
                "brand",
                normalization.get("brand"),
            )
            specifications = normalization.get("specifications")
            if not isinstance(specifications, Mapping):
                specifications = {}
            for name in _NORMALIZED_FIELDS[1:]:
                _append_normalized_field(
                    fields, statuses, name, specifications.get(name)
                )

        return cls(
            item_key=item_key,
            fields=tuple(fields),
            source_record_fingerprint=fingerprint,
            normalization_schema=normalization_schema,
            field_statuses=tuple(
                (name, statuses[name])
                for name in (*_BASE_FIELDS, *_NORMALIZED_FIELDS)
                if name in statuses
            ),
            catalog_eligible=catalog_eligible,
        )


def _canonical_text(value: object) -> tuple[str | None, str]:
    if value is None:
        return None, "missing"
    if isinstance(value, str):
        value = unicodedata.normalize("NFKC", value)
        value = " ".join(value.split())
        return (value, "present") if value else (None, "missing")
    if isinstance(value, (list, tuple)):
        if not value:
            return None, "missing"
        if not all(isinstance(part, str) for part in value):
            return None, "invalid"
        text = " ".join(
            " ".join(unicodedata.normalize("NFKC", part).split()) for part in value
        ).strip()
        return (text, "present") if text else (None, "missing")
    return None, "invalid"


def _append_normalized_field(
    fields: list[tuple[str, str]],
    statuses: dict[str, str],
    name: str,
    field_value: object,
) -> None:
    if not isinstance(field_value, Mapping):
        statuses[name] = "missing"
        return
    status = field_value.get("status")
    value = field_value.get("value")
    if (
        status == "normalized"
        and isinstance(value, (str, int))
        and not isinstance(value, bool)
    ):
        text = " ".join(unicodedata.normalize("NFKC", str(value)).split())
        if text:
            fields.append((name, text))
            statuses[name] = "present"
            return
    statuses[name] = str(status) if isinstance(status, str) else "invalid"


def tokenize_electronics_text(text: str) -> tuple[str, ...]:
    """NFKC/casefold text; keep alphanumerics joined by model/unit punctuation."""
    normalized = unicodedata.normalize("NFKC", text).translate(_DASHES).casefold()
    return tuple(_TOKEN_PATTERN.findall(normalized))


def _item_tokens(item: ContentItem, config: ContentConfig) -> tuple[str, ...]:
    tokens: list[str] = []
    remaining = config.max_tokens_per_document
    for _, raw_value in item.fields:
        if remaining == 0:
            break
        clipped = raw_value[: config.max_characters_per_field]
        field_tokens = tokenize_electronics_text(clipped)
        tokens.extend(field_tokens[:remaining])
        remaining -= min(len(field_tokens), remaining)
    return tuple(tokens)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _unit_normalize(weights: Mapping[int, float]) -> SparseVector:
    norm = math.sqrt(math.fsum(value * value for value in weights.values()))
    if not norm:
        return ()
    return tuple(
        (index, value / norm) for index, value in sorted(weights.items()) if value > 0
    )


def _dot(left: SparseVector, right: SparseVector) -> float:
    left_index = 0
    right_index = 0
    score = 0.0
    while left_index < len(left) and right_index < len(right):
        left_column, left_value = left[left_index]
        right_column, right_value = right[right_index]
        if left_column == right_column:
            score += left_value * right_value
            left_index += 1
            right_index += 1
        elif left_column < right_column:
            left_index += 1
        else:
            right_index += 1
    return min(1.0, max(0.0, score))


@dataclass(frozen=True, slots=True)
class SparseTfidfVectorizer:
    """Smoothed TF-IDF with raw term frequency and L2-normalized sparse rows."""

    vocabulary: Mapping[str, int]
    idf: Mapping[str, float]
    document_count: int
    config: ContentConfig

    @classmethod
    def fit(
        cls, reference_products: Sequence[ContentItem], config: ContentConfig
    ) -> SparseTfidfVectorizer:
        if not reference_products:
            raise ValueError("At least one reference product is required.")
        if len(reference_products) > config.max_catalog_items:
            raise ValueError("Reference catalog exceeds the configured item limit.")
        _require_unique_items(reference_products)

        document_frequency: Counter[str] = Counter()
        total_frequency: Counter[str] = Counter()
        document_count = 0
        for product in reference_products:
            if not product.catalog_eligible:
                continue
            tokens = _item_tokens(product, config)
            if not tokens:
                continue
            document_count += 1
            term_counts = Counter(tokens)
            new_terms = term_counts.keys() - total_frequency.keys()
            if len(total_frequency) + len(new_terms) > config.max_distinct_terms:
                raise ValueError(
                    "Reference corpus exceeds the configured distinct-term limit."
                )
            document_frequency.update(term_counts.keys())
            total_frequency.update(term_counts)
        if not document_count:
            raise ValueError("Reference catalog contains no usable content documents.")

        selected = sorted(
            total_frequency,
            key=lambda token: (-total_frequency[token], token),
        )[: config.max_vocabulary_size]
        ordered_tokens = tuple(sorted(selected))
        vocabulary = {token: index for index, token in enumerate(ordered_tokens)}
        idf = {
            token: math.log((1 + document_count) / (1 + document_frequency[token]))
            + 1.0
            for token in ordered_tokens
        }
        return cls(vocabulary, idf, document_count, config)

    def transform(self, product: ContentItem) -> SparseVector:
        counts: Counter[str] = Counter(_item_tokens(product, self.config))
        weights = {
            self.vocabulary[token]: float(count) * self.idf[token]
            for token, count in counts.items()
            if token in self.vocabulary
        }
        return _unit_normalize(weights)


def _require_unique_items(items: Sequence[ContentItem]) -> None:
    seen: set[str] = set()
    for item in items:
        if item.item_key in seen:
            raise ValueError(f"Duplicate item identity in catalog: {item.item_key}.")
        seen.add(item.item_key)


def _item_manifest_record(item: ContentItem) -> dict[str, object]:
    return {
        "item_key": item.item_key,
        "fields": item.fields,
        "source_record_fingerprint": item.source_record_fingerprint,
        "normalization_schema": item.normalization_schema,
        "catalog_eligible": item.catalog_eligible,
    }


@dataclass(frozen=True, slots=True)
class ContentMatch:
    item_key: str
    score: float


@dataclass(frozen=True, slots=True)
class ContentRecommendation:
    items: tuple[ContentMatch, ...]
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class UserContentProfile:
    """Ephemeral vector and seen set; deliberately carries no user identity."""

    vector: SparseVector
    seen_item_keys: frozenset[str]
    prior_positive_item_count: int
    missing_content_item_count: int


@dataclass(frozen=True, slots=True)
class ContentIndex:
    """Sparse product content vectors and deterministic top-K scoring."""

    vectorizer: SparseTfidfVectorizer
    candidate_keys: tuple[str, ...]
    candidate_vectors: Mapping[str, SparseVector]
    content_vectors: Mapping[str, SparseVector]
    catalog_manifest_sha256: str
    reference_catalog_sha256: str
    code_revision: str
    total_candidate_count: int
    eligible_candidate_count: int
    vocabulary_sha256: str

    @classmethod
    def fit(
        cls,
        reference_products: Iterable[ContentItem],
        candidate_products: Iterable[ContentItem],
        *,
        code_revision: str,
        config: ContentConfig = ContentConfig(),
    ) -> ContentIndex:
        if not isinstance(code_revision, str) or not code_revision.strip():
            raise ValueError("A code revision is required for reproducibility.")
        references = tuple(reference_products)
        candidates = tuple(candidate_products)
        if (
            len(references) > config.max_catalog_items
            or len(candidates) > config.max_catalog_items
        ):
            raise ValueError("Catalog exceeds the configured item limit.")
        _require_unique_items(references)
        _require_unique_items(candidates)
        vectorizer = SparseTfidfVectorizer.fit(references, config)

        all_products: dict[str, ContentItem] = {}
        for item in (*references, *candidates):
            existing = all_products.get(item.item_key)
            if existing is not None and _item_manifest_record(
                existing
            ) != _item_manifest_record(item):
                raise ValueError("Reference and candidate product identity conflict.")
            all_products[item.item_key] = item
        if len(all_products) > config.max_catalog_items:
            raise ValueError("Combined catalog exceeds the configured item limit.")

        content_vectors: dict[str, SparseVector] = {}
        nonzero_count = 0
        for item_key in sorted(all_products):
            product = all_products[item_key]
            if not product.catalog_eligible:
                continue
            vector = vectorizer.transform(product)
            if vector:
                nonzero_count += len(vector)
                if nonzero_count > config.max_total_nonzero:
                    raise ValueError(
                        "Sparse catalog exceeds the configured nonzero limit."
                    )
                content_vectors[item_key] = vector

        candidate_keys = tuple(
            sorted(
                product.item_key
                for product in candidates
                if product.catalog_eligible and product.item_key in content_vectors
            )
        )
        candidate_vectors = {key: content_vectors[key] for key in candidate_keys}
        catalog_records = [
            _item_manifest_record(item)
            for item in sorted(candidates, key=lambda row: row.item_key)
        ]
        reference_records = [
            _item_manifest_record(item)
            for item in sorted(references, key=lambda row: row.item_key)
        ]
        vocabulary_sha256 = _vocabulary_digest(vectorizer)
        return cls(
            vectorizer=vectorizer,
            candidate_keys=candidate_keys,
            candidate_vectors=candidate_vectors,
            content_vectors=content_vectors,
            catalog_manifest_sha256=_sha256(_canonical_json(catalog_records)),
            reference_catalog_sha256=_sha256(_canonical_json(reference_records)),
            code_revision=code_revision,
            total_candidate_count=len(candidates),
            eligible_candidate_count=len(candidate_keys),
            vocabulary_sha256=vocabulary_sha256,
        )

    def recommend_similar(
        self,
        query: ContentItem,
        *,
        k: int,
        eligible_item_keys: Set[str] | None = None,
        exclude_query_item: bool = True,
    ) -> ContentRecommendation:
        _validate_k(k, self.vectorizer.config)
        if k == 0:
            return ContentRecommendation((), "zero_limit")
        query_vector = self.vectorizer.transform(query)
        if not query_vector:
            return ContentRecommendation((), "empty_query_content")

        eligible = None if eligible_item_keys is None else set(eligible_item_keys)
        if (
            eligible is not None
            and len(eligible) > self.vectorizer.config.max_catalog_items
        ):
            raise ValueError(
                "Eligible candidate set exceeds the configured item limit."
            )
        scored: list[ContentMatch] = []
        for item_key in self.candidate_keys:
            if exclude_query_item and item_key == query.item_key:
                continue
            if eligible is not None and item_key not in eligible:
                continue
            score = _dot(query_vector, self.candidate_vectors[item_key])
            if score > 0.0:
                scored.append(ContentMatch(item_key, score))
        scored.sort(key=lambda result: (-result.score, result.item_key))
        results = tuple(scored[:k])
        reason = None if results else "no_positive_similarity"
        return ContentRecommendation(results, reason)

    def recommend_many(
        self,
        queries: Sequence[ContentItem],
        *,
        k: int,
        eligible_item_keys: Set[str] | None = None,
    ) -> tuple[ContentRecommendation, ...]:
        if len(queries) > self.vectorizer.config.max_query_batch_size:
            raise ValueError("Query batch limit exceeded.")
        _validate_k(k, self.vectorizer.config)
        return tuple(
            self.recommend_similar(query, k=k, eligible_item_keys=eligible_item_keys)
            for query in queries
        )

    def profile_from_training_history(
        self,
        training_events: Iterable[Interaction],
        *,
        user_key: str,
        prediction_time_ms: int,
        target_item_key: str | None = None,
        positive_min_rating: Decimal = Decimal("4"),
    ) -> UserContentProfile:
        """Build an equal-weight profile from unique, strictly prior positives."""
        if not user_key.strip():
            raise ValueError("A user key is required to select training history.")
        if (
            isinstance(prediction_time_ms, bool)
            or not isinstance(prediction_time_ms, int)
            or prediction_time_ms < 0
        ):
            raise ValueError("Prediction timestamp must be non-negative milliseconds.")
        if not positive_min_rating.is_finite() or not Decimal(
            "1"
        ) <= positive_min_rating <= Decimal("5"):
            raise ValueError("Positive rating threshold must be within [1, 5].")

        prior_events: list[Interaction] = []
        for event_count, event in enumerate(training_events, start=1):
            if event_count > self.vectorizer.config.max_history_events:
                raise ValueError("Training history exceeds the configured event limit.")
            if event.split is not DataSplit.TRAIN:
                raise ValueError("Content profiles accept training-only events.")
            if event.user_key == user_key and event.event_time_ms < prediction_time_ms:
                prior_events.append(event)

        seen_items = frozenset(event.item_key for event in prior_events)
        positive_items = {
            event.item_key
            for event in prior_events
            if event.rating >= positive_min_rating and event.item_key != target_item_key
        }
        vectors: list[SparseVector] = []
        missing_content = 0
        for item_key in sorted(positive_items):
            vector = self.content_vectors.get(item_key)
            if vector:
                vectors.append(vector)
            else:
                missing_content += 1

        if not vectors:
            profile_vector: SparseVector = ()
        else:
            sums: dict[int, float] = {}
            for vector in vectors:
                for index, value in vector:
                    sums[index] = sums.get(index, 0.0) + value
            count = float(len(vectors))
            profile_vector = _unit_normalize(
                {index: value / count for index, value in sums.items()}
            )
        return UserContentProfile(
            vector=profile_vector,
            seen_item_keys=seen_items,
            prior_positive_item_count=len(positive_items),
            missing_content_item_count=missing_content,
        )

    def recommend_for_profile(
        self,
        profile: UserContentProfile,
        *,
        k: int,
        eligible_item_keys: Set[str] | None = None,
    ) -> ContentRecommendation:
        _validate_k(k, self.vectorizer.config)
        if k == 0:
            return ContentRecommendation((), "zero_limit")
        if not profile.vector:
            return ContentRecommendation((), "empty_user_profile")
        eligible = (
            set(self.candidate_keys)
            if eligible_item_keys is None
            else set(eligible_item_keys)
        )
        if len(eligible) > self.vectorizer.config.max_catalog_items:
            raise ValueError(
                "Eligible candidate set exceeds the configured item limit."
            )
        eligible.difference_update(profile.seen_item_keys)
        scored: list[ContentMatch] = []
        for item_key in self.candidate_keys:
            if item_key not in eligible:
                continue
            score = _dot(profile.vector, self.candidate_vectors[item_key])
            if score > 0.0:
                scored.append(ContentMatch(item_key, score))
        scored.sort(key=lambda result: (-result.score, result.item_key))
        results = tuple(scored[:k])
        reason = None if results else "no_positive_similarity"
        return ContentRecommendation(results, reason)

    def to_artifact_bytes(self) -> bytes:
        vocabulary = [
            [token, index, self.vectorizer.idf[token]]
            for token, index in sorted(
                self.vectorizer.vocabulary.items(), key=lambda pair: pair[1]
            )
        ]
        vectors = {
            key: [[index, value] for index, value in self.content_vectors[key]]
            for key in sorted(self.content_vectors)
        }
        record: dict[str, object] = {
            "artifact_schema": CONTENT_INDEX_ARTIFACT_SCHEMA,
            "feature_schema": CONTENT_FEATURE_SCHEMA,
            "tokenizer_schema": TOKENIZER_SCHEMA,
            "configuration": asdict(self.vectorizer.config),
            "code_revision": self.code_revision,
            "candidate_eligibility_policy": _CANDIDATE_POLICY,
            "catalog_manifest_sha256": self.catalog_manifest_sha256,
            "reference_catalog_sha256": self.reference_catalog_sha256,
            "vocabulary_sha256": self.vocabulary_sha256,
            "document_count": self.vectorizer.document_count,
            "total_candidate_count": self.total_candidate_count,
            "eligible_candidate_count": self.eligible_candidate_count,
            "vocabulary": vocabulary,
            "candidate_keys": self.candidate_keys,
            "content_vectors": vectors,
        }
        return _canonical_json(record) + b"\n"

    @classmethod
    def from_artifact_bytes(cls, artifact: bytes) -> ContentIndex:
        """Load only validated JSON artifacts; never deserialize Python objects."""
        try:
            raw: object = json.loads(artifact)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as error:
            raise ValueError(
                "Content retrieval artifact must be valid JSON."
            ) from error
        if not isinstance(raw, dict):
            raise ValueError("Content retrieval artifact root must be an object.")
        if raw.get("artifact_schema") != CONTENT_INDEX_ARTIFACT_SCHEMA:
            raise ValueError("Unsupported content retrieval artifact schema.")
        if raw.get("feature_schema") != CONTENT_FEATURE_SCHEMA:
            raise ValueError("Unsupported content feature schema.")
        if raw.get("tokenizer_schema") != TOKENIZER_SCHEMA:
            raise ValueError("Unsupported content tokenizer schema.")
        if raw.get("candidate_eligibility_policy") != _CANDIDATE_POLICY:
            raise ValueError("Unsupported candidate eligibility policy.")

        configuration = raw.get("configuration")
        if not isinstance(configuration, dict):
            raise ValueError("Content retrieval configuration is malformed.")
        try:
            config = ContentConfig(**configuration)
        except (TypeError, ValueError) as error:
            raise ValueError("Content retrieval configuration is invalid.") from error

        vocabulary_rows = raw.get("vocabulary")
        if not isinstance(vocabulary_rows, list):
            raise ValueError("Content vocabulary is malformed.")
        vocabulary: dict[str, int] = {}
        idf: dict[str, float] = {}
        for expected_index, row in enumerate(vocabulary_rows):
            if (
                not isinstance(row, list)
                or len(row) != 3
                or not isinstance(row[0], str)
                or row[1] != expected_index
                or isinstance(row[2], bool)
                or not isinstance(row[2], (int, float))
                or not math.isfinite(float(row[2]))
                or float(row[2]) <= 0
            ):
                raise ValueError("Content vocabulary entries are invalid.")
            vocabulary[row[0]] = expected_index
            idf[row[0]] = float(row[2])
        vectorizer = SparseTfidfVectorizer(
            vocabulary=vocabulary,
            idf=idf,
            document_count=_required_positive_int(
                raw.get("document_count"), "document count"
            ),
            config=config,
        )
        vocabulary_sha256 = _vocabulary_digest(vectorizer)
        if raw.get("vocabulary_sha256") != vocabulary_sha256:
            raise ValueError("Content vocabulary checksum mismatch.")

        candidate_keys_value = raw.get("candidate_keys")
        vectors_value = raw.get("content_vectors")
        if not isinstance(candidate_keys_value, list) or not all(
            isinstance(key, str) for key in candidate_keys_value
        ):
            raise ValueError("Candidate key list is malformed.")
        if candidate_keys_value != sorted(set(candidate_keys_value)):
            raise ValueError("Candidate key ordering is invalid.")
        if not isinstance(vectors_value, dict):
            raise ValueError("Content vector map is malformed.")
        content_vectors = {
            key: _read_sparse_vector(value, len(vocabulary))
            for key, value in vectors_value.items()
            if isinstance(key, str)
        }
        if len(content_vectors) != len(vectors_value) or not set(
            candidate_keys_value
        ) <= set(content_vectors):
            raise ValueError("Candidate vectors are missing or malformed.")
        if (
            len(content_vectors) > config.max_catalog_items
            or sum(len(vector) for vector in content_vectors.values())
            > config.max_total_nonzero
        ):
            raise ValueError("Artifact vectors exceed configured resource limits.")

        catalog_hash = _require_sha256(
            raw.get("catalog_manifest_sha256"), "catalog manifest"
        )
        reference_hash = _require_sha256(
            raw.get("reference_catalog_sha256"), "reference catalog"
        )
        revision = raw.get("code_revision")
        if not isinstance(revision, str) or not revision.strip():
            raise ValueError("Artifact code revision is missing.")
        total_candidates = _required_nonnegative_int(
            raw.get("total_candidate_count"), "total candidate count"
        )
        eligible_candidates = _required_nonnegative_int(
            raw.get("eligible_candidate_count"), "eligible candidate count"
        )
        if (
            eligible_candidates != len(candidate_keys_value)
            or total_candidates < eligible_candidates
        ):
            raise ValueError("Candidate counts are inconsistent.")
        return cls(
            vectorizer=vectorizer,
            candidate_keys=tuple(candidate_keys_value),
            candidate_vectors={
                key: content_vectors[key] for key in candidate_keys_value
            },
            content_vectors=content_vectors,
            catalog_manifest_sha256=catalog_hash,
            reference_catalog_sha256=reference_hash,
            code_revision=revision,
            total_candidate_count=total_candidates,
            eligible_candidate_count=eligible_candidates,
            vocabulary_sha256=vocabulary_sha256,
        )


def _validate_k(k: int, config: ContentConfig) -> None:
    if (
        isinstance(k, bool)
        or not isinstance(k, int)
        or not 0 <= k <= config.max_recommendations
    ):
        raise ValueError(
            f"Recommendation count exceeds the maximum of {config.max_recommendations}."
        )


def _vocabulary_digest(vectorizer: SparseTfidfVectorizer) -> str:
    rows = [
        [token, index, vectorizer.idf[token]]
        for token, index in sorted(
            vectorizer.vocabulary.items(), key=lambda pair: pair[1]
        )
    ]
    return _sha256(_canonical_json(rows))


def _read_sparse_vector(value: object, vocabulary_size: int) -> SparseVector:
    if not isinstance(value, list):
        raise ValueError("Sparse vector is malformed.")
    result: list[tuple[int, float]] = []
    prior_index = -1
    for row in value:
        if (
            not isinstance(row, list)
            or len(row) != 2
            or isinstance(row[0], bool)
            or not isinstance(row[0], int)
            or not 0 <= row[0] < vocabulary_size
            or row[0] <= prior_index
            or isinstance(row[1], bool)
            or not isinstance(row[1], (int, float))
            or not math.isfinite(float(row[1]))
            or float(row[1]) <= 0
        ):
            raise ValueError("Sparse vector entries are invalid.")
        result.append((row[0], float(row[1])))
        prior_index = row[0]
    if result and not math.isclose(
        math.fsum(value * value for _, value in result), 1.0, rel_tol=1e-7, abs_tol=1e-7
    ):
        raise ValueError("Sparse vectors must be L2 normalized.")
    return tuple(result)


def _required_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"Artifact {label} must be a positive integer.")
    return value


def _required_nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Artifact {label} must be a non-negative integer.")
    return value


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not _FINGERPRINT_PATTERN.fullmatch(value):
        raise ValueError(f"Artifact {label} checksum is malformed.")
    return value
