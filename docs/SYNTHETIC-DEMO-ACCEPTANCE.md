# Phase 6.4 — Synthetic Application Demonstration Acceptance

> The tables and browser evidence in this file describe the earlier Phase 6.4
> catalog generation. Phase 7.1B current identity and validation are recorded
> at the end of this document.

**Status:** Conditional acceptance for project-owner review. Local synthetic
application behavior was demonstrated; exact-width responsive browser checks
remain unverified. No production, real-data, or rights-gate status changes are
made. ADR-018 and ADR-019 remain Proposed; Phase 4.2C remains ON HOLD.

## Scope and non-goals

This checkpoint verifies a reproducible, loopback-only demonstration of the
existing invented-electronics frontend and synthetic recommendation API. It
does not add recommendation algorithms, train models, access Amazon files or
metadata, load external checkpoints, evaluate real recommendation quality,
authorize publication, or deploy the application.

## Reproducible local setup

Prerequisites recorded by the project: Python 3.13 with `uv`, Node.js 20.9 or
newer, and pnpm 11.25.0. From the repository root, install the frozen
dependencies and start the API in one local terminal:

```powershell
uv sync --frozen --offline
$env:RECFUSION_SYNTHETIC_DEMO_ENABLED = "true"
$env:RECFUSION_SYNTHETIC_DEMO_MAX_CONCURRENCY = "2"
$env:RECFUSION_SYNTHETIC_DEMO_ALLOWED_ORIGIN = "http://127.0.0.1:3000"
uv run uvicorn recfusion_api.main:app --host 127.0.0.1 --port 8000
```

From `apps/web`, in a second terminal:

```powershell
pnpm install --frozen-lockfile
pnpm dev
```

Open `http://127.0.0.1:3000`. Check API liveness and readiness at
`http://127.0.0.1:8000/health` and `/ready`; both returned HTTP 200 in this
acceptance. Stop each server with Ctrl+C in its terminal. Fixture mode works
without the API. The API must stay bound to loopback and must not be exposed
through a proxy, tunnel, or public listener.

## Integration inventory

| Area | Verified implementation |
|---|---|
| Frontend routes | `/` discovery, `/explore` Recommendation Lab, `/products/[id]` product detail, plus framework not-found handling |
| Frontend fixture | `synthetic-electronics-v1`, 13 invented product records; fixture fingerprint `9314ae2a389269c8a641c0befb4157a05160de568b9dd9a718b71a29bc1f7657`; artifact fingerprint `eb1b6a178b74bec9e767d32cac86315691215e04f12eddd5950c64d1c1600451` |
| API | Explicitly enabled `POST http://127.0.0.1:8000/v1/recommendations`; frontend transport URL is fixed in code |
| API contracts | `recfusion.recommendation-request.v1` and `recfusion.recommendation-response.v1`; errors use `recfusion.recommendation-error.v1` |
| API synthetic catalog | ID `synthetic-electronics-v1`, distinct serving catalog fingerprint `d8f61df61a5595611faf2f6d4d75e44299e221778ac98e87d566e6bd3805b46d`; active content artifact fingerprint `aa09a00b6d3a62f0d5c37f735da2f840311ec08bcc9c80e311412c439116b434` |
| Algorithms | `tfidf_content` v1 for product and synthetic-user content; `weighted_rrf` v1 for hybrid |
| Candidate policies | `content_catalog` for content results; `warm_hybrid` and `content_eligible_hybrid` for hybrid |
| Runtime | FastAPI lifespan initializes one deterministic in-memory synthetic recommendation service and bounded per-app capacity limiter; requests reuse it |

The frontend and API catalogs share an ID namespace but have different
fingerprints and product sets. API results are presented as canonical IDs
with response-backed ranking and provenance only. The UI does not join API
IDs to frontend titles, artwork, attributes, routes, or cohort labels.

## Demonstration walkthrough

1. Introduce RecFusion as an electronics recommendation-system prototype;
   all catalog records in this walkthrough are invented.
2. Browse the 13-item fixture catalog, search for “headphones,” filter the
   Audio category, and sort by name.
3. Open a product detail, follow a similar-item link, then visit an unknown
   product route and confirm the fixture not-found state.
4. Open Recommendation Lab. Fixture mode is the default and states that it
   makes no network request. Its short fixture result list is labeled as
   prewritten synthetic ordering, not personalization or a quality claim.
5. Explicitly select Local API and run product-to-product retrieval. Explain
   `tfidf_content` v1 and content-similarity provenance.
6. Select a synthetic-user profile. Explain that the context uses invented
   training interactions and that raw history is never displayed.
7. Select Hybrid and show the `warm_hybrid` policy, `weighted_rrf` v1, and
   contributing synthetic BPR, item-CF, and content source lists.
8. Explain that source membership is provenance rather than causation, and
   different modes have different candidate sets and no shared score scale.
9. Point out a legitimate short list: the live warm-only hybrid request
   returned four of five requested recommendations. No filler was added.
10. Describe unavailable, empty, invalid, timeout, cancellation, retry, and
    saturation states from deterministic tests. The UI never silently falls
    back to fixture results after an API failure.
11. State the limits: this is synthetic and local-only; it is not a deployed
    service, a real-product catalog, or evidence of model quality.

## Acceptance evidence

### Fixture mode

With the API stopped, the browser showed the home and Explore routes, product
search, Audio filtering, sorting, product details, similar-product navigation,
Recommendation Lab fixture mode, fixture provenance, and the unknown-product
not-found state. Fixture mode explicitly reported that it was offline and
made no network request. The fixture response returned three of five
requested recommendations without padding. No backend was needed for these
observations.

### Local API mode

The API was started with the documented explicit opt-in and loopback
configuration. `/health` returned `{"status":"ok"}` and `/ready` returned
`{"status":"ready"}`. The browser showed the Local API mode and successful
results for all three supported request modes:

| Mode | Live browser result | Provenance / integrity observation |
|---|---|---|
| Product-to-product | 5 of 5 returned | `tfidf_content` v1, `content_catalog`, ordered canonical IDs |
| Synthetic-user content | 5 of 5 returned | `tfidf_content` v1, synthetic profile label; no history or preference details shown |
| Hybrid | 4 of 5 returned | `weighted_rrf` v1, `warm_hybrid`; source lists identify synthetic BPR, item-CF, and content contributors |

Repeating the same product request returned the same five canonical item IDs
in the same order. Request IDs differed, as expected. The browser showed the
v1 schema label, algorithm, policy, catalog fingerprint, artifact fingerprint,
and result provenance. No DevTools network capture or HAR was retained, so
request/response body inspection is supported by the typed contract code and
automated tests rather than a recorded browser payload.

### Empty, error, and accessibility states

Live short-list behavior was observed in fixture and hybrid modes. Automated
frontend tests cover valid empty results, accessible loading/status and error
announcements, typed 503 handling, API unavailable behavior, explicit retry,
request timeout, cancellation, and stale-response protection. Contract tests
cover typed invalid-request and unknown-context errors, valid empty API
responses, bounded request handling, and typed 503 saturation/unavailability.
No live saturation was induced. API failures do not trigger fixture fallback.

### Security and privacy

Inspected configuration and tests verify that the synthetic API is disabled
by default, production activation is rejected, and the documented server
binds to `127.0.0.1`. Recommendation requests require the exact configured
Origin and loopback Host/client/server scope. CORS allows only the configured
origin, POST, and Content-Type without credentials or wildcard origin. The
request body is capped at 16 KiB, K at 20, exclusions at 64, and active
inference concurrency defaults to 2 (maximum 4). Arbitrary backend URLs are
not user-configurable; forwarding headers do not establish loopback scope.
Responses expose safe typed fields; request bodies and histories are not
logged or displayed.

Loopback is not caller authentication. Another local process may call or
exhaust the demo. A local forwarding proxy could satisfy loopback checks and
is outside the supported setup. Each application instance has its own
concurrency limiter. Do not use a proxy, tunnel, public listener, or real
user data with this development service.

### Exact responsive acceptance

The current browser tooling did not expose a reliable CSS viewport setter, so
the requested widths were not measured. Screenshot pixel dimensions or
browser zoom are not substituted for CSS viewport measurements.

| CSS viewport | Header/navigation | Catalog/search/filter | Detail | Recommendation/provenance | IDs/errors/focus/overflow |
|---:|---|---|---|---|---|
| 1440 px | Unverified | Unverified | Unverified | Unverified | Unverified |
| 900 px | Unverified | Unverified | Unverified | Unverified | Unverified |
| 700 px | Unverified | Unverified | Unverified | Unverified | Unverified |
| 375 px | Unverified | Unverified | Unverified | Unverified | Unverified |

The project has semantic controls, visible focus styling, and responsive CSS,
but those facts do not replace manual checks at the specified widths. Exact
overflow, clipping, narrow-screen focus, and long-ID wrapping remain open
acceptance items.

## Quality validation

Commands run for this checkpoint:

| Command | Result |
|---|---|
| `pnpm install --frozen-lockfile` (`apps/web`) | Passed |
| `pnpm lint` (`apps/web`) | Passed with 22 existing CSS warnings (18 descending-specificity, 4 reduced-motion `!important`); generated Next.js `next-env.d.ts` is excluded from lint/format checks |
| `pnpm typecheck` (`apps/web`) | Passed; no TypeScript errors |
| `pnpm test` (`apps/web`) | Passed: 7 files, 41 tests |
| `pnpm build` (`apps/web`) | Passed; `/`, `/explore`, and 13 generated product routes prerendered; `/_not-found` generated |
| `uv sync --frozen --offline` | Passed; 52 packages checked |
| `uv lock --check --offline` | Passed; 54 packages resolved |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed; 168 files formatted |
| `uv run mypy packages apps/api/src` | Passed; 80 source files |
| `uv run pytest` | Passed: 363 tests; one existing PyTorch warning because NumPy is absent |

`pre-commit run --all-files` passed after removing malformed inherited
`GIT_CONFIG_*` variables from the hook process environment. The first
unadjusted invocation failed because Git rejected an empty inherited config
value. `git diff --check` and `git diff --cached --check` passed.

## Determinism and limitations

The repeated live product-to-product request retained identical ordered item
IDs while changing its request ID. Test coverage also exercises deterministic
synthetic service responses. Fixture catalog and serving API fingerprints
remain intentionally distinct. API v1 does not provide per-item warm/cold
status; the UI says so instead of inferring it. No raw history, real data,
product metadata, price, availability, or model-quality claim is part of this
acceptance. Next.js prerendered its current routes; standalone static export
and static-host compatibility are not configured or verified.

## Owner decision

**Conditional GO for Phase 6.4 owner review.** The synthetic local integration,
all three API modes, deterministic replay, and listed automated checks passed.
Do not claim complete responsive acceptance until a local browser records
actual CSS viewport sizes 1440, 900, 700, and 375 px and checks the specified
content and overflow conditions. This checkpoint does not authorize a public
demo, production serving, real-data access, Phase 4.2C work, or ADR status
changes.

## Phase 7.1B shared catalog closure

The current shared asset is `recfusion.synthetic-catalog.v2`, catalog
`synthetic-electronics-v1`, version `2`. Fingerprints are:

| Fingerprint | Value |
|---|---|
| Exact shared asset bytes | `b7d29b34eb6eaf5c1d9a935a3c94769023cae6dd8401b0aca1daf4d47fb97c78` |
| Inference compatibility projection | `6cfcdb984ee561b3d4a8f82ed7514f0433e888e3110a6c4c316c5d13fe42ab5f` |
| Recommendation bundle | `0244b50e0cff15ffba48c7144101ec5c19d0155d9c558f11683cc8b72d4c85eb` |
| Prepared inference artifact | `7f50c2dea0b9374e40433a2519b0bcc863d1f5a097d7755596c6db79a696f3fd` |

Frozen recommendation-order parity passed for product-to-product, synthetic
user, warm hybrid, content-eligible hybrid, and the empty synthetic-user
profile. A local loopback HTTP smoke passed all four non-empty policies and
returned 404 for an unknown synthetic user; the product mode retained ordered
IDs `000006, 000002, 000007, 000004, 000003`. The v1 API schema, algorithm
versions, candidate policies, and ranking weights are unchanged. Next.js
compiled the shared sibling package JSON after the Turbopack root was set to
the repository root; nine visible product routes were prerendered. The Python
wheel includes both the shared asset and manifest. Automated checks exercise
exact-fingerprint joins and retain unknown IDs as ID-only.

This task did not run browser automation or capture browser/network evidence.
The prior 1440/900/700/375-pixel responsive measurements remain unverified.
ADR-018/019 remain Proposed and Phase 4.2C remains ON HOLD. No commit, push,
deployment, or Phase 7.2 work is part of this closure.

## Phase 7.3 final QA evidence

**Reviewed:** 2026-11-27. This section supersedes the preceding Phase 7.1B
statement that no browser automation or responsive measurements were
available. It does not erase the earlier phase-specific records.

Local Chrome verified the built app at CSS widths 1440, 900, 700, and 375 px.
Home, Explore, and product detail each had `documentElement.scrollWidth` equal
to the viewport at all four widths. Screenshots were visually inspected for
the route layouts; recommendation-card details and provenance were inspected
at 375 px. This establishes no horizontal document overflow for the tested
route-width pairs, while exhaustive clipping and contrast review remain open.

Browser recommendation flows returned: fixture product-to-product 5/5;
Local API product-to-product 5/5; synthetic-user content 5/5; warm hybrid
4/5; content-eligible hybrid 5/5. Fixture mode also returned the five-item
hybrid fixture with the API stopped and stated that no network request was
made. The warm hybrid short list was not padded. Browser results displayed
versioned provenance, original ranks, canonical product IDs, catalog and
artifact fingerprints, and valid detail links. No synthetic history was
displayed. No browser HAR was retained.

Chrome's Issues panel showed 0 page errors, 0 breaking changes, and 2 possible
improvements; one says a form field on two resources lacks `id` or `name`,
which may affect autofill. The production browser console had 0 messages.

Automated frontend and backend suites passed (56 and 369 tests respectively).
Tests cover product identity/fingerprint resolution, restricted and unknown
items, request failures, accessible statuses, retries, cancellations, stale
responses, and deterministic ordering. The reduced-motion override is
present, and the previously observed smooth-scroll warning did not recur in
the browser console. Keyboard-only route traversal, focus-ring inspection,
and independent contrast measurement remain unverified.

See [`SYNTHETIC-PORTFOLIO-DEMO.md`](./SYNTHETIC-PORTFOLIO-DEMO.md) for launch
commands, walkthrough, full viewport evidence, limitations, and verdict; see
[`LOCAL-FRONTEND-API-INTEGRATION.md`](./LOCAL-FRONTEND-API-INTEGRATION.md)
for current integration and security evidence. Phase 7.3 is **Conditional GO
for a local portfolio walkthrough**; complete responsive and manual
accessibility acceptance remain open. ADR-018/019 remain Proposed and Phase
4.2C remains ON HOLD. No commit, push, deployment, or Phase 7.4 work is
authorized by this QA review.

## Phase 7.4 accessibility and portfolio audit

This later local-browser audit supersedes Phase 7.3 statements that
responsive, keyboard/focus, control-contrast, and autofill checks were still
open. Earlier phase-specific evidence remains historical. See
[`ACCESSIBILITY-AND-PORTFOLIO-REVIEW.md`](./ACCESSIBILITY-AND-PORTFOLIO-REVIEW.md)
for the full evidence matrix and limitations.

Local Chrome checked home, Explore, and product detail at 1440, 900, 700,
and 375 CSS px. `scrollWidth` equalled `clientWidth` for all pairs. At 375 px,
long canonical IDs, fingerprints, provenance, and product-card details
wrapped; search/select controls measured 46.4 px, submit 46 px, filter chips
40.8 px, and mode cards 68 px. The first 375 px screenshot showed a 5 px
right-edge crop on the header; the mobile page/header width was reduced. A
follow-up screenshot showed “Demo mode” fully visible, and all three routes
were rechecked at 375 px. No screenshot or HAR was retained.

The keyboard pass verified the visible skip link, primary navigation actions,
source/mode radio selection, focused select and submit controls, product
detail links, and Enter-key retry recovery. Complete keyboard traversal and
paired screen-reader testing remain open. Contrast measurement found the old
control border at 1.48:1 on white; control borders now measure 4.76:1 on white
and 4.26:1 on the soft surface. Emulated reduced motion set page scrolling
to `auto` and transitions/animations to `0.00001s`. Search/sort controls now
have stable, unique ID/name pairs and regression coverage; Chrome Issues
reported zero remaining findings.

Fixture product-to-product returned 5/5 offline. Browser Local API results
were product-to-product 5/5, synthetic-user 5/5, warm hybrid 4/5, and
content-eligible hybrid 5/5. The unavailable state was explicit and offered
Retry; after restoring the loopback request, Enter on Retry recovered to 5/5
live results with no fixture substitution. Result ranks, identities,
fingerprints, provenance, and links were present. No API or security
contract changed. ADR-018/019 remain Proposed; Phase 4.2C remains ON HOLD.
Project-owner review is pending; no commit, push, or deployment occurred.
