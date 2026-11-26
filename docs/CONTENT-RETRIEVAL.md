# Synthetic content retrieval baseline

**Status:** Phase 4.3A implementation and tests use synthetic products and
interactions only. This module is not a product-data ingestion pipeline, does
not authorize dataset use, and has not been used with real Amazon data.

## Feature contract

`recfusion_ml.retrieval.content` provides deterministic sparse TF-IDF item and
user-profile retrieval. Content inputs are explicit canonical product records
and, when available, a matching `recfusion.product-normalization.v1` record.
The feature schema is `recfusion.content-feature.v1`; the persisted sparse
index schema is `recfusion.content-tfidf-index.v1`.

The approved text fields are title, category, categories, description,
features, normalized brand, and normalized electronics specifications
(RAM/storage capacity, storage type, display size, weight, battery capacity,
processor, and GPU). Raw attributes, source attribute keys, ratings, rating
counts, prices, images, videos, store/seller values, and identifiers are never
tokenized. Missing and malformed field statuses remain visible. Products marked
`conflict_retained` are ineligible for fitting and retrieval; conflicting
records are not merged or selected by input order.

Text is Unicode NFKC-normalized and case-folded. The tokenizer retains common
electronics model/unit punctuation (for example `USB-C`, `M.2`, and `2.4GHz`).
Term frequency is raw count; IDF is smoothed as
`log((1 + document_count) / (1 + document_frequency)) + 1`; sparse vectors use
L2 normalization and cosine similarity. Vocabulary terms are selected by
corpus frequency with lexical tie-breaking, then stored in lexical order.
Stable item-key tie-breaking is used for equal recommendation scores.

## Fitting, candidates, and histories

Callers supply reference products separately from candidate products. Only
eligible reference documents fit the vocabulary and IDF. The candidate set
does not change fitted statistics, so a cold item can be transformed and
retrieved without contributing to vocabulary fitting. Callers are responsible
for supplying the intended train-only reference catalog and explicit
catalog-eligible item keys. Empty or all-out-of-vocabulary queries return no
results; there is no popularity fallback.

User profiles accept training-split `Interaction` records only. The profile
uses unique positive-rated products (rating at least 4 by default) with event
times strictly earlier than the prediction time. Equal-time and future events
are excluded. The target product is masked from profile construction, while
all strictly prior observed items are retained in the seen set for candidate
exclusion. Product vectors are averaged equally and normalized. Missing product
content is counted and does not create an inferred preference. The resulting
profile contains no user identifier and is intended to be ephemeral.

This is content retrieval, separate from collaborative embeddings and neural
retrieval vectors. Product metadata has no point-in-time guarantee; if real
metadata is later used, describe it as snapshot metadata and do not claim
historical availability or catalog state.

## Reproducibility, artifacts, and resource limits

The implementation uses the Python standard library; it adds no dependency.
The deterministic JSON artifact records feature/tokenizer/artifact schemas,
configuration, code revision, candidate policy, source catalog manifest hashes,
vocabulary checksum, counts, and sparse vectors. It does not serialize Python
objects or raw source text. Artifact loading validates schemas, checksums,
finite values, vector ordering, normalization, and configured bounds. Exact
results are deterministic for identical inputs, configuration, and code
revision; the artifact hashes identify the reference and candidate catalog
records used for the run.

`ContentConfig` bounds selected vocabulary size, distinct reference terms,
characters and tokens per document, catalog size, total sparse nonzeros, batch
size, supplied history events, and requested recommendation count. Sparse
nonzeros are checked as vectors are built. Defaults are conservative
application safeguards, not measured capacity guarantees. No synthetic
benchmark establishes real-catalog latency or memory requirements. Reassess
those limits using authorized data and measured target hardware before
production use.

The test fixture at `tests/fixtures/content/` is invented synthetic data. Tests
cover field selection and provenance, malformed/missing values, normalization
identity and schema checks, tokenization, deterministic vocabulary and
artifacts, cosine ranking, candidate eligibility, bounded queries, cold-item
retrieval, user-history cutoff and target masking, seen-item filtering, and
resource-limit rejection. Test results do not establish dataset quality,
rights, recommendation quality, or deployment readiness.

Phase 4.3B adds an aggregate-only synthetic benchmark with separate warm-only
and content-eligible candidate policies, cold-item metrics, fixed controls, and
metadata-quality ablations. Its scope, results, reproducibility hashes, and
limitations are documented in [CONTENT-BENCHMARK.md](./CONTENT-BENCHMARK.md).
Phase 4.4A connects this index to train-scoped collaborative rankings with
source-specific candidate pools and deterministic RRF; see
[HYBRID-RETRIEVAL.md](./HYBRID-RETRIEVAL.md).
