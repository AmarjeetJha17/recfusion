# TESTING — Verification strategy

**Status:** The repository bootstrap and API foundation have unit and contract tests, and CI runs the current quality checks. Integration, ML, agent, security and end-to-end coverage remains planned as those features are implemented.

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

## 6. CI gates

Current CI runs formatting, lint, type checks, the existing unit/contract suite, all pre-commit hooks, and a package build. It does not start PostgreSQL/Qdrant or run dataset/model jobs. Add service-backed integration, ML, agent-safety, security and end-to-end checks as those features and fixtures are implemented; keep heavy dataset jobs and training in separately approved workflows.

## 7. Bug reporting

Provide reproduction inputs, environment, expected/actual output, logs with redaction, model/catalog/version IDs, affected constraints and regression test. Fixes must add a test reproducing the issue.
