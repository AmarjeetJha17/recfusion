# Repository Publication Checklist

Use this before making the repository public or accepting the first external contribution. Check items only after verifying them on the target repository and machine.

## Local foundation checks

- [ ] `uv sync --frozen`
- [ ] `uv run ruff check .`
- [ ] `uv run ruff format --check .`
- [ ] `uv run mypy packages apps/api/src`
- [ ] `uv run pytest`
- [ ] `uv run pytest --cov=packages --cov=apps/api/src --cov-report=term-missing`
- [ ] `uv run pre-commit run --all-files`
- [ ] `uv build --offline`
- [ ] With the ignored `.env` populated locally: `docker compose --env-file .env -f infra/compose/compose.yaml config --quiet`
- [ ] If local services are needed, verify loopback bindings and health; use ordinary `docker compose down` to preserve data.
- [ ] Start the API using the README command and verify `/health`, `/ready`, and development OpenAPI.

## Security review

- [ ] Run an approved secret scanner over the complete Git history and working tree; verify no local `.env`, credentials, datasets, checkpoints, or generated artifacts are tracked.
- [ ] Confirm `.env.example` contains placeholders only and `.env` remains ignored.
- [ ] Review dependency and GitHub Action updates; keep the Python lockfile and immutable action references current.
- [ ] Confirm workflow permissions remain least-privilege and CI does not receive application secrets.
- [ ] Confirm PostgreSQL and Qdrant remain loopback-only. Do not expose unauthenticated Qdrant publicly or treat local Compose settings as production configuration.
- [ ] Confirm production debug mode is false; review authentication, authorization, privacy, retention, TLS, backups, and incident-response requirements before any deployment.

## Repository publication

- [x] Verify repository owner/name, visibility, and intended primary branch. Current repository: `AmarjeetJha17/recfusion`, public, `master` (retained public at the user's direction).
- [ ] Choose and record a repository license; GitHub currently reports no license.
- [x] Verify the configured `origin` remote and that local and remote `master` point to the published audit commit.
- [x] Review tracked files and Git history paths; a common credential-pattern scan found no matches across the published commit history. This does not replace a full secret-scanner run.
- [ ] Protect the primary branch and require the CI quality job before merging.
- [ ] Do not add a README workflow badge until the real repository and workflow URL are confirmed.

## GitHub Actions verification

- [x] Confirm CI runs on a push to the intended primary branch and on a pull request targeting it (`master`).
- [x] Verify the hosted run on `963607da6f34ae99a01556a7d17ec9853bd94499` completed successfully: dependency sync, Ruff, mypy, tests, pre-commit, and package build.
- [x] Confirm Python resolves from `.python-version` and the workflow needs no Docker, datasets, model weights, or application secrets.
- [x] Confirmed the target default branch is `master`, matching the current workflow branch filters.

## Documentation and acceptance

- [ ] Confirm README setup, API, Compose, and CI commands match the repository.
- [ ] Keep proposed product, dataset, architecture, and security choices labeled until approved.
- [ ] Verify all published claims distinguish implemented foundations from planned recommendation functionality and measured results from targets.
- [ ] Accept Phase 1 only when local checks pass, the primary branch is confirmed, and hosted CI succeeds.
- [ ] Obtain review/signoff before starting Phase 2.
