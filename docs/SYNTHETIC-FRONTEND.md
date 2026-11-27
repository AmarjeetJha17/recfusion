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
Product artwork is authored local SVG. The displayed
catalog is a UI fixture and is not claimed to match the serving catalog,
metadata coverage, or any real product facts. Prices, review content, and
unverified attributes are absent. Unavailable attributes stay unavailable.

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
- `features/catalog/` — invented display fixture.
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

The recommendation request model follows the API's
`recfusion.recommendation-request.v1` fields, and the response parser enforces
`recfusion.recommendation-response.v1` shape. The provider returns static
fixture outputs and validated product IDs. The frontend and backend use the
same catalog ID but have different catalog fingerprints and product sets.
Local API results therefore show canonical IDs and source provenance only;
they do not join to frontend display metadata or product routes. Unknown IDs
with a valid API namespace render as IDs only; malformed identifiers fail
response validation. API errors never fall back to fixtures. The Local
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
derived dataset rows are present. Fixture recommendation modes label their
contexts as synthetic. Fixture results use requestable frontend fixture IDs;
Local API mode displays canonical synthetic IDs only and never invents
product metadata for them. No generated dataset artifact or model checkpoint
is part of the frontend package.

## Phase 6.3B entry criteria

1. Review the controlled local API integration and its exact-Origin boundary.
2. Preserve the distinct frontend and backend synthetic catalog fingerprints;
   do not join by title or namespace alone.
3. Preserve the local fixture provider for deterministic offline UI tests.
4. Keep production deployment, authentication, real metadata, and Phase 4.2C
   blocked until their independent decisions are approved.

## Phase 6.3C review notes

The UI keeps one active result set, identifies the selected synthetic mode and
request context, and distinguishes trusted fixture cohorts from unavailable
API v1 cohort metadata. It preserves canonical ID-only Local API results and
does not compare incompatible scores. Exact 1440/900/700/375-pixel browser
measurements for this checkpoint remain unverified.
