# TESTING — Verification strategy

**Status:** The repository bootstrap/API foundation and local synthetic ingestion foundation have unit, contract, and integration tests, and CI runs the current quality checks. Service-backed integration, ML, agent, security and end-to-end coverage remains planned as those features are implemented.

## 1. Test pyramid

| Layer | Scope | Expected execution |
|---|---|---|
| Unit | domain contracts, parsers, fusion, constraints, fallback | every PR |
| Contract | REST schemas, typed tool inputs/outputs, feature schemas | every PR |
| Integration | PostgreSQL, Qdrant, model loading, auth boundaries | PR/CI services |
| ML | datasets, splits, determinism, ranking metrics, baseline parity | quick fixtures on PR; full offline jobs separately |
| Agent | golden intents, tool dispatch, source grounding, adversarial inputs | mocked provider on PR; selected real provider runs by approval |
| Security | user isolation, injection, rate limits, secrets, malformed payloads | PR and release |
| E2E | onboarding, search, refine, compare, feedback, no results | release candidate |
| Performance | retrieval P95, model load, throughput, agent latency | controlled environment, pre-release |

## 2. Required product and ML tests (future features)

- **Constraint invariants:** no candidate with absent/invalid mandatory price passes a strict budget filter; wrong category excluded; reranking cannot reintroduce rejected IDs.
- **Provenance:** explanation evidence must refer to fields of returned product and source; unknown spec is not asserted as fact.
- **Cold start:** no user history / unseen item / empty index / no candidates return valid behavior.
- **Model:** input feature schema, expected embedding dimensions, serialization parity, deterministic seed smoke tests.
- **Splits:** chronological ordering, user-specific historical context, no future leakage, train-only normalization, duplicate controls.
- **Metrics:** hand-calculated fixture for Recall@K, NDCG@K, HitRate@K, coverage; zero-positive user policy stated.
- **Auth:** user A cannot read/change user B's preferences/history, including by guessing IDs.
- **Tool safety:** prompt-injection text can't cause extra tool calls or changed instruction hierarchy.

## 3. Fixtures and external services

Use tiny synthetic product catalogs and interaction tables with explicit provenance. No production/user secrets. Mock LLM providers and network calls in CI. Start Postgres/Qdrant ephemeral containers for integration tests and tear down safely. Freeze clocks for time-dependent tests.

## 4. ML evaluation protocol

See `EVALUATION.md` for leakage controls and exact metric definitions. A model acceptance PR must include dataset version, split manifest, candidate universe, baseline comparisons, seeds, run configuration and stored outputs. Never declare a model better based only on one random split or an unverifiable screenshot.

## 5. Current foundation commands

These commands are implemented and documented in the README. The GitHub Actions quality workflow runs them on pull requests and pushes to `master`; it also builds the configured Python package.

```powershell
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy packages apps/api/src
uv run pytest
uv run pre-commit run --all-files
uv build
```

Frontend checks run from `apps/web` with the locked Node.js and pnpm
toolchain. The CI job uses the same scripts after a frozen installation:

```powershell
Set-Location apps/web
pnpm install --frozen-lockfile
pnpm run lint
pnpm run typecheck
pnpm run test
pnpm run build
```

## 6. CI gates

Current CI runs the Python formatting, lint, type checks, existing unit/contract suite, all pre-commit hooks, and package build. A separate frontend job runs the frozen pnpm install, Biome lint, TypeScript type check, Vitest suite, and Next.js production build. It does not start PostgreSQL/Qdrant or the local API, access external data/model services, run dataset/model jobs, or publish build artifacts. Add service-backed integration, ML, agent-safety, security and end-to-end checks as those features and fixtures are implemented; keep heavy dataset jobs and training in separately approved workflows. Frontend CI scope and limitations are recorded in [`FRONTEND-CI-READINESS.md`](./FRONTEND-CI-READINESS.md).

The Phase 6.2B synthetic API suite covers opt-in/production routing, exact configured local Origin and preflight behavior, local Host and ASGI scope checks, request media/body boundaries, offline/HTTP result parity, bounded inference admission, and runtime cleanup. Phase 6.3B adds synthetic frontend provider and mode-selection tests. These are local synthetic safeguards; they do not provide authentication or production network authorization.

## 7. Evaluation performance fixtures

The Phase 5.1A SMALL synthetic evaluation correctness/resource-safety test is
part of normal unit CI. MEDIUM and LARGE remain opt-in and are not CI gates.
See [EVALUATION-PERFORMANCE.md](./EVALUATION-PERFORMANCE.md) for workload
bounds, measurement scope, and the local aggregate-only smoke report.

Phase 8.2 adds the frozen, synthetic-only scenario manifest at
[`tests/fixtures/phase_8_2_synthetic_scenarios.json`](../tests/fixtures/phase_8_2_synthetic_scenarios.json).
Its unit acceptance tests reuse the existing content benchmark, hybrid
benchmark, hybrid retrieval, and shared synthetic catalog. They freeze seeds,
source/catalog/bundle fingerprints, selected aggregate output hashes, and
hand-calculated concentration examples; they do not introduce a new evaluator
or make empirical quality claims. Run them with:

```powershell
uv run --frozen pytest tests/unit/test_phase_8_2_quality_acceptance.py tests/unit/test_hybrid_benchmark.py
```

The keyboard empty-state focus recovery is covered by the frontend component
tests. Full Phase 8.2 evidence and the paired screen-reader limitation are in
[`PHASE-8-QUALITY-ACCEPTANCE.md`](./PHASE-8-QUALITY-ACCEPTANCE.md).

## 8. Bug reporting

Provide reproduction inputs, environment, expected/actual output, logs with redaction, model/catalog/version IDs, affected constraints and regression test. Fixes must add a test reproducing the issue.
