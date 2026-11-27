# Phase 7.1A/7.1B — Unified Synthetic Catalog Design and Closure

**Status:** Phase 7.1A design baseline; Phase 7.1B owner-directed
implementation is recorded in the closure section below. The implementation
does not authorize model training, real-data access, or production serving.
ADR-018 and ADR-019 remain Proposed. Phase 4.2C remains ON HOLD.

**Baseline reviewed:** `794e6b1dbf5ab2e9a6c3f1b023cd4dfaa8550daa`
(`docs(demo): document end-to-end synthetic application acceptance`), dated
2026-11-27. The working tree was clean at the start of this design review.
Phase 6.4 acceptance documentation is committed; its roadmap status remains
conditional pending owner review.

Related contracts: [synthetic frontend](./SYNTHETIC-FRONTEND.md),
[synthetic API](./SYNTHETIC-RECOMMENDATION-API.md),
[offline inference](./OFFLINE-RECOMMENDATION-INFERENCE.md),
[local integration](./LOCAL-FRONTEND-API-INTEGRATION.md),
[content retrieval](./CONTENT-RETRIEVAL.md), and
[hybrid retrieval](./HYBRID-RETRIEVAL.md).

## 1. Existing catalog inventory (Phase 7.1A baseline)

### Frontend fixture

Source: retired [`catalog-data-v1.json`](../apps/web/features/catalog/archive/catalog-data-v1.json),
consumed by [`apps/web/lib/catalog.ts`](../apps/web/lib/catalog.ts).

| Property | Current value |
|---|---|
| Product count | 13 |
| Top-level schema | `recfusion.synthetic-electronics-frontend.v1` |
| Catalog ID | `synthetic-electronics-v1` |
| Product IDs | `synthetic-electronics-v1:item:000001` through `...000008`, then `...000011` through `...000015` |
| Categories | `laptop` (3), `headphones` (3), `smartphone` (2), `monitor` (2), `accessory` (3) |
| Fields | `id`, nullable `name`, `category`, `description`, nullable-value `specifications` map, `cohort`, `recommendationEligible`, `visible`, `synthetic` |
| Visibility | All 13 records have `visible: true` and `synthetic: true` |
| Cohort values | IDs 1–5 are `warm`; 6–7 and 11–15 are `cold`; ID 8 is `unknown` |
| Recommendation eligibility | IDs 1–7 are eligible; ID 8 and IDs 11–15 are ineligible |
| Route behavior | Static params are generated for each product. The route ID replaces every `:` with `-`; no slug is stored in the fixture. Unknown slugs call Next.js `notFound()`. |
| Fingerprint | SHA-256 of the exact catalog JSON bytes: `9314ae2a389269c8a641c0befb4157a05160de568b9dd9a718b71a29bc1f7657` |

The fixture includes explicit null specification values and an item with no
display name. It has no price, ratings, reviews, availability, or product
source fields. The separate recommendation fixture file has its own raw-byte
SHA-256 (`eb1b6a178b74bec9e767d32cac86315691215e04f12eddd5950c64d1c1600451`);
that hash is not a product-catalog fingerprint.

The frontend sorts by canonical ID before exposing the catalog. It checks the
top-level schema and catalog ID and requires visible synthetic records. Tests
check current ID uniqueness and route round-trips, but there is no explicit
runtime rejection for duplicate route slugs before the route map is built.

### Backend inference catalog

Source: [`apps/api/src/recfusion_api/services/synthetic_catalog.py`](../apps/api/src/recfusion_api/services/synthetic_catalog.py),
adapted to the `SyntheticProduct` contract in
[`packages/recfusion_core/contracts/recommendation.py`](../packages/recfusion_core/contracts/recommendation.py).

| Property | Current value |
|---|---|
| Product count | 10 |
| Catalog schema | `recfusion.synthetic-catalog.v1` |
| Catalog ID / version | `synthetic-electronics-v1` / `1` |
| Generator schema / default seed | `recfusion.synthetic-electronics-generator.v1` / `44041` |
| Canonical item IDs | `synthetic-electronics-v1:item:{number:06d}`, for numbers 1–10 |
| Categories | `laptop` (4), `smartphone` (1), `audio` (2), `monitor` (1), `accessory` (1), and one `null` category |
| Product fields | `item_key`, nullable `title` and `category`, string-tuple `description` and `features`, optional `Money`, source-record SHA-256, `catalog_eligible`, and `visible` |
| Product ordering | Sorted by canonical `item_key`; the seeded shuffle is followed by this sort |
| Catalog fingerprint | `d8f61df61a5595611faf2f6d4d75e44299e221778ac98e87d566e6bd3805b46d` for the default seed; SHA-256 of compact, sorted-key canonical product records |
| Bundle fingerprint | `afe98b2328f40cb8fee63bba22586edf77b68caeb141df3383eb2285216776e1` for the default seed; includes catalog fingerprint, version/seed/generator schema, train events, and fixed collaborative rankings |

Products 1–7 have invented title, category, description, features, and USD
constraint values. Product 8 has no title, category, description, features,
or price, while remaining visible and catalog-eligible; it has no content
vector from which to retrieve. Product 9 is the conflict test record and is
catalog-ineligible; product 10 is hidden. Both also have synthetic USD
constraint values. These flags are independent: the current model has no
structured conflict-reason field. The USD values are
synthetic inference inputs, not current commercial prices and are not part of
the frontend display contract.

The five train-known products are IDs 1–5, from five synthetic train events
for three synthetic user contexts. IDs 6–7 are visible, catalog-eligible
cold products with content. The warm-only hybrid candidate policy restricts
collaborative and final candidates to train-known products; the
content-eligible hybrid policy can include eligible content-only cold
products. A non-train-known product is not automatically cold-eligible: it
must also be visible, catalog-eligible, and a candidate in the fitted content
index.

The backend computes each product fingerprint from its ID, fields, flags,
catalog ID, and seed using canonical JSON. The catalog fingerprint covers the
sorted product records. The separate bundle fingerprint covers the catalog
fingerprint plus generator/version state, train interactions, and synthetic
collaborative rankings. The inference artifact records both fingerprints,
the generator provenance, algorithms/policies, vocabulary hash, and content
index checksum.

### Identity and metadata mismatch

Both sides currently use the same `synthetic-electronics-v1` namespace. That
namespace overlap is not proof that equal suffixes identify equal product
records. The front-end set is IDs 1–8 and 11–15; the backend set is IDs 1–10.
IDs 9–10 exist only in the backend, and IDs 11–15 exist only in the frontend.
IDs 1–8 overlap, but there is no reviewed cross-catalog mapping or shared
fingerprint. Their fields and category vocabulary differ: for example, the
backend uses `audio` where the frontend uses `headphones`, backend content is
an ordered text list, and frontend specifications are a key/value map.
Backend ID 8 has no category while frontend ID 8 says `accessory`.

At this Phase 7.1A baseline the frontend rendered API recommendations as
canonical-ID-only results because fingerprints differed. Do not join records
by title, category similarity, or matching numeric suffix. Phase 7.1B below
records the shared-asset migration and exact-fingerprint join rule.

## 2. Authoritative catalog options

| Criterion | A — Backend catalog is authoritative | B — Shared versioned JSON | C — Separate catalogs plus explicit map |
|---|---|---|---|
| Implementation complexity | Medium: frontend needs a deterministic export/build input or runtime API access; backend Python remains the source | Medium: define one schema and two adapters; validate Python package-data and Next.js static import behavior | Low at first, rising with every record/version; map and conflict audit must stay synchronized |
| Determinism | High if export ordering, seed, and serialization are fixed | High; one checked-in byte source, stable ordering, and SHA-256 | High only if the map and both catalogs are version-pinned |
| Schema compatibility | Medium: frontend display fields and backend inference fields still need an explicit projection | Medium: schema can separate display from retrieval fields, with typed adapters in both languages | Low to medium: each catalog keeps its own schema and every mapped field needs a rule |
| Static frontend compatibility | Medium: a build-time export step is required; fetching the API would break offline/static behavior | High by design: Next imports the shared JSON during build; implementation must prove monorepo and package-data inclusion | High; frontend keeps its existing static fixture |
| Inference artifact compatibility | High impact: any product-catalog change invalidates the current strict fingerprint pin | High impact: same strict pin; rebuilding is explicit and testable | Low if the backend catalog and item IDs stay unchanged; mapping changes do not affect retrieval |
| Product display quality | Medium until display-only attributes are authored and reviewed | High after display fields are added without changing retrieval text | High for currently mapped products; unmapped API IDs remain ID-only |
| Rebuild requirements | Catalog exporter, frontend build, fingerprinted inference artifact | Shared JSON, both validators, static frontend build, inference artifact, cross-language fingerprint checks | Mapping file and frontend build; backend artifact can remain unchanged |
| Testing effort | Medium | Medium to high initially; lower steady-state drift risk | High over time: mapping completeness, stale versions, collisions, and unknowns |
| Maintenance cost | Medium; frontend depends on backend export process | Low to medium; one product source with separate consumer adapters | High; two evolving catalogs plus crosswalk |

### Recommendation — Option B (approved by owner for implementation)

Use one versioned, synthetic-only JSON product catalog as the authority. It
fits the current offline/static frontend, avoids a browser-time API dependency,
and gives Python and TypeScript the same exact product bytes to validate. Keep
the backend synthetic interaction histories, user contexts, and authored
collaborative rankings in a separate backend-only inference bundle; they are
not product display data. Adapt the shared products to the existing
`SyntheticProduct` contract without changing retrieval functions or API v1.

Place the asset under a shared package-data location such as
`packages/recfusion_core/data/synthetic-electronics-v2.json`. The backend
should load it with package-resource APIs; the frontend should import the
same file at build time. Whether Next.js can bundle the sibling workspace JSON
and whether setuptools includes it in distributions must be verified in
Phase 7.1B before choosing the final path. Do not add `output: "export"` or
make the frontend depend on a running API as part of this design.

Option A is a reasonable alternative if the team explicitly wants Python to
own catalog authoring, but a stable exporter is still needed for the
offline/static frontend. Option C is a safe temporary bridge only for
individually reviewed mappings; it does not remove duplicate catalog
maintenance and cannot resolve the current mismatches automatically.

## 3. Proposed shared schema and display rules

**Proposed schema identifier:** `recfusion.synthetic-catalog.v2`. This is a
new schema; do not reinterpret the backend generator's existing v1 envelope
or the frontend-specific v1 fixture schema. Keep three versions distinct:

- `schema_version` identifies the JSON structure.
- `catalog_id` identifies the canonical item-ID namespace. Preserve
  `synthetic-electronics-v1` while its identity format remains in use.
- `catalog_version` identifies the immutable product snapshot; increment it
  for any record, eligibility, or route change. Use a new catalog ID if the
  identity namespace itself changes.

Proposed record shape (types are normative; values are illustrative only):

```json
{
  "schema_version": "recfusion.synthetic-catalog.v2",
  "catalog_id": "synthetic-electronics-v1",
  "catalog_version": "2",
  "provenance": {
    "data_kind": "synthetic",
    "generator_schema": "recfusion.synthetic-electronics-generator.v1",
    "generator_seed": 44041,
    "source_revision": "<reviewed catalog authoring revision>"
  },
  "products": [
    {
      "canonical_item_id": "synthetic-electronics-v1:item:000001",
      "route_slug": "synthetic-electronics-v1-item-000001",
      "display": {
        "name": "Synthetic display name",
        "category_label": "Laptop",
        "description": "Invented example, clearly labeled synthetic.",
        "specifications": {"Memory": "16 GB", "Weight": null}
      },
      "retrieval": {
        "title": "Synthetic laptop 16GB RAM 512GB SSD",
        "category": "laptop",
        "description": ["invented electronics catalog example"],
        "features": ["16GB memory", "512GB SSD", "USB-C"]
      },
      "eligibility": {
        "visible": true,
        "catalog_eligible": true,
        "cohort": "warm",
        "metadata_status": "complete"
      },
      "synthetic": true
    }
  ]
}
```

The example does not authorize these exact display values as a migration map.
For every record, `retrieval` must preserve the backend's exact current
`content_fields` values and ordering for existing IDs unless an owner-reviewed
decision accepts a ranking-affecting change. `display.specifications` is
presentation-only and must never be parsed into retrieval text implicitly.
Use a canonical category code for backend retrieval and an explicit
`category_label` for UI wording; the `audio` → `Headphones` label is an
explicit taxonomy presentation rule, not an identity match.

The safe display projection may contain only the canonical ID, explicitly
invented display name, category label, invented description, invented
specifications, stable route slug, catalog version, and optional trusted
eligibility metadata. Preserve missing values as `null` and display them as
unavailable. Do not display reviews, ratings, customer information, real
prices, current prices, availability, certifications, or unverified
recommendation explanations. Existing USD values remain synthetic
constraint-only inputs if required by the existing backend contract; they
must not be included in the display projection or presented as commercial
prices.

`metadata_status` is proposed as `complete`, `partial`, or `conflicted`.
Conflicted records are never recommendation-eligible; disputed field values
are not displayed. Partial records retain null/unknown attributes. Set
visibility and eligibility independently. Cohort values are optional and
must be supported by the active trusted training/catalog data. Do not infer
`cold` merely from absence in the training set: content eligibility and the
active reference vocabulary also matter. The v1 API response does not expose a
separate bundle fingerprint or per-item cohort, so API result cards must not
show per-item warm/cold labels unless the exact catalog and eligibility
provenance can be verified. A `warm_hybrid` policy label may describe the
request policy; it is not a substitute for per-item provenance.

## 4. Canonical IDs, ordering, and routes

- Preserve existing backend canonical IDs exactly for existing backend
  products. Do not renumber IDs based on display order, title, or category.
- Treat IDs as opaque outside a versioned parser. The current backend pattern
  is `synthetic-electronics-v1:item:{six-digit-number}`; generated API IDs
  are validated against the synthetic namespace.
- Give frontend-only items IDs only through an explicit owner-reviewed
  migration manifest. Do not claim they already correspond to backend items
  because their suffixes or titles look similar.
- Keep products in ascending canonical-ID order in the JSON array. Consumers
  preserve that ordering; sorting/filtering may create views but must not
  mutate the source order.
- Preserve current route slugs for existing frontend IDs by replacing `:`
  with `-` (for example `synthetic-electronics-v1-item-000001`). Do not
  derive routes from display names or mutable specifications.
- Store or deterministically compute the route slug from the canonical ID,
  then reject duplicate IDs and duplicate slugs before constructing maps.
  Restrict slugs to a Windows-safe lowercase ASCII route alphabet with a
  non-reserved prefix. Unknown IDs continue to use the current explicit
  not-found/unknown-item behavior; never guess a nearest item.
- Keep catalog source/version provenance on the manifest and include it in
  the fingerprinted bytes. Retain per-record source fingerprints where the
  backend contract requires them.

## 5. Fingerprint and compatibility policy

Use SHA-256 of the **exact shared JSON file bytes** as the shared
`catalog_fingerprint`. The frontend already fingerprints exact fixture bytes;
the backend currently hashes canonical product-record objects, so this
algorithm changes during migration and requires regeneration of the existing
inference artifact. Both consumers must hash the same bytes, not independently
serialize parsed objects. A formatting-only change will also change this
fingerprint and must be treated as a new catalog snapshot.

Keep `bundle_fingerprint` separate. It must pin the shared catalog
fingerprint plus the generator schema/seed, train interactions,
collaborative rankings, and any inference-relevant policy configuration.
Keep `artifact_fingerprint` as the checksum of the complete inference
artifact. The API v1 response can remain unchanged: it already returns
`catalog_id`, `catalog_fingerprint`, and `artifact_fingerprint`. The frontend
may join a recommendation ID to display metadata only when both catalog ID
and exact catalog fingerprint match. On mismatch or unknown ID, keep the
current ID-only safe rendering; do not silently fall back to a similarly
named fixture.

Compatibility requires all of the following before serving a catalog/artifact
pair:

1. Exact schema version is supported by both validators.
2. Catalog ID and full catalog fingerprint match.
3. Bundle fingerprint matches the active inference bundle.
4. Artifact schema, checksum, content-index schema, vocabulary hash,
   vectorizer configuration, algorithm versions, and candidate policies
   match the active service.
5. Candidate and train-known IDs belong to the catalog, and visible,
   eligibility, and conflict policies are applied deterministically.

At the Phase 7.1A baseline, the loader validated the catalog fingerprint and
artifact checksums but did not compare the bundle fingerprint to an expected
active bundle. The Phase 7.1B implementation below adds that internal check
and a separate inference compatibility check without an API v1 schema change.

## 6. Artifact and ranking implications

No artifact or model is rebuilt in Phase 7.1A. In the later migration:

| Change | Required action |
|---|---|
| Shared catalog bytes, IDs, eligibility, or catalog version change | Regenerate the catalog fingerprint and the inference artifact; the current loader rejects stale catalog fingerprints. |
| Retrieval title/category/description/features change | Refit TF-IDF vocabulary and IDF, rebuild the content index, and rerun deterministic rankings and parity checks. |
| Product additions/removals or eligibility changes | Rebuild candidate keys/index and recheck warm/cold candidate policies and all three API modes. |
| Train interactions or synthetic collaborative rankings change | Recompute bundle fingerprint and revalidate/rebuild the artifact envelope and hybrid source rankings. |
| Display specifications, label, or route changes | Under the proposed single exact-byte catalog fingerprint, rebuild/revalidate the artifact even if retrieval text is unchanged. This conservative rule avoids a display/API mismatch. |
| API policy, RRF weights, or retrieval algorithms change | Out of scope for this migration; require a separate reviewed change and compatibility/version decision. |

Before migration, capture the default catalog/bundle/artifact fingerprints
and the ordered recommendation IDs for product-to-product,
synthetic-user-content, and both supported hybrid candidate policies. The
serving artifact is currently prepared from the synthetic catalog during API
startup; there is no promoted production model or registry. Exact unchanged
retrieval fields and candidate sets should preserve existing outputs. If any
ordered IDs change, stop and explain the source of the difference rather
than calling the change harmless.

## 7. Migration and rollback sequence for Phase 7.1B

1. Obtain owner review of this proposal and the field-level identity
   disposition for every overlapping ID. Preserve backend IDs; do not infer
   identity from title or similarity.
2. Freeze baseline fingerprints, canonical retrieval fields, candidate sets,
   and ordered outputs for the existing API v1 modes. Keep all data synthetic.
3. Create the shared JSON and cross-language schema validators. Copy
   backend retrieval fields exactly for IDs 1–10. Add frontend display
   attributes only as explicitly authored synthetic fields with nulls for
   unknowns. Promote frontend-only IDs only through an explicit manifest;
   do not reuse backend conflict/hidden IDs.
4. Add backend and frontend adapters. Keep the current API request/response
   schema, policy allowlist, retrieval code, and RRF configuration unchanged.
5. Validate raw-byte catalog fingerprint parity, uniqueness, ordering,
   slugs, package-data inclusion, Next build/prerender behavior, and stale
   artifact rejection.
6. Regenerate the synthetic TF-IDF artifact from the approved shared catalog
   and bundle. Compare ordered recommendation IDs and candidate eligibility
   with the frozen baseline. Fail closed on any mismatch.
7. Switch both consumers to the shared asset in one reviewable change. Do not
   ship a state where the frontend and API read different catalog versions.
8. Roll back atomically by restoring the prior frontend fixture, backend
   generator/catalog, and matching artifact/fingerprints together. Never pair
   the old artifact with the new catalog or vice versa.

## 8. Regression test plan

| # | Test | Expected invariant |
|---:|---|---|
| 1 | Canonical ID uniqueness and grammar | No duplicates; every ID belongs to the declared namespace and item kind. |
| 2 | Slug uniqueness | Duplicate or malformed slugs fail validation before map construction. |
| 3 | Windows-safe static routes | Slugs use the allowlisted safe alphabet, have a safe prefix, and round-trip through static params. |
| 4 | Cross-language schema validation | TypeScript and Python accept the same valid JSON and reject the same malformed fields, null/type errors, unknown schema versions, and duplicate entries. |
| 5 | Catalog fingerprint equality | Frontend and backend SHA-256 of the exact asset bytes is identical and matches the checked manifest. |
| 6 | Artifact compatibility | Stale catalog, bundle, artifact, vocabulary, schema, or vectorizer fingerprints fail closed. |
| 7 | Missing/unknown product behavior | Missing display fields stay unavailable; unknown route is not-found; unknown valid API ID remains ID-only. |
| 8 | Warm/cold eligibility | Warm-only excludes non-train-known items; content-eligible policy admits only trusted eligible cold candidates. |
| 9 | Metadata conflict | Conflicted items cannot enter recommendation candidates or expose disputed attributes. |
| 10 | Product-to-product regression | Same request, seed, catalog, and retrieval text produce the frozen ordered IDs and provenance. |
| 11 | Synthetic-user regression | Strictly prior train history and existing seen/target masks remain unchanged. |
| 12 | Hybrid regression | Existing source rankings, source order, RRF policy, eligibility, and ordered outputs remain unchanged. |
| 13 | Response-to-card mapping | Display join requires exact `catalog_id` and fingerprint; mismatch never shows a guessed product card. |
| 14 | Deterministic build | Repeated generation/build yields byte-identical catalog JSON, ordering, slugs, and fingerprints. |
| 15 | No real-data access | Tests/build use checked-in invented fixtures only; no Amazon files, private checkpoints, or external fetches. |
| 16 | API v1 compatibility | Existing request/response schema, policy IDs, and error contracts are unchanged. |
| 17 | No unexpected ranking changes | Frozen per-mode canonical recommendation IDs match; any difference blocks migration pending explanation and approval. |

These are proposed Phase 7.1B tests, not tests run in this design phase.

## 9. Data governance and open decisions

- Keep the shared catalog invented, local, and visibly labeled synthetic.
- Do not copy Amazon IDs, review text, ratings, images, metadata, or derived
  private records into it. No real-data access is required for this phase.
- Do not display synthetic USD constraint values as commercial prices. Do
  not introduce ratings, reviews, current availability, certifications, or
  unsupported explanations.
- Keep catalog display metadata separate from the inference bundle's user
  contexts, train events, and collaborative rankings. Do not put user
  histories or identifiers into a frontend asset.
- Preserve missing values as unknown. Conflict must fail closed for
  recommendations; no title-based precedence or fuzzy reconciliation.
- ADR-018 and ADR-019 remain Proposed. Phase 4.2C remains ON HOLD. This
  design does not authorize production serving, deployment, or model
  promotion.

The Phase 7.1B owner instruction resolves the design choices above: Option B
is approved; the shared asset is authoritative; backend IDs 1–10 remain
unchanged; no title/suffix join or frontend-only ID promotion is allowed;
IDs 11–15 and prior frontend recommendations are archived; ID 8 remains
incomplete, ID 9 remains visible but ineligible, and ID 10 remains hidden;
catalog ID stays `synthetic-electronics-v1` with version `2`; synthetic USD
constraints remain backend-only. No open identity choice remains for this
implementation.

## 10. Phase 7.1B implementation direction

Implementation uses shared package-data JSON, strict Python and TypeScript
validators, separate asset-byte/compatibility/bundle fingerprints, matching
backend and frontend adapters, and regression tests. It preserves API v1,
existing ranking policies and weights, and the captured output order. It does
not start Phase 7.2 or change ADR status.

## 11. Validation performed for Phase 7.1A

- Read the repository agent instructions and the requested architecture,
  contract, frontend, API, inference, retrieval, security, testing, decision,
  and roadmap documents.
- Inspected the frontend catalog JSON, catalog/route implementation,
  fingerprint manifest and tests, backend synthetic catalog generator,
  core product contract, inference artifact loader, service compatibility
  checks, and product detail route.
- Confirmed default backend values by running the local deterministic
  synthetic catalog builder offline; no artifact was rebuilt.
- Confirmed Phase 6.4 acceptance documentation is committed at `794e6b1` and
  ADR-018/019 remain Proposed; Phase 4.2C remains ON HOLD.
- No runtime code, API schema, ranking behavior, Roadmap, ADR, model, or
  artifact was changed. No tests were run because this phase only adds a
  design document.
- Markdown links point to checked-in files. The final staged diff check and
  Git status are recorded in the task report. No commit or push is authorized.

## 12. Phase 7.1B implementation closure

The active asset is
[`packages/recfusion_core/data/synthetic-electronics-v2.json`](../packages/recfusion_core/data/synthetic-electronics-v2.json),
with its exact-byte and inference-compatibility hashes pinned in the adjacent
manifest. Python and TypeScript consume the same bytes. The backend keeps
synthetic price constraints outside that frontend-shipped asset. The active
frontend catalog exposes visible IDs 1–9, while ID 10 remains in the shared
source but has no UI route; content requestability is derived from backend
eligibility and recorded content.

The API v1 `catalog_fingerprint` now carries the exact shared asset SHA-256.
The inference artifact separately pins asset, compatibility, and bundle
fingerprints; stale expected values fail closed. Frozen IDs/provenance are
compared against
[`tests/fixtures/phase_7_1b_v1_baseline.json`](../tests/fixtures/phase_7_1b_v1_baseline.json).
Previous frontend-only records and recommendation outputs remain archived.

Validation performed for Phase 7.1B:

- Frontend frozen install, typecheck, all 42 tests, and production build passed.
  Biome lint completed with 22 warnings (18 CSS specificity and 4 intentional
  reduced-motion `!important` warnings).
- Backend frozen offline sync and lock check, Ruff check/format, mypy (81
  source files), and all 369 pytest tests passed.
- The built Python wheel includes both the shared catalog and manifest.
- Direct loopback smoke passed all four non-empty API policies and returned
  404 for an unknown synthetic user. The ordered product-query IDs matched
  the frozen baseline.
- The browser was not opened for this phase; no browser/network evidence or
  new viewport measurements were captured. Phase 6.4 responsive widths stay
  unverified.

ADR-018/019 stay Proposed; Phase 4.2C stays ON HOLD. No commit, push,
deployment, or Phase 7.2 work is part of this closure.
