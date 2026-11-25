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

## ADR-008 — Dataset feasibility source and pilot

- **Status:** Proposed
- **Choice:** Evaluate Amazon Reviews 2023 Electronics as the first offline research source. Use the official 5-core absolute-timestamp split for a bounded, reproducible dense pilot; follow with a 0-core profile before making long-tail or cold-start claims.
- **Why:** The source documents 43.9M Electronics reviews and provides a processed 5-core Electronics timestamp split (13.1M / 1.2M / 1.2M train/validation/test interactions). The 5-core filtering is useful for a dense pilot but changes the original population.
- **Evidence:** [Dataset overview](https://amazon-reviews-2023.github.io/) and [5-core processing and split documentation](https://amazon-reviews-2023.github.io/data_processing/5core.html).
- **Revisit if:** Profiling shows insufficient metadata coverage, unsuitable temporal support, or prohibitive resource needs.
- **Open:** Actual metadata join/field coverage, license/terms review, pilot resource usage, and whether to proceed.

## ADR-009 — Review feedback and temporal evaluation

- **Status:** Proposed
- **Choice:** Treat records as review/rating feedback, never as clicks, impressions, or complete purchase events. For an initial binary relevance analysis, test ratings 4–5 as relevant, ratings 1–2 as explicitly low-rated, and rating 3 as neutral; missing interactions are unobserved. Use global time cutoffs and a training-time warm-item catalog, with cold users/items reported separately.
- **Why:** The source contains ratings and review timestamps but does not provide an exposure log. Its absolute timestamp split is explicit and reproducible; metadata does not have per-item effective timestamps.
- **Evidence:** [Review schema and source description](https://amazon-reviews-2023.github.io/) and [5-core timestamp split](https://amazon-reviews-2023.github.io/data_processing/5core.html).
- **Revisit if:** A pilot demonstrates different label behavior or a source with valid exposure/query labels becomes available.
- **Open:** Rating threshold acceptance, negative-feedback use, exact candidate policy, and whether rating-based LTR is defensible.

## ADR-010 — Conservative product metadata normalization

- **Status:** Proposed
- **Choice:** Keep canonical product metadata unchanged and add an opt-in, versioned normalized sidecar. Normalize only explicitly keyed brand/category text and recognized specification labels with explicit units; retain raw values, parse states, source fingerprints, and all distinct conflicting product records.
- **Why:** Electronics metadata is heterogeneous. Deterministic field-level normalization supports later profiling without guessing missing specifications, silently choosing conflicts, changing the Step 2.2A output by default, or coupling the canonical schema to a source-specific representation.
- **Revisit if:** Synthetic-only tests pass and authorized, terms-reviewed profiling demonstrates the normalized fields and parsing rules are appropriate for a selected source.
- **Open:** Whether these broad unit/range conventions and the supported attribute aliases are suitable for any future real source; source-specific adapters remain separately gated.

## ADR-011 — Deterministic interaction preprocessing and quality reports

- **Status:** Proposed
- **Choice:** Keep interaction preprocessing as a separate source-independent layer over canonical per-split JSONL outputs. Preserve each input split, source fingerprint, rating and timestamp provenance; label observed rating feedback with configurable provisional thresholds; collapse only exact within-split duplicates; reject conflicting variants within a split; retain and report cross-split fingerprint conflicts without changing either partition.
- **Why:** This enables reproducible data-quality checks without mutating ingestion outputs, introducing a source adapter, interpreting unobserved products as negatives, or allowing validation/test outcomes to determine train-derived state. Timestamp ties use stable fingerprint/payload ordering rather than input order.
- **Evidence:** Synthetic fixture and contract/integration tests cover rating-label boundaries, exact and conflicting fingerprints, repeated user-item events, split boundaries, cold-start diagnostics, timestamp validation, and reordered inputs. These tests establish implementation behavior only, not real-source quality.
- **Revisit if:** An approved source requires additional event fields or timestamp semantics, or a separately reviewed training-only vocabulary contract is ready.
- **Open:** Whether the provisional rating thresholds suit any future experiment; whether/how to fit integer ID mappings from train while representing validation/test unknown users/items; acceptable source-specific treatment of duplicate events.

## Pre-Phase-1 blockers / questions to settle

| Topic | Default proposal | Verification / approval needed |
|---|---|---|
| Initial app catalog | laptops first, expand to smartphones/headphones | user confirms scope |
| Dataset | Amazon Reviews 2023 Electronics, dense 5-core pilot first | license/terms review, schema profile, and use conditions |
| Catalog freshness | synthetic/curated demo with visible source | source and permitted asset usage |
| User data | guest first; optional sign-in later | consent/retention policy |
| ML hardware | local CPU + optional GPU | actual device capacity |
| Hosting | local Docker Compose first | deployment cost/budget |
| LLM provider | abstract provider and mocked tests | token budget, terms, privacy |
| Ranking labels | ratings are review feedback; defer LambdaRank unless group labels are justified | rating policy and empirical candidate/group validation |
| Success criteria | reproducible benchmarks, not numeric win guarantee | evaluation report review |

## How to update this log

For each accepted decision change **Status** to Accepted with date and approver. Superseded decisions retain history and link the replacement. Do not retroactively imply approval of unreviewed proposals.
