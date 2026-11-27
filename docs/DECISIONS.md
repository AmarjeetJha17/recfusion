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
- **Open:** Actual metadata join/field coverage, any additional source-term or institution-specific limits, pilot resource usage, and whether to expand beyond local coursework use.

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

## ADR-012 — Temporal split validation and train-only vocabulary

- **Status:** Proposed
- **Choice:** Add a separate source-independent temporal layer with two explicit modes: validate and preserve trusted pre-split membership, or assign explicitly unpartitioned canonical interactions by required absolute UTC cutoffs. Use half-open train/validation/test boundaries, binary-sorted train-only user/item vocabularies with unknown index 0, and a candidate pool containing only train-observed items. Keep held-out interactions auditable; block evaluation on split contradictions, chronology violations, cross-split duplicates, or fingerprint conflicts rather than repairing or hiding them.
- **Why:** Reproducible temporal evaluation requires immutable split provenance and train-only transforms. Explicitly rejecting split-bearing input in cutoff mode prevents accidental recomputation of official membership, while reserved unknown IDs preserve cold-start cases without using held-out outcomes to fit vocabularies.
- **Evidence:** Synthetic boundary, reorder, duplicate/conflict, warm/cold, and held-out-invariance tests validate the implementation contract only. They are not dataset measurements, rights approval, or evidence of product availability at historical prediction times.
- **Revisit if:** An approved source requires alternate split semantics, timestamp precision, event de-duplication, or a separately reviewed candidate catalog snapshot.
- **Open:** Whether proposed provisional rating labels are suitable for any future metric; whether timestamp-effective catalog snapshots are available; whether source-specific official split chronology has additional rules.

## ADR-013 — Leakage-safe feature generation and snapshot metadata boundary

- **Status:** Proposed
- **Choice:** Generate encoded interactions, strictly prior training-only user/item aggregates, and separate item metadata features from checksum-verified Step 2.5 outputs. Fit category vocabularies and population z-score parameters only from unique, non-conflicting metadata attached to training-candidate items. Keep validation/test histories training-only; exclude simultaneous events. Preserve conflicting item metadata as an audited exclusion, not a row-order selection.
- **Why:** The source-independent pipeline should provide baseline-ready observed rating records while preventing target, future-event, held-out-label, and held-out-catalog leakage. Product metadata has no effective timestamps, so keep its feature block separately marked snapshot-only; it cannot establish historical product availability. Do not generate price or rating-aggregate features.
- **Evidence:** Synthetic tests cover train-only fitting, exact as-of boundaries, equal timestamps, held-out-label invariance, unknown/missing values, conflicts, deterministic reordered inputs and output manifests. These tests establish implementation behavior only.
- **Revisit if:** An approved source provides effective-time catalog snapshots or a separately reviewed temporal feature policy.
- **Open:** Whether snapshot metadata is appropriate for a future clearly labeled experiment; whether source-specific product evidence can establish historical availability; no dataset usage-rights gate is resolved by this implementation.

## ADR-014 — Scoped local academic coursework use

- **Status:** Owner-scoped local coursework decision documented; legal clearance is not established.
- **Date:** 2026-11-25
- **Context:** The project owner confirms that RecFusion is non-commercial MCA coursework. The intended experiment is local preprocessing, offline training, and offline evaluation of Amazon Reviews 2023 Electronics 5-core timestamp data.
- **Assessment:** The reviewed project docs and maintainer discussion identify no specific university approval requirement or explicit source term prohibiting this narrowly described local coursework use. This is not a finding that no such requirement exists: institution-specific rules and applicable law have not been independently verified.
- **Decision:** Record the owner's informed choice to limit project use to local, non-commercial academic coursework preprocessing, training, and evaluation. This internal scope decision is not a dataset license, legal opinion, or clearance; it does not mark any legal requirement as satisfied. The owner remains responsible for applicable law, source terms, and institution policy. The maintainer's favorable reply to another student's thesis question is not treated as permission for RecFusion.
- **Safeguards:** Keep source and derived data local and gitignored. Do not commit or publish raw reviews, source user IDs, benchmark CSVs, row-level outputs, or original product images. Use appropriate attribution in academic reporting, with reviewed aggregate results only. Commercial use and redistribution remain outside this decision and require separate review.
- **Consequences:** A 100-user local canary may be considered under this scope after project-owner review of this clarification and normal technical preflight. No real data is processed by this decision record alone. No metadata coverage or feature-release readiness is implied.
- **Evidence:** [Official dataset page and citation](https://amazon-reviews-2023.github.io/), [5-core processing documentation](https://amazon-reviews-2023.github.io/data_processing/5core.html), [maintainer terms discussion](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/discussions/1), and [ACL 2026 research publication](https://aclanthology.org/2026.acl-long.147/).
- **Revisit if:** Applicable source terms or law are clarified, institutional policy requires review, project scope changes, or storage/publication/derived-data use changes.

## ADR-015 — Bounded item-based collaborative filtering baseline

- **Status:** Proposed
- **Date:** 2026-11-26
- **Choice:** Compare a deterministic sparse item-CF baseline with Phase 3.1 popularity on the same verified Step 2.5 validation cohort. Use binary positive signals for ratings >=4, collapse repeated user/item positives only in the derived signal, require two shared users per cosine pair, cap positive histories at 20 and retained neighbors per item at 100, exclude all train-seen items, and do not fall back to popularity.
- **Why:** This provides an interpretable collaborative baseline while bounding pair expansion and keeping the validation comparison on one candidate universe and denominator.
- **Evidence:** Synthetic unit and integration tests plus the aggregate-only 10,000-user validation report. These do not establish deployment readiness or superiority.
- **Open:** Whether alternate support/history/neighbor caps or a graded rating signal should be evaluated; assess only through validation protocol and preserve test as untouched until model selection is complete.

## ADR-016 — Deterministic collaborative rank fusion

- **Status:** Proposed
- **Date:** 2026-11-26
- **Choice:** Use weighted Reciprocal Rank Fusion over ranked collaborative and popularity candidate sources. Default rank constant 60, one-based ranks, optional independent source-depth caps, canonical item-key tie breaks, train-known catalog filtering, and train-seen exclusion. Preserve source provenance and audit counts. Missing/empty sources contribute zero with no implicit popularity fallback. Phase 3.4B should compare equal-weight all-source fusion with a Two-Tower+BPR ablation at fixed depth 100 and K=5/10/20.
- **Why:** Rank fusion does not require raw model-score calibration and gives a deterministic test of complementary ranking and coverage behavior observed in Phase 3.3C.
- **Evidence:** Synthetic unit and evaluator-compatibility tests only. No real fusion run or quality gain is claimed.
- **Limitations:** RRF weights and rank constant are not tuned or known to be optimal. Popularity may concentrate results; sparse sources may produce short lists. Fusion does not add cold-item coverage or remove validation checkpoint-selection optimism. Aggregate union coverage is not final top-K coverage.
- **Revisit if:** The fixed validation experiment shows no useful trade-off, source candidate generation changes, or a separate ranking protocol is approved. Keep the reserved test split untouched until validation-based selection is complete.

## ADR-017 — Source-scoped synthetic hybrid retrieval

- **Status:** Proposed
- **Date:** 2026-11-26
- **Choice:** Reuse the Phase 3 RRF ranker and add optional source-specific candidate pools. For hybrid retrieval, collaborative lists are restricted to train-known items; the content list may use warm and cold items present in the fitted `ContentIndex` candidate keys. Provide separate warm-only and content-eligible global policies, preserve original source ranks while filtering, and report source-pool exclusions separately. Keep explicit source weights/depths and no fallback.
- **Why:** A single global pool cannot both admit eligible cold content items and prevent collaborative sources from introducing cold products. Filtering source rankings before fusion would also compress their ranks. An optional source-pool filter in the existing RRF engine preserves Phase 3 defaults and one-based ranks.
- **Evidence:** Synthetic unit and end-to-end tests exercise source-specific eligibility, cold-item retrieval, train-seen filtering, fixed RRF scores, deterministic output, and aggregate diagnostics. These tests establish interface behavior only.
- **Limitations:** Callers must supply collaborative rankings trained from training-only representations; the interface cannot inspect their model fitting. The synthetic smoke run is not a relevance comparison or quality claim. Real metadata remains gated separately under Phase 4.2C.
- **Revisit if:** Phase 4.4B freezes its evaluation protocol or candidate-source interfaces change. Do not tune weights against the smoke test.

## ADR-018 — Evaluation-first synthetic research continuation

- **Status:** Proposed; awaiting project-owner review
- **Date:** 2026-11-27
- **Choice:** Make evaluation and performance infrastructure hardening, using synthetic workloads and no new model training, the proposed next research milestone after the Phase 4.4C synthesis. Freeze artifact, cohort, metric, and determinism contracts before any later diagnostic experiment. Keep real metadata integration under the separate Phase 4.2C hold.
- **Why:** Real interaction experiments are single-cohort validation results with validation-selected neural checkpoints and no independent test evaluation. Phase 4.4B documents meaningful synthetic hybrid trade-offs but its engineered fixture cannot support real-catalog claims. Strengthening repeatability and resource observability improves future evidence without expanding data use or choosing a production model.
- **Evidence:** `docs/RECOMMENDATION-RESEARCH-SYNTHESIS.md`, `docs/EVALUATION.md`, `docs/MODEL-COMPARISON.md`, and `docs/HYBRID-BENCHMARK.md`.
- **Limitations:** Synthetic throughput is not serving capacity; no model is promoted; the documented experiments do not establish performance in new populations. This proposal authorizes no real-data parsing, metadata acquisition, or model training.
- **Revisit if:** Project-owner review changes the next-step priority, the evaluation contract changes, or a separate source-specific rights decision is made. Phase 4.2C remains ON HOLD unless separately reviewed.

## ADR-019 — Contract-first local synthetic recommendation serving

- **Status:** Proposed; awaiting project-owner review
- **Date:** 2026-11-27
- **Context:** The offline retrieval and evaluation components exist, but the API currently exposes only health/readiness. No recommendation model is promoted, and no catalog provider, serving artifact registry, compatibility/promotion lifecycle, or authorization implementation exists. The research synthesis identifies serving readiness as unimplemented.
- **Choice:** Define a versioned recommendation request/response contract with explicit product-to-product, synthetic-user, and hybrid modes. Keep policy and hybrid sources/weights server-side; resolve candidates through an authoritative catalog provider; apply deterministic seen, visibility, and hard-constraint checks before response; require immutable compatible artifact manifests; and fail closed without implicit model fallback. The first application/provider is local-only, read-only, deterministically versioned, and synthetic-only.
- **Why:** A contract-first modular-monolith boundary lets the existing content/RRF interfaces be reused without treating research artifacts as promoted models or allowing model output to bypass catalog truth and hard constraints. A synthetic provider provides a testable application path without expanding Amazon data use or implying real metadata readiness.
- **Evidence:** Existing API app/error contracts, `ContentIndex`, source-scoped `retrieve_hybrid`, RRF tie/filter behavior, and synthetic retrieval tests. They do not establish online serving correctness, authorization, latency, model quality, artifact promotion, or deployment readiness.
- **Limitations:** All route shapes, response fields, resource limits, catalog/history providers, release manifests, and error-status details remain proposed until owner review and implementation tests. No model is approved for serving. Phase 4.2C and real metadata use remain ON HOLD.
- **Revisit if:** Owner review changes the initial application scope, an artifact or identity design is approved, compatibility requirements change, measured target-resource results justify different bounds, or a non-loopback deployment is proposed. Any model promotion and deployment require separate review.

## Pre-Phase-1 blockers / questions to settle

| Topic | Default proposal | Verification / approval needed |
|---|---|---|
| Initial app catalog | laptops first, expand to smartphones/headphones | user confirms scope |
| Dataset | Amazon Reviews 2023 Electronics, dense 5-core pilot first | confirm applicable terms/institution rules, schema profile, and use conditions |
| Catalog freshness | synthetic/curated demo with visible source | source and permitted asset usage |
| User data | guest first; optional sign-in later | consent/retention policy |
| ML hardware | local CPU + optional GPU | actual device capacity |
| Hosting | local Docker Compose first | deployment cost/budget |
| LLM provider | abstract provider and mocked tests | token budget, terms, privacy |
| Ranking labels | ratings are review feedback; defer LambdaRank unless group labels are justified | rating policy and empirical candidate/group validation |
| Success criteria | reproducible benchmarks, not numeric win guarantee | evaluation report review |

## How to update this log

For each accepted decision change **Status** to Accepted with date and approver. Superseded decisions retain history and link the replacement. Do not retroactively imply approval of unreviewed proposals.
