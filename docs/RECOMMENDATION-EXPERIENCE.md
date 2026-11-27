# Recommendation Experience

**Status:** Phase 6.3C synthetic UI implementation for owner review.

## 1. UX objectives

The Recommendation Lab identifies the selected mode and source, active
candidate policy, current synthetic context, result counts, and provenance
actually present in the response. It presents one result set at a time and
does not change ranking, candidate eligibility, or model policy.

## 2. Mode terminology

| Mode | User-facing description | Versioned algorithm |
| --- | --- | --- |
| Product to product | Retrieves eligible products by similarity over available approved content features. Similarity is not proof of preference. | `tfidf_content` v1 |
| Synthetic-user content | Uses permitted prior synthetic training interactions and product content to form a temporary retrieval context. History is not displayed. | `tfidf_content` v1 |
| Hybrid | Combines separately ranked synthetic collaborative and content lists using the existing weighted Reciprocal Rank Fusion policy. | `weighted_rrf` v1 |

Different modes can use different candidate sets and return different list
lengths. The UI does not compare scores across modes or label one mode as
better.

## 3. Provenance field mapping

| Response field | Presentation |
| --- | --- |
| `mode` | Human-readable mode name |
| `algorithm_id`, `algorithm_version` | Algorithm label and stable identifier/version |
| `candidate_policy`, `policy_id` | Policy label plus stable identifiers |
| `catalog_id`, `catalog_fingerprint` | Catalog identity and fingerprint |
| `artifact_fingerprint` | Shown only when supplied |
| `request_id` | Shown only when supplied |
| `rank` | Preserved response order and rank |
| `source_names[]` | One safe label per contributing ranked source, retaining each code |
| `reason_codes[]` | Safe text derived only from recognized reason codes |
| `result_count` and requested K | Returned/requested count when requested K is available |

The frontend v1 parser validates known codes. No raw feature vectors, histories,
filesystem paths, server exception text, or fabricated source contributions are
shown. Missing optional provenance is omitted or labeled unavailable.

## 4. Safe explanation principles

Source membership says which ranked lists contained an item; it does not prove
that a source caused a preference. “Retrieved using product-content similarity”
and “ranked by weighted RRF over source-list positions” describe the implemented
mechanism without claiming a personal preference or causal explanation.

## 5. Warm/cold terminology

The UI does not show per-item warm/cold labels. The policy explanations retain
their existing meanings: `warm_hybrid` uses the backend's train-known set;
`content_eligible_hybrid` can include visible, catalog-eligible items in the
content index. These are candidate rules, not quality, stock, or commercial
availability labels. API v1 does not expose per-item cohort metadata.

Hybrid policy explanations preserve source rules: `warm_hybrid` limits eligible
items to train-known synthetic items. `content_eligible_hybrid` can admit eligible
cold products through content retrieval; its collaborative source pool remains
train-known.

## 6. Short-list semantics

The UI reports the actual returned count and requested K. If fewer than K are
returned, it explains that policy eligibility and available candidates can
produce a shorter list. It never appends filler or switches to fixture results.

## 7. Empty, error, and timeout states

A valid `no_results` response is a completed request with a zero count and no
ranked items; it is not an alert. Loading and result counts use polite status
announcements. Errors use an alert and sanitized text. Typed unknown-product
and unknown-user errors explain the missing synthetic context. Unsupported
requests, malformed responses, service unavailability, timeout, and capacity
saturation keep safe bounded messages. Retry repeats only the selected source
and current form selections. Cancellation and stale-response protection remain
in place. There is no automatic retry or implicit fixture fallback.

## 8. Fixture versus Local API

Fixture mode remains the default and makes no request. It displays shared
synthetic catalog product details and frozen backend-generated recommendation
fixtures. Local API mode is an explicit development-only opt-in to fixed
loopback transport. API results join to product routes only when both catalog
ID and the exact shared asset fingerprint match. Unknown IDs and mismatched
fingerprints remain canonical IDs with response-backed provenance only.

## 9. Accessibility

Native radio groups, fieldsets, labels, semantic headings, a polite live mode
description, live result counts, loading status, and alert errors provide
keyboard and screen-reader context. Source and reason entries are lists; stable
codes remain visible beside plain-language labels. Focus and reduced-motion
behavior continue to use existing design-system rules.

## 10. Responsive behavior

The existing two-column explorer collapses at the established tablet breakpoint.
Provenance grids use content-sized columns that collapse as space narrows, and
long identifiers wrap. Existing responsive layout rules are retained. New
browser measurements at 1440, 900, 700, and 375 pixels have not been captured
for this checkpoint.

## 11. Synthetic-only limitations

All UI and tests use invented synthetic records or mocked v1 responses. The
interface does not access Amazon data, load real checkpoints, claim model
quality, show real metadata, or make production recommendations. The API v1
contract has no per-item cohort metadata. Product display joins are permitted
only after exact shared asset fingerprint validation.

## 12. UI testing results

Focused component/provider tests cover mode explanations, safe wording,
candidate policy identifiers, source/reason attribution, count and short-list
behavior, valid empty output, retry without fixture fallback, and safe typed
404 messages. Validation completed with frozen frontend installation, lint,
typecheck, all 41 frontend tests, and production build passing. Backend
regressions also passed: offline frozen sync and lock check, Ruff lint/format,
mypy, all 363 pytest tests, and pre-commit. Biome reports 22 pre-existing CSS
warnings; this change adds none. The Python suite reported one installed
PyTorch warning because NumPy is absent; no test failed.

## 13. Browser acceptance evidence

The owner documented local Chrome acceptance for Phase 6.3B in
LOCAL-FRONTEND-API-INTEGRATION.md, including local fixture/API paths and
unavailable-service behavior. That evidence predates these 6.3C presentation
changes. A local in-app browser showed the updated hybrid policy, actual 3-of-5
count, source attribution, and safe reason label after this change. The
available browser interface did not expose a calibrated viewport override, so
the requested exact 1440/900/700/375-pixel measurements remain open for owner
review.

## 14. Deferred improvements

- Capture exact responsive widths and horizontal-overflow measurements in a
  supported local browser.
- Consider richer per-item cohort provenance only through a separately reviewed
  API contract change.
- Evaluate side-by-side comparisons only if a future request orchestration
  contract is approved.

## 15. Proposed Phase 6.4 demonstration scope

Proposed: a reproducible local synthetic demonstration of catalog discovery,
single-result recommendation modes, fixture/API source selection, provenance,
empty/error recovery, and responsive keyboard navigation. It should retain
fixed loopback transport, exact-Origin checks, fixture default, synthetic-only
data, and current review gates. This proposal does not authorize deployment,
real-data use, production serving, or acceptance of ADR-018/019. Phase 4.2C
remains ON HOLD.
