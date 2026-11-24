# Phase 1 Foundation Audit

**Audit date:** 2026-11-24
**Result:** Conditional pass. The local foundation validates; hosted publication and CI still need remote-repository verification.

## Scope and delivered foundation

Steps 1.1–1.5 are represented by the committed history:

- `0e31669` — repository bootstrap and Python tooling
- `5cae28c` — FastAPI application foundation
- `a75aa46` — PostgreSQL and Qdrant local infrastructure
- `2ca22e6` — GitHub Actions quality pipeline

The only local branch is `master`; the working tree was clean at audit start. No Git remote is configured.

| Area | Implemented inventory |
|---|---|
| Repository | Monorepo placeholders for API/web, core/data/ML/agent packages, configs, scripts, tests, experiments, infra, and GitHub workflows. Root-local datasets and configuration files under `configs/datasets/` are separately handled by `.gitignore`. |
| Python | Python 3.13, `pyproject.toml`, tracked `uv.lock`, Ruff, mypy, pytest/coverage, pre-commit, and a setuptools build configuration. |
| API | `apps/api/src/recfusion_api/`: app factory, settings, error contracts, structured logging, `main:app`, `/health`, `/ready`, and health/error schemas. `packages/recfusion_core/` is importable. |
| Tests | Two unit test modules and one API contract test module; the configured suite currently contains 12 tests. |
| Infrastructure | `infra/compose/compose.yaml`: digest-pinned PostgreSQL 18.6 Alpine and Qdrant 1.19.1, named volumes, required PostgreSQL environment values, and loopback-only ports. No application schema or Qdrant collection is provisioned. |
| CI | `.github/workflows/ci.yml`: PRs and pushes targeting `master`; locked Python quality checks and package build, without Docker, datasets, model weights, or application secrets. |

No recommender, dataset ingestion, database schema, agent, or frontend functionality is implemented.

## Validation evidence from this audit

Environment: Windows, Python 3.13.11, uv 0.13.1. Docker CLI 29.8.0 and Compose v5.5.1 are installed.

| Command/check | Result |
|---|---|
| `uv sync --frozen` | PASS — 44 packages checked; no dependency changes required. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS — 30 files already formatted. |
| `uv run mypy packages apps/api/src` | PASS — no issues in 12 source files. |
| `uv run pytest` | PASS — 12 passed. |
| `uv run pytest --cov=packages --cov=apps/api/src --cov-report=term-missing` | PASS — 12 passed; 98% measured coverage (138/141 statements). |
| `uv run pre-commit run --all-files` | PASS — configured hygiene, TOML/YAML, Ruff lint, and format hooks. |
| `uv build --offline` | PASS — source distribution and wheel built. |
| `docker compose --env-file .env -f infra/compose/compose.yaml config --quiet` | PASS — used the ignored local `.env`; no values were printed. |
| Bounded Uvicorn smoke on `127.0.0.1:8765` | PASS — `/health` and `/ready` returned their documented JSON; `/health` returned a request ID; `/openapi.json` and `/docs` were available. The process was stopped after the check. |

Coverage is limited to the small bootstrap/API codebase, not recommendation behavior. Three statements were missed: the `ApplicationError` invalid-status guard and the `main.py` entrypoint statements. Ten files were omitted from the table because they were fully covered.

The first Compose config attempt omitted `--env-file .env` and failed on the required PostgreSQL variables. The documented explicit-env-file invocation above passed.

## Infrastructure verification history

The runtime checks below were completed in the preceding Step 1.4 verification, **not repeated during this audit**: both services became healthy; PostgreSQL accepted an authenticated query; Qdrant `/healthz` returned HTTP 200; temporary PostgreSQL and Qdrant test records survived a container restart and were then removed; ordinary `docker compose down` preserved both named volumes. During this audit, only Compose configuration validation was run; containers and volumes were not modified.

## Security and CI review

- The tracked-file scan found no matches for common GitHub, AWS, API-key, or private-key patterns. This is a pattern scan, not a full secret-scanner attestation; `gitleaks` is not installed.
- `.env` exists locally, is ignored and untracked; `.env.example` is tracked and uses an empty password placeholder. No credential value is included in CI or staged files.
- PostgreSQL and unauthenticated Qdrant bind only to `127.0.0.1`. Qdrant must not be exposed publicly; this Compose configuration is local development only.
- Production debug mode is rejected by settings validation. OpenAPI and Swagger are disabled in production. Request logs contain route templates and selected metadata, not request bodies, authorization headers, or exception messages.
- All three workflow actions are pinned to verified immutable commit SHAs; workflow permissions are read-only `contents`, and checkout credentials are not persisted. Workflow YAML passes the pre-commit YAML hook.
- `actionlint` is not installed. GitHub-hosted execution has not been observed because no remote is configured.

## Findings and corrections

**Critical:** None found.

**Major:** The repository has no remote or remote default-branch reference. `master` is the only local branch and matches the workflow filters, but the hosted repository's intended primary branch cannot yet be confirmed. First hosted CI execution is also unverified.

**Minor:** The generic `datasets/` ignore pattern also hid the intended `configs/datasets/.gitkeep`. The pattern is now root-anchored so the configuration directory can be tracked without unignoring root dataset downloads. The Testing guide's bootstrap status and command examples were also stale and have been aligned with current CI.

**Informational:** Qdrant's container health check verifies that its REST port is listening; it does not itself make an HTTP request. The documented external `/healthz` check was verified during the previous runtime verification. The build backend is declared as `setuptools>=75.0`, rather than pinned in `uv.lock`; the offline build passed, but the isolated backend version on a fresh hosted runner has not been exercised.

## Open decisions and Phase 2 entry criteria

The proposed decisions in `docs/DECISIONS.md` remain unresolved: dataset terms/subset, positive-event definition and negative sampling, demo catalog source and freshness, initial category, identity and retention, hosting budget, and ML hardware.

Before Phase 2 dataset feasibility work:

1. Review dataset license/access conditions and verify its actual manifest and schema.
2. Approve an initial subset, positive-event policy, temporal split, and leakage checks.
3. Decide the demo catalog provenance and how historical, synthetic, and live data will be distinguished.
4. Record source hashes, configuration, seed, split manifest, and exclusions in a reproducible dataset manifest.

No Phase 2 functionality was started.
