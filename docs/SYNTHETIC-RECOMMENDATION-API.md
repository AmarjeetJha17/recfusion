# Development-only synthetic recommendation API

**Status:** Phase 6.2A development-only implementation; owner review pending.
This API is for an explicitly enabled local development demonstration over
invented records only. It is not a production serving path. ADR-019 remains
Proposed and Phase 4.2C remains ON HOLD.

## Intent and scope

Expose the existing Phase 6.1B application service through FastAPI without
creating another recommendation engine. Support product-to-product,
synthetic-user content, and explicit synthetic hybrid requests. Reuse the
existing versioned request/response contracts, synthetic catalog, validated
content artifact, content index, and weighted RRF behavior.

Out of scope: real Amazon data or metadata, model loading/training/promotion,
database access, authentication or persistent user state, frontend work,
public deployment, production serving, implicit fallback, or changes to
evaluation semantics.

## Approaches considered

1. **One versioned route with a discriminated request union — selected.**
   Mount `POST /v1/recommendations` only when the synthetic demo is explicitly
   enabled outside production. The existing request `mode` selects one of the
   three supported use cases. This reuses the current schema and keeps shared
   validation and error handling in one place.
2. **Separate routes for each mode.** This makes the URL identify the mode,
   but duplicates transport behavior and makes the existing mode field
   redundant. It is not needed for this local demo.
3. **No route until server binding is controlled.** The current ASGI factory
   does not own a Uvicorn listener. The selected design adds a fail-closed
   per-request loopback scope check and documents the supported loopback-only
   launch command. If the ASGI scope lacks valid loopback peer and server
   addresses, the route is unavailable. The demo must not run behind a reverse
   proxy or be exposed through a public tunnel.

## Activation and lifecycle

Add a `RECFUSION_SYNTHETIC_DEMO_ENABLED` setting, default `false`. Enabling it
in production is rejected during settings validation. With the flag disabled,
recommendation routes are not mounted or advertised in OpenAPI; existing
health/readiness behavior is unchanged. When enabled, routes are mounted only
in development or test configuration and require loopback client and server
addresses on every recommendation request. The documented local server
command binds explicitly to `127.0.0.1`; no CORS middleware or proxy trust is
added.

During FastAPI lifespan, build the deterministic synthetic catalog, prepare
and validate the existing synthetic JSON artifact, and create one immutable
in-memory recommendation service. Requests reuse this service and artifact;
they do not regenerate the catalog, read files, reload artifacts, or fit
TF-IDF. A startup validation failure prevents readiness and prevents route
use. Shutdown clears the app-scoped service. Test apps receive isolated state.
If app state is unexpectedly missing after startup, readiness fails and the
route returns `DEMO_UNAVAILABLE` (503).

The route reads the request body with a bounded stream up to the existing
16-KiB limit, then validates the existing request model. It preserves the
20-result and 64-exclusion schema limits. Synchronous ranking is run in
Starlette's threadpool so it does not block the async event loop. No custom
queue, cache, or worker process is introduced.

## Contract and error behavior

The single request body uses
`recfusion.recommendation-request.v1`. It preserves the existing `mode`,
`algorithm_id`, `algorithm_version`, `policy_id`, `candidate_policy`, `k`,
query, exclusions, and constraints fields. The server allowlist continues to
select the supported algorithm/policy combinations and fixed hybrid sources.

Successful responses reuse `recfusion.recommendation-response.v1`, including
provenance, stable ranks, aggregate diagnostics, and valid `no_results`
responses. They contain no histories, embeddings, raw scores, private paths,
or exception details. The request correlation ID is taken from the existing
middleware and returned in the versioned response/error body and
`X-Request-ID` header.

| Failure | HTTP status | Recommendation error code |
|---|---:|---|
| Malformed body or invalid fields | 422 | `INVALID_REQUEST` |
| Unsupported contract version | 422 | `UNSUPPORTED_CONTRACT_VERSION` |
| K or exclusion bound | 422 | `TOP_K_LIMIT_EXCEEDED` / `EXCLUSION_LIMIT_EXCEEDED` |
| Non-loopback or missing ASGI client/server address | 403 | `INVALID_REQUEST` |
| Unknown synthetic product or user | 404 | `UNKNOWN_SYNTHETIC_PRODUCT` / `UNKNOWN_SYNTHETIC_USER` |
| Ineligible query product | 422 | `QUERY_PRODUCT_INELIGIBLE` |
| Unsupported algorithm/version or policy combination | 422 | `UNSUPPORTED_ALGORITHM` / `UNSUPPORTED_CANDIDATE_POLICY` |
| Missing, corrupt, incompatible, or catalog-mismatched artifact/source | 503 | Existing artifact/source code |
| Demo service unavailable after startup | 503 | `DEMO_UNAVAILABLE` (additive typed code) |
| Unexpected inference failure | 500 | `EXECUTION_FAILED` with a generic message |
| Valid empty result | 200 | `no_results` response; not an error |

The handler maps the existing typed inference errors to these statuses without
returning exception text. It does not duplicate service policy validation.

## Security and privacy boundary

All fixtures and artifact content are synthetic and in memory. Request fields
cannot supply file paths, URLs, checkpoints, source rankings, or RRF weights.
The loopback guard rejects requests with missing, malformed, or non-loopback
ASGI client/server addresses. Forwarded-address headers do not grant access.
Run Uvicorn bound to `127.0.0.1` and do not place it behind a reverse proxy,
tunnel, or gateway. The guard cannot detect a local proxy that connects from
loopback, so it is a development safeguard and not an exposure-proof network
boundary. Production configuration rejects demo activation and cannot mount
the routes. Existing request logging records route, status, and request ID
only; handlers do not log request bodies, IDs, histories, or recommendations.
No CORS expansion is planned.

The local demo has no authentication because it contains no real users or
user state. Any production-facing system requires a separate authentication,
authorization, privacy, deployment, and release review.

## Acceptance checks

Contract tests cover disabled-by-default and production
behavior, loopback checks, all three modes, schema and response versions,
determinism, request bounds, expected typed HTTP errors, empty histories,
seen-item and target masking, permitted cold content candidates, artifact
startup failures, service state isolation, request-ID propagation, and safe
unexpected errors. Existing Phase 6.1B tests remain unchanged and run with the
full suite. Tests use FastAPI TestClient and invented records only; no real
data or external network is involved.

Local launch example (PowerShell):

```powershell
$env:RECFUSION_SYNTHETIC_DEMO_ENABLED = "true"
uv run uvicorn recfusion_api.main:app --host 127.0.0.1 --port 8000
```

The TestClient smoke tests submit one request for each mode, validate response
models and aggregates, and verify the disabled app does not advertise the
route. They use synthetic fixtures only.

## Remaining limitations and Phase 6.2B

The loopback scope guard and local Uvicorn command protect the supported
direct-local development path; they are not a substitute for production
network controls and do not authorize proxying or tunneling. Resource limits
are request/catalog bounds from Phase 6.1B, not latency guarantees. There is
no production model, registry, promotion, rollback, authentication, database,
or durable catalog.

Phase 6.2B may integrate the local API into an application workflow only
after owner review. It must separately address production identity and
authorization, catalog ownership, artifact promotion, operational limits,
deployment network controls, monitoring, and security review. This checkpoint
does not approve those decisions.
