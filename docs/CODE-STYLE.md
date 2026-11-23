# CODE-STYLE — Engineering conventions

**Status:** Proposed coding policy; exact formatter/linter versions pinned at bootstrap.

## 1. Principles

- **Readable > clever; explicit contracts > implicit assumptions; measurable behavior > marketing claims.**
- Small cohesive functions and modules; enforce dependency direction described in `ARCHITECTURE.md`.
- Avoid premature generalization, hidden side effects, shared mutable global state, and training logic in request handlers.
- Add tests and documentation with behavior changes; do not silently change public schemas.

## 2. Python

- Target Python 3.13 *subject to dependency compatibility validation*. Use `uv` and lock dependencies.
- Ruff for format/lint, mypy with gradually strict typed package boundaries, pytest for tests.
- Public functions, domain dataclasses/Pydantic contracts and service interfaces should be typed.
- Use descriptive names; `snake_case` for functions/modules, `PascalCase` for classes, `UPPER_CASE` for constants.
- Domain errors as typed exceptions/error results; preserve root cause internally, present safe API messages.
- Use structured logging with `request_id`, `model_version`, `catalog_version`; never log secrets or unnecessary personal data.
- File/DB/network operations behind interfaces with explicit timeouts and cancellation.

## 3. TypeScript / Next.js

- Strict TypeScript; avoid `any` unless explicitly justified.
- Separate presentation components from server/client data-access functions.
- Schema-validate external responses; loading, error, empty and partial-data states are first-class.
- Accessible inputs, focus styles, keyboard navigation and reduced-motion support.
- Prefer colocated feature components and tests over a monolithic components directory.

## 4. ML code

- Separate transforms used during train/eval/serve; serialize feature schemas alongside models.
- Config-driven experiments (YAML or typed configuration), fixed seeds with honest nondeterminism notes, tracked artifact hashes.
- `fit` must not load validation/test targets; no dynamic Internet downloads during reproducibility tests.
- Each metric reports evaluation population, K, filtering rules and model version.
- Distinguish `retrieval_score`, `ranking_score` and calibrated probability; don't name raw scores `confidence`.

## 5. Data and naming

- Time is stored UTC; represent money with decimal precision and explicit ISO 4217 currency.
- Source provenance is required for product specifications and prices; missing fields are `null`/unknown, never invented defaults.
- Domain identifiers are opaque; separate external dataset item IDs from public API IDs.
- Keep sample/synthetic fixture namespaces obvious (`demo_`, `synthetic_`).

## 6. Pull request protocol

Small, reviewable changes with purpose, related docs/ADRs, migration notes, tests run, result logs and risks. Follow Conventional Commits where practical (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`). New dependency requires rationale and lockfile update. Generated artifacts must not be blindly committed.

## 7. Forbidden shortcuts

No `except: pass`, hardcoded keys, bypassing auth for demo routes, silent hard-constraint relaxation, fabricated benchmark data, raw user prompts in telemetry, or disabled failing tests to make CI green.
