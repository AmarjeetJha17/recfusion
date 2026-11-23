# DECISIONS — Architecture decision log

**Status:** All entries below are **proposed** until explicitly approved. Record changes with an ID, date, status, context, alternatives, consequences and reviewer.

## ADR-001 — Modular monolith first

- **Status:** Proposed
- **Choice:** Next.js frontend + FastAPI modular backend + offline ML scripts, not multi-service ML microservices.
- **Why:** simpler to test, debug and deploy in a portfolio budget.
- **Revisit if:** measured throughput/resource isolation demands it.

## ADR-002 — Dataset and live catalog separation

- **Status:** Proposed
- **Choice:** Amazon Reviews 2023 electronics for offline experiments; independently sourced/clearly synthetic demo catalog for shopping UI.
- **Why:** historical reviews and prices do not prove current India availability.
- **Open:** exact subset, license review, demo catalog source and coverage.

## ADR-003 — Model-first hybrid approach

- **Status:** Proposed
- **Choice:** popularity/content/collaborative baselines → PyTorch Two-Tower retrieval → semantic fusion → optional LambdaRank.
- **Why:** independently testable learning contribution and stepwise ablations.
- **Open:** positive feedback threshold, sampled negatives and embedding dimension.

## ADR-004 — Agents use typed tools

- **Status:** Proposed
- **Choice:** bounded stateful orchestration, no untrusted direct DB/shell/web execution, code-enforced filters and catalog-grounded explanations.
- **Why:** safety, explainability and predictability.
- **Open:** hosted vs local LLM provider, budget, persistence and consent.

## ADR-005 — Persistence and vector search

- **Status:** Proposed
- **Choice:** PostgreSQL application data + Qdrant dense/sparse or named-vector retrieval.
- **Why:** explicit separation of structured transactional state from approximate nearest-neighbor search.
- **Open:** whether small MVP can start with FAISS/local index before introducing Qdrant.

## ADR-006 — Versioned offline evaluation

- **Status:** Proposed
- **Choice:** temporal holdout as primary generalization protocol; optional benchmark split reported separately; fixed test candidate universe and clear metric denominators.
- **Why:** limit leakage, comparison bias and false improvement claims.
- **Open:** cutoff selection from observed timestamps; full-catalog feasibility.

## ADR-007 — Privacy-first guest experience

- **Status:** Proposed
- **Choice:** guest sessions by default, explicit user consent for durable profile, retention/deletion controls.
- **Why:** reduce friction and minimize PII.
- **Open:** authentication provider, retention periods, data export policy.

## Pre-Phase-1 blockers / questions to settle

| Topic | Default proposal | Verification / approval needed |
|---|---|---|
| Initial app catalog | laptops first, expand to smartphones/headphones | user confirms scope |
| Dataset | Amazon Reviews 2023 electronics | license, schema and use conditions |
| Catalog freshness | synthetic/curated demo with visible source | source and permitted asset usage |
| User data | guest first; optional sign-in later | consent/retention policy |
| ML hardware | local CPU + optional GPU | actual device capacity |
| Hosting | local Docker Compose first | deployment cost/budget |
| LLM provider | abstract provider and mocked tests | token budget, terms, privacy |
| Ranking labels | defer LambdaRank until labels justified | empirical candidate/group validation |
| Success criteria | reproducible benchmarks, not numeric win guarantee | evaluation report review |

## How to update this log

For each accepted decision change **Status** to Accepted with date and approver. Superseded decisions retain history and link the replacement. Do not retroactively imply approval of unreviewed proposals.
