# Local Frontend–API Integration

> The Phase 6.3B identity and validation notes below are historical. Current
> shared catalog behavior is recorded in “Phase 7.1B shared catalog closure.”

**Status:** Phase 6.3B implementation for project-owner review. Synthetic
development use only. ADR-018 and ADR-019 remain Proposed; Phase 4.2C remains
ON HOLD.

## Architecture and mode selection

The recommendation lab keeps its deterministic, offline fixture provider as
the default. In a non-production Next.js runtime it also offers an explicit
Local API source option. That option calls the fixed endpoint
`http://127.0.0.1:8000/v1/recommendations` through
`apps/web/lib/local-api-provider.ts`; UI components do not configure or
discover backend URLs. Production builds omit the Local API selector and the
transport rejects execution when `NODE_ENV` is `production`. API failures are
shown as safe errors and never trigger fixture fallback.

The frontend sends `recfusion.recommendation-request.v1` and parses
`recfusion.recommendation-response.v1` using the existing typed contract.
Product-to-product and synthetic-user requests use `tfidf_content` v1;
hybrid requests use `weighted_rrf` v1. The UI preserves mode, candidate
policy, stable response order, source names, reason codes, and request IDs in
the contract parser. K is selected from 5, 10, or 20; the transport caps the
serialized request at 16 KiB and sends no credentials, history, model weights,
or arbitrary parameters. Calls have an eight-second abort timeout. Changing
an input cancels the active request; a monotonically increasing request token
prevents stale results from replacing current state. There are no automatic
retries.

## Catalog identity and display mapping

At the Phase 6.3B baseline, the frontend fixture and serving API shared the
`synthetic-electronics-v1` catalog ID but had distinct fingerprints and
product sets. Namespaced IDs alone were not enough evidence to join metadata.
Phase 7.1B replaces that baseline with one versioned asset and an exact
catalog-ID plus fingerprint join rule. Unknown valid IDs remain ID-only;
malformed IDs are rejected.

## Local launch

Use two local terminals. From the repository root, start the API with the
documented loopback origin and listener:

```powershell
$env:RECFUSION_SYNTHETIC_DEMO_ENABLED = "true"
$env:RECFUSION_SYNTHETIC_DEMO_MAX_CONCURRENCY = "2"
$env:RECFUSION_SYNTHETIC_DEMO_ALLOWED_ORIGIN = "http://127.0.0.1:3000"
uv run uvicorn recfusion_api.main:app --host 127.0.0.1 --port 8000
```

From `apps/web`, run `pnpm dev`, which binds to `127.0.0.1:3000`. Browse using
that exact numeric origin. Fixture mode does not require the API. The API must
be disabled outside local development; production activation is rejected.

## Local network threat model

| Boundary | Behavior |
|---|---|
| Frontend origin | `http://127.0.0.1:3000`, configured exactly in API settings |
| API listener | Uvicorn binds to `127.0.0.1:8000` |
| Browser `Origin` | Required on the recommendation route and compared exactly; absent or unexpected origins receive 403 |
| Request `Host` | Must be `localhost` or a loopback IP; malformed/public hosts are rejected |
| ASGI peer/server | Both must be loopback addresses; wildcard/non-loopback server scope is rejected |
| CORS | Exact origin only; preflight allows POST and Content-Type; no wildcard or credentials |
| Forwarded headers | Not trusted; they cannot upgrade a non-loopback peer |
| Proxy/tunnel | Unsupported. A local proxy that connects from loopback cannot be detected; do not proxy, tunnel, or expose the service |
| DNS rebinding | Frontend API target is a fixed numeric loopback address; API Host validation rejects an unrelated hostname |
| Caller identity | No authentication. Origin/CORS are browser boundaries, not authorization; another local process can call or exhaust the synthetic demo |
| Production | API routes are absent unless enabled, and enabling the backend demo in production is rejected; UI API mode is unavailable in production |

The local demo contains only invented records. These controls constrain the
intended browser path but do not secure a production service or authenticate
local processes. Do not expose it to a network.

## Error, loading, and capacity behavior

Loading is exposed through an accessible status role; errors use an alert.
The transport maps invalid requests, unknown contexts, unavailable service,
and malformed responses to sanitized messages. A typed 503
`CONCURRENCY_LIMIT_EXCEEDED` is described as temporary local capacity
exhaustion, not a model-quality result. The API has a two-request default
non-queuing inference limit. Superseded requests are aborted and stale
responses are ignored. No API error silently changes the selected source.

## Verification evidence

Synthetic frontend tests cover the offline default, explicit API selection,
fixed URL and versioned request body, safe typed 503 handling, no fixture
fallback, and refusing unknown product IDs. FastAPI contract tests cover the
exact Origin, rejected and missing Origin, bounded preflight, loopback scope,
Host checks, forwarded-header spoofing, disabled routes, production
activation rejection, request limits, typed errors, and concurrency. All
fixtures are invented. No Amazon source files, metadata, real checkpoints, or
generated real-data artifacts are read.

The API and UI fixture catalogs remain different, so returned product detail
links are intentionally unavailable in Local API mode. This is a known
catalog integration limitation, not a claim that the API omitted a returned
product. Static build and component tests do not substitute for browser
review.

## Phase 6.3B browser closure evidence (2026-11-27)

The implementation commit is `9e33ab4de0abc975fc1afed586d9cece2e8ed7f1`
(`feat(web): integrate local synthetic recommendation API`). The working tree
was clean when reviewed. The user-provided Chrome screenshot shows the
discovery page at a desktop-sized capture (1920 × 1080 image); it does not
establish a 1440 CSS-pixel viewport. A fresh workspace-host request to `/`
returned HTTP 200. A local Chrome capture of
`/products/not-a-real-product` showed the expected “We can’t find that
fixture” page and a return-to-discovery link.

| Requested viewport | Evidence reviewed | Result |
|---|---|---|
| 1440 px | Supplied 1920 × 1080 desktop screenshot; CSS viewport not recorded | Exact-width responsive result unverified |
| 900 px | Earlier local Chrome capture at browser zoom 110%, approximately 935 CSS px | Approximate evidence only; result list was readable, canonical IDs wrapped; exact 900 px and overflow measurement unverified |
| 700 px | Earlier local Chrome capture at browser zoom 150%, approximately 685 CSS px | Approximate evidence only; long IDs wrapped into narrow columns but were not visibly truncated; exact 700 px and overflow measurement unverified |
| 375 px | No local capture found | Unverified |

Local Chrome interaction evidence from this review covered the home and
Explore pages, search/category filtering, a valid product detail route, an
unknown product route, and visible keyboard focus. It also covered explicit
Local API selection and these displayed responses:

| Mode | Browser-displayed result |
|---|---|
| Product-to-product | Five recommendations; `TFIDF_CONTENT V1`, content provenance, and canonical IDs. The captured IDs were `synthetic-electronics-v1:item:000006`, `...000002`, `...000007`, `...000004`, and `...000003`. |
| Synthetic-user content | Five recommendations with content-similarity provenance; the interface stated that history stays private. Individual returned IDs were not retained in the review notes. |
| Hybrid | Four recommendations in Warm-only policy with `WEIGHTED_RRF V1`; displayed source provenance included synthetic BPR, item-CF, and content sources. Individual returned IDs were not retained in the review notes. |

With FastAPI unavailable, Local API mode displayed a safe unavailable-service
error without switching providers. After selecting Fixture mode, the hybrid
fixture request returned three fixture results and indicated that no network
request was made. The UI exposes only curated product and user contexts, so
unknown product/user identifiers were not entered through its controls. The
unknown-user 404 remains direct-HTTP evidence described below, not browser
evidence. The unknown product route was verified in local Chrome.

The earlier isolated Browser Use worker reported `ERR_CONNECTION_REFUSED` for
the workspace loopback address. It was not retried. This is a limitation of
that worker path and does not contradict the workspace-host HTTP 200 or the
local Chrome evidence above. No browser console log, DevTools Network capture,
or HAR was retained; detailed request timing, payloads, and console/network
errors remain unverified. Browser observations above are separate from the
direct HTTP smoke and automated tests. They do not establish exact-width
responsive behavior, no-overflow guarantees, or a clean browser console.

The earlier local HTTP smoke used the v1 contract directly against the
loopback API:
`/ready` returned ready; allowed-origin preflight returned 204; product-to-
product, synthetic-user, and hybrid calls each returned five recommendations;
repeating the product query returned the same ordered recommendation list;
an unexpected Origin returned 403; and an unknown synthetic user returned
404. This verifies HTTP integration, not browser end-to-end behavior. During
that earlier smoke, both development servers were bound only to `127.0.0.1`
and then stopped. The frontend was responding again during this closure
review, when `/` returned HTTP 200; the API's current process state was not
checked.

Frontend checks passed: `pnpm install --frozen-lockfile`, `pnpm typecheck`,
`pnpm test` (30 passed), and `pnpm build`. `pnpm lint` completed with 22
warnings: 18 CSS descending-specificity warnings and four reduced-motion
`!important` warnings described above. Backend checks passed: `uv sync --frozen --offline`
and `uv lock --check --offline`; Ruff check/format and mypy passed. Pytest had
363 passes and one PyTorch warning that NumPy is not installed; pre-commit
passed. Pre-commit first failed because inherited `GIT_CONFIG_*`
environment entries included empty values; it passed when rerun with those
entries removed from the hook process. The Next.js production build
prerendered `/`, `/explore`, and generated product routes. The repository does
not configure `output: "export"`, so this verifies the existing Next.js
prerender/SSG architecture rather than a standalone static-export artifact.
Production build passes; relevant routes are prerendered; standalone static
export is not configured; static-host compatibility is unverified; and no
deployment is authorized. No backend data was fetched during the build, and
no server-side API proxy was added.

## Biome warning audit

The existing reduced-motion declarations use four `!important` directives
to override component animations and smooth scrolling when the user requests
reduced motion; they are retained for that behavior. The CSS specificity
warnings arise from the global stylesheet checker comparing selectors from
unrelated component subtrees (for example `.sort-control span` and
`.hero__index span:first-child` cannot match the same element). None points
to the newly added canonical-ID wrapping rule. No warning-specific visual
defect was demonstrated in the supplied desktop screenshot or approximate
local Chrome captures; exact requested responsive widths remain unverified.
No cascade change was justified solely to silence the warnings. The
optional-chain warning in the fixture provider was removed
using an explicit missing-product guard. The exact remaining lint count is
recorded by the validation run.

## Proposed next checkpoint (historical)

Phase 7.1B defines the authoritative synthetic catalog projection and stable
route mapping. Browser-level coverage for API interaction, failures,
responsive behavior, and keyboard navigation remains separate verification.
Product identity comes from the shared asset and exact fingerprint, never
title or suffix. This checkpoint does not authorize real metadata, real-data
serving, production deployment, or changes to ADR-018/019.

## Phase 7.1B shared catalog closure

Both consumers read
[`packages/recfusion_core/data/synthetic-electronics-v2.json`](../packages/recfusion_core/data/synthetic-electronics-v2.json).
The catalog ID remains `synthetic-electronics-v1`; schema/version are
`recfusion.synthetic-catalog.v2` / `2`. The API v1 response carries the
asset-byte SHA-256 in its existing `catalog_fingerprint` field. The inference
artifact separately pins the compatibility projection and bundle fingerprints.
The frontend joins product detail only after exact catalog ID and asset hash
match; otherwise it keeps API IDs and provenance without metadata. No browser
automation was run for this closure. ADR-018/019 remain Proposed and Phase
4.2C remains ON HOLD.
