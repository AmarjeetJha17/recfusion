# Phase 7.2 — Verified Synthetic Recommendation Product Cards

**Status:** Implementation and local acceptance evidence prepared for owner
review. Phase 7.2 is not owner-accepted. No backend ranking, API v1 contract,
artifact validation, or local-only security policy changed.

## Identity verification

The frontend reuses the existing TypeScript adapter in
[`apps/web/lib/catalog.ts`](../apps/web/lib/catalog.ts), which validates the
shared `recfusion.synthetic-catalog.v2` asset and its record set. The card
resolver receives that trusted catalog context and the response identity; it
does not parse catalog JSON or reconstruct product metadata.

For a product card, the resolver requires all of the following:

1. The trusted context is catalog `synthetic-electronics-v1` with the exact
   asset fingerprint from the checked manifest.
2. The API v1 response has that same catalog ID and byte-level asset
   fingerprint. `artifact_fingerprint` remains provenance and is not used as a
   substitute for catalog compatibility.
3. The response `product_id` matches a canonical product ID exactly and has
   exactly one record in the trusted catalog. Repeated response IDs and
   duplicate catalog membership resolve as ambiguous.
4. The matched record is visible, catalog-eligible, content-eligible, and
   synthetic.
5. A detail link is created only when the existing canonical-ID-to-slug
   mapping resolves back to the same catalog product.

No title/category lookup, suffix join, metadata construction, ranking, or score
calculation occurs in the frontend. The existing response contract already
contains the catalog ID and asset fingerprint; no API v1 fields were added.

## Card fields and provenance

Resolved cards show the response rank, shared-catalog name, category,
description, recorded synthetic features, canonical ID, and existing source
and reason provenance. Algorithm ID/version and candidate-policy identifiers
remain in the response provenance panel. Product detail navigation uses the
verified route. Existing local SVG artwork is reused; no new image assets were
added.

Missing optional display values remain unavailable and are not guessed. Cards
contain no prices, ratings, reviews, stock claims, purchase actions, or
unsupported warm/cold labels. RRF provenance is described as source-list
membership, not causal preference explanation. Actual rank order, result
count, requested count, short lists, and empty-result behavior are preserved.

## Unknown, mismatched, and restricted results

| Condition | Presentation |
| --- | --- |
| Catalog ID/fingerprint mismatch | Keep the response rank, canonical ID, and response provenance; withhold product metadata and route. |
| Unknown canonical ID | Keep an ID-only result and safe diagnostic; do not guess a product. |
| Duplicate/ambiguous identity | Preserve each response item and rank; withhold metadata and navigation. |
| Hidden product | Preserve rank and provenance, report a restricted result, and withhold its ID and product details. |
| Visible but ineligible or incomplete result | Preserve rank and provenance; raise a policy-integrity alert and withhold product details. |
| Missing optional display fields | Render unavailable markers without changing recommendation status or count. |
| Invalid/unavailable detail route | Do not render a link; the resolver reports route unavailability. |

The current shared catalog exposes `catalog_eligible` but no conflict-reason
field. A returned ineligible item is reported as a generic policy-integrity
issue; the frontend cannot safely distinguish a conflict from another reason
for ineligibility. It does not disclose hidden record details. Product 9 is
visible but ineligible; product 10 is hidden; product 8 is incomplete and not
content-eligible.

## Fixture and Local API modes

Fixture mode uses the same shared catalog and resolver, is deterministic, and
requires no API. Local API mode remains explicit, development-only, fixed to
`127.0.0.1:8000`, and uses the existing exact-Origin and loopback safeguards.
An API failure does not switch to fixtures. The API response must pass the
existing v1 parser before display resolution.

## Validation and evidence (2026-11-27)

### Frontend checks

- `pnpm run typecheck` — passed.
- `pnpm test` — passed: 8 files, 56 tests.
- `pnpm run lint` — passed with 21 CSS warnings (17 specificity and 4
  reduced-motion `!important` warnings); no new warning points to the card
  selectors.
- `pnpm build` — passed; `/`, `/explore`, and all nine visible product detail
  routes prerendered.
- Resolver tests cover exact identity and fingerprint checks, mismatch, unknown
  ID, duplicate/ambiguous identity, hidden and ineligible records, missing
  optional fields, and route suppression.
- Component tests cover card fields, ranks, provenance, navigation, safe
  unresolved results, counts, and restricted/ineligible behavior.

### Local browser/API smoke

Using an isolated local in-app browser at `http://127.0.0.1:3000/explore` and
services bound only to loopback:

| Path | Observed result |
| --- | --- |
| Product-to-product Local API | 5/5 results; exact catalog fingerprint; verified metadata, ranks, source, and reason fields. |
| Synthetic-user Local API | 5/5 results; history remained undisplayed; same identity and provenance checks. |
| Warm hybrid Local API | 4/5 results; short-list count was accurate and no filler was added. |
| Content-eligible hybrid Local API | 5/5 results; candidate policy and multiple source attribution were shown. |
| Product detail route | Opened the verified monitor detail route (`...item-000005`) successfully. |
| Unknown product/user API requests | Direct loopback requests returned 404 with `UNKNOWN_SYNTHETIC_PRODUCT` and `UNKNOWN_SYNTHETIC_USER`. |
| Fixture with API stopped | Fixture mode still returned its deterministic 5/5 product-to-product list. |

The browser showed the shared asset fingerprint on Local API responses and
resolved the displayed cards to the shared catalog. The browser UI did not
provide a network panel; request/response capture was not saved. Unknown ID
and fingerprint-mismatch display paths were verified by frontend tests, while
the unknown product/user status codes above were verified by direct local HTTP
requests.

The accessibility tree exposed labeled recommendation controls, result status,
rank, product links, feature lists, and source/reason lists. A keyboard Tab
reached the first card link and the focus outline was visible. This was a
targeted keyboard check, not a complete assistive-technology audit. The Next.js
development server emitted its existing smooth-scroll configuration warning;
no browser console log capture was available.

### Responsive and remaining checks

The available local browser did not expose a calibrated viewport override.
Exact 1440, 900, 700, and 375 px measurements, mobile card stacking, horizontal
overflow, reduced-motion emulation, and full keyboard traversal remain
unverified. A screenshot was inspected at the browser's default size only; no
viewport-specific evidence was saved.

No backend source was changed, so the full backend regression suite was not
rerun for Phase 7.2. The live local API modes and unknown-context HTTP paths
were exercised; the Phase 7.1B closure recorded 369 backend tests passing.

## Git, privacy, and project gates

The Phase 7.1B commit `d738c3a` is present and the worktree was clean before
Phase 7.2 changes. Only frontend source, frontend tests, and the requested
documentation are intended for staging. No dataset, model artifact, generated
build, environment file, or secret is included. No commit, push, or deployment
was performed.

ADR-018 and ADR-019 remain Proposed. Phase 4.2C remains ON HOLD. The Phase 7.2
implementation and evidence are for owner review; exact responsive browser
acceptance remains open.
