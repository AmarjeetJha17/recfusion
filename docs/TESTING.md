# TESTING — Verification strategy

**Status:** Planned. No tests have been run by virtue of producing these documents.

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

## 2. Required core tests

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

## 5. Suggested commands (to be implemented in Phase 1)

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy packages apps/api
uv run pytest tests/unit tests/contract -q
# Only when integration infra is running:
uv run pytest tests/integration -q
```

These are **future intended commands**, not guaranteed to work until repository bootstrap.

## 6. CI gates

On PR: formatting, lint, type check, synthetic fixture unit/contract/agent safety tests, package build; optional integration with services. Heavy dataset jobs and training are manual/approved workflows with bounded cost/time. Release candidate: e2e, security, performance, model artifact compatibility and evaluation reports.

## 7. Bug reporting

Provide reproduction inputs, environment, expected/actual output, logs with redaction, model/catalog/version IDs, affected constraints and regression test. Fixes must add a test reproducing the issue.
