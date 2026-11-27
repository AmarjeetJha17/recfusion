# Synthetic Electronics Discovery Frontend

**Status:** Phase 6.3C synthetic recommendation experience for owner review. Fixture
mode remains the default and works offline; Local API mode is an explicit
development-only choice. The UI does not connect to a real catalog.
ADRs 018/019 remain Proposed; Phase 4.2C remains ON HOLD.

## Scope and boundaries

The Next.js App Router frontend provides catalog search, category filters,
sorting, product detail and similar-item navigation, plus a recommendation
explorer for product-to-product, synthetic-user, and hybrid requests. It
includes loading, error, empty, and result states. Catalog and recommendation
results come from static invented fixtures by default. The separate opt-in
Local API mode calls the fixed loopback development API. Recommendation
rankings and explanations are not computed in the browser.

This checkpoint does not read Amazon Reviews files or metadata, load model
artifacts, train or rank in the browser, or make external image requests.
Product artwork is authored local SVG. The displayed catalog is the same
synthetic catalog asset used by the local API; it does not represent real
products. Prices, review content, and unverified attributes are absent.
Unavailable attributes stay unavailable.

## Local development

Requirements: Node.js 20.9 or newer and pnpm 11.25.0. From `apps/web`:

```powershell
pnpm install --frozen-lockfile
pnpm dev
```

The development server binds to `127.0.0.1`. Quality commands:

```powershell
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

The frontend package has its own lockfile and toolchain. It does not change
Python runtime dependencies. Biome provides lint/format checks; Vitest and
Testing Library cover domain, provider, component, and interaction behavior.

## Structure and UI behavior

- `app/` — App Router pages, shared layout, and responsive CSS.
- `components/` — site navigation, product cards/art/detail, catalog, and
  recommendation result presentation.
- `packages/recfusion_core/data/synthetic-electronics-v2.json` — shared
  versioned synthetic catalog, consumed by Python and Next.js.
- `features/catalog/archive/` — retired frontend-only v1 catalog fixture;
  it is not imported by the application.
- `features/recommendations/` — explicit user controls for mode, context,
  exclusions, result count, and hybrid policy.
- `lib/catalog.ts` — search, category filter, stable sorting, and similar-item
  lookup over the fixed fixture. Canonical fixture IDs keep their namespace;
  product pages use a safe colon-to-hyphen route slug for static generation.
- `lib/recommendation-provider.ts` — typed request/response validation and a
  deterministic fixture-backed provider.
- `lib/local-api-provider.ts` — centralized fixed-loopback HTTP transport,
  bounded payload and timeout handling, and sanitized API errors.
- `tests/` — synthetic-only unit and component tests.

The shared catalog keeps the existing `synthetic-electronics-v1` ID namespace
and uses `recfusion.synthetic-catalog.v2` with catalog version `2`. The exact
asset byte fingerprint and a separate inference compatibility fingerprint
are checked against `synthetic-electronics-v2.manifest.json`. Python and
TypeScript enforce the same ten IDs and strict product shape. The backend
keeps synthetic USD constraint values outside the frontend-shipped asset.
The frontend displays canonical `audio` as “Headphones”; API requests retain
`audio`.

The recommendation request and response remain v1. Frontend/API product
joins require both the catalog ID and exact asset fingerprint. Unknown IDs
remain ID-only. The requestable content set is derived from authoritative
eligibility, visibility, and recorded content; no per-item warm/cold labels
are inferred or displayed. The retired frontend-only IDs 11–15 and previous
recommendation outputs are preserved under `features/*/archive/` and are not
active. Fixture recommendation outputs were regenerated from the frozen
backend synthetic service. API errors never fall back to fixtures. The Local
API option is absent in production builds; API URL selection is unavailable
in the UI.

The Recommendation Lab's mode explanations, safe provenance presentation,
warm/cold policy labels, short-list and empty states, and retry behavior are
documented in [RECOMMENDATION-EXPERIENCE.md](./RECOMMENDATION-EXPERIENCE.md).
These are presentation-only changes over the existing v1 contract.

## Accessibility and responsive behavior

The interface uses the repository's design tokens, semantic headings and
controls, visible keyboard focus, accessible status/result labels, responsive
catalog layouts, and reduced-motion handling. Search and filter controls are
usable without a pointer. Manual browser review should cover narrow phone,
tablet, and desktop widths before any public demo.

## Privacy and safety

No real users, Amazon records, raw identifiers, user histories, images, or
derived real-data rows are present. Fixture recommendation modes label their
contexts as synthetic. Fixture results use requestable frontend fixture IDs;
Local API results join to product metadata only when catalog ID and the exact
asset fingerprint match; unknown IDs remain canonical IDs only. The frontend
package contains no generated real-data artifact or model checkpoint.

## Phase 6.3B entry criteria (historical)

1. Review the controlled local API integration and its exact-Origin boundary.
2. Preserve strict catalog identity; do not join by title or namespace alone.
3. Preserve the local fixture provider for deterministic offline UI tests.
4. Keep production deployment, authentication, real metadata, and Phase 4.2C
   blocked until their independent decisions are approved.

## Phase 6.3C review notes

The UI keeps one active result set, identifies the selected synthetic mode and
request context, and shows only response-backed provenance. It does not
display per-item warm/cold labels or compare incompatible scores. Exact
1440/900/700/375-pixel browser measurements for this checkpoint remain
unverified.

## Phase 7.1B catalog integration

The backend and frontend consume the same package-data JSON. The API response
continues to use `catalog_fingerprint` as the exact asset-byte SHA-256; the
inference artifact separately pins the compatibility projection and bundle
fingerprints. Static Next.js compilation and package inclusion are required
checks before closing this checkpoint. ADR-018/019 remain Proposed and Phase
4.2C remains ON HOLD.

## Phase 7.2 verified recommendation cards

Recommendation results use the existing TypeScript shared-catalog adapter and
an exact-ID resolver. A product card requires the response catalog ID and
asset-byte fingerprint to match the trusted shared asset, one exact canonical
record, and visible, synthetic, catalog-eligible, content-eligible flags. A
product route is linked only after the existing slug map round-trips to that
same product. No API fields or recommendation behavior changed.

Verified cards display catalog-authored names, category, description, recorded
synthetic features, canonical ID, rank, and existing provenance. Unknown or
mismatched records remain ID-only; hidden details are withheld; unexpected
ineligible results raise a policy-integrity diagnostic while retaining their
original rank and response count. Phase 7.2 implementation, tests, local smoke,
and remaining responsive limitations are recorded in
[`VERIFIED-RECOMMENDATION-CARDS.md`](./VERIFIED-RECOMMENDATION-CARDS.md).
Exact viewport measurements and full accessibility acceptance remain open for
owner review. ADR-018/019 remain Proposed; Phase 4.2C remains ON HOLD.
