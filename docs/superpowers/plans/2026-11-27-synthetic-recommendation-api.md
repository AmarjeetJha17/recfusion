# Phase 6.2A Synthetic Recommendation API Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the existing session (native execution). Do not commit or push.

**Goal:** Expose the Phase 6.1B synthetic recommendation service through a development-only, explicitly enabled, versioned FastAPI endpoint with fail-closed loopback enforcement.

**Architecture:** Mount one `POST /v1/recommendations` router only when `Settings.synthetic_demo_enabled` is true outside production. Build the synthetic catalog, prepare/load/validate its JSON artifact, and create the service once in FastAPI lifespan; route handlers parse bounded request bytes, call the service in Starlette's threadpool, and map existing typed errors to safe versioned responses.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, Starlette TestClient/threadpool, existing `recfusion_core` / `recfusion_ml` interfaces.

**Spec:** `docs/SYNTHETIC-RECOMMENDATION-API.md`

## Global Constraints

- Preserve Phase 6.1B request/response names and schema versions.
- Demo enablement defaults to false and production settings reject enablement.
- Recommendation requests require loopback ASGI client and server addresses; missing or invalid addresses fail closed.
- Use synthetic data only; no Amazon inputs, model checkpoints, generated persisted artifacts, or network access.
- Reuse existing retrieval/service logic; no new algorithm, dependency, CORS configuration, persistence, or global user state.
- Preserve ADR-018/ADR-019 as Proposed and Phase 4.2C ON HOLD.
- Stage only intended source, API test, and documentation files; do not commit or push.

## Review Focus

- Invalid, oversized, chunked, or malformed JSON request bodies receive bounded, safe 422 responses.
- Direct requests with missing or non-loopback ASGI peer/server addresses cannot reach recommendation inference.
- Production or default configuration never mounts or advertises recommendation routes.
- Invalid or missing artifacts fail before readiness; runtime service absence maps to a safe 503.
- Unexpected service exceptions never expose details, histories, or identifiers in the HTTP body or logs.

---

### Task 1: Development-only activation and app-scoped service lifecycle

**Files:**
- Modify: `apps/api/src/recfusion_api/config.py`
- Modify: `apps/api/src/recfusion_api/app.py`
- Modify: `apps/api/src/recfusion_api/routes/health.py`
- Create: `apps/api/src/recfusion_api/services/recommendation_runtime.py`
- Test: `tests/contract/test_recommendation_api.py`

**Interfaces:**
- `Settings.synthetic_demo_enabled: bool = False`, environment variable `RECFUSION_SYNTHETIC_DEMO_ENABLED`.
- `build_synthetic_recommendation_service() -> RecommendationService` builds one deterministic provider, prepares and validates its synthetic artifact, and returns an app-scoped service.
- App state `recommendation_service: RecommendationService | None`; readiness remains 200 when demo is disabled and requires a valid service when enabled.

- [x] **Step 1: Write failing configuration and lifecycle tests**
  - `test_demo_is_disabled_by_default_and_route_is_absent_from_openapi`
  - `test_production_rejects_synthetic_demo_activation`
  - `test_service_is_built_once_per_app_lifespan` and `test_missing_runtime_is_not_ready_and_returns_typed_503`
  - `test_artifact_startup_failure_prevents_app_startup`
  - Assert disabled `/openapi.json` omits the route; normal health response is unchanged.
- [x] **Step 2: Run the new tests and confirm expected failures**
  - Run: `uv run pytest tests/contract/test_recommendation_api.py -q`
  - The restricted run stalled in TestClient before assertions because loopback socket access was unavailable; the regression suite was rerun successfully in the normal local context after implementation.
- [x] **Step 3: Implement opt-in settings, builder, and lifespan wiring**
  - Build the catalog/artifact/service once per enabled app lifespan; validate artifact against catalog ID/fingerprint before publishing app state.
  - Do not mount the router in disabled or production configuration.
  - Extend `/ready` only to report `not_ready` for an enabled demo without a usable service; leave `/health` unchanged.
- [x] **Step 4: Run Task 1 tests and confirm pass**
  - The 16-test API module and full 319-test repository suite passed.

### Task 2: Bounded route, loopback guard, and typed HTTP errors

**Files:**
- Create: `apps/api/src/recfusion_api/routes/recommendations.py`
- Create: `apps/api/src/recfusion_api/dependencies/recommendation.py`
- Modify: `apps/api/src/recfusion_api/schemas/recommendation.py`
- Test: `tests/contract/test_recommendation_api.py`

**Interfaces:**
- `POST /v1/recommendations` accepts the existing `RecommendationRequest` schema and returns `RecommendationResponse` or `RecommendationErrorResponse`.
- `require_loopback_scope(request: Request) -> bool` verifies valid loopback ASGI `client` and `server` hosts; any missing/non-loopback value is rejected.
- `RecommendationRequestParseError` carries an existing stable `RecommendationErrorCode` and a generic safe message.
- Add the stable `RecommendationErrorCode.DEMO_UNAVAILABLE` value for the app-state-unavailable case; do not overload an unrelated service error code.
- Status map: invalid/version/algorithm/policy/query eligibility 422; unknown synthetic IDs 404; artifact/source/demo unavailable 503; unexpected inference failure 500; valid empty response 200.

- [x] **Step 1: Write failing route contract tests**
  - `test_enabled_app_serves_all_three_modes_with_versioned_responses`
  - `test_non_loopback_peer_is_rejected`, `test_non_loopback_server_is_rejected`, and `test_missing_asgi_addresses_fail_closed`
  - `test_request_body_bounds_and_schema_failures_are_safe` and `test_top_k_and_exclusion_bounds_have_specific_error_codes`
  - `test_unknown_ids_have_typed_not_found_errors` and `test_unexpected_runtime_errors_are_safe`
  - `test_service_is_built_once_per_app_lifespan` and `test_app_instances_have_separate_runtime_state`
- [x] **Step 2: Run route tests and confirm expected failures**
  - Run: `uv run pytest tests/contract/test_recommendation_api.py -q`
  - The restricted run stalled before assertions on TestClient loopback; local execution later passed all route regressions.
- [x] **Step 3: Implement request parsing and loopback dependency**
  - Read `Request.stream()` incrementally and stop above `MAX_REQUEST_BYTES` before JSON parsing.
  - Map schema version, top-K, exclusion, and malformed payload failures to typed generic request errors; preserve the existing Pydantic schema for business validation.
  - Reject missing/non-IP/non-loopback ASGI client or server addresses; do not trust forwarded headers.
  - Add explicit OpenAPI request/response schema metadata for the bounded raw-body endpoint and verify it appears only when the opt-in router is mounted.
- [x] **Step 4: Implement the thin route and service error mapping**
  - Use the app-state service, run synchronous inference through `run_in_threadpool`, propagate middleware `request_id` into success/error bodies, and do not log request bodies or identifiers.
  - Return the existing versioned response models; preserve service candidate/seen/constraint checks and no-fallback behavior.
- [x] **Step 5: Run route tests and confirm pass**
  - `uv run pytest tests/contract/test_recommendation_api.py -q` and the full suite passed.
  - Focused API tests: 16 passed; full suite: 319 passed.

### Task 3: HTTP smoke coverage, documentation, and final audit

**Files:**
- Modify: `docs/SYNTHETIC-RECOMMENDATION-API.md`
- Modify: `docs/RECOMMENDATION-SERVING-DESIGN.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ROADMAP.md`
- Test: `tests/contract/test_recommendation_api.py`

**Interfaces:**
- The API document records verified route schemas/statuses, activation, lifecycle, bounds, loopback limitations, local smoke procedure, and Phase 6.2B plan.

- [x] **Step 1: Add smoke and app-isolation regressions**
  - `test_enabled_app_serves_all_three_modes_with_versioned_responses`
  - `test_repeated_requests_are_deterministic_except_request_id`
  - `test_app_instances_have_separate_runtime_state`
  - `test_demo_is_disabled_by_default_and_route_is_absent_from_openapi`
  - Assert exactly one permitted content-bearing cold item can appear under the content-eligible hybrid policy; assert no held-out or real-data input exists in the app path.
- [x] **Step 2: Run smoke tests and confirm expected behavior**
  - `uv run pytest tests/contract/test_recommendation_api.py -q` passed (16 tests).
- [x] **Step 3: Document implementation and update only stale serving status**
  - Keep ADR-019 Proposed and Phase 4.2C ON HOLD; do not describe this local route as production readiness.
- [x] **Step 4: Run required repository validation**
  - `uv sync --frozen --offline`
  - `uv lock --check --offline`
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run mypy packages apps/api/src`
  - `uv run pytest`
  - `uv run pre-commit run --all-files`
  - `git diff --check` and `git diff --cached --check`
- [x] **Step 5: Audit staged paths and data boundary**
  - Confirm only intended API/config/tests/docs files are staged; no dataset, checkpoint, generated artifact, private map, report, or secret is staged.
  - Leave changes staged for review; do not commit or push.
