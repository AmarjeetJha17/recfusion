# Accessibility and portfolio review

**Phase 7.4 review:** 2026-11-27
**Status:** Local browser checks recorded; project-owner review pending.

This review covers the local synthetic frontend and its explicitly enabled
loopback API. It is not a production release approval. ADR-018 and ADR-019
remain **Proposed**; Phase 4.2C remains **ON HOLD**.

## Starting state and scope

The Phase 7.3 implementation is committed at `ed06b14`
(`docs(qa): record synthetic portfolio demo acceptance`) on `master`. The
checkout was clean before Phase 7.4 edits; the branch was four commits ahead
of `origin/master`. This review changes only form identifiers, control-border
contrast, tests, and documentation. It does not change recommendation
algorithms, catalog identities, API contracts, or security policies.

Local Chrome was used against the app at `127.0.0.1:3000` and the documented
development API at `127.0.0.1:8000`. Responsive widths were explicit CSS
viewport overrides at device scale 1. Screenshots were inspected in the
browser during the run but were not saved in the repository. No HAR was
retained.

## Responsive route check

At every requested width, `document.documentElement.scrollWidth` equalled
`clientWidth` for home, Explore, and product detail. Chrome's vertical
scrollbar consumed 15 CSS pixels in these measurements, so the values are
reported directly rather than treating `innerWidth` as the document width.

| CSS viewport (`innerWidth`) | Home | Explore | Product detail |
|---:|---:|---:|---:|
| 1440 px | 1425 / 1425 | 1425 / 1425 | 1425 / 1425 |
| 900 px | 885 / 885 | 885 / 885 | 885 / 885 |
| 700 px | 685 / 685 | 685 / 685 | 685 / 685 |
| 375 px | 360 / 360 | 360 / 360 | 360 / 360 |

Values are `scrollWidth / clientWidth`. No horizontal document overflow was
observed. At 375 px, the screenshot showed wrapped catalog/artifact
fingerprints, product IDs, provenance, and product-card text inside the page.
The first 375 px screenshot showed a 5 px crop at the right edge of the
header. The mobile page/header width was reduced to keep the full “Demo mode”
label inside the available layout. A follow-up screenshot showed the label
fully visible, with the header ending at x=344 in a 360 px content viewport;
all three routes were rechecked at 375 px and retained no horizontal
overflow. Search and select controls measured 46.4 px high, the submit
button 46 px, category chips 40.8 px, and mode cards 68 px. The screenshot
also showed the skip link when keyboard focus was on it, as intended.

## Keyboard and semantic checks

**Passed in the local browser:**

- The skip link became visible on focus and moved the page to `#main-content`.
- The home-page browse and recommendation-lab actions were activated by
  keyboard; the recommendation action opened `/explore`.
- Source and mode radio groups accepted arrow-key selection. The context
  select and submit button received visible focus outlines.
- A ranked product link opened its canonical detail route; the similar
  product link on detail also opened a product route.
- After an intentionally blocked local API request, keyboard Enter on
  **Retry request** recovered to live recommendations.
- The accessibility tree exposed header navigation, main landmark, labelled
  search/select controls and radio groups, ranked list items, meaningful
  product links, result status, and recommendation provenance.

The full keyboard-only path through every search, filter, sort, product card,
detail control, provenance item, loading state, and error-recovery state was
not completed. Keyboard trap, screen-reader announcements with a paired
assistive technology, and exhaustive focus order remain **unverified**.
Component tests cover keyboard behavior for search/category controls and
accessible loading, empty, error, retry, and stale-response states; they do
not replace those manual checks.

## Form association and browser issues

Chrome's earlier Issues panel had reported a form field without an `id` or
`name`, potentially affecting autofill. The catalog search and sort controls
now have unique stable pairs: `catalog-search` and `catalog-sort`. Regression
coverage checks both attributes and ID uniqueness. In the rendered home page,
both controls had their expected IDs, names, and labels. After the change,
Chrome's Issues panel reported **0 page errors, 0 breaking changes, and 0
possible improvements**.

The Recommendation Lab's synthetic-context and result-count selects retain
their existing IDs and associated labels. Source and mode radios have group
labels, associated wrapping labels, and stable `name` attributes.

## Contrast and motion

WCAG 2.2 AA reference thresholds used: 4.5:1 for normal text, 3:1 for large
text, and 3:1 for required non-text control boundaries and states.

| Rendered pair | Measured ratio | Result |
|---|---:|---|
| `#0f172a` body text on white | 17.85:1 | Pass |
| `#475569` muted text on white | 7.58:1 | Pass |
| `#1d4ed8` primary text/link on white | 6.70:1 | Pass |
| White button text on `#1d4ed8` | 6.70:1 | Pass |
| Original `#cbd5e1` control border on white | 1.48:1 | Fail |
| Revised `#64748b` control border on white | 4.76:1 | Pass |
| Revised `#64748b` control border on `#eef3f7` | 4.26:1 | Pass |

The original select/search/filter boundary was too faint to meet the 3:1
non-text threshold. A dedicated `--control-border: #64748b` now applies to
selects, the search wrapper, and filter chips; the general decorative border
token is unchanged. This limited change preserves card and divider styling.

Chrome emulated `prefers-reduced-motion: reduce`: `matchMedia` returned true,
document scroll behavior became `auto`, and button transitions and animated
elements computed to `0.00001s`. The emulation was cleared after checking.
This verifies the existing CSS override under the emulated preference; the
host operating-system preference was not changed.

## Browser API and fixture acceptance

| Browser scenario | Result | Evidence |
|---|---|---|
| Fixture, product-to-product | Pass, 5/5 | `tfidf_content` v1, `content_catalog`; UI identified offline fixture mode and no request |
| Local API, product-to-product | Pass, 5/5 | `tfidf_content` v1, `content_catalog`; catalog-backed cards and detail links |
| Local API, synthetic-user content | Pass, 5/5 | `tfidf_content` v1, `content_catalog`; no raw history displayed |
| Local API, warm hybrid | Pass, 4/5 | `weighted_rrf` v1, `warm_hybrid`; short list announced, not padded |
| Local API, content-eligible hybrid | Pass, 5/5 | `weighted_rrf` v1, `content_eligible_hybrid` |
| Unavailable/failed request | Pass, error surfaced | UI stated the local API was unavailable and offered **Retry request**; no fixture result was substituted |
| Retry after API restored | Pass | Enter on **Retry request** returned to live API results (5/5) |

The API-backed results displayed schema version, algorithm and candidate
policy, catalog and artifact fingerprints, original ranks, canonical item
IDs, and source attribution. Identity/metadata remained tied to the exact
catalog ID, fingerprint, canonical membership, and display eligibility.
No arbitrary IDs were submitted through the browser controls.

Browser requests observed for the application were limited to the frontend
and the fixed numeric loopback API. Browser console error/warning retrieval
returned no entries; Chrome's Issues panel was clear after the form fix.
Next.js development emitted informational React DevTools/HMR notices in the
native local browser. The intentionally blocked API request was part of the
failure/retry check. No HAR was retained, so this is not a packet-level or
payload audit.

## Real-data research evidence and demo limits

The synthetic portfolio demo is UI and contract evidence only. It does not
establish real-world relevance, personalization quality, or conversion.
Earlier real collaborative experiments are recorded separately in
[`RECOMMENDATION-RESEARCH-SYNTHESIS.md`](./RECOMMENDATION-RESEARCH-SYNTHESIS.md):
on one 10,000-user Electronics 5-core pilot, the validation-selected
Two-Tower checkpoint had NDCG@10 `0.015572`, Recall@10 `0.025889`, and only
`0.000684` K=10 candidate coverage (31 of 45,331). Its checkpoint was selected
on validation; no independent test set was evaluated. The low coverage and
selection optimism limit interpretation. Amazon review signals are not
purchase conversions, impressions, or confirmed negative feedback. The
synthetic Phase 4.4B cold-item results are a separate toy benchmark and must
not be combined with those real interaction metrics.

ADR-018 and ADR-019 remain **Proposed**. Phase 4.2C remains **ON HOLD**. No
real Amazon metadata access, model retraining, model promotion, deployment,
commit, push, or Phase 6.3C work occurred in this review.

## CI and remaining limitations

The repository workflow at [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
runs Python lint, formatting, mypy, pytest, pre-commit, and package build.
It does not run the frontend quality commands. GitHub returned no combined
status entries for the reviewed Phase 7.3 commit, so remote CI status is
**unverified**. Local checks run for this Phase 7.4 documentation and
accessibility change are recorded in the final report and the portfolio demo
document.

Remaining manual work: full keyboard traversal across all controls and
routes; paired screen-reader review; wider component-by-component clipping
inspection; and retaining a browser Network/HAR artifact if a future audit
requires detailed request payload/timing evidence. The local browser
acceptance is a conditional portfolio walkthrough, pending project-owner
review; it is not a public release or production approval.
