# Phase 8.1 — Research Readiness and Next-Stage Architecture Review

**Review date:** 2026-11-27
**Scope:** Evidence and architecture review only. No feature implementation, model training, real-data evaluation, test-split access, deployment, or API contract change was performed.

## Executive assessment

RecFusion is a credible research prototype with a useful, synthetic-only local demonstration and a reproducible offline evaluation stack. It is not a production recommendation service, and the available evidence does not establish that any model is generally superior. The real-data evidence is a narrow validation pilot with a warm-only candidate universe and validation-selected checkpoints. All content and hybrid cold-item quality figures are from small, engineered synthetic fixtures. The untouched real test split remains untouched.

The best next bounded milestone is **evaluation-protocol robustness on synthetic workloads**, building on ADR-018's Proposed direction. It should test repeatability, metric/candidate-policy invariants, and resource-bound reporting without opening private data or claiming product relevance. This recommendation is for owner review; it does not authorize implementation. A separate accessibility closure is also a reasonable low-risk engineering milestone. Real metadata or test evaluation must remain gated by a separate rights, governance, and project-owner decision.

## Review boundary and repository state

The review used the documented research reports, architecture and data contracts, CI/accessibility/demo records, current tracked implementation, and Git history. No private dataset, real interaction CSV, checkpoint binary, or ignored artifact was opened. No model was trained, promoted, or evaluated. No changes were made to source code or API behavior.

At review start, the worktree was clean on `master`, tracking `origin/master`. HEAD and `origin/master` were both `427f50190e4afac7ea876c19826b09aeef9c6898` (`docs(ci): record verified hosted quality gates`). Relative to the hosted CI-verified commit `f695bc3a8761b5930d9f91e1fa6c7f804444773b`, that commit changes only `docs/FRONTEND-CI-READINESS.md` and `docs/ROADMAP.md`. The current repository state is therefore published and clean before this review's documentation changes.

## Project maturity by area

| Area | Current maturity | Evidence and boundary |
|---|---|---|
| Real-data recommendation research | Exploratory validation | A 10k-user coursework pilot has aggregate-only validation results. It is not independent test evidence, a population-level result, or a production model selection. |
| Content and hybrid quality | Synthetic feasibility | Small fixtures validate contracts and illustrate behaviors. They do not estimate real-catalog relevance or cold-start performance. |
| Offline evaluation | Strong protocol foundations; limited experimental breadth | Leakage-aware training/validation separation, train-known candidates, strict prior histories, explicit eligibility, and aggregate reporting are documented. Seed/cohort/model-selection limitations remain. |
| Local serving | Synthetic development demonstration | An opt-in loopback-only route uses an in-memory invented catalog and validated synthetic artifacts. There is no production provider, authentication, registry, promotion, rollback, or deployment lifecycle. |
| Catalog identity | Strong synthetic boundary | Backend and frontend consume one versioned synthetic catalog; exact identity and fingerprints guard product-card rendering. This says nothing about rights or correctness for a real catalog. |
| Frontend and accessibility | Portfolio-demo readiness with open manual checks | Browser review covered three routes at four viewport widths and measured selected accessibility behaviors; full keyboard and paired screen-reader review remain open. |
| CI | Hosted quality gates verified for the published CI commit | Both Python and frontend jobs passed on `f695bc3...`; later `427f501...` is documentation-only. Warnings are recorded below. |
| Data governance | Real metadata remains blocked | Phase 4.2C remains ON HOLD; no Amazon metadata acquisition, join, or expanded data use is approved. |

## Research evidence

### Real validation evidence

The documented real-data pilot uses a private/local, owner-scoped, non-commercial coursework Electronics 5-core dataset. The events are review/rating signals, not purchases, impressions, exposures, or confirmed negative feedback. The project's academic-use assessment is not a blanket legal clearance or independent institutional determination. Metadata acquisition and joining remain held under Phase 4.2C.

The reported cohort contains 1,369 users and 1,911 distinct eligible positive targets, evaluated at K=10 against 45,331 train-known candidate items. Relevance is provisionally defined as rating at least 4; train-seen items are excluded. The warm-only policy excludes cold catalog items. The validation record describes 3,153 positive observations before cold-item exclusions. Missing interactions are not treated as known negatives for interpretation. The test files were checksum-verified in the documented runs but their rows were not parsed; the untouched test split must stay unused until a separately approved selection protocol is complete.

| Validation model | Recall@10 | NDCG@10 | HitRate@10 | MRR@10 | Unique recommended items / candidate coverage |
|---|---:|---:|---:|---:|---:|
| Popularity | 0.022784 | 0.009878 | 0.029949 | 0.006866 | 15 / 0.0331% |
| Item-CF | 0.005990 | 0.003259 | 0.008035 | 0.002870 | 750 / 1.6545% |
| BPR | 0.011566 | 0.005384 | 0.013148 | 0.003633 | 1,312 / 2.8943% |
| History-aware Two-Tower | 0.025889 | 0.015572 | 0.033601 | 0.014899 | 31 / 0.0684% |

These are descriptive outcomes for one validation setup, not a superiority claim. Two-Tower has the highest listed ranking metrics and very low catalog coverage: its top ten items account for 93.02% of placements; normalized entropy is 0.2293, Gini is 0.999770, and mean list overlap is approximately 0.9035. BPR used one seed and selected epoch 13 using the same validation data used for comparison. Two-Tower selected epoch 2 from that validation set; NDCG declined to 0.001794 by epoch 20 while training loss continued to fall. This is consistent with overfitting, but does not prove its cause. Validation checkpoint selection creates optimism in model comparisons.

The paired user bootstrap uses 2,000 resamples, but intervals are exploratory and unadjusted for multiple comparisons or validation-based selection. With sparse eligible targets, most users tie. These intervals do not repair the selection issue or create independent confirmation.

### Two-Tower history and concentration

The user representation combines the user ID embedding with the mean of up to 50 recent prior item-ID embeddings. It uses events regardless of rating and only strict prior history. The item tower uses item IDs only, so it cannot retrieve unseen items from product content. There is no ANN index in this 45k-candidate evaluation; full-candidate inference is practical at the documented scale but says little about larger catalogs.

In the single documented history ablation, empty-history NDCG@10 was 0.015737 and Recall@10 0.026254, compared with 0.015572 and 0.025889 for normal history. Empty-history output contained 15 unique items versus 31; average list overlap was 0.973 and vector cosine similarity 0.972. Also, 7,806 of 65,842 training positive targets had empty history. This checkpoint-level ablation suggests limited incremental ranking effect in this setup, not that history is generally useless. Concentration, ID-only retrieval, 5-core selection, and warm-only eligibility limit generalization and cold-start conclusions.

### Coverage versus relevance and candidate generation

Popularity has very low recommendation coverage. Item-CF and BPR increase the number of distinct recommended items, while the Two-Tower achieves the best observed ranking metrics at markedly lower coverage than either. The real fusion checks did not establish a gain: four-source RRF reached NDCG@10 0.009649 (106 unique items); Two-Tower+BPR reached 0.009890 (299 unique items). Their paired differences versus popularity included zero, and Two-Tower+BPR was lower than standalone Two-Tower in the reported comparison. Aggregate source-union coverage is not final top-K coverage. No fusion evidence supports a production choice.

Candidate generation is constrained to warm train-known IDs for collaborative models. Item-CF can return short lists for sparse users; BPR and Two-Tower do not provide content-driven cold-item retrieval. Full scoring over 45,331 items has not been replaced or benchmarked against ANN. There is no realistic long-tail or 0-core evidence, no exposure correction, no availability-time catalog, and no confirmed negative label. Do not extrapolate these results to cold products, new users, or a current marketplace.

### Synthetic evidence and its limits

The Phase 4.3B content fixture contains 24 warm products, 18 cold products, 16 synthetic users, 70 train interactions, and 27 evaluation interactions. Content-only cold recall is 7/8 (0.875) among its eligible synthetic positives. The Phase 4.4B hybrid fixture uses 16 synthetic users and fixed profiles: content retrieved 7/8 eligible cold positives at K=5, while hybrids retrieved 0/8 at K=5 and K=10 and 7/8 at K=20. These are engineered behavior demonstrations, not statistically supported results, learned collaborative quality, or evidence for the real catalog. They must not be combined with the real validation table.

All TF-IDF content and hybrid content/popularity quality figures are synthetic. There is no real-content baseline because real metadata use is still gated. A learning-to-rank baseline is also not justified yet: defensible query groups and unbiased relevance labels are absent.

## Evaluation methodology assessment

**Strengths:** the protocol documents immutable train/validation/test boundaries, train-only vocabulary and feature fitting, strict temporal history, full train-known candidate sets, explicit cold-item exclusions, no future target leakage, aggregate-only outputs, and source checksums. The documented real runs did not parse test rows. Synthetic unit/contract tests provide good coverage of deterministic filtering and evaluator behavior.

**Limits and future opportunities:** only one narrow cohort/pilot is available; neural results are single-seed; checkpoint selection and model comparison reuse validation; bootstrap intervals are exploratory; the 5-core sample is selection-biased; there is no real content retrieval or cold-item result, no exposure-aware label, no multiple temporal validation windows, and no independent test outcome. The reserved test split is correctly untouched and must remain so. Missing interactions remain unknown, while BPR's sampled unobserved examples are a modeling assumption, not observed dislike.

Useful future ablations, after protocol review, include deterministic reruns across fixed seeds on synthetic data, popularity-stratified coverage/concentration summaries, controlled history perturbation cases, and candidate-policy invariants. Real-data multi-seed or test analyses are explicitly outside this phase. Any future supervised reranker depends on suitable unbiased labels and query groups.

## Engineering and governance assessment

### Serving, catalog, and artifacts

The API is a modular monolith. A separately guarded development-only `POST /v1/recommendations` can be enabled for a local synthetic demo. It is disabled by default and rejected in production configuration; it applies loopback Origin/Host/client/server checks, a 16 KiB body bound, K and exclusion caps, and bounded concurrency. It serves an in-memory synthetic catalog and validated artifact at startup. The frontend defaults to fixtures and only calls this route in explicit local integration mode.

The shared synthetic catalog has an explicit schema/version and is consumed by Python and TypeScript. Asset, compatibility, and bundle fingerprints serve distinct integrity purposes. Recommendation cards require exact catalog identity and fail closed for missing, mismatched, hidden, or ineligible records. These safeguards are purposeful and should not be removed as cleanup. The implementation is not a production online system: it has no authentication, durable profiles, external catalog/history provider, production model registry, promotion/rollback path, ANN index lifecycle, or public deployment validation. A local loopback policy does not provide authentication or protect against a forwarding proxy.

ADR-019 remains **Proposed**. Its current context overstated that the API exposes only health/readiness and its limitations described every route/field/resource bound as still unimplemented. This review corrects that factual drift while retaining the Proposed status and all production limitations. This does not accept the ADR or change API contracts.

### Determinism and performance

Artifact/catalog identity and inference contracts are versioned and deterministic in synthetic tests. Phase 5 performance checks used SMALL (20 users, 100 warm candidates, 144 synthetic rows) and MEDIUM (200 users, 5,000 warm candidates, 5,440 synthetic records) workloads. Profiling overhead was measured at 27.85% in the paired run; measured operations and outputs matched. Windows process peak RSS was unavailable. Phase 5.2 concluded **NO OPTIMIZATION NEEDED**: profiling did not show a meaningful bottleneck. These local synthetic timings do not establish serving capacity or an SLA. SMALL is suitable for CI; MEDIUM and LARGE runs are opt-in and bounded.

### Accessibility, hosted CI, and technical debt

The Phase 7.4 local Chrome audit covered home, explore, and product routes at 1440, 900, 700, and 375 CSS pixels, with no horizontal document overflow. It checked selected contrast, reduced-motion, identifiers, API modes, error/retry, and keyboard behavior. Full keyboard traversal, paired screen-reader testing, exhaustive component clipping review, and a retained HAR remain unverified; portfolio readiness is therefore conditional.

GitHub Actions run [#10](https://github.com/AmarjeetJha17/recfusion/actions/runs/46021624320) verified Python and frontend jobs on published commit `f695bc3a8761b5930d9f91e1fa6c7f804444773b`. Python reported 369 passing tests and a PyTorch warning because NumPy is absent. Frontend quality passed with 21 Biome warnings (17 CSS specificity and four reduced-motion `!important` overrides) and Node deprecation warnings for `punycode` and `url.parse()`. The wheel and source distribution were created in the ephemeral runner; no artifact was published. The current `427f501...` is a later documentation-only commit, so that run does not claim CI execution on current HEAD.

Meaningful technical debt is limited and explicit: the ADR-019 prose drift, unverified manual accessibility tasks, no production auth/registry/promotion lifecycle, no real-content/cold-start evidence, and the narrow/validation-selected model evidence. Existing version/fingerprint checks and resource guardrails are justified by their integrity and safety contracts. Phase 5 found no evidence that performance optimization is needed. CI warnings should be triaged deliberately; suppressing them without understanding their sources is not a readiness goal.

### Data governance

Phase 4.2C remains **ON HOLD**. No Amazon metadata should be acquired or joined under this recommendation. The existing academic-use assessment is not enough to establish current reuse, derivative-artifact, storage, or publication rights. A future gate would need source-specific terms, owner/institution review as applicable, lineage and retention decisions, and an explicitly approved data plan. This phase did not access real interaction CSVs.

## Prioritized next-stage alternatives

Complexity is relative: low means documentation/manual verification; medium means bounded code/tests and repeatable synthetic experiments; high means new production interfaces or external governance.

| Priority | Alternative | Research value | Engineering depth | Complexity | Reproducibility / evaluation | Portfolio value | Governance risk | Dependencies / blockers |
|---:|---|---|---|---|---|---|---|---|
| 1 | Synthetic evaluation robustness and protocol hardening | Medium; improves confidence in implementation behavior, not recommender quality | Medium | Medium | High if fixtures/seeds/metrics are frozen | High for research rigor | Low | Owner review of ADR-018; synthetic-only scope |
| 2 | Manual accessibility closure for current demo | Low research value; high usability confidence | Low–medium | Low–medium | High and directly auditable | High | Low | Browser/screen-reader availability and recorded checklist |
| 3 | Real metadata/content or untouched test research | Potentially high | Medium–high | High | Potentially high after governance and protocol gates | High | High | Separate rights/owner review, frozen analysis plan; not authorized here |
| 4 | Production serving lifecycle (auth, registry, promotion, rollback, index) | Low immediate research value; high operational value later | High | High | Needs explicit operational and compatibility tests | High | Medium–high | Accepted serving architecture, threat model, model/catalog/data governance, SLOs |
| 5 | Train a new ranker / semantic retriever | Unclear before valid labels and real content | High | High | Currently weak without valid labels and independent protocol | Medium–high | High | Data rights, trustworthy labels, frozen candidate universe and evaluation protocol |

### Recommended proposal: synthetic evaluation robustness (ADR-018 continuation)

**Goal:** Demonstrate that RecFusion's evaluation and synthetic serving contracts produce deterministic, auditable outputs across a small, frozen set of synthetic scenarios, while keeping resource use bounded.

**Justification:** The real pilot's one-seed, validation-selected neural comparisons and the synthetic content/hybrid fixtures answer different questions. Before any broader research, the project can improve repeatability and protocol confidence without touching gated data or training. Existing metrics and candidate filters provide a concrete foundation; Phase 5 found no need for speculative optimization.

**Required evidence:** Versioned synthetic scenario definitions; scenario and output hashes; explicit user/item eligibility and candidate-universe declarations; frozen metric implementations; repeated-run equality; expected results for empty history, short candidates, exclusions, ties, cold/warm policies, and concentration summaries; bounded runtime/record/report limits. Clearly label all results synthetic and do not compare them with real validation numbers.

**Acceptance criteria:**

1. Owner reviews the proposal and the scope remains synthetic-only; no ADR is auto-accepted.
2. At least three frozen, distinct synthetic scenario families exercise warm collaborative ranking, cold-content eligibility, and sparse/empty histories. Scenario definitions and data-generation seeds are versioned.
3. Repeated runs for each fixed scenario/seed produce byte-stable canonical aggregate reports and identical metric outputs.
4. Contract tests assert candidate eligibility, exclusions, tie order, no implicit fallback, metric denominators, and empty/short result behavior.
5. Reports include candidate-pool sizes, cohort counts, recommendation coverage/concentration, run limits, and explicit synthetic labels; no item-level or user-level private output is created.
6. The SMALL profile remains within documented CI bounds; larger profiles require explicit opt-in and cannot access real-data paths.
7. Documentation records all executed commands and results, warnings, and limitations. CI passes on the commit under review before the milestone is called complete.

These criteria establish reproducible implementation behavior only. They have no target relevance score, do not claim recommendation quality, and do not justify serving-capacity claims.

**Risks:** Overfitting scenario design to expected outputs; fixture complexity obscuring production behavior; confusing deterministic synthetic results with empirical validity; introducing brittle snapshots; resource measurements varying by platform.

**Dependencies:** Project-owner review; ADR-018 scope confirmation; inventory of current evaluators/fixtures to prevent duplicate harnesses; existing synthetic-only security and data boundaries.

**Explicit non-goals:** Amazon data/metadata access; reading or evaluating the untouched real test split; model training/retraining/promotion; API contract or algorithm changes; real-catalog quality, cold-start, relevance, or capacity claims; ANN adoption; production deployment; ADR-018/019 acceptance; releasing Phase 4.2C.

### Secondary option: accessibility closure

**Goal:** Close the manual checks already identified for the local synthetic portfolio demo. **Justification:** The automated/local viewport evidence is useful but does not establish complete keyboard or screen-reader usability. **Required evidence:** Route-by-route keyboard checklist, paired screen-reader notes, focused clipping review, and retained browser evidence with app/API mode identified. **Acceptance:** No critical keyboard trap or inaccessible control in the tested routes; errors and retry state are announced and reachable; remaining exceptions are documented. **Risks:** Screen-reader differences and scope creep into redesign. **Dependencies:** Local browser and screen-reader access. **Non-goals:** Changing recommendation behavior, claiming WCAG conformance from a partial audit, production release, or touching real data.

### Deferred alternatives and gates

Real metadata/content and test-set research are deferred until source terms, rights, institutional/owner review, intended use, retention, and an analysis plan are independently approved. The untouched test split stays untouched. Production-serving work should follow only after explicit product/operational requirements, threat model, auth, artifact/catalog lifecycle, compatibility, rollback, and service-level evidence are designed. A learned ranker or semantic retriever should wait until defensible labels, query groups, and a valid evaluation protocol exist.

## Governance and final disposition

- ADR-018: **Proposed; awaiting project-owner review**.
- ADR-019: **Proposed; awaiting project-owner review**.
- Phase 4.2C: **ON HOLD**.
- No Amazon metadata acquisition, real interaction CSV access, model training, test evaluation, model promotion, service deployment, or API contract change occurred in this review.
- Documentation changes should be staged for owner review only. No commit or push is made.

**Disposition:** **CONDITIONAL GO to review the synthetic evaluation robustness proposal.** This is not authorization to start implementation. Accessibility closure is a viable alternative. Real-data evaluation, metadata use, production serving, and model development remain blocked by their separate evidence and governance gates.

## Evidence sources reviewed

Project and governance: [`AGENTS.md`](../AGENTS.md), [`PRD.md`](./PRD.md), [`ARCHITECTURE.md`](./ARCHITECTURE.md), [`DATASETS.md`](./DATASETS.md), [`DATA-CONTRACTS.md`](./DATA-CONTRACTS.md), [`EVALUATION.md`](./EVALUATION.md), [`SECURITY.md`](./SECURITY.md), [`TESTING.md`](./TESTING.md), [`ROADMAP.md`](./ROADMAP.md), and [`DECISIONS.md`](./DECISIONS.md).

Research, performance, and serving: [`RECOMMENDATION-RESEARCH-SYNTHESIS.md`](./RECOMMENDATION-RESEARCH-SYNTHESIS.md), [`MODEL-COMPARISON.md`](./MODEL-COMPARISON.md), [`CONTENT-BENCHMARK.md`](./CONTENT-BENCHMARK.md), [`HYBRID-BENCHMARK.md`](./HYBRID-BENCHMARK.md), [`EVALUATION-PERFORMANCE.md`](./EVALUATION-PERFORMANCE.md), [`RECOMMENDATION-SERVING-DESIGN.md`](./RECOMMENDATION-SERVING-DESIGN.md), [`OFFLINE-RECOMMENDATION-INFERENCE.md`](./OFFLINE-RECOMMENDATION-INFERENCE.md), and [`SYNTHETIC-RECOMMENDATION-API.md`](./SYNTHETIC-RECOMMENDATION-API.md).

Demo, catalog, accessibility, and CI: [`SYNTHETIC-PORTFOLIO-DEMO.md`](./SYNTHETIC-PORTFOLIO-DEMO.md), [`SYNTHETIC-CATALOG-ALIGNMENT.md`](./SYNTHETIC-CATALOG-ALIGNMENT.md), [`VERIFIED-RECOMMENDATION-CARDS.md`](./VERIFIED-RECOMMENDATION-CARDS.md), [`ACCESSIBILITY-AND-PORTFOLIO-REVIEW.md`](./ACCESSIBILITY-AND-PORTFOLIO-REVIEW.md), and [`FRONTEND-CI-READINESS.md`](./FRONTEND-CI-READINESS.md). The hosted workflow link above is the primary evidence for the recorded GitHub Actions conclusions.
