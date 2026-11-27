# RecFusion — documentation-first project starter

**Status:** Phase 1 repository/API foundations and a Phase 2 source-independent ingestion foundation exercised only with synthetic local fixtures. No recommendation features, trained models, performance measurements, live inventory, or product integrations are implied by this implementation.

RecFusion is an **evaluation-driven hybrid electronics recommender**: classical and neural retrieval generate candidates; deterministic constraints and a learned ranker order products; a bounded agent workflow extracts preferences, calls typed tools, and explains catalog-grounded results. It is **not** an LLM that invents shopping recommendations.

## Reading order

1. [`AGENTS.md`](AGENTS.md) — instructions for AI coding assistants and delivery protocol.
2. [`docs/PRD.md`](docs/PRD.md) — product goals, users, scope, acceptance criteria.
3. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — modules, data flow, service contracts.
4. [`docs/DATABASE.md`](docs/DATABASE.md) — schemas, data ownership and migrations.
5. [`docs/DATASETS.md`](docs/DATASETS.md) — sources, licenses, splits, provenance.
6. [`docs/ML-SYSTEM.md`](docs/ML-SYSTEM.md) — retrievers, ranker, serving and fallback.
7. [`docs/EVALUATION.md`](docs/EVALUATION.md) — leakage-resistant experiments and gates.
8. [`docs/AGENT-WORKFLOWS.md`](docs/AGENT-WORKFLOWS.md) — agent state machine and safety.
9. [`docs/DESIGN-SYSTEM.md`](docs/DESIGN-SYSTEM.md) — accessible design rules.
10. [`docs/SECURITY.md`](docs/SECURITY.md) — trust boundaries and privacy.
11. [`docs/CODE-STYLE.md`](docs/CODE-STYLE.md) — implementation conventions.
12. [`docs/TESTING.md`](docs/TESTING.md) — test pyramid, fixtures, CI.
13. [`docs/ROADMAP.md`](docs/ROADMAP.md) — phased build and definition of done.
14. [`docs/DECISIONS.md`](docs/DECISIONS.md) — proposed decisions and open questions.

## Ground rules

- All performance numbers in these documents are **targets**, never measured results.
- Amazon Reviews 2023 is proposed for offline experiments. Its historical prices and reviews are **not** live Indian product listings, clicks, stock, or sales.
- The live/demo catalog is a separate data contract; synthetic examples must be visibly marked.
- Unresolved product, data, identity, and hosting decisions remain proposed; see `docs/DECISIONS.md`.

## Repository layout

```text
recfusion/
├── AGENTS.md
├── docs/                  # this documentation pack
├── apps/api/              # FastAPI application foundation
├── apps/web/              # Next.js, later
├── packages/recfusion_core/
├── packages/recfusion_data/
├── packages/recfusion_ml/
├── packages/recfusion_agents/
├── configs/
├── scripts/
├── tests/
├── infra/
└── .github/workflows/
```

## API foundation

Install the locked Python dependencies and start the API from the repository root:

```powershell
uv sync --frozen
uv run uvicorn recfusion_api.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

| Endpoint | Purpose | Successful response |
|---|---|---|
| `GET /health` | Liveness only | `{"status":"ok"}` |
| `GET /ready` | Local application initialization only | `{"status":"ready"}` |

Readiness does not check PostgreSQL, Qdrant, or other external services. Swagger UI (`/docs`) and OpenAPI (`/openapi.json`) are enabled outside production and disabled in production. Run the tests with `uv run pytest`.

## Synthetic local data ingestion

The source-independent CSV/JSONL ingestion prototype accepts canonical local data only. It has no external data adapter or download behavior; Amazon Reviews 2023 remains behind its documented terms-review gate. See [`docs/INGESTION.md`](docs/INGESTION.md) for the exact synthetic-fixture command, output manifest, validation policy, and limitations.

## Local PostgreSQL and Qdrant

The local-only Compose stack is in `infra/compose/compose.yaml`. It uses digest-pinned official images: PostgreSQL 18.6 Alpine and Qdrant 1.19.1. Both ports bind to loopback; Qdrant has no API key in this development configuration and must not be exposed publicly.

Copy `.env.example` to `.env`, then set `POSTGRES_PASSWORD` to a unique local secret before starting. Compose rejects a blank password. The `.env` file is ignored by Git. `POSTGRES_USER`, `POSTGRES_DB`, and `POSTGRES_PORT` are also read from that file. PostgreSQL listens on container port 5432; this machine already has a local listener on host port 5432, so the example uses host port 5433. Change `POSTGRES_PORT` if needed. Qdrant REST API uses host port 6333.

```powershell
Copy-Item .env.example .env
# Edit .env and set a unique POSTGRES_PASSWORD before continuing.
docker compose --env-file .env -f infra/compose/compose.yaml config --quiet
docker compose --env-file .env -f infra/compose/compose.yaml up -d
docker compose --env-file .env -f infra/compose/compose.yaml ps
docker compose --env-file .env -f infra/compose/compose.yaml exec -T postgres sh -c 'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --no-psqlrc --command "SELECT 1 AS connectivity_check;"'
curl.exe --fail --silent --show-error http://127.0.0.1:6333/healthz
docker compose --env-file .env -f infra/compose/compose.yaml logs --follow --tail=100 postgres qdrant
docker compose --env-file .env -f infra/compose/compose.yaml restart
docker compose --env-file .env -f infra/compose/compose.yaml down
```

Ordinary `down` preserves both named data volumes. **Destructive reset — permanently deletes local PostgreSQL and Qdrant data:** run `docker compose --env-file .env -f infra/compose/compose.yaml down --volumes` only when you explicitly intend to reset them.

PostgreSQL health uses the image-provided `pg_isready`. The Qdrant image does not include an HTTP client, so its container health check uses `/bin/sh` and `/proc/net/tcp` to confirm that the REST port is listening; the documented `curl.exe` command checks Qdrant's HTTP `/healthz` endpoint directly. If Docker reports that it cannot connect to its engine, start Docker Desktop's Linux engine and retry. If host port 5433 is occupied, choose another unused `POSTGRES_PORT`.

## Python development setup

RecFusion uses Python 3.13 and uv for reproducible Python tooling.

```powershell
uv python install 3.13
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy packages apps/api/src
uv run pytest
uv run pre-commit run --all-files
```

## Continuous integration

The [CI workflow](.github/workflows/ci.yml) runs on pull requests targeting `master` and pushes to `master`. It installs the locked Python dependencies, runs Ruff lint/format checks, mypy, pytest, all pre-commit hooks, and builds the Python package. It does not require Docker, PostgreSQL, Qdrant, datasets, or ML models.

## Synthetic local application demo

The local Next.js app demonstrates invented electronics discovery and an
opt-in loopback-only synthetic recommendation API. Start-up commands,
walkthrough, acceptance evidence, security limits, and unverified responsive
checks are recorded in [`docs/SYNTHETIC-DEMO-ACCEPTANCE.md`](docs/SYNTHETIC-DEMO-ACCEPTANCE.md).
This is a development demonstration, not a public or production service; it
does not access real Amazon data or metadata.
