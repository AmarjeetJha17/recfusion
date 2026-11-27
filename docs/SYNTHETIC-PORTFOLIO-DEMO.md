# RecFusion Synthetic Portfolio Demonstration

**Phase 7.3 final QA — reviewed 2026-11-27**

**Acceptance:** Conditional GO for a local synthetic portfolio walkthrough; full responsive and manual accessibility sign-off remains open.

## What this demonstrates

RecFusion is an electronics recommendation-system prototype. Its web app is a catalog browser and a Recommendation Lab; it does not run a model in the browser. This demonstration uses invented products and synthetic interaction histories only. Results are interface and integration evidence, not evidence of real-world relevance, accuracy gains, customer behavior, conversion, production use, or service scale.

## Implemented architecture and identities

| Area | Current implementation |
|---|---|
| Shared product source | `packages/recfusion_core/data/synthetic-electronics-v2.json`; 10 records, schema `recfusion.synthetic-catalog.v2`, catalog ID `synthetic-electronics-v1`, catalog version `2` |
| Consumers | TypeScript frontend catalog adapter and Python synthetic API adapter read the same asset; synthetic user contexts and recommendation rankings remain backend inference inputs |
| Asset fingerprint | `b7d29b34eb6eaf5c1d9a935a3c94769023cae6dd8401b0aca1daf4d47fb97c78` |
| Inference compatibility fingerprint | `6cfcdb984ee561b3d4a8f82ed7514f0433e888e3110a6c4c316c5d13fe42ab5f` |
| Recommendation bundle fingerprint | `0244b50e0cff15ffba48c7144101ec5c19d0155d9c558f11683cc8b72d4c85eb` |
| Prepared inference artifact fingerprint | `7f50c2dea0b9374e40433a2519b0bcc863d1f5a097d7755596c6db79a696f3fd` |
| API contract | `recfusion.recommendation-request.v1`, `recfusion.recommendation-response.v1`, and `recfusion.recommendation-error.v1` |
| Content modes | Product-to-product and synthetic-user content use `tfidf_content` v1 with `content_catalog` |
| Hybrid mode | `weighted_rrf` v1 with either `warm_hybrid` or `content_eligible_hybrid` |
| Product card resolution | The frontend requires exact catalog ID, exact asset fingerprint, canonical item membership, and an eligible, visible display record before showing shared catalog metadata. It keeps unknown valid IDs ID-only, retains returned rank, and does not infer cohort labels. |
| Product routes | `/`, `/explore`, and `/products/[id]`; unrecognized product routes use the framework not-found route |

Products 1–8 are catalog-eligible; item 8 has incomplete display metadata. Item 9 is visible but ineligible and is retained as a conflict case. Item 10 is hidden. Their visible, eligible, metadata-complete states are separate checks. The shared catalog contains no real product data.

## Run the demonstration locally

Prerequisites: Python 3.13 and `uv`, Node.js 20.9 or newer, and pnpm 11.25.0. Keep both servers bound to loopback. Use separate PowerShell terminals.

API terminal, from the repository root:

```powershell
uv sync --frozen --offline
$env:RECFUSION_SYNTHETIC_DEMO_ENABLED = "true"
$env:RECFUSION_SYNTHETIC_DEMO_MAX_CONCURRENCY = "2"
$env:RECFUSION_SYNTHETIC_DEMO_ALLOWED_ORIGIN = "http://127.0.0.1:3000"
uv run uvicorn recfusion_api.main:app --host 127.0.0.1 --port 8000
```

Web terminal, from `apps/web`:

```powershell
pnpm install --frozen-lockfile
pnpm dev
```

Open `http://127.0.0.1:3000`. The frontend API URL is fixed to `http://127.0.0.1:8000/v1/recommendations`. Stop both processes with Ctrl+C. Fixture mode works when the API is stopped. Do not use a tunnel, public listener, or forwarding proxy.

## Suggested 3–5 minute walkthrough

1. Introduce RecFusion as a recommendation-system prototype for electronics. State that the displayed catalog and user contexts are invented.
2. Browse Discover. Use the labelled search field, category filters, and sort control. Open an eligible product card, show its recorded synthetic features, then follow a similar-item link.
3. Open Recommendation Lab and start with Fixture mode. It identifies the result as prewritten synthetic ordering and states that it makes no network request.
4. In Local API mode, request product-to-product recommendations. Point out `tfidf_content` v1, `content_catalog`, original ranks, canonical IDs, and source attribution.
5. Select a synthetic profile and run synthetic-user content. Explain that no raw history or preference details are displayed.
6. Run Hybrid in Warm-only mode, then Content-eligible. Describe `weighted_rrf` v1 and the candidate-policy difference. A live warm-only request returned four of five; a content-eligible request returned five of five. The UI reports the actual count and does not pad short lists.
7. Point to the catalog ID and exact asset fingerprint. The UI displays product metadata only after an exact match. Source-list membership records provenance, not preference or causation.
8. Point to the automated local quality checks and the repository's [CI workflow](../.github/workflows/ci.yml), which runs Python lint, format, typecheck, tests, pre-commit, and package build on pushes and pull requests to `master`. The current external CI run status was not queried.
9. Close with limitations: synthetic results are not validated personalization or a real-world quality claim. Real metadata research remains separate. ADR-018/019 remain Proposed; Phase 4.2C remains ON HOLD.

## Phase 7.3 browser evidence

The built application was inspected in local Chrome using its responsive device toolbar. CSS widths were set in the width control; browser zoom was not used as viewport evidence. The browser ran at device scale 1. Local screenshots were viewed during the session but were not saved as repository artifacts.

| CSS viewport | Home | Explore | Product detail |
|---:|---|---|---|
| 1440 px | `scrollWidth` 1440 / 1440; visually inspected | `scrollWidth` 1440 / 1440; visually inspected | `scrollWidth` 1440 / 1440; visually inspected |
| 900 px | `scrollWidth` 900 / 900; visually inspected | `scrollWidth` 900 / 900; visually inspected | `scrollWidth` 900 / 900; visually inspected |
| 700 px | `scrollWidth` 700 / 700; visually inspected | `scrollWidth` 700 / 700; visually inspected | `scrollWidth` 700 / 700; visually inspected |
| 375 px | `scrollWidth` 375 / 375; visually inspected | `scrollWidth` 375 / 375; controls/results inspected | `scrollWidth` 375 / 375; route inspected |

All three routes had no horizontal document overflow at the four tested
widths. The screenshots were viewed locally and were not retained in the
repository. Result-card details and provenance were specifically inspected
at 375 px. This pass did not exhaustively inspect every component edge for
clipping; independent text contrast measurement remains open. A HAR/network
export was not retained.

The browser showed the page landmarks, labelled form controls, recommendation status and ranked lists. It showed these live API results at 375 px:

| Scenario | Returned | Browser-observed contract and card evidence |
|---|---:|---|
| Fixture product-to-product | 5/5 | `tfidf_content` v1, `content_catalog`; IDs `000006`, `000002`, `000007`, `000004`, `000003`; ranks and matching product links shown |
| Local API product-to-product | 5/5 | `tfidf_content` v1, `content_catalog`; five ranked catalog-matched cards with valid detail links |
| Local API synthetic-user content | 5/5 | `tfidf_content` v1, `content_catalog`; no raw history or preference details shown |
| Local API warm hybrid | 4/5 | `weighted_rrf` v1, `warm_hybrid`; the shorter list was announced and not padded |
| Local API content-eligible hybrid | 5/5 | `weighted_rrf` v1, `content_eligible_hybrid`; original ranks and contributing source lists shown |
| Fixture while API stopped | 5/5 | UI stated “Fixture mode · offline · no network request”; a prewritten hybrid result rendered while the API process was stopped |

For the live API cards, the UI displayed catalog ID `synthetic-electronics-v1`, asset fingerprint `b7d29b34…fb97c78`, and artifact fingerprint `7f50c2de…a696f3fd`. All cards inspected had approved metadata and product-detail links. Browser flows did not submit arbitrary/unknown IDs; those and mismatch cases are covered by automated resolver and API tests.

### Accessibility findings

- The browser accessibility tree exposed a skip link, header, main navigation, main region, headings, labelled search/select controls, labelled radio groups, ranked recommendation list items, meaningful product-link names, and a live result status.
- Automated frontend tests passed for keyboard-operable search/category controls, empty-search messaging, accessible loading/empty/error states, retry labelling, and stale-response handling.
- The stylesheet includes focus-visible rules and a `prefers-reduced-motion: reduce` override. The earlier smooth-scroll warning was not reproduced in the local browser console; reduced-motion CSS disables smooth scrolling and animations.
- A complete keyboard-only route traversal and direct visual inspection of focus rings were not established by this run. Text contrast was not independently measured. Treat those checks as unverified. The automated component tests do not substitute for that manual review.
- The production browser console had zero messages. Chrome's Issues panel reported zero page errors, zero breaking changes, and two possible improvements. One finding says a form field without an `id` or `name` appeared on two resources and may affect autofill; the second was not separately identified in the retained inspection. Development-session React DevTools/HMR notices were informational. No HAR was retained, so this is not a complete network audit.

## Catalog integrity and failure handling

The passing frontend suite includes tests for exact catalog/fingerprint joins, unknown IDs remaining ID-only, hidden-item detail suppression, ineligible-item integrity errors, duplicate membership, missing metadata, rank preservation, unavailable detail routes, and explicit empty results. The API suite covers the v1 request schema, typed unknown product/user 404s, invalid requests, empty results, bounded body/K/exclusions, and sanitized server errors. These are automated tests; unknown and restricted IDs were not injected through the browser UI.

Failure behavior covered by automated tests includes API unavailable without fixture fallback, typed 503 mapping, malformed response rejection, timeout, cancellation, stale response suppression, explicit retry, valid empty results, typed 404, and invalid request handling. No live saturation load was generated. The local browser run directly confirmed the fixture provider works while the API is stopped.

Determinism is checked in two layers: the browser fixture provider test resolves repeated identical requests without calling `fetch`, and backend contract tests compare repeated responses after excluding only the volatile `request_id`. The frozen Phase 7.1B baseline checks ordered IDs for product-to-product, synthetic-user, both hybrid policies, and an empty synthetic-user profile. Browser UI requests were not replayed and compared in this session.

## Local API safeguards and limits

The API is disabled by default and rejects activation in production. The demonstration config uses an exact loopback Origin and binds to `127.0.0.1`. The server validates Origin, Host, ASGI client/server loopback scope, and restricted preflight; forwarded headers do not grant loopback scope. It limits the serialized request body to 16 KiB, `k` to 20, exclusions to 64, and concurrency to a per-app default of 2 (maximum 4). The frontend uses a fixed numeric loopback URL; users cannot configure an arbitrary API URL. API request history is not displayed or logged by this flow.

Loopback is not authentication: another local process can call or exhaust the demo. A forwarding proxy could satisfy loopback checks and is unsupported. No public exposure, real-data access, training, promotion, or deployment was part of Phase 7.3.

## Quality checks and current verdict

Frontend: frozen pnpm install passed; typecheck passed; 56 tests passed; build passed and prerendered `/`, `/explore`, and generated product routes. Biome completed with 21 existing CSS warnings (17 descending-specificity warnings and four reduced-motion `!important` overrides); no styling change was made solely to silence them.

Backend: offline frozen sync and lock check passed; Ruff check/format and mypy passed; 369 tests passed. Pytest emitted one existing PyTorch warning because NumPy is absent. Pre-commit passed after retrying with malformed inherited `GIT_CONFIG_*` entries removed from its process environment.

The checked-in [CI workflow](../.github/workflows/ci.yml) defines Python lint, formatting, type checking, pytest, pre-commit, and package-build jobs on pushes and pull requests targeting `master`. Its current remote run status was not queried; the results above are local evidence.

**Conditional GO for a local portfolio walkthrough.** The requested route-by-width matrix has no horizontal overflow at 1440/900/700/375 px. Manual accessibility sign-off remains open: keyboard-only route traversal, direct focus-ring review, and contrast measurement were not completed. Chrome also surfaced an autofill markup improvement. The implementation and automated quality gates passed; browser/API mode flows passed as recorded above. This does not authorize a commit, push, deployment, real-data work, Phase 4.2C, or another implementation phase.
