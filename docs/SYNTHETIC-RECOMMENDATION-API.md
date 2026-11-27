# Development-only synthetic recommendation API

**Status:** Phase 6.2B development-only implementation; owner review pending.
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
in development or test configuration. Each request requires loopback ASGI
client and server addresses, a `Host` authority of `localhost` or a
loopback IP, and the exact configured frontend `Origin`. Enabling the demo
requires `RECFUSION_SYNTHETIC_DEMO_ALLOWED_ORIGIN` to be a single explicit
loopback HTTP origin with a port (for the documented frontend:
`http://127.0.0.1:3000`). The recommendation route accepts preflight only for
`POST` and the `Content-Type` request header. Successful and error responses
for that exact origin echo that origin; wildcard and credentialed CORS are
not used. The documented local server command binds explicitly to
`127.0.0.1`; forwarded headers are not trusted.

The local inference cap is controlled by
`RECFUSION_SYNTHETIC_DEMO_MAX_CONCURRENCY`, default `2`, bounded from `1` to
`4`. This is a development resource guard, not a throughput target. Excess
calls receive an immediate typed 503 response; the API does not queue waiting
inference requests.

During FastAPI lifespan, build the deterministic synthetic catalog, prepare
and validate the existing synthetic JSON artifact, and create one immutable
in-memory recommendation service and a per-app AnyIO capacity limiter.
Requests reuse this service and artifact; they do not regenerate the catalog,
read files, reload artifacts, or fit TF-IDF. If initial synthetic artifact
preparation or validation fails, startup aborts; the app does not retry, refit,
or repair an invalid artifact. The service and limiter are published only
after successful initialization. Shutdown and failed startup clear both.
Test apps receive isolated state.
If app state is unexpectedly missing after startup, readiness fails and the
route returns `DEMO_UNAVAILABLE` (503).

The route accepts only `application/json`, rejects URL query parameters, and
reads the request body with a bounded stream up to the existing 16-KiB limit,
including requests without `Content-Length`. It preserves the 20-result and
64-exclusion schema limits. Synchronous ranking is run in Starlette's
threadpool only after nonblocking concurrency admission; a `finally` block
releases capacity after success, errors, or cancellation. No custom queue,
cache, or worker process is introduced.

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
| Unsupported or missing content type | 415 | `UNSUPPORTED_CONTENT_TYPE` |
| URL query parameters | 422 | `INVALID_REQUEST` |
| Missing or unexpected browser Origin | 403 | `INVALID_REQUEST` |
| Non-loopback ASGI client/server or unsupported Host | 403 | `INVALID_REQUEST` |
| Unknown synthetic product or user | 404 | `UNKNOWN_SYNTHETIC_PRODUCT` / `UNKNOWN_SYNTHETIC_USER` |
| Ineligible query product | 422 | `QUERY_PRODUCT_INELIGIBLE` |
| Unsupported algorithm/version or policy combination | 422 | `UNSUPPORTED_ALGORITHM` / `UNSUPPORTED_CANDIDATE_POLICY` |
| Missing, corrupt, incompatible, or catalog-mismatched artifact/source | 503 | Existing artifact/source code |
| Demo service unavailable after startup | 503 | `DEMO_UNAVAILABLE` (additive typed code) |
| Inference capacity exhausted | 503 | `CONCURRENCY_LIMIT_EXCEEDED` |
| Unexpected inference failure | 500 | `EXECUTION_FAILED` with a generic message |
| Valid empty result | 200 | `no_results` response; not an error |

The handler maps the existing typed inference errors to these statuses without
returning exception text. It does not duplicate service policy validation.

## Security and privacy boundary

All fixtures and artifact content are synthetic and in memory. Request fields
cannot supply file paths, URLs, checkpoints, source rankings, or RRF weights.
The guard rejects missing, malformed, or non-loopback ASGI client/server
addresses, unexpected Host authorities, and any missing or unexpected
browser `Origin`. Origin validation and the narrow CORS response enable the
documented browser call but do not authenticate non-browser callers; CORS is
not authorization. Run Uvicorn bound to `127.0.0.1` and do not place it behind
a reverse proxy, tunnel, or gateway. The guard cannot detect a local proxy
that connects from loopback, so the demo does not protect synthetic service
availability from other local processes. The fixed numeric API URL avoids
frontend URL discovery and DNS rebinding of the API host; an unrelated web
origin is rejected. Production configuration rejects demo activation and
cannot mount the routes. Existing request logging records route, status, and
request ID only; handlers do not log request bodies, IDs, histories, or
recommendations.

The local demo has no authentication because it contains no real users or
user state. Any production-facing system requires a separate authentication,
authorization, privacy, deployment, and release review.

## Acceptance checks

Contract and unit tests cover disabled-by-default and production behavior,
Host and ASGI loopback checks (IPv4 and IPv6), forwarded-header spoofing,
unsupported media types, query parameters, chunked body limits, all three
modes, offline/HTTP parity, deterministic results, request bounds, typed
errors, empty results, seen-item and target masking, cold-item policy,
artifact startup failures, concurrency saturation, exception/cancellation
permit release, service isolation, request-ID propagation, and safe logs and
responses. Existing Phase 6.1B tests remain unchanged. Tests use FastAPI
TestClient and invented records only; no real data or external network is
involved.

Local launch example (PowerShell):

```powershell
$env:RECFUSION_SYNTHETIC_DEMO_ENABLED = "true"
$env:RECFUSION_SYNTHETIC_DEMO_MAX_CONCURRENCY = "2"
$env:RECFUSION_SYNTHETIC_DEMO_ALLOWED_ORIGIN = "http://127.0.0.1:3000"
uv run uvicorn recfusion_api.main:app --host 127.0.0.1 --port 8000
```

The TestClient smoke tests submit one request for each mode, validate response
models and aggregates, and verify the disabled app does not advertise the
route. They use synthetic fixtures only.

A controlled Uvicorn smoke was also run with the server bound to `127.0.0.1`.
Seven loopback requests covered health, readiness, all three modes, a repeated
product query, and an unknown synthetic user. Health/readiness were `ok`/
`ready`; each recommendation mode returned five items; repeat rankings matched
after excluding request IDs; the unknown user returned 404. Aggregate elapsed
time was 158.13 ms for all seven requests on the local development machine.
This is only smoke evidence and is not a serving-latency measurement.

## Remaining limitations and Phase 6.2B

The loopback scope guard and local Uvicorn command describe the supported
direct-local development path; they are not a substitute for production
network controls, do not authenticate callers, and do not authorize proxying
or tunneling. The concurrency setting only caps active synthetic inference; it
is not a serving capacity claim. Request/catalog bounds are not latency
guarantees. There is no production model, registry, promotion, rollback,
authentication, database, or durable catalog.

Phase 6.3 may integrate the local API into a larger application only after
owner review. Entry criteria include separately approved production identity
and authorization, catalog ownership and product-source policy, immutable
artifact promotion/rollback and compatibility checks, target-specific
resource budgets and load tests, deployment network/TLS controls, sanitized
monitoring and retention, and a security review. This checkpoint approves
none of those production decisions.
