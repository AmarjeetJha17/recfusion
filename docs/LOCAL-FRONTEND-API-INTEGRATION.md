# Local Frontend–API Integration

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

The frontend fixture and serving API currently share the catalog ID
`synthetic-electronics-v1`, but they have distinct fingerprints and product
sets. Namespaced IDs overlap; that is not enough evidence to assert that
attributes or route details are the same product. The API result view
therefore shows the API's canonical item ID, rank, source, reason code,
algorithm, and candidate policy. It does not join IDs to frontend titles,
specifications, cohort labels, artwork, or product routes. The response
parser validates the canonical synthetic ID namespace and response shape. A
valid but unknown ID is shown as an ID only; malformed IDs are rejected. The
view never represents frontend fixture metadata as API metadata. An
authoritative catalog/metadata join is deferred to a separately reviewed
checkpoint.

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

In the final acceptance pass, the workspace host started the API and frontend
on `127.0.0.1`; `/ready` and `/explore` each returned HTTP 200 from that host.
The available Browser Use runner could not reach the workspace host's
`127.0.0.1:3000` and reported `ERR_CONNECTION_REFUSED` (its worker environment
had no listener on that address). It captured blocked-state evidence at the
requested 1440-, 900-, 700-, and 375-pixel widths, but no application page was
loaded. The browser run was not retried. Responsive overflow, clipping,
keyboard focus, routes, fixture mode, visual empty/error states, Local API
requests and responses, canonical IDs, provenance, unknown-input behavior,
and browser console/network findings therefore remain unverified. The local
HTTP responses and automated tests below are separate evidence and are not
browser end-to-end results.

The local HTTP smoke used the v1 contract directly against the loopback API:
`/ready` returned ready; allowed-origin preflight returned 204; product-to-
product, synthetic-user, and hybrid calls each returned five recommendations;
repeating the product query returned the same ordered recommendation list;
an unexpected Origin returned 403; and an unknown synthetic user returned
404. This verifies HTTP integration, not browser end-to-end behavior. Both
development servers were bound only to `127.0.0.1` and stopped after the
smoke. The prior browser review covered the home and Explore pages at a
desktop-sized viewport, search/category filtering, a product detail route,
unknown-product not-found behavior, and visible keyboard focus. Responsive
widths and selecting Local API through the browser remain unverified. An
earlier browser-control session stopped when URL verification failed; the
latest attempt was blocked by the isolated browser worker's inability to reach
the workspace host, as described above.

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
defect was demonstrated in the earlier desktop review or the current build,
but responsive visual effects remain unverified because browser automation
was unavailable. No cascade change was justified solely to silence the
warnings. The optional-chain warning in the fixture provider was removed
using an explicit missing-product guard. The exact remaining lint count is
recorded by the validation run.

## Proposed next checkpoint

Phase 6.3C may define and review a single authoritative synthetic catalog
projection and stable route mapping, then add browser-level coverage for the
API interaction, failures, responsive behavior, and keyboard navigation.
It must not infer product identity from title or reuse a fingerprint across
the two current catalogs. This checkpoint does not authorize real metadata,
real-data serving, production deployment, or changes to ADR-018/019.
