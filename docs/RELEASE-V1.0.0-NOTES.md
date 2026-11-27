# RecFusion v1.0.0 Release Notes — Draft

**Release status:** Proposed portfolio release only. This draft does not indicate that v1.0.0 has been tagged, published, packaged, or deployed.

## Overview

RecFusion is a local electronics recommendation research prototype with a synthetic-only catalog demonstration and an offline evaluation codebase. The interface demonstrates recommendation contracts and provenance. It does not make a real-world quality, conversion, or commercial-uplift claim.

## Included capabilities

- Browse, search, filter, sort, and inspect invented electronics products.
- Use the frontend's offline fixture recommendation mode without starting the API.
- Optionally start a FastAPI recommendation service bound to loopback for product-to-product, synthetic-user content, and hybrid examples.
- Inspect TF-IDF content results and weighted-RRF hybrid results using warm-only and content-eligible policies.
- Inspect verified catalog-backed product cards, recommendation counts, source attribution, catalog/artifact fingerprints, and explicit failure/retry behavior.
- Reproduce frozen synthetic evaluation scenarios and run Python/frontend checks locally or through GitHub Actions.

## Architecture

The Next.js frontend reads the shared synthetic catalog and has a default
offline fixture path. Its optional development-only API provider sends to a
fixed loopback URL. FastAPI checks its explicit enable flag, exact Origin,
loopback client/server/Host, body limits, and bounded inference concurrency.
It validates a deterministic in-memory synthetic artifact and applies the
existing content and weighted-RRF paths. The frontend resolves returned IDs
against exact catalog identity/fingerprints before showing product metadata.
Offline training and real-data evaluation tooling are not the demo's serving
path. See [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## Synthetic demo evidence

The shared asset is `recfusion.synthetic-catalog.v2`, catalog ID
`synthetic-electronics-v1`. The API, browser fixture path, and frozen test
manifest validate exact asset/catalog identity; artifact and bundle
fingerprints are separately represented. In local Chrome during the Phase
8.3 check, fixture product-to-product returned 5/5; live API
product-to-product 5/5; synthetic-user content 5/5; warm hybrid 4/5; and
content-eligible hybrid 5/5. The UI surfaced the warm list's actual count
without padding. Stopping the API produced an unavailable state and Retry;
after restart, Retry restored live 5/5 results. Fixture mode returned 5/5
while the API was stopped.

These are deterministic synthetic interface and integration examples. They
are not real recommendation metrics or capacity measurements.

## Research evidence and limitations

The real Electronics 5-core pilot is validation-only. Its 1,369-user cohort
had 1,911 eligible positive targets and 45,331 warm train-known candidates at
K=10. The validation-selected Two-Tower checkpoint reported Recall@10
`0.025889` and NDCG@10 `0.015572`, with only 31 recommended unique items
(`0.0684%` of candidates). The one-cohort, validation-selected, concentrated
result is descriptive; it does not establish general model superiority. The
untouched test split remains unevaluated. Ratings/reviews are not confirmed
purchases, impressions, or dislikes.

Synthetic fixtures verify contracts, retrieval integration, source
attribution, eligibility, deterministic outputs, and metric calculations.
Synthetic evidence is kept separate from the real validation table. No
commercial uplift, current inventory, real product specification, or
production serving claim is made.

## Accessibility

The repository records four-width responsive evidence, improved control
contrast, reduced-motion behavior, form labels/IDs, keyboard traversal, and
search focus restoration. Phase 8.3 checked local Chrome catalog, product,
recommendation, error, retry, and fixture flows. Paired screen-reader
verification, exhaustive component clipping review, and full WCAG
certification remain open. See
[`ACCESSIBILITY-AND-PORTFOLIO-REVIEW.md`](./ACCESSIBILITY-AND-PORTFOLIO-REVIEW.md)
and [`PHASE-8-QUALITY-ACCEPTANCE.md`](./PHASE-8-QUALITY-ACCEPTANCE.md).

## Security and privacy

The local API is disabled by default, unavailable in production configuration,
restricted to exact loopback Origin/Host/scope checks, and documented for
direct loopback use only. It has no authentication; loopback checks are not
authorization against other local processes. Do not use a tunnel, proxy, or
public listener. The demo uses invented products and histories only. No
private local `.env`, private Amazon dataset, real product metadata, real-data
checkpoint, or row-level research artifact is part of the tracked release
tree. The demo does not write recommendation history.

## Known non-goals

- No public deployment, production authentication, durable user profiles, or merchant inventory.
- No live Amazon metadata, untouched test evaluation, model training/retraining, or model promotion.
- No browser-side trained model, learned ranker, or bounded agent workflow in the release demo.
- No database or vector service requirement for the local demonstration.
- No claim of recommendation superiority, commercial uplift, production latency, or scalability.

## Git and CI evidence

Phase 8.2 base commit `4e3cc0c8e76cfd5900b0afff921b3972b8d71d94` is
published on `master`. [GitHub Actions run #12](https://github.com/AmarjeetJha17/recfusion/actions/runs/46028982036)
was triggered by push to that SHA and both Python quality and Frontend
quality succeeded. The release-preparation documentation edits are
uncommitted and have no hosted CI result. The current Python package metadata
is `0.1.0`; no package build or publication version change is part of this
draft.

## Release blockers and owner decision

This is a draft until the owner reviews the staged checklist and notes, accepts
the stated research/accessibility limitations, and reviews a final committed
SHA with hosted CI. If full accessibility certification or a published Python
package is expected, that requires additional work and separate approval.

Do not create a tag, GitHub Release, package publication, or deployment from
this draft. ADR-018/019 remain **Proposed** and Phase 4.2C remains **ON HOLD**.
