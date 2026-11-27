# RecFusion v1.0.0 Release Checklist

**State:** Draft for project-owner review. No v1.0.0 tag, GitHub Release, package publication, or deployment has been created.

**Audited commit:** `4e3cc0c8e76cfd5900b0afff921b3972b8d71d94` (`master`; Phase 8.2). It is published and had a clean worktree at the start of Phase 8.3. The release-preparation documentation changes are currently uncommitted; they are not included in the audited SHA and have no hosted CI result.

## Release scope

RecFusion v1.0.0 is scoped as a local synthetic electronics recommendation research prototype. It includes a Next.js UI, an explicitly activated loopback FastAPI demo, a shared versioned synthetic catalog, identity/fingerprint checks, TF-IDF content retrieval, existing weighted-RRF hybrid inference over fixed synthetic sources, offline evaluation code, and local/hosted quality checks. It is not production serving, a real-data demo, or a commercial listing service.

## Evidence checklist

| Area | Status | Evidence and remaining limit |
|---|---|---|
| Phase 8.2 committed and published | Pass | SHA `4e3cc0c8e76cfd5900b0afff921b3972b8d71d94`; GitHub `master` matched at audit start. |
| Hosted Python and frontend CI | Pass for audited SHA | [Run #12](https://github.com/AmarjeetJha17/recfusion/actions/runs/46028982036), push trigger, both jobs succeeded. This does not cover later documentation edits. |
| Frozen dependency setup | Pass locally and in isolated checkout | `uv sync --frozen`, `uv lock --check`, and `pnpm install --frozen-lockfile` passed. The isolated worktree at the audited SHA completed both frozen installs; Python 3.13.11 / uv 0.13.1 and Node 24.12.0 / pnpm 11.25.0. |
| Python package build and catalog assets | Pass locally and in isolated checkout | `uv build` built sdist and wheel in both checkouts. The primary-checkout wheel was inspected and contains `synthetic-electronics-v2.json` and its manifest. Package metadata remains version `0.1.0`; no package release is proposed. |
| Frontend production build | Pass locally and in isolated checkout | Next.js build prerendered `/`, `/explore`, and nine synthetic product routes. |
| Shared catalog and fingerprints | Pass | Backend/frontend tests check shared asset identity; browser response and cards displayed matching catalog/artifact fingerprints. |
| Product discovery/search/filter/sort/detail | Pass in local Chrome | Search, category filter, sort, verified catalog cards, and canonical product-detail navigation observed. |
| Fixture product-to-product | Pass in local Chrome | 5/5 returned; fixture mode remained operational while the API was stopped. |
| API product-to-product | Pass in local Chrome | 5/5 returned with TF-IDF provenance and verified product cards. |
| Synthetic-user content | Pass in local Chrome | 5/5 returned; no raw history displayed. |
| Warm hybrid | Pass in local Chrome | 4/5 returned; short-list count surfaced and no filler was added. |
| Content-eligible hybrid | Pass in local Chrome | 5/5 returned; candidate policy and source attribution shown. |
| API failure and retry | Pass in local Chrome | Unavailable state appeared with retry; after API restart, retry returned 5/5. |
| Frozen synthetic scenarios | Pass at Phase 8.2 | Three scenario families, input/catalog/bundle fingerprints, and canonical output hashes are tested in `tests/unit/test_phase_8_2_quality_acceptance.py`. No empirical quality claim follows. |
| Keyboard and responsive accessibility evidence | Partial | Keyboard route, mode, product, empty-search recovery and retry checks recorded. Four viewport widths have Phase 7.4 evidence. Paired screen-reader review, exhaustive visual clipping audit, and full WCAG certification remain unverified. |
| Research claims | Pass with restrictions | Real Electronics evidence is validation-only; test split untouched; synthetic results separate. No superiority or commercial uplift claim. |
| Privacy/security contents audit | Pass for tracked release tree | No tracked `.env`, `.next`, `node_modules`, private checkpoint, or local machine path found. Tracked Amazon-named CSVs are tiny test fixtures documented as synthetic; private/local research data are not included in the tracked tree. No private CSV contents or untouched test rows were read in Phase 8.3. |
| Local quality gates on the release-prep working changes | Pass | Frontend: frozen install, Biome (21 warnings: 17 CSS specificity and 4 intentional reduced-motion `!important`), typecheck, 59 Vitest tests across 8 files, and production build passed. Next emitted a non-blocking `scroll-behavior` configuration warning. Python: frozen sync/lock check, Ruff check/format (180 files), mypy (81 files), 375 pytest tests, package build, and pre-commit passed. Pytest emitted one existing PyTorch warning because NumPy is absent. A parallel pytest attempt during build had one transient Git-working-tree-manifest mismatch; isolated retry and the final sequential full suite passed. |
| Hosted CI on the final release-prep SHA | Pending | Documentation edits are not committed or published; run #12 applies to the audited base SHA only. |
| Owner release approval | Pending | Required before any tag, GitHub Release, package publication, or public deployment. None is authorized here. |

## Release blockers and accepted limitations

Before an owner approves a portfolio-only v1.0.0 release, review the draft
release notes and checklist, accept the synthetic-only boundary and research
limitations, and decide whether paired screen-reader evidence is required as a
release gate. The current accessibility record is not a WCAG certification.

If the owner expects a published Python package, its project metadata still
declares version `0.1.0`; deciding and validating that package version is a
separate release requirement. The current scope does not publish a package.

The final documentation SHA and its hosted CI status do not exist until the
owner reviews and commits/publishes these docs. The project has no production
auth, model promotion/rollback registry, public service, real catalog, or
commercial performance evidence. These are explicit non-goals for this local
prototype release.

## Governance and owner approval

- [ ] Owner approves the v1.0.0 portfolio scope and synthetic-only demo label.
- [ ] Owner accepts the real-validation and synthetic-evidence separation.
- [ ] Owner accepts the remaining accessibility limitations or requests paired screen-reader evidence.
- [ ] Owner reviews the final committed SHA and its hosted Python/frontend CI.
- [ ] Owner explicitly authorizes a tag or GitHub Release in a later action.
- [ ] Owner explicitly authorizes public deployment only if that scope is separately proposed and reviewed.

ADR-018 and ADR-019 remain **Proposed**. Phase 4.2C remains **ON HOLD**. No
test-split evaluation, model training/promotion, real metadata acquisition,
API contract change, tag, push, or deployment is part of this checklist.
