# Phase 8.2 — Final Synthetic Evaluation Robustness and Essential Accessibility Closure

**Status:** Quality checks passed locally; paired screen-reader review remains unverified. Owner review pending.
**Scope:** Synthetic-only evaluator regression coverage and local keyboard accessibility. No new ranking logic, feature development, API contract change, model research, or real-data work.

## 1. Existing evaluator audit

The audit found broad existing coverage; it did not add a second evaluator or metric implementation.

| Area | Existing implementation and tests | Coverage before Phase 8.2 |
|---|---|---|
| Ranking metrics | `packages/recfusion_ml/evaluation/metrics.py`; `tests/unit/test_recommendation_evaluation.py`; `tests/unit/test_evaluation_performance.py` | Independent hand calculation for Recall/NDCG/HitRate/MRR/coverage; macro denominator; zero-hit and empty predictions; empty eligible cohort; exact pool, duplicate/unknown IDs, seen items, missing users, short lists and K larger than the pool. |
| Content scenarios | `content_benchmark.py`; `tests/unit/test_content_benchmark.py` | Seed and generator determinism, warm/content-eligible policies, empty-history users, cold-target denominator, conflicts, missing/malformed metadata, zero vectors, ablations, aggregate-only output hashes and strict prior history. |
| Hybrid and RRF | `hybrid_benchmark.py`, `fusion.py`, `tests/unit/test_hybrid_retrieval.py`, `tests/unit/test_rrf.py`, `tests/unit/test_hybrid_benchmark.py` | Warm and content-eligible candidate pools, source-specific eligibility, seen and foreign candidate filters, depth handling, stable ties, duplicate source entries, no fallback, source attribution, candidate-union accounting and deterministic reruns. |
| Serving modes and identity | `tests/integration/test_offline_recommendation_service.py`, `tests/unit/test_synthetic_recommendation_catalog.py`, frontend recommendation tests | Product-to-product, synthetic-user and hybrid requests; unknown product/artifact failure; shared catalog identity; all fixture modes; hybrid policy selection; unknown/conflicted product display safeguards. |
| Frontend states | `apps/web/tests/recommendation-explorer.test.tsx`, `apps/web/tests/components.test.tsx`, and related tests | Search/category controls, result links, loading/empty/error/retry states, stale-response handling, source and mode behavior, and visible keyboard focus patterns in components. |

## 2. Actual gaps addressed

Two reproducibility gaps remained despite local repeated-run tests: no single checked-in manifest froze the seeds, source inputs, catalog identity, bundle identity, and expected aggregate output hashes across three scenario families; and recommendation concentration had no small hand-calculated HHI/max-share oracle. Phase 8.2 adds both without changing metric definitions or retrieval algorithms.

Local keyboard inspection also demonstrated that activating **Clear filters** removed the focused button and returned focus to the page root. The catalog now restores focus to its search field. A Vitest regression test verifies the full keyboard path. A second frontend test verifies arrow-key selection in the recommendation-mode radio group.

## 3. Frozen synthetic scenario manifest

The source of truth is [`tests/fixtures/phase_8_2_synthetic_scenarios.json`](../tests/fixtures/phase_8_2_synthetic_scenarios.json), validated by `tests/unit/test_phase_8_2_quality_acceptance.py`. The tests call the existing generator, content benchmark, hybrid benchmark, and hybrid retrieval function.

| Scenario family | Seed | Existing policy/path | Frozen expected summary |
|---|---:|---|---|
| Warm-only retrieval | 43031 | Content benchmark `warm_only` | 24 eligible candidates, 16 evaluated users, zero eligible cold candidates. |
| Content-eligible cold retrieval | 43031 | Hybrid benchmark `content_eligible_hybrid` | 32 candidates, 8 eligible cold targets across 8 eligible cold users. |
| Sparse/empty-history retrieval | 44041 | Hybrid retrieval with an empty synthetic user's history | Empty profile, 32 eligible candidates, no recommendations, zero source-generated items. |

Each entry records `recfusion.synthetic-content-generator.v1`, seed, source checksums, the synthetic generated catalog fingerprint, its canonical scenario-bundle fingerprint, summary values, and SHA-256 of the canonical output projection. The manifest also pins the shared application catalog ID, catalog fingerprint, compatibility fingerprint, and bundle fingerprint. The benchmark product-source fingerprint and shared application catalog fingerprint are distinct identities and are not interchanged.

The warm and cold families intentionally use the same fixed synthetic seed and source fixture to compare different existing candidate policies. The sparse family uses the existing retrieval implementation with a second frozen seed. These synthetic results demonstrate only repeatability and contracts; they are not empirical recommendation evidence.

## 4. Seed and version policy

Seeds are fixed in the manifest and do not depend on wall-clock time, process state, or test order. Generator schema, scenario manifest schema, catalog identity, and bundle identity are explicit. An intentional fixture or algorithm change must update the expected summaries/hashes in a reviewed change; it must not silently regenerate gold values during a test run.

The test checks source hashes and recomputes each scenario bundle fingerprint from its versioned descriptor. It runs each scenario twice and compares both results with the frozen expected output hash. The canonical hash input is UTF-8 JSON with sorted keys, compact separators, and non-finite values rejected.

## 5. Metric denominator policy

No denominator or metric definition changed.

- Temporal Electronics evaluation continues to exclude users without eligible warm, unseen positive targets from macro metrics and reports exclusion counts separately.
- Synthetic content/hybrid benchmark ranking metrics retain their documented macro user cohort, including users with empty prediction lists. Cold recall uses only users with at least one eligible cold positive; the manifest freezes 8 users and 8 eligible cold targets for the cold scenario.
- Recall divides retrieved relevant targets by that user's eligible target count. Binary NDCG uses the existing ideal DCG through `min(K, eligible targets)`. HitRate is binary; MRR is the reciprocal rank of the first hit and zero if none is returned.
- Catalog coverage is the count of unique returned eligible item IDs divided by the scenario's eligible catalog candidate count, before user-specific seen filtering as defined by each benchmark protocol. Candidate union diagnostics are not final top-K coverage.
- Empty eligible temporal cohorts remain undefined (`null`) under the existing API; an eligible user with an empty or short ranking remains in the macro denominator and receives zero for a no-hit ranking.

The existing independent metric oracle and denominator tests remain authoritative. The new concentration test uses four recommendation placements (`a, b` and `a, c`): three unique products, maximum share 0.5, and HHI 0.375. An all-empty ranking has zero placements and zero concentration values. Concentration counts item placements in top-K output; it is not a relevance metric.

## 6. Candidate accounting and source attribution

The existing candidate contracts continue to reject duplicates, IDs outside the exact train-known pool, train-seen recommendations, and missing per-user rankings where the evaluator requires full coverage. Warm-only excludes cold products. Content-eligible hybrid admits eligible cold products through content retrieval while keeping collaborative candidates restricted to the train-known source pool. Missing, conflicted, hidden, malformed, or zero-vector products remain ineligible according to the existing contracts.

Existing RRF diagnostics tests cover source attribution and the distinction between source-union candidates and final recommendations. Phase 8.2 adds no source names, weights, rank constants, filtering, or fallback behavior.

## 7. Frozen output determinism

The new unit acceptance suite checks all three scenario output hashes and input/bundle/catalog fingerprints. Existing content and hybrid report tests continue to compare repeated manifest bytes and hashes. Volatile runtime durations, timestamps, and request IDs are excluded from the frozen scenario output projections. Existing SMALL/MEDIUM/LARGE resource caps and opt-in requirements are unchanged; Phase 8.2 adds no optimization.

## 8. Accessibility evidence and limitations

**Passed in local Chrome with keyboard input:**

- Traversed the home route through skip link, navigation, browse/recommendation links, sort/search, category filters, all product links, and the end of the page; no keyboard trap was observed.
- Opened the Recommendation Lab by keyboard and traversed its source, mode, context, candidate-policy, result-count, and submit controls. Arrow keys selected product-to-product, synthetic-user, hybrid, and content-eligible candidate policy.
- Ran all three fixture modes by keyboard. Result product links were focusable, had visible focus, and a product link opened its canonical product-detail route. Product detail breadcrumb and related product links were traversable.
- Typed a no-match search, reached category checkboxes and **Clear filters**, and verified the fix returns focus to the search field after the empty state disappears.
- Selected Local API mode and reached the unavailable-service alert and retry control by keyboard. The retry was activated; the service was intentionally not running, so the unavailable state remained. This verifies the browser error/retry interaction, not a successful browser-to-API response.

The browser was local to the workspace; no remote Browser Use worker was used. The local development server was stopped after testing. Existing Phase 7.4 viewport results remain the responsive-layout evidence; Phase 8.2 did not repeat the 1440/900/700/375 measurements.

**Unverified:** no paired NVDA/Chrome or Narrator/Chrome review was performed. The browser accessibility tree and keyboard checks are not screen-reader verification. There is no complete WCAG conformance claim. Browser dev output included Next.js's non-blocking `scroll-behavior` configuration warning; no app runtime error was reported during the observed route interactions.

## 9. Quality gate results

| Check | Result |
|---|---|
| Frozen frontend install | `pnpm install --frozen-lockfile` passed with pnpm 11.25.0 / Node 24.12.0. |
| Biome | Passed with 21 warnings: 17 CSS specificity warnings and four intentional reduced-motion `!important` warnings. |
| TypeScript | `pnpm run typecheck` passed. |
| Vitest | `pnpm run test` passed: 59 tests across 8 files. |
| Next.js build | `pnpm run build` passed and prerendered `/`, `/explore`, and the synthetic product routes. |
| Frozen Python environment | `uv sync --frozen --offline` passed. |
| Ruff lint and format | Passed after formatting the new test module. |
| mypy | Passed with no issues in 81 source files. |
| pytest | `uv run --frozen pytest` passed: 375 tests, 1 existing PyTorch warning because NumPy is absent. |
| Python package build | `uv build` passed for source distribution and wheel. |
| pre-commit | `uv run --frozen --offline pre-commit run --all-files` passed: all configured hooks. |

These are local quality gates. No hosted GitHub Actions run was triggered because the changes are intentionally uncommitted and unpushed.

## 10. Research limitations

All Phase 8.2 scenarios are synthetic, small, and fixture-defined. They establish repeatability, candidate accounting, metric calculations, and contract behavior only. They provide no real catalog relevance, user behavior, cold-start performance, statistical significance, model superiority, or serving-capacity evidence. The Electronics validation pilot remains a separate real-data validation result, and its untouched test split remains untouched.

## 11. Release blockers versus deferred work

**Before a v1.0 release that claims accessibility readiness:** paired screen-reader checks and owner review of the remaining accessibility limitations are still needed. The local keyboard audit is not WCAG certification. The new code has local quality evidence only; hosted CI has not run on this uncommitted change set.

**Deferred by governance or scope:** Amazon metadata acquisition, private Amazon CSV access, untouched test evaluation, training/retraining, checkpoint promotion, algorithm/RRF/TF-IDF changes, API v1 changes, public deployment, production auth/registry/rollback work, and new real-data research. These are not Phase 8.2 failures; they remain outside authorization or require separate gates.

## 12. Phase 8.3 handoff

Phase 8.2 adds no authorization to start Phase 8.3. The project owner should review the staged tests and report, decide whether to require paired screen-reader evidence before v1.0, and confirm the next phase scope. Until that review, ADR-018 and ADR-019 remain **Proposed**, Phase 4.2C remains **ON HOLD**, and the real test split remains unused.

**Phase 8.2 disposition:** **CONDITIONAL GO for owner review of Phase 8.3 scope.** No Phase 8.3 implementation is authorized by this report.
