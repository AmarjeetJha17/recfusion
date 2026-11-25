# Data Release Checklist

This checklist distinguishes the synthetic pipeline release from any
real-data or model-training release. A pass in the synthetic section cannot
clear the external dataset terms gate.

## Synthetic-only pipeline release

- [x] Inputs are committed synthetic canonical fixtures only.
- [x] No external dataset download, scraping, or third-party data processing.
- [x] Existing ingestion, preprocessing, temporal splitting, and feature
  generation stages are reused in order.
- [x] Opt-in product normalization is explicitly enabled by this synthetic
  release command; the normalizer remains opt-in for existing ingestion use.
- [x] Stage manifests, output schemas, provenance checksums, and record counts
  are checked before publication.
- [x] Train-only user/item vocabularies reserve unknown index `0`; candidate
  items come only from the training vocabulary.
- [x] Held-out interactions remain auditable; no validation/test labels fit
  vocabularies, transformers, histories, or candidates.
- [x] Exact UTC cutoff boundaries and simultaneous-event histories are tested.
- [x] Invalid records, exact duplicates, conflicting product metadata, and
  normalization ambiguity are counted.
- [x] Feature outputs contain no source user/item keys.
- [x] Repeated identical runs have byte-identical release manifests and
  derived output hashes.
- [x] Failed stage execution blocks publication and removes its staging tree.
- [x] The output must be a new child directory under ignored
  `data/processed/`; existing output is never overwritten.
- [x] No model training or inference is part of this release.

**Synthetic gate result:** PASS for the bounded committed fixture and tested
workflow only. See [the Phase 2 report](./PHASE-2-REPORT.md) for measured
counts, hashes, performance, validation results, and limitations.

## Before any real-data pilot

- [ ] Review and record the exact dataset license, terms of service, access
  requirements, redistribution limits, and intended-use restrictions.
- [ ] Obtain explicit authorization for the selected dataset and processing
  purpose; do not infer permission from public availability.
- [ ] Record the approved source URL/revision, retrieval time, source hashes,
  schema version, and terms-review evidence in a restricted provenance
  manifest.
- [ ] Verify permitted storage, retention, access, deletion, and derived-data
  handling before acquisition.
- [ ] Keep raw data, user identifiers, credentials, and sensitive source text
  out of Git, CI artifacts, public logs, and committed fixtures.
- [ ] Run a bounded source-format pilot only after the above approvals, with
  explicit exclusions, source-specific duplicate rules, and auditable
  quality reports.
- [ ] Independently review chronological split semantics, event meaning,
  product metadata provenance, and timestamp-effective catalog availability.
- [ ] Re-run integrity, leakage, reproducibility, and resource checks on the
  authorized pilot. Report actual failures as well as successes.

**Real-data gate result:** BLOCKED until all required approvals and a
terms-reviewed authorized pilot are complete.

## Before declaring Phase 3 readiness

- [ ] Review actual pilot data quality, population/filter effects, split
  integrity, and train-only feature behavior.
- [ ] Establish an explicit positive-event definition; do not treat missing
  interactions as negatives or infer clicks, purchases, or impressions from
  review ratings.
- [ ] Select and document a candidate universe and metric denominator that
  do not rely on future availability or held-out labels.
- [ ] Compare against appropriate popularity, content, and collaborative
  baselines using leakage-aware chronological evaluation.
- [ ] Record failed experiments, data/model versions, seeds, configuration,
  and resource use.
- [ ] Obtain review of the evaluation protocol and rights restrictions before
  any model results or readiness claims are published.

**Phase 3 real-data readiness:** NOT ESTABLISHED by this synthetic release.
