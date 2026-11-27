# Synthetic Electronics Discovery Frontend

**Status:** Phase 6.3A implementation for owner review. The UI runs locally
against invented fixtures. It is not connected to the API or a real catalog.
ADRs 018/019 remain Proposed; Phase 4.2C remains ON HOLD.

## Scope and boundaries

The Next.js App Router frontend provides catalog search, category filters,
sorting, product detail and similar-item navigation, plus a recommendation
explorer for product-to-product, synthetic-user, and hybrid requests. It
includes loading, error, empty, and result states. Catalog and recommendation
results come from static invented fixtures; the recommendation provider
validates typed v1 request/response envelopes but never calls `fetch` or any
network service. Recommendation rankings and explanations are prewritten
fixtures, not model outputs computed in the browser.

This checkpoint does not read Amazon Reviews files or metadata, load model
artifacts, train or rank in the browser, call the development API, or make
external image requests. Product artwork is authored local SVG. The displayed
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
  deterministic fixture-backed provider; no URL, credentials, or transport.
- `tests/` — synthetic-only unit and component tests.

The recommendation request model follows the API's
`recfusion.recommendation-request.v1` fields, and the response parser enforces
`recfusion.recommendation-response.v1` shape. The provider returns static
fixture outputs and validated product IDs. It does not establish API parity:
the frontend catalog includes presentation-only entries and its fixture
fingerprints are separately recorded in `lib/fixture-manifest.ts`. Phase 6.3B
must reconcile the authoritative API catalog/version and fixture provenance
before replacing the provider. Keep the provider seam typed; do not add
network fallback or expose internal API URLs in this checkpoint.

## Accessibility and responsive behavior

The interface uses the repository's design tokens, semantic headings and
controls, visible keyboard focus, accessible status/result labels, responsive
catalog layouts, and reduced-motion handling. Search and filter controls are
usable without a pointer. Manual browser review should cover narrow phone,
tablet, and desktop widths before any public demo.

## Privacy and safety

No real users, Amazon records, raw identifiers, user histories, images, or
derived dataset rows are present. Fixture recommendation modes label their
contexts as synthetic. Only invented, requestable fixture product IDs may
appear as recommendation results. No generated dataset artifact or model
checkpoint is part of the frontend package.

## Phase 6.3B entry criteria

1. Confirm this synthetic UI checkpoint in project-owner review.
2. Reconcile frontend product identifiers and catalog fingerprint against an
   authoritative catalog contract; keep unknown or unavailable fields
   explicit.
3. Select the local development API integration and its opt-in lifecycle;
   retain loopback-only operation and safe generic errors.
4. Add contract tests for each request mode and response/error behavior across
   the actual HTTP boundary, without logging request histories or identifiers.
5. Preserve the local fixture provider for deterministic offline UI tests.
6. Keep production deployment, authentication, real metadata, and Phase 4.2C
   blocked until their independent decisions are approved.
