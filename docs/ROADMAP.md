# ROADMAP — Gated implementation milestones

**Status:** Phase 1 foundation steps 1.1–1.5 are implemented locally; the phase gate remains pending primary-branch confirmation, a successful hosted CI run, and user sign-off. Later phases remain planned. Approximate part-time horizon **14–20 weeks** is illustrative, not a deadline or promise. Phase gates, not dates, determine progress.

## Phase 0 — Documentation agreement (before implementation)

Deliverables: eight core docs plus data/ML/agent/evaluation roadmap; accepted open decisions; chosen development hardware and catalog provenance plan. **Gate:** documents reviewed, contradiction check passed, outstanding blockers assigned.

## Phase 1 — Repository foundation

Set up monorepo, Python/TypeScript tooling, dependency locks, lint/types/test CI, minimal API `/health` and `/ready`, and PostgreSQL/Qdrant containers if needed. **Gate:** clean clone→setup→tests work on documented environment. No model claims.

## Phase 2 — Dataset feasibility and ETL

Verify dataset license and actual schema, inspect missing fields, profile sparsity, create filtered sample, provenance manifest and chronological split. **Gate:** reproducible dataset with leakage checks and report.

## Phase 3 — Baselines

Implement popularity, content, collaborative baselines with exact metric definitions and stable candidate pools. **Gate:** reproducible baseline report with at least Recall@K/NDCG@K.

## Phase 4 — Neural retrieval

Train Two-Tower PyTorch model, export item embeddings, build index and verify train/serve parity. **Gate:** model artifact, documented tuning and baseline comparison; no assumed gains.

## Phase 4.4C — Research synthesis checkpoint

The aggregate evidence inventory and architecture readiness assessment are in
[`RECOMMENDATION-RESEARCH-SYNTHESIS.md`](./RECOMMENDATION-RESEARCH-SYNTHESIS.md).
The synthesis does not promote a model or advance the Phase 4.2C metadata-use
gate. Its proposed next milestone is evaluation and resource-bound hardening
on synthetic workloads without new model training (see ADR-018 in
[`DECISIONS.md`](./DECISIONS.md)); this proposal awaits project-owner review.

## Phase 5 — Hybrid fusion + ranking

Add semantic retriever, candidate dedup/provenance, hard filters and deterministic fusion. Introduce LambdaRank only with valid labels/query groups. **Gate:** full ablation, cold-start tests and constraint invariants.

## Phase 6 — Backend and state

API, catalog, sessions, user preferences, events, impressions and feedback; migrations and auth boundaries. **Gate:** API contract/integration/authorization tests.

### Phase 6.1A — Recommendation serving contracts (proposed)

The proposed versioned requests/responses, synthetic-only catalog boundary,
artifact compatibility/lifecycle, deterministic eligibility rules, resource
guardrails, and contract/security test plan are recorded in
[`RECOMMENDATION-SERVING-DESIGN.md`](./RECOMMENDATION-SERVING-DESIGN.md).
This is a documentation checkpoint only: no route, provider, registry,
promotion process, or serving model exists. The design awaits project-owner
review and does not close Phase 4.2C.

### Phase 6.1B — Synthetic serving contracts and local application (proposed)

After review of Phase 6.1A, implement the approved core request/response
contracts, deterministic synthetic catalog/history provider, and local-only
application path with unit, API contract, security, and compatibility tests.
Keep models unpromoted until an independent release decision. Use only
invented catalog/history data. Exact scope and limits remain Proposed.

## Phase 7 — Bounded agent workflow

Intent extraction, preference state, typed tools, grounded comparisons/explanations, clarification and no-match recovery. **Gate:** golden cases and adversarial suite pass; no unverified product claims.

## Phase 8 — Frontend experience

Next.js discovery/chat/comparison/profile/ML Explorer with responsive/accessibility checks. **Gate:** complete e2e demo including empty/offline/failure states.

## Phase 9 — MLOps and observability

Model registry/versioning, MLflow experiments, source-aware metrics, traces, alerts, performance benchmark. **Gate:** exact model/data version traceability and documented results.

## Phase 10 — Release hardening

Security and privacy review, tests, deployment, accessible docs, model/data cards, architecture diagrams, demo recording. **Gate:** verifiable public demo or reproducible local demo with explicit limitations.

## Delivery protocol

At each phase: (1) scope/checklist, (2) code and tests, (3) local commands & evidence, (4) failure/limitation report, (5) ADR updates, (6) user signoff. Never label phases complete solely because a file was written.

## v1 Definition of Done

- [ ] Product catalog and source provenance are explicit
- [ ] Reproducible ETL + leakage-aware dataset splits
- [ ] At least three baselines with metrics and cohorts
- [ ] Trained and evaluated Two-Tower with versioned artifact
- [ ] Hybrid fusion and validated hard filtering
- [ ] Optional ranker used only if label construction is defensible
- [ ] Functional cold-start and fallback behaviors
- [ ] Typed agent tools and evidence-grounded explanations
- [ ] Working application for browse, chat, compare, save/feedback
- [ ] Unit/contract/integration/ML/agent/security/e2e tests
- [ ] Documented latency experiment and observability
- [ ] README, architecture, model/data cards, limitations and release instructions
