# Recommendation serving design

**Status:** Proposed serving contract and architecture. Phase 6.1A is documented;
Phase 6.1B now has a local synthetic application-service checkpoint prepared
for owner review. No recommendation endpoint, online model registry, artifact
promotion process, or production serving path is implemented. This design
authorizes none of those changes. The synthetic application uses invented data
only.

## Purpose and scope

This document defines a versioned boundary between a future HTTP API and the
existing deterministic retrieval components. It covers three explicit query
modes: product-to-product, a synthetic-user profile, and collaborative plus
content hybrid retrieval. It does not change the offline evaluation protocol,
train or promote a model, use Amazon product metadata, or make any model a
serving-ready choice. Phase 4.2C remains ON HOLD.

The first application target is a local synthetic demonstration. It must not
read Amazon Review CSVs, Amazon metadata, existing real-data pilot artifacts,
or maps derived from their identifiers. All products, text, ratings, histories,
and IDs must be generated or authored specifically as synthetic fixtures.

## Existing implementation and gaps

| Area | Reusable implementation | Serving gap |
|---|---|---|
| HTTP | FastAPI app factory, lifespan, request IDs, safe error envelope, health/readiness routes | No recommendation route, request/response schemas, identity/auth provider, or catalog/model dependencies |
| Content | `ContentIndex` fits bounded TF-IDF from explicit reference items, transforms candidates, supports product similarity and train-history profiles, and reads validated JSON artifacts | Phase 6.1B adds a synthetic catalog, synthetic artifact validation, and in-memory runtime source; there is no production registry or approved deployed index |
| Hybrid | `retrieve_hybrid` uses explicit source lists and candidate pools; collaborative sources stay train-known and content can supply eligible cold items | The caller must provide collaborative rankings, train context, exact item pool, and config; provenance does not prove model training scope |
| Fusion | Weighted RRF uses one-based original ranks, stable item-key tie breaks, explicit weights/depths, catalog/seen filters, and no implicit fallback | No active serving policy or per-model release provenance |
| Collaborative models | Popularity, item-CF, BPR, and Two-Tower rankers support offline use; Two-Tower checkpoint loading is CPU/weights-only | These are offline research artifacts, not promoted serving artifacts. BPR/Two-Tower checkpoints contain private identifier mappings and are not general public artifacts |
| Catalog/domain | `ProductMetadata` is a core data contract; canonical product IDs are source scoped | Phase 6.1B adds an in-memory synthetic app-catalog schema and deterministic eligibility checks; there is no production catalog repository |
| Release lifecycle | Offline reports/manifests capture hashes and configurations | No immutable serving release manifest, compatibility gate, promotion authorization, rollback, or hot-swap lifecycle |

The application boundary should be a domain-level `RecommendationService` in
the modular monolith. FastAPI validates/translates HTTP input and output;
`recfusion_core` owns versioned public contracts; an application service
resolves an allowlisted policy and compatible immutable artifacts; ML
retrievers return candidate IDs; the catalog provider resolves and verifies
those IDs; deterministic eligibility/seen/constraint checks run before the
response. Neither the route nor an agent should invoke SQL, load arbitrary
files, or bypass the catalog check.

## Proposed request contract

Route: `POST /v1/recommendations`. The route version and body schema version
are both explicit; incompatible schema changes require a new schema version.
Unknown fields and unsupported modes/policies are rejected. Clients cannot
specify filesystem paths, artifact hashes, candidate lists, RRF weights, source
rankings, raw score values, source user IDs, or model checkpoint contents.

```json
{
  "schema_version": "recfusion.recommendation-request.v1",
  "mode": "product_to_product",
  "catalog_id": "synthetic-electronics-v1",
  "algorithm_id": "tfidf_content",
  "algorithm_version": "1",
  "candidate_policy": "content_catalog",
  "query": {"product_id": "synthetic-electronics-v1:item:000042"},
  "policy_id": "content-similarity-v1",
  "k": 10,
  "constraints": {"category": null, "max_price": null}
}
```

Use a discriminated `query` union, with exactly one allowed shape per mode:

| `mode` | `query` fields | Required behavior |
|---|---|---|
| `product_to_product` | `product_id` | Resolve the visible seed in the requested catalog, retrieve similar eligible products, and always exclude the seed itself. |
| `synthetic_user` | `user_id` | Resolve only an ID from the named synthetic bundle; derive preference/seen context from that bundle's allowed history. Never accept a real Amazon user key or an arbitrary client-supplied history. |
| `hybrid` | `user_id` | Explicitly opt into the registered hybrid policy for that synthetic user. The server policy names its content and collaborative sources and fixed weights/depths; the client cannot construct source lists or tune weights. |

`policy_id` is a server-side allowlist key, not a model selector or path. It
must resolve to a registry entry compatible with the selected mode and
catalog. Unknown or incompatible policies fail explicitly. `k` is a positive
bounded integer. `constraints` is a typed set of hard filters; absent values
mean no constraint, not a preference. A missing or invalid attribute cannot
pass a corresponding hard constraint. A future contract may add fields only
with schema-version and test updates. A proposed `max_price` value is a
positive decimal amount plus an explicit three-letter currency; no implicit
currency conversion is allowed. If product price is missing, invalid, or in a
different currency, it fails that hard cap.

### Proposed initial request bounds

These are conservative guardrails for a first implementation, not measured
capacity claims or latency SLAs. Recheck them with contract and bounded-load
tests before approval:

| Input/work | Proposed limit | Basis / note |
|---|---:|---|
| Request body | 16 KiB | IDs, enums, and compact constraints only; no free text/history payload |
| `k` | 1–20 | Existing evaluation cutoffs include 5/10/20; `ContentConfig` allows at most 100 |
| Source depth | at most 100 | Consistent with the frozen Phase 3.4B research configuration; a serving policy remains server-owned |
| Hybrid sources | at most 4 configured sources | Matches the existing four-source comparison, not a requirement to enable all sources |
| Catalog/index size | no more than the artifact's declared bound and current `ContentConfig` limit | Current default content catalog bound is 50,000; load-time validation must reject larger artifacts |
| Per-request history | server-loaded only, capped by policy | No client history upload. Current Two-Tower uses up to 50 prior items; decide shared policy before implementation |
| Execution deadline | Proposed 2 seconds for retrieval work | Must be measured and revisited; not a verified SLO. No unbounded retry or sync training |

Request parsing, retrieval, catalog resolution, and serialization must each
have explicit limits. A timeout or exhausted budget returns a stable service
error, not a partial list silently treated as complete.

## Proposed response contract

Successful requests return `200` and a versioned response, including a valid
empty result when no eligible products remain. The response exposes only
catalog-owned product IDs and verified display fields; it does not expose raw
model scores, source user IDs, embeddings, training maps, or internal
recommendation lists beyond the requested result.

```json
{
  "schema_version": "recfusion.recommendation-response.v1",
  "request_id": "server-generated-correlation-id",
  "mode": "product_to_product",
  "algorithm_id": "tfidf_content",
  "algorithm_version": "1",
  "candidate_policy": "content_catalog",
  "policy_id": "content-similarity-v1",
  "catalog_id": "synthetic-electronics-v1",
  "catalog_fingerprint": "...",
  "artifact_fingerprint": "...",
  "status": "ok",
  "result_count": 1,
  "recommendations": [
    {"product_id": "synthetic-electronics-v1:item:000107", "rank": 1,
     "source_names": ["tfidf_content"], "evidence_fields": ["category", "title"]}
  ],
  "applied_constraints": {"category": null, "max_price": null},
  "provenance": {
    "catalog_id": "synthetic-electronics-v1",
    "catalog_version": "sha256:...",
    "policy_id": "content-similarity-v1",
    "artifact_ids": ["synthetic-content-index-v1"],
    "feature_schema": "recfusion.content-feature.v1",
    "synthetic_data": true
  },
  "diagnostics": {"candidate_count": 18, "eligible_count": 12,
                   "returned_count": 1, "history_event_count": 0,
                   "seen_exclusion_count": 0},
  "warnings": []
}
```

`status` is `ok` or `no_results`. Aggregate counts and bounded reason codes
are allowed; do not include item IDs in diagnostics. `source_names` are
allowlisted identifiers, not claims about causal contribution. `evidence_fields`
must name fields present on the resolved product and may be empty. Product
facts and descriptions come from the current trusted catalog lookup, never
from model output. Synthetic products and any shown attributes must be visibly
labeled as synthetic in the UI/application.

## Selection, eligibility, and temporal rules

1. Resolve `catalog_id` and `policy_id` only through server configuration. Do
   not permit request-controlled artifact paths or arbitrary model identifiers.
2. A policy selects exactly the compatible model/index release recorded in an
   immutable server-side manifest. There is no implicit model substitution or
   fallback. A separately approved, versioned policy may declare a compatible
   degradation path; if used, its strategy and artifacts must be returned in
   provenance. Without such a policy, a missing required artifact returns a
   typed unavailable error.
3. Generate candidate IDs only from the catalog/index candidate universe for
   that release. Resolve IDs from the catalog and verify they are visible and
   belong to the requested catalog before returning them.
4. Apply hard constraints deterministically after retrieval/fusion. Recheck
   the returned IDs and attributes against the catalog immediately before
   serialization; a ranker or future agent cannot reintroduce rejected IDs.
5. Remove the product-to-product seed and every item in a synthetic user's
   observed/seen set. Seen means all observations, including low or neutral
   ratings; it is not limited to positive preferences.
6. User histories, collaborative vocabularies, popularity counts, and learned
   transforms must be constructed from training/serving-eligible history only.
   Query-time profile events must be explicitly observed before the prediction
   time. Equal-time and future events are excluded. Validation/test labels and
   rows must never be loaded into a serving artifact or query profile.
7. Warm candidates must be in the release's train-known candidate set. Cold
   products can enter only through a compatible content index and must exist
   in the same catalog snapshot. No model may invent an item ID.
8. Missing, conflicted, invisible, zero-vector, or incompatible content is
   unavailable as a content candidate. Metadata unavailable means unknown; do
   not invent brand, price, or specifications. The real metadata join and
   feature-release question remains blocked under Phase 4.2C.
9. For hybrid mode, use the existing RRF semantics: original one-based ranks,
   configured fixed weights and depths, no raw score mixing, stable ascending
   canonical item ID tie break, and filtering without rank compression. An
   absent source contributes zero. If all sources are absent/empty or no
   candidates survive, return `no_results`; never substitute popularity or
   another unrequested model.
10. Sort final results by the configured deterministic ranking and stable
    canonical item ID tie break. Return no more than `k`; short lists are valid.

## Artifact compatibility and lifecycle

An immutable release manifest should identify at least:

- release ID, creation/build code revision, artifact schema versions, and
  content feature/tokenizer schemas;
- catalog ID/version/checksum, candidate policy, and canonical ID namespace;
- each model/index ID, its SHA-256, model family, expected input/feature schema,
  dimensionality where applicable, and inference configuration;
- training-source/split manifest fingerprints and the fit scope required by
  the artifact (for example train-only); evaluation report ID and evidence
  status; no raw rows, source identifiers, or private vocabulary values in the
  public manifest;
- hybrid source set, fixed weights and depths, RRF rank constant, seen-item
  policy, and candidate policy;
- release approval/provenance and the previous release ID for rollback.

At startup, validate manifest schema, hashes, safe artifact format, ID
namespace, catalog/model compatibility, feature schema, bounds, and required
dependencies before readiness. The existing content index uses validated
deterministic JSON. Existing Two-Tower checkpoints are loaded CPU-mapped with
`weights_only=True`, but are private research checkpoints and must not be
served just because they can be loaded. Do not load untrusted pickle or
arbitrary checkpoint objects.

Build artifacts offline into a new immutable location. An authorized release
process validates and approves the manifest, then atomically switches a
server-owned release pointer; retain the previous known-good version for
rollback. No in-place mutation or request-time artifact reload. On a missing,
corrupt, incompatible, or unapproved required artifact, readiness is false or
the request returns `MODEL_UNAVAILABLE`/`CATALOG_UNAVAILABLE`; never silently
fall back. A predeclared and surfaced fallback is a separate explicit policy,
not an automatic recovery behavior. There is currently no registry, promotion
route, release approval identity, rollback implementation, or
serving-authorized model.

## Synthetic catalog provider

The first provider is a deterministic, local-only fixture/bundle, separate
from Amazon source data and the live product catalog. A proposed
`recfusion.synthetic-catalog.v1` bundle contains invented product records,
invented user keys and interactions, explicit visible/eligible flags,
category and optional clearly synthetic price values, content-index inputs,
and a manifest with schema version, generator code revision, fixed seed,
configuration hash, bundle checksum, and an explicit `synthetic: true` marker.
Product IDs use a namespace such as
`synthetic-electronics-v1:item:<stable-id>`; user IDs use a distinct synthetic
namespace. No real Amazon ID, title, review, metadata, image, or derived pilot
mapping may be copied into the bundle.

The provider contract should be read-only:

```text
SyntheticCatalogProvider.get_catalog(catalog_id) -> CatalogSnapshot
SyntheticCatalogProvider.get_product(catalog_id, product_id) -> Product | None
SyntheticCatalogProvider.get_visible_products(catalog_id, item_ids) -> products
SyntheticHistoryProvider.get_history(catalog_id, synthetic_user_id) -> events
```

It verifies bundle version/hash at load, rejects unknown namespaces and
duplicate IDs, caps record counts, returns deterministic ID ordering, and
does not mutate source files. Catalog eligibility and visibility are
independent of whether a product appears in a recommendation model. A
synthetic provider cannot be selected in production configuration. If the
bundle is absent or invalid, synthetic recommendation readiness fails closed.
All screens and exported examples must identify this data as invented; no
Amazon metadata or image coverage claim follows from the fixture.

## HTTP, security, and reliability boundaries

- **Local scope:** the first application mode binds only to loopback and uses
  the synthetic provider. It does not expose a public network endpoint or
  upload artifacts. Do not treat loopback as a substitute for authorization
  if the listener can be reached by other principals on a shared host.
- **Identity:** current guest/session and account authorization choices remain
  unresolved. For any persisted or non-synthetic user context, authenticate
  and authorize every lookup server-side; IDs are not proof of ownership.
  Never accept an Amazon/user key as authority. Scope synthetic IDs to the
  named bundle.
- **Errors:** retain the existing error envelope with `request_id`, stable
  error code, and generic message. Proposed status mapping: malformed/schema
  error 422; invalid hard constraint 422 (`INVALID_CONSTRAINT`); unauthenticated
  or unauthorized 401/403; unknown catalog object 404 without revealing
  cross-scope existence; rate limit 429 (`RATE_LIMITED`); unavailable catalog
  or model 503 (`CATALOG_UNAVAILABLE` / `MODEL_UNAVAILABLE`); unexpected
  failures 500 with no exception detail. No-results is a successful empty
  response, not a server failure.
- **Logging:** record request ID, route template, mode, status, latency,
  policy/release IDs, and aggregate counts only. Do not log request bodies,
  user/product IDs, histories, vectors, raw product/review text, credentials,
  or private recommendation lists. Retain no synthetic user state beyond the
  fixture/request unless a later consented persistence design is approved.
- **Network and abuse controls:** enforce request-size, `k`, candidate, source,
  history, and deadline bounds; use bounded concurrency and cancellation;
  rate-limit before expensive work. For any later non-loopback deployment,
  require a separate security review for TLS, authentication/authorization,
  CORS, CSRF where applicable, secret management, network policy, and abuse
  budgets before enabling it.
- **Failure behavior:** no synchronous training, arbitrary URL/tool call,
  implicit retry loop, partial silent result, or model fallback. Catalog
  ownership/visibility failure is fail-closed. LLM explanations are outside
  this contract; if later added, they can describe only catalog-verified
  fields on returned products and cannot alter ranking or constraints.

## Synthetic contract and security test plan

Use tiny invented fixtures and no network, real dataset, private checkpoint,
or external service. Required tests before implementation approval:

1. Each mode accepts only its versioned discriminated request and rejects
   malformed, extra, oversized, unsupported, or cross-mode fields.
2. Product-to-product excludes its seed; synthetic-user and hybrid modes
   exclude all seen items, including neutral/low observations; unknown or
   cross-catalog IDs never resolve as eligible products.
3. Catalog authorization is rechecked after retrieval and constraint filtering;
   a malicious retriever cannot inject an unknown, hidden, or other-catalog ID.
4. Category and price hard constraints fail closed on missing/invalid data;
   no reranking stage can restore a rejected product.
5. Synthetic-user contexts use only the matching bundle's eligible prior
   events. Future/equal-time and validation/test events are excluded; changing
   held-out labels does not change artifacts or rankings.
6. Hybrid tests assert source allowlisting, fixed weights/depths, original-rank
   preservation, stable RRF ties, source/candidate provenance, and no
   implicit fallback when sources are empty or unavailable.
7. Warm/cold policy tests prove collaborative sources cannot introduce cold
   items and content can return only same-catalog indexed items.
8. Manifest/hash, feature-schema, candidate-policy, ID namespace, artifact
   corruption, missing-model and incompatible-version failures block readiness
   or return the typed 503. Existing immutable release is not partially
   replaced on failure.
9. Repeat requests with identical bundle, artifacts, request and policy yield
   identical ordered IDs and aggregate diagnostics; output size and work obey
   configured caps.
10. Error envelopes include request IDs without internals; logs contain no
    query IDs, raw text, secrets, or row-level recommendation/user data.
11. API contract tests cover 200 `ok`, 200 `no_results`, 422, 401/403, 404,
    429, 503, readiness, and production docs/network configuration.

These remain proposed gates for a future HTTP API. The Phase 6.1B local
application checkpoint covers the synthetic request/response contracts and
service behavior listed in
[`OFFLINE-RECOMMENDATION-INFERENCE.md`](./OFFLINE-RECOMMENDATION-INFERENCE.md).
It adds no endpoint; the API health, readiness, error, and OpenAPI tests still
cover only the existing HTTP surface.

An error retains the current envelope shape, for example:

```json
{
  "error": {
    "code": "MODEL_UNAVAILABLE",
    "message": "The recommendation service is unavailable."
  },
  "request_id": "server-generated-correlation-id"
}
```

The HTTP status is determined by the typed error mapping above. Existing
`MODEL_UNAVAILABLE`, `CATALOG_UNAVAILABLE`, and `RATE_LIMITED` codes are
available in the API error enum; route-specific use remains unimplemented.

## Decisions and unresolved questions

Proposed for owner review: use one versioned route with an explicit mode
union; keep policy/source weights server-side; use only immutable compatible
artifacts; fail closed with no automatic fallback; make synthetic catalog and
history providers local/read-only and visibly labeled; and return `no_results`
as a successful empty response. Proposed initial resource limits are not
verified service budgets.

Open before endpoint implementation: whether the first app needs synthetic
user and hybrid modes at all; exact catalog/constraint schema and handling of
synthetic prices; a serving artifact manifest and registry/promotion owner;
approved model policy (currently none); serving-compatible user-history
semantics; authentication/session and retention; how model availability and
catalog versions change; chosen resource limits and target hardware; and
whether any non-loopback deployment is in scope. Resolve with project-owner
review and relevant tests; keep Phase 4.2C and real metadata authorization
separate.

## References

- [ARCHITECTURE.md](./ARCHITECTURE.md) — modular boundaries, request path, and
  artifact/version principles.
- [ML-SYSTEM.md](./ML-SYSTEM.md), [CONTENT-RETRIEVAL.md](./CONTENT-RETRIEVAL.md),
  and [HYBRID-RETRIEVAL.md](./HYBRID-RETRIEVAL.md) — offline model/content/RRF
  behavior and limitations.
- [DATA-CONTRACTS.md](./DATA-CONTRACTS.md) and [SECURITY.md](./SECURITY.md) —
  identity, provenance, privacy, and trust boundaries.
- [EVALUATION.md](./EVALUATION.md),
  [RECOMMENDATION-RESEARCH-SYNTHESIS.md](./RECOMMENDATION-RESEARCH-SYNTHESIS.md),
  and [DECISIONS.md](./DECISIONS.md) — evidence status and open decisions.
