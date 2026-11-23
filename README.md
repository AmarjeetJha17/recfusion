# RecFusion — documentation-first project starter

**Status:** Pre-implementation planning. No repository source code, trained models, performance measurements, live inventory, or product integrations are implied by these documents.

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
- Do not start Phase 1 implementation until a human reviews and accepts these specifications. `AGENTS.md` gives the handoff workflow.

## Intended repository layout (implementation is future work)

```text
recfusion/
├── AGENTS.md
├── docs/                  # this documentation pack
├── apps/api/              # FastAPI, later
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

**Suggested initial milestone:** documentation review, open-decision resolution, dataset feasibility spike, and automated repository bootstrap.

## Python development setup

RecFusion uses Python 3.13 and uv for reproducible Python tooling.

```powershell
uv python install 3.13
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy packages
uv run pytest
uv run pre-commit run --all-files
```
