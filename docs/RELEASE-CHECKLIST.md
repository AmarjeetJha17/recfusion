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

- [ ] Choose and verify repository owner/name, license, visibility, and intended primary branch.
- [ ] Configure the remote and default branch through the authorized repository workflow; this local repository currently has no remote.
- [ ] Review staged and tracked files, Git history, ignore rules, and documentation links before publishing.
- [ ] Protect the primary branch and require the CI quality job before merging.
- [ ] Do not add a README workflow badge until the real repository and workflow URL are confirmed.

## GitHub Actions verification

- [ ] Confirm CI runs on a push to the intended primary branch and on a pull request targeting it.
- [ ] Verify the first hosted run completes dependency sync, Ruff, mypy, tests, pre-commit, and package build.
- [ ] Confirm Python resolves from `.python-version` and the workflow needs no Docker, datasets, model weights, or application secrets.
- [ ] If the target default branch differs from `master`, update and review the workflow branch filters before relying on its status check.

## Documentation and acceptance

- [ ] Confirm README setup, API, Compose, and CI commands match the repository.
- [ ] Keep proposed product, dataset, architecture, and security choices labeled until approved.
- [ ] Verify all published claims distinguish implemented foundations from planned recommendation functionality and measured results from targets.
- [ ] Accept Phase 1 only when local checks pass, the primary branch is confirmed, and hosted CI succeeds.
- [ ] Obtain review/signoff before starting Phase 2.
