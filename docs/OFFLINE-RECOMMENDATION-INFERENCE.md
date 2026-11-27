# Offline synthetic recommendation inference

**Status:** Phase 6.1B implementation checkpoint prepared for project-owner
review. This is a local application-service demonstration over invented
records. This Phase 6.1B service itself is not an HTTP recommendation API,
promoted model release, or production serving path. Phase 6.2A adds a separate
development-only HTTP wrapper described in
[`SYNTHETIC-RECOMMENDATION-API.md`](./SYNTHETIC-RECOMMENDATION-API.md). The
proposed contracts in
[`RECOMMENDATION-SERVING-DESIGN.md`](./RECOMMENDATION-SERVING-DESIGN.md) and
ADRs 018/019 remain Proposed. Phase 4.2C remains ON HOLD.

## Scope and package boundaries

The implementation adds versioned request, response, and error contracts in
`recfusion_api.schemas.recommendation`, a read-only seeded synthetic catalog,
and `RecommendationService` in the API application package. The Phase 6.1B
application-service layer has no route, network listener, database, filesystem
artifact lookup, training job, or request-time content fitting. Core inference
ports live in `recfusion_core.contracts`; `recfusion_ml.inference` adapts the existing
`ContentIndex` and weighted RRF implementation to those ports.

The provider is generated in memory with seed `44041`, schema
`recfusion.synthetic-catalog.v1`, ten invented products, and three invented
user contexts. It contains five train-known products, visible cold products,
one product without content, one ineligible product, and one hidden product.
Its catalog and bundle fingerprints are deterministic. Synthetic user
contexts contain training events only; event times at or after prediction time
are excluded when constructing preference and seen-item context. No Amazon
CSV, product metadata, image, pilot artifact, or real identifier is read.

## Request contract

Requests use `recfusion.recommendation-request.v1` and explicitly specify
`mode`, `catalog_id`, `algorithm_id`, `algorithm_version`, `policy_id`,
`candidate_policy`, bounded `k`, a mode-specific query, bounded product
exclusions, and typed hard constraints. Unknown fields and non-synthetic IDs
are rejected. The serialized payload limit is 16 KiB, `k` is 1–20, and at
most 64 distinct product exclusions are accepted. Policy IDs are resolved by
a server-owned allowlist; callers cannot supply model paths, rankings, RRF
weights, or artifact locations.

| Mode and policy | Algorithm | Candidate policy | Behavior |
|---|---|---|---|
| `product_to_product` / `content-similarity-v1` | `tfidf_content` v1 | `content_catalog` | Existing content index retrieves similar products; the query product is excluded. |
| `synthetic_user` / `synthetic-user-content-v1` | `tfidf_content` v1 | `content_catalog` | Existing content index forms a positive preference profile from strictly prior synthetic training history; all strictly prior observed items are excluded. |
| `hybrid` / `synthetic-hybrid-warm-v1` | `weighted_rrf` v1 | `warm_hybrid` | Existing weighted RRF combines fixed synthetic item-CF, BPR-control, and content source rankings; candidates are train-known. |
| `hybrid` / `synthetic-hybrid-content-v1` | `weighted_rrf` v1 | `content_eligible_hybrid` | Existing weighted RRF permits eligible content-only cold products; collaborative sources remain train-known. |

The fixture’s collaborative rankings are authored synthetic controls; they
are not trained or evaluated model artifacts. Hybrid source weights are fixed
by server policy. There is no automatic substitute model or popularity
fallback.

## Artifact preparation and loading

`prepare_synthetic_recommendation_artifact` fits the existing TF-IDF index
once from synthetic train-known reference products and eligible fixture
content. It produces a bounded canonical JSON envelope containing the
existing content-index JSON, schema/configuration identifiers, synthetic
catalog fingerprints, supported policies, and SHA-256 fingerprints. The
loader checks the caller-pinned outer checksum, size bound, envelope/schema,
catalog identity and fingerprint, algorithm and candidate-policy support,
vectorizer configuration, inner index checksum, vocabulary fingerprint, and
candidate bounds before constructing an in-memory artifact. Runtime service
calls receive only an already-loaded artifact through an in-memory
allowlist. No pickle, arbitrary Python object, path, or request-time refit is
used. The artifact is synthetic-only and is not a model promotion mechanism.

The Phase 6.1A design proposed a release registry and immutable release
manifest, but none exists yet. This checkpoint deliberately uses an
in-memory synthetic artifact source and does not claim readiness, approval,
rollback, or production artifact lifecycle support.

## Eligibility, privacy, and errors

After retrieval, the service removes explicit exclusions, the product query
seed or user target, and all strictly prior observed items. It resolves
candidate IDs against the active synthetic catalog and returns only visible,
catalog-eligible products satisfying any category and currency-matched price
caps. Unknown or missing attributes fail the corresponding hard constraint.
Duplicate candidates are collapsed and final ranks are contiguous. Short and
empty results are valid; the service does not silently refill a short list
from an unrequested source.

Responses use `recfusion.recommendation-response.v1` and expose catalog-owned
synthetic product IDs, rank, allowlisted source names, bounded reason codes,
catalog/artifact fingerprints, and aggregate counts. They do not include user
IDs, histories, raw product text, model scores, embeddings, or row-level
diagnostic IDs. Safe typed errors use
`recfusion.recommendation-error.v1`; they contain a generated request ID,
stable error code, and generic message without internal exceptions. No HTTP
status mapping is implemented in this checkpoint.

The fixture is not a real catalog and its synthetic prices/specifications
must not be represented as marketplace facts. This implementation does not
resolve identity, authorization, persistence, retention, online exposure,
non-loopback network safety, release approval, or user-facing explanation.

## Verification

Focused synthetic coverage verifies contract bounds and versioning,
deterministic catalog fingerprints, train-only histories, warm/cold
eligibility, content and hybrid modes, seen-item and explicit exclusions,
hard constraints, typed fail-closed errors, missing artifacts, and that
request inference never calls TF-IDF fitting. The synthetic artifact tests
cover checksum, schema, catalog mismatch, and deterministic preparation.
This checkpoint adds no real-data processing or new dependencies.

The checkpoint is ready for owner review after the repository validation
reported with this change. It does not advance Phase 6.1C, accept ADR-019, or
change the hold on real Amazon metadata under Phase 4.2C.
