# Phase 7.5 — Frontend CI and repository release readiness

**Review date:** 2026-11-27
**Status:** Hosted GitHub Actions verification passed on published commit
`f695bc3a8761b5930d9f91e1fa6c7f804444773b`; project-owner review remains
pending.

This checkpoint adds frontend quality gates to the existing GitHub Actions CI
workflow and records hosted verification for the published commit below. It
does not authorize deployment or a later phase. ADR-018 and ADR-019 remain
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

## Hosted GitHub Actions verification

| Field | Verified value |
|---|---|
| Published commit | [`f695bc3a8761b5930d9f91e1fa6c7f804444773b`](https://github.com/AmarjeetJha17/recfusion/commit/f695bc3a8761b5930d9f91e1fa6c7f804444773b) |
| Trigger | Push to `master` |
| Workflow run | [Run #10 — success](https://github.com/AmarjeetJha17/recfusion/actions/runs/46021624320) |
| Python quality job | [Success](https://github.com/AmarjeetJha17/recfusion/actions/runs/46021624320/job/140582435985) |
| Frontend quality job | [Success](https://github.com/AmarjeetJha17/recfusion/actions/runs/46021624320/job/140582436317) |

The run was for the exact published commit above. GitHub reported every step
in both jobs as successful:

- Python: checkout, Python and uv setup, frozen dependency install, Ruff,
  formatting, mypy, pytest, pre-commit, and `uv build`.
- Frontend: checkout, pnpm and Node setup, frozen install, Biome, TypeScript,
  Vitest, and Next.js production build.

The Python job built `recfusion-0.1.0.tar.gz` and
`recfusion-0.1.0-py3-none-any.whl` in its ephemeral runner. GitHub reported
zero workflow artifacts, so neither package was published as a workflow
artifact.

### Hosted warnings and the earlier failed attempt

The Python test step passed **369 tests** with one PyTorch warning because
NumPy is absent in the CI environment. The frontend job passed with 21 Biome
CSS warnings (17 specificity warnings and four reduced-motion `!important`
warnings), plus Node deprecation warnings for `punycode` and `url.parse()`.
These warnings did not fail their steps. GitHub reported no failed, skipped,
cancelled, or warning-conclusion steps and no annotations.

The preceding run for `3b7acff` failed in pre-commit because this report had
trailing whitespace. That whitespace was removed in the published commit
above; pre-commit passed in run #10. The actual run and job summaries are
linked above.

### Hosted security and data audit

The workflow file fetched from the exact published commit has workflow-level
`contents: read` permissions. Checkout uses `persist-credentials: false` in
both jobs. Checkout, setup-python, setup-uv, pnpm/action-setup, and
actions/setup-node are pinned to full commit SHAs. The jobs contain no deploy,
release, or production API activation. No user-defined repository secret is
referenced; checkout uses GitHub's standard read-only job token and disables
credential persistence. The commands install lockfile-pinned software
dependencies and run quality checks; no Amazon dataset download or serialized
model/checkpoint acquisition occurred. The Python build packaged a source
module named `two_tower_checkpoint.py`, not a model checkpoint or weights. No
workflow artifacts were uploaded.

Both job logs were retrievable through GitHub's workflow-job API and reviewed.
A targeted scan found no common GitHub, AWS, or OpenAI secret-token patterns;
the temporary checkout Authorization value was masked as `***`. This is a
log inspection for this run, not a guarantee about later workflow changes.

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
| Hosted GitHub Actions | Passed | Run #10 on the published commit above; both jobs and every listed step succeeded |

## Scope and remaining release checks

This workflow does not validate responsive browser behavior, full keyboard or
screen-reader flows, network requests, runtime API modes, real-data model
performance, authentication, hosting, or deployment. The manual accessibility
and portfolio limitations remain in
[`ACCESSIBILITY-AND-PORTFOLIO-REVIEW.md`](./ACCESSIBILITY-AND-PORTFOLIO-REVIEW.md).
This hosted result covers one push run and does not replace browser acceptance,
manual accessibility review, production security review, or future CI runs.

No recommendation algorithm, API contract, security policy, catalog identity,
or model/data status is changed by this CI addition. Phase 7.5 is not a public
release gate, ADR acceptance, Phase 4.2C approval, or authorization to start
Phase 7.6 or Phase 6.3C.
