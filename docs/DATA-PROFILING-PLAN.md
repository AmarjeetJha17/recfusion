# Dataset pilot profiling plan

Status: proposed; no data has been downloaded or profiled. This plan is gated on an affirmative terms/legal review. It is a profiling task, not ingestion implementation, model training, or approval to redistribute source data.

## 1. Pilot question and inputs

Determine whether one Electronics slice is sufficiently parseable, joinable, and temporally usable for later offline recommender experiments, and measure its local resource cost before expanding scope.

Preferred first input is the official **5-core Electronics absolute-timestamp split**, not the full raw review corpus. The official page gives:

- `t1 = 1628643414042` and `t2 = 1658002729837` Unix milliseconds.
- Train: timestamp `< t1`; validation: `[t1, t2)`; test: `[t2, +∞)`.
- Electronics counts: approximately 13.1M / 1.2M / 1.2M train/validation/test interactions, 1.6M users, and 368.2K items.
- CSV columns include `user_id`, `parent_asin`, `rating`, and `timestamp`; some processed split variants include a `history` field. Reconstruct history from the selected training events rather than trusting this convenience field.

Source: [official 5-core documentation](https://amazon-reviews-2023.github.io/data_processing/5core.html). These cutoffs and counts are a published reference, not a claim that the split is the only acceptable protocol.

## 2. Deterministic bounded sample

1. After terms approval, pin the exact official split files by source revision where possible and compute SHA-256 checksums. Record retrieval time and source URLs.
2. Obtain the distinct `user_id` set across the three Electronics splits. Select exactly 10,000 users (or all users if fewer) by sorting the SHA-256 digest of `recfusion-phase2-pilot-v1|amazon_reviews_2023|Electronics|<exact-source-user-id>` and taking the first 10,000. Use UTF-8 bytes and a deterministic tie-breaker on the exact source ID. This is a deterministic sample based on IDs, not ratings, item outcomes, or time.
3. Keep every input split row for selected users; never truncate histories or select users based on validation/test performance. Preserve source train/validation/test membership and original event timestamps.
4. Join only the selected distinct `parent_asin` values to Electronics product metadata. If streaming the full metadata file is required, retain only matching rows and report bytes read, output size, and peak process memory. Do not copy the full source file into the repository.
5. If the measured sample exceeds local resource limits, stop and define a smaller, separately versioned user count before computing any metrics. Do not silently drop events from selected users.
6. Only if review-text/optional-review-field profiling is needed and approved, stream the pinned raw Electronics review file and maintain a fixed-seed reservoir sample of at most 50,000 rows. This requires scanning the source and is not required for the initial ID-only benchmark pilot; report transfer/scan cost before proceeding.

For orientation only, proportionally scaling the official rounded 15.5M interactions / 1.6M users to 10,000 users gives about 97,000 rows. This is an arithmetic planning estimate, not a measured sample size or a guarantee; user activity is not uniform. No RAM estimate is asserted. Measure peak memory and disk use on the actual run.

## 3. Measurements

Publish only aggregate counts, after terms review. For every statistic, record numerator, denominator, split, and missing/invalid treatment.

### Input and integrity

- Rows read per source file and per split; unique users, `parent_asin`, and `(user_id, parent_asin)` pairs.
- Rating distribution (1–5); timestamp minimum/maximum and counts by time partition.
- Parse failures, missing required keys, invalid ratings/timestamps, and duplicate event rows/fingerprints.
- Cross-split duplicate fingerprint count; train/validation/test boundary assertions.
- Deterministic selected-user count, selected rows by split, distinct items, and rerun output checksums.
- Source bytes read/downloaded, retained output bytes, wall time, and measured peak resident memory; distinguish compressed transfer from uncompressed file bytes.

### Product metadata

- Join coverage by distinct review `parent_asin` and separately by review-event count.
- Duplicate and conflicting metadata keys.
- Presence and non-empty rates for `title`, `main_category`, `features`, `description`, `categories`, `details`, `price`, and `images`.
- Price raw type/value-shape counts, missing/sentinel/unparseable/non-positive/valid counts; do not report historical values as current prices.
- Image metadata counts: no entries, entries by available resolution/variant field, missing URL fields. Do not request image binaries or claim URL reachability.
- Numeric distributions of source `average_rating` and `rating_number` for profiling only. Exclude these snapshot aggregates from historical model features unless valid as-of timestamps are established.

### Optional raw-review profile

For the separately approved reservoir sample, measure presence rates for `title`, `text`, `verified_purchase`, `helpful_vote`, and review `images`; count parse/type anomalies. Do not publish example review text, user IDs, image URLs, or record-level output.

## 4. Evaluation and leakage safeguards

- The initial reproducibility comparison uses the official timestamp split and the 10,000-user sample; histories are derived only from train events before each query cutoff.
- For any re-created split, use the same absolute boundaries and half-open intervals above. Order ties by `(timestamp, deterministic event fingerprint)`. Never move a duplicate event across partitions.
- Proposed relevance mapping for analysis only: ratings 4–5 relevant, 1–2 explicitly low-rated, rating 3 neutral. Preserve ordinal values and report label counts by split and eligible query. This proposal requires approval.
- Candidate pool for warm-item retrieval: products with at least one training interaction before the prediction cutoff. Use the same candidate universe for popularity, content, collaborative, and hybrid comparisons. Evaluate held-out positive review items in that universe; report test positives outside it separately as cold-item cases, not as warm-item misses.
- Prefer full eligible-catalog ranking. If candidate sampling is needed, retain all held-out targets, deterministically sample the remaining candidates with a fixed recorded seed, and use exactly the same candidates for every model. Mark these metrics sampled-candidate metrics. Unreviewed items are unknown, not verified negatives.
- Do not use test interactions, held-out item appearance, or validation/test popularity to build the catalog or features. Build user/item vocabularies, popularity, text transforms, and normalizers on train only.
- Metadata has no documented per-item effective timestamp. Treat item text/specification fields as a later snapshot and test them only in a clearly labeled snapshot-metadata experiment; exclude `average_rating`, `rating_number`, and historical `price` from as-of temporal features by default.
- This 5-core cohort is not a cold-start evaluation: filtering excludes sparse users/items. A later 0-core audit must separately report users/items with no training history. Do not claim strict historical new-item availability from this metadata snapshot.
- Review-only data has no impression/exposure context. Do not interpret ranking metrics as CTR, conversion, or unbiased preference estimates. Defer LambdaRank claims unless valid query groups and judged candidate sets are justified.

## 5. Acceptance criteria

The pilot is complete only when all conditions below are reported:

1. Terms review is recorded before retrieval or processing; exact source files and checksums, retrieval date, code commit, and config are recorded.
2. The sampler produces the same selected-user IDs and output checksums on repeat with the same pinned inputs and config.
3. Every retained row is assigned to exactly one source split; split boundary checks pass; no cross-split duplicate event fingerprints remain unexplained.
4. Required identifier, rating, and timestamp validation results are reported with denominators; every excluded row has a counted reason, with no silent dropping.
5. User/item counts, rating/time distributions, metadata join coverage, field missingness, duplicate/conflict counts, and measured storage/resource results are reported.
6. Raw IDs/reviews and record-level artifacts remain outside Git and public reports. Public outputs are aggregate-only and subject to terms review.
7. No model quality claim is made from the profiling stage. Owners review actual coverage/resource results and approve or reject the source, sample size, relevance mapping, and next evaluation split before Step 2.2.

No minimum metadata-completeness percentage is asserted before measurement. A threshold would be a project decision and must be recorded with its justification after seeing the profile, not invented from source-level counts.
