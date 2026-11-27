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

## Phase 7.3 final synthetic application QA

**Reviewed:** 2026-11-27. This section supersedes earlier statements in this
file that the Phase 7.1B implementation had no browser evidence or exact
responsive measurements. Earlier phase-specific evidence remains historical.

### Current implementation identity

Both consumers read
[`synthetic-electronics-v2.json`](../packages/recfusion_core/data/synthetic-electronics-v2.json),
schema `recfusion.synthetic-catalog.v2`, catalog ID
`synthetic-electronics-v1`, version `2` (10 records; 9 visible). Fingerprints:

| Fingerprint | Value |
|---|---|
| Shared asset bytes | `b7d29b34eb6eaf5c1d9a935a3c94769023cae6dd8401b0aca1daf4d47fb97c78` |
| Inference compatibility projection | `6cfcdb984ee561b3d4a8f82ed7514f0433e888e3110a6c4c316c5d13fe42ab5f` |
| Recommendation bundle | `0244b50e0cff15ffba48c7144101ec5c19d0155d9c558f11683cc8b72d4c85eb` |
| Prepared inference artifact | `7f50c2dea0b9374e40433a2519b0bcc863d1f5a097d7755596c6db79a696f3fd` |

The v1 request, response, and error schemas are unchanged. Content requests
use `tfidf_content` v1 / `content_catalog`; hybrid requests use `weighted_rrf`
v1 / `warm_hybrid` or `content_eligible_hybrid`. The frontend only displays
catalog metadata when catalog ID, exact asset fingerprint, canonical item
membership, and display eligibility match. Unknown valid IDs remain ID-only;
hidden or ineligible entries do not receive metadata. The UI preserves rank
and provenance and does not derive warm/cold labels from product details.

### Local browser evidence

Local Chrome and DevTools responsive mode exercised the built Next.js app at
`127.0.0.1:3000`; API scenarios used `127.0.0.1:8000`. Widths were set in CSS
pixels with device scale 1. Both servers were stopped after QA. Local
screenshots were inspected but not retained as repository files. No HAR or
network export was retained.

| Viewport | Home | Explore | Product detail |
|---:|---|---|---|
| 1440 px | `scrollWidth` 1440 = viewport; visually inspected | `scrollWidth` 1440 = viewport; visually inspected | `scrollWidth` 1440 = viewport; visually inspected |
| 900 px | `scrollWidth` 900 = viewport; visually inspected | `scrollWidth` 900 = viewport; visually inspected | `scrollWidth` 900 = viewport; visually inspected |
| 700 px | `scrollWidth` 700 = viewport; visually inspected | `scrollWidth` 700 = viewport; visually inspected | `scrollWidth` 700 = viewport; visually inspected |
| 375 px | `scrollWidth` 375 = viewport; visually inspected | `scrollWidth` 375 = viewport; controls and results inspected | `scrollWidth` 375 = viewport; product detail inspected |

These measurements establish no horizontal document overflow for the three
routes at the requested widths. They do not replace a component-by-component
clipping review or contrast measurement. At widths other than 375 px, this
pass focused on route layout and overflow; recommendation-card detail was
browser-verified at 375 px.

At 375 px, the accessibility tree exposed the main landmark, labelled radio
groups and selects, recommendation status, ranked list, provenance, canonical
IDs, and product links. Browser results were: fixture product-to-product
5/5; API product-to-product 5/5; synthetic-user content 5/5; warm hybrid
4/5; content-eligible hybrid 5/5. The warm short list was announced without
padding. API results showed catalog and artifact fingerprints, ranks, and
source attribution. With the API stopped, the fixture hybrid flow returned
5/5 and stated “offline · no network request.”

Chrome's Issues panel reported zero page errors, zero breaking changes, and
two possible improvements. One reported that a form field without `id` or
`name` appeared on two resources; Chrome notes this may impair autofill. The
second possible improvement was not separately identified in the retained
inspection. The app console had zero messages in the production session.
Keyboard-only route traversal, direct focus-ring inspection, and independent
text contrast measurement remain unverified. Automated tests cover keyboard
operation for search/category controls and accessible status/error states.
The reduced-motion override is present; the prior smooth-scroll warning did
not recur. Development React DevTools/HMR messages were informational.

### Regression, errors, and determinism

Frontend: 56 tests passed in eight files. Coverage includes exact
catalog/fingerprint joins; unknown, hidden, ineligible, duplicate, and
incomplete product records; route availability; empty and short results;
fixture determinism/no-fetch; API-unavailable without fixture fallback;
typed 503; malformed response; timeout; cancellation; stale response;
explicit retry; and accessible loading/error/status behavior.

Backend: 369 tests passed. Contract tests cover API disabled by default and
production rejection; loopback server, client, Host, Origin, and restricted
preflight checks; body/schema/K/exclusion bounds; typed 404 and invalid
request; empty result; safe 500/503; and repeated-response determinism
excluding `request_id`. The frozen Phase 7.1B baseline checks ordered IDs for
product, synthetic-user, both hybrid policies, and an empty synthetic-user
profile. No live saturation traffic was generated. Each API browser scenario
was observed once; browser-level repeat comparison was not performed.

### Security, validation, and limitations

Inspected code and tests retain disabled-by-default API activation,
production rejection, numeric loopback binding/URL, exact Origin and
loopback Host/client/server checks, restricted preflight, 16 KiB request
limit, `k` limit 20, exclusion limit 64, and per-app concurrency default 2
(maximum 4). Forwarded headers are not trusted. No arbitrary API URL, proxy,
or tunnel is used. Loopback is not authentication: another local process can
call or exhaust the service, and a local forwarding proxy is unsupported.
No real-data access, training, promotion, or deployment occurred.

Frontend checks passed: frozen install, lint, typecheck, tests, and build.
Biome reported 21 existing CSS warnings (17 descending-specificity and four
reduced-motion `!important`). Backend sync, lock check, Ruff check/format,
mypy, and pytest passed; pytest emitted one PyTorch warning because NumPy is
absent. Pre-commit passed after malformed inherited `GIT_CONFIG_*` entries
were removed from its process environment. The build prerendered `/`,
`/explore`, and generated product routes. Standalone static export is not
configured.

The checked-in [CI workflow](../.github/workflows/ci.yml) defines Python
lint, format, typecheck, tests, pre-commit, and package-build steps for pushes
and pull requests targeting `master`. Its remote run status was not queried;
the validation results here are local.

## Phase 7.4 accessibility and browser acceptance closure

**Reviewed:** 2026-11-27. This section supersedes Phase 7.3 statements above
that keyboard acceptance, control contrast, form IDs/names, mobile clipping,
and browser mode flows were still unverified. Earlier phase-specific records
remain historical. Full evidence and limits are in
[`ACCESSIBILITY-AND-PORTFOLIO-REVIEW.md`](./ACCESSIBILITY-AND-PORTFOLIO-REVIEW.md).

Local Chrome verified home, Explore, and product detail at CSS widths 1440,
900, 700, and 375 px. `scrollWidth` equalled `clientWidth` at every pair; no
horizontal document overflow was observed. At 375 px, long fingerprints,
canonical IDs, provenance, and card details wrapped within the page. Search
and select controls were 46.4 px high, submit 46 px, filter chips 40.8 px,
and mode cards 68 px. The first 375 px screenshot exposed a 5 px crop on the
right edge of the header; the mobile page/header width was reduced, and a
follow-up screenshot showed the full “Demo mode” label within the viewport.
All three routes were rechecked at 375 px after that fix. Screenshots were
visually inspected but not retained; no HAR was retained.

The keyboard walkthrough verified the focused skip link and main-content
target, home navigation actions, source/mode radio operation, focused context
select and submit, recommendation card/detail navigation, and Enter on
**Retry request**. The full keyboard path through all search, filter, sort,
card, detail, provenance, and error states; keyboard-trap checks; and paired
screen-reader testing remain open.

Contrast was measured from rendered CSS colors. Normal text pairs measured
at least 6.70:1 and white text on the primary button measured 6.70:1. The
original `#cbd5e1` control boundary measured 1.48:1 on white and failed the
3:1 non-text threshold. A dedicated `--control-border: #64748b` now applies
to select, search, and filter controls; it measures 4.76:1 on white and
4.26:1 on the soft surface. Reduced-motion emulation returned true for the
media query; document scrolling computed to `auto`, with transitions and
animations at `0.00001s`.

Catalog search and sort now have the unique ID/name pairs `catalog-search`
and `catalog-sort`, with regression coverage. Chrome Issues reported zero
page errors, breaking changes, and possible improvements after this update.
The app console contained no errors or warnings; the native development
browser showed only informational React DevTools/HMR notices. Observed app
requests used the frontend and fixed loopback API; the failed request was an
intentional check of the unavailable/retry state.

Browser results: fixture product-to-product 5/5; API product-to-product
5/5; synthetic-user 5/5; warm hybrid 4/5; content-eligible hybrid 5/5. The
UI preserved rank, exact IDs, fingerprints, provenance, and links; the warm
hybrid short list was announced and not padded. Blocking the local API
request surfaced the explicit unavailable message and Retry button; after
unblocking, keyboard Enter on Retry returned live results without fixture
fallback. Fixture mode rendered offline and made no recommendation request.

The earlier real-data Two-Tower result remains validation-only: NDCG@10
`0.015572` with K=10 catalog coverage `0.000684` (31/45,331) in one
10,000-user Electronics 5-core pilot; no independent test evaluation was
performed. Synthetic demo metrics are not real-data performance evidence.
ADR-018/019 remain Proposed and Phase 4.2C remains ON HOLD. No serving,
training, data-access, or security policy changed. The full keyboard review,
paired assistive-technology check, exhaustive component clipping review,
and detailed HAR/payload review remain unverified. No commit, push, or
deployment was performed.

**Phase 7.3 verdict: Conditional GO for a local portfolio walkthrough.** The
API/fixture flows, identity checks, and automated gates passed. Complete
responsive acceptance, keyboard/focus traversal, and contrast measurement
remain open. See [`SYNTHETIC-PORTFOLIO-DEMO.md`](./SYNTHETIC-PORTFOLIO-DEMO.md)
for the walkthrough and detailed evidence. ADR-018/019 remain Proposed and
Phase 4.2C remains ON HOLD. No commit, push, or deployment was performed.
