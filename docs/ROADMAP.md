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

### Phase 6.1B — Synthetic serving contracts and local application (owner review pending)

A local synthetic application-service checkpoint is implemented and described
in [`OFFLINE-RECOMMENDATION-INFERENCE.md`](./OFFLINE-RECOMMENDATION-INFERENCE.md).
It includes versioned contracts, a deterministic invented catalog/history
provider, safe synthetic content-artifact validation, and adapters for the
existing content and weighted-RRF retrieval. It has no production
recommendation route, release promotion, production model, or real-data input.
Phase 6.2A adds a separately documented, guarded development-only route over
the synthetic service. ADRs 018/019 remain Proposed and Phase 4.2C remains ON
HOLD.

### Phase 6.3A — Synthetic electronics discovery frontend (owner review pending)

The local Next.js frontend provides catalog discovery and a fixture-backed
recommendation explorer using invented electronics records only. It makes no
API or external network requests and does not use Amazon interaction data or
metadata. Scope, run instructions, contracts, fixture limits, and the Phase
6.3B handoff are documented in
[`SYNTHETIC-FRONTEND.md`](./SYNTHETIC-FRONTEND.md). This checkpoint does not
advance ADRs 018/019 or the Phase 4.2C hold.

### Phase 6.3B — Controlled local frontend/API integration (owner review pending)

The frontend keeps offline fixture mode as its default and adds an explicit
development-only option for the loopback synthetic API. Exact-Origin checks,
ID-only API result presentation, local run instructions, and remaining
limitations are documented in
[`LOCAL-FRONTEND-API-INTEGRATION.md`](./LOCAL-FRONTEND-API-INTEGRATION.md).
This remains a local synthetic integration only; it does not authorize
production serving, real-data access, or advancement of ADR-018/019 or
Phase 4.2C.

### Phase 6.3C — Recommendation experience, provenance, and explainability UI (owner review pending)

The synthetic Recommendation Lab explains each mode and candidate policy,
shows only response-backed provenance, and reports short/empty/error states
without adding fallback results. Its original cohort-label behavior was
removed during Phase 7.1B. This remains presentation-only. See
[RECOMMENDATION-EXPERIENCE.md](./RECOMMENDATION-EXPERIENCE.md). ADR-018/019
remain Proposed and Phase 4.2C remains ON HOLD.

### Phase 6.4 — Synthetic application demonstration (conditional owner review)

The existing discovery frontend and explicit loopback API were demonstrated
with synthetic fixtures and all three API request modes. Automated frontend
and backend quality checks passed. Exact CSS viewport checks at 1440, 900,
700, and 375 px remain unverified; see
[`SYNTHETIC-DEMO-ACCEPTANCE.md`](./SYNTHETIC-DEMO-ACCEPTANCE.md). The
checkpoint remains conditional pending owner review of those responsive
checks. ADR-018/019 remain Proposed, and Phase 4.2C remains ON HOLD.

### Phase 7.1B — Unified synthetic catalog implementation

The shared `recfusion.synthetic-catalog.v2` package-data JSON is consumed by
the backend and frontend. Backend IDs 1–10 remain authoritative; the retired
frontend-only records and old recommendation fixtures are archived. API v1,
candidate policies, ranking weights, and frozen ordered recommendations are
preserved. Asset-byte, inference-compatibility, and bundle fingerprints are
separate and checked. See
[`SYNTHETIC-CATALOG-ALIGNMENT.md`](./SYNTHETIC-CATALOG-ALIGNMENT.md) for
evidence and limitations. This milestone does not start Phase 7.2, alter ADR
status, or release Phase 4.2C from ON HOLD.

### Phase 7.2 — Verified synthetic recommendation product cards (owner review pending)

The Recommendation Lab uses an exact shared-catalog ID and asset-fingerprint
resolver before showing synthetic product metadata or detail routes. Original
ranks, counts, source attribution, policy context, and API v1 remain unchanged.
Automated frontend checks and local loopback mode smoke passed. Unknown,
mismatched, hidden, duplicate, incomplete, and ineligible identity behavior is
covered by resolver/component tests. See
[`VERIFIED-RECOMMENDATION-CARDS.md`](./VERIFIED-RECOMMENDATION-CARDS.md).
The Phase 7.2 checkpoint left exact 1440/900/700/375 browser measurements
and complete responsive/accessibility acceptance open; the later Phase 7.4
audit records the measurements and remaining manual gaps. This implementation
is awaiting project-owner review; it does not change ADR-018/019 status or
Phase 4.2C ON HOLD.

### Phase 7.4 — Accessibility closure and portfolio release audit (owner review pending)

Local Chrome verified all three routes at 1440, 900, 700, and 375 CSS px with
no horizontal document overflow. Form control contrast was measured and the
search/select/filter boundaries were strengthened; reduced-motion emulation,
stable search/sort identifiers, local API modes, failure messaging, and
keyboard retry recovery were checked. Browser results and limitations are
recorded in [`ACCESSIBILITY-AND-PORTFOLIO-REVIEW.md`](./ACCESSIBILITY-AND-PORTFOLIO-REVIEW.md)
and [`SYNTHETIC-PORTFOLIO-DEMO.md`](./SYNTHETIC-PORTFOLIO-DEMO.md).

Full keyboard traversal, paired screen-reader testing, exhaustive component
clipping review, and a retained HAR remain unverified. The audit does not
advance a release milestone or change ADR-018/019 or Phase 4.2C, which remains
ON HOLD. Project-owner review is pending.

### Phase 7.5 — Frontend CI and repository release readiness (hosted CI verified; owner review pending)

The existing GitHub Actions workflow retains its Python quality job and adds
a separate frontend job for frozen pnpm installation, Biome, TypeScript,
Vitest, and the Next.js production build. Both jobs are read-only and run on
pull requests to and pushes on `master`; the frontend job is synthetic-only,
does not call the local API, and does not upload build artifacts. The local
workflow and frontend checks are documented in
[`FRONTEND-CI-READINESS.md`](./FRONTEND-CI-READINESS.md). Both hosted jobs
passed on published commit `f695bc3a8761b5930d9f91e1fa6c7f804444773b` in
[GitHub Actions run #10](https://github.com/AmarjeetJha17/recfusion/actions/runs/46021624320).
The CI gate is verified for this commit; project-owner review remains pending.
This checkpoint does not change ADR-018/019 Proposed status or the Phase 4.2C
ON HOLD status.

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
