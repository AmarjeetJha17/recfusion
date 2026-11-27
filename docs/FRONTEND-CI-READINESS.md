# Phase 7.5 — Frontend CI and repository release readiness

**Review date:** 2026-11-27
**Status:** Workflow and local validation recorded; hosted GitHub Actions run pending.

This checkpoint adds frontend quality gates to the existing GitHub Actions CI
workflow. It does not claim a hosted run has passed and does not authorize a
commit, push, deployment, or later phase. ADR-018 and ADR-019 remain
**Proposed**; Phase 4.2C remains **ON HOLD**.

## Workflow coverage

The workflow at [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
continues to trigger on pull requests targeting `master` and pushes to
`master`. Its existing Python quality job is retained. The new independent
frontend job runs on `ubuntu-24.04` with a 15-minute timeout and runs from
`apps/web`:

1. Checks out the repository with checkout credentials persistence disabled.
2. Installs pnpm `11.25.0` using `pnpm/action-setup` pinned to commit
   `d9184bf108216479bc5a137cc391f4d7b14c870b` (release `v6.1.0`).
3. Installs Node.js `24.12.0` using `actions/setup-node` pinned to commit
   `395ad3262231945c25e8478fd5baf05154b1d79f` (release `v6.1.0`). The app
   manifest currently permits Node.js `>=20.9`; CI uses the exact 24.12.0
   runtime recorded in the workflow.
4. Enables setup-node's pnpm package-store cache keyed by
   `apps/web/pnpm-lock.yaml`. It does not cache `node_modules`.
5. Runs `pnpm install --frozen-lockfile`, then the existing `lint`,
   `typecheck`, `test`, and `build` package scripts.

Both jobs inherit workflow-level `contents: read` permissions. No job receives
secrets or write permissions. The frontend job has no deploy, release, or
artifact-upload step. Pull-request cache entries are scoped by GitHub to the
PR merge ref; they do not grant a fork write access to the base branch's
cache. Cache contents are an optimization only; the frozen lockfile remains
the dependency source of truth.

## Python checks preserved

The existing Python job remains on `ubuntu-24.04`, Python from
`.python-version` (`3.13`), and uv `0.13.1`. It retains its frozen dependency
sync, Ruff lint and format checks, mypy, pytest, pre-commit, and Python package
build. Its uv cache remains keyed from Python project and lock files. CI does
not provision Postgres or Qdrant.

## Synthetic-only and service boundaries

Frontend lint, typecheck, tests, and production build operate on checked-in
source and synthetic fixtures. The job does not start the Next.js development
server or FastAPI, invoke the loopback recommendation API, contact a model or
data service, access Amazon data, or require credentials. This is frontend
build and test coverage; it is not browser acceptance, API integration, model
quality evidence, or production release approval.

The existing Biome configuration excludes `next-env.d.ts` and Next.js
generated output. TypeScript includes the generated Next.js declarations as
configured by `tsconfig.json`. The CI job does not gate on a clean post-build
Git diff, so framework-generated declaration changes cannot create a false
dirty-tree failure. Local validation below records whether the production
build rewrites the tracked declaration file in this checkout.

## Local validation record

The commands below were run locally from `apps/web` using Node.js `24.12.0`
and pnpm `11.25.0`. These checks validate the workflow's commands locally;
they do not substitute for a hosted Actions run.

| Check | Result | Evidence |
|---|---|---|
| Frozen pnpm install | Passed | `pnpm install --frozen-lockfile` exited 0 |
| Biome lint | Passed with warnings | `pnpm run lint` exited 0; 21 CSS warnings (17 specificity and 4 reduced-motion `!important`) |
| TypeScript | Passed | `pnpm run typecheck` exited 0 |
| Vitest | Passed | `pnpm run test`: 8 files, 57 tests passed |
| Next.js production build | Passed | `pnpm run build` exited 0; prerendered `/`, `/explore`, not-found, and 9 synthetic product routes |
| Workflow YAML and pre-commit checks | Passed on retry | `uv run --frozen --offline pre-commit run --all-files`: all hooks passed, including `check-yaml`; first attempt failed because inherited malformed `GIT_CONFIG_*` environment entries made Git commands fail |
| Tracked `next-env.d.ts` after build | Verified and restored | Build rewrote two generated route imports; Biome excludes this file. Restored those generated-only lines, so it is not part of the Phase 7.5 change set |
| Hosted GitHub Actions | Unverified | No commit or push was made, so GitHub did not execute this change |

## Scope and remaining release checks

This workflow does not validate responsive browser behavior, full keyboard or
screen-reader flows, network requests, runtime API modes, real-data model
performance, authentication, hosting, or deployment. The manual accessibility
and portfolio limitations remain in
[`ACCESSIBILITY-AND-PORTFOLIO-REVIEW.md`](./ACCESSIBILITY-AND-PORTFOLIO-REVIEW.md).
Hosted CI remains unverified until GitHub executes the workflow after a
reviewed push or pull request. Do not describe this local validation as
hosted CI acceptance.

No recommendation algorithm, API contract, security policy, catalog identity,
or model/data status is changed by this CI addition. Phase 7.5 is not a public
release gate, ADR acceptance, Phase 4.2C approval, or authorization to start
Phase 7.6 or Phase 6.3C.
