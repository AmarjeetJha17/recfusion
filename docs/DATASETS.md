# DATASETS — Data sourcing and integrity

**Status:** Dataset proposal; licensing, download access, observed schema and category counts must be verified in a dataset feasibility spike.

## 1. Primary research source

**Proposed:** [Amazon Reviews 2023 (McAuley Lab)](https://amazon-reviews-2023.github.io/), hosted via [Hugging Face](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023). Use the electronics category/related subcategories only after inspecting actual file manifests and schema. Available fields may include pseudonymous user IDs, product IDs, ratings, timestamps, review text and product metadata; verify field presence instead of assuming.

**Critical distinction:** Reviews/ratings are *review interactions*; they are not observed purchases, clicks, exposures or conversions. A dataset with only positive review events is insufficient for offline CTR or conversion uplift claims. Missing reviews are unknown, not explicit negatives.

## 2. Separate data planes

| Plane | Source | Permitted use |
|---|---|---|
| Offline behavior benchmark | historical review/rating interactions | train/evaluate ranking and retrieval |
| Offline catalog metadata | dataset metadata, where permitted | semantic features and attributes for research |
| Application demo catalog | clearly labeled curated or synthetic catalog | UI and explainable budget/spec scenarios |
| Future real-time offers | contracted, permitted merchant/feed integration | real prices and availability only with timestamps |

No assumed ID overlap between historical dataset and live/demo catalog. An explicit versioned mapping is required if interoperability is desired. Synthetic records must not be presented as real merchant offers.

## 3. Proposed initial scope and sampling

Start by testing feasibility on a small subset (e.g., 10k–30k items, 20k–100k users, 100k–500k review events), **targets only, not guaranteed counts**. Consider a laptop-oriented application demo even if training data are a broader electronics review category; describe any domain mismatch honestly.

Sampling order: verify source manifest and license → inspect schema/dtypes → check identifier validity and timestamps → measure missing descriptions/specs/prices → deduplicate → filter categories based on actual taxonomy → examine user-item sparsity → choose supported sample. Do not apply k-core filtering without recording the bias it introduces.

## 4. Data contracts

`ReviewEvent`: `source_event_id`, `source_user_id`, `source_item_id`, `rating`, `event_at_utc`, `source_dataset_version`; optional text with privacy policy. `CatalogProduct`: `source_item_id`, title, category, optional brand, description, structured attributes, metadata provenance. `TrainingInteraction`: mapped user/item IDs, event timestamp, event type = review, positive label policy, split ID.

Validate primary keys, numeric ranges, timestamps, null rates, deduplication criteria, category distributions, price currency/source, attribute units, and mapping coverage. Log exclusions with counts and reasons. Do not derive guest app identity from historical dataset identifiers.

## 5. Splits and leakage policy

- Default: chronological train/validation/test windows with documented cutoff timestamps; ensure training-derived user profiles contain no later data.
- For next-item/replay evaluation, construct history as-of each prediction timestamp and exclude target events from historical features.
- Separate warm/cold user/item cohorts and state which populations are actually supported by the split.
- Product titles/specs may be timeless, but price, review counts and other mutable features must be sourced as-of cutoff or omitted from historical experiments.
- Normalize and fit vocabulary/statistical transforms on training data only. Recompute test-time information consistently without future exposure.
- Explicitly define relevance (e.g., rating ≥ threshold) and how neutral/low ratings are treated; negative-sampling strategies must be documented.

## 6. Versioning and reproducibility

Every derived dataset must have a manifest containing: source URL and version, acquisition date, license review result, file hashes, preprocessing commit, config, seed, row/user/item counts, excluded counts, schema version, split strategy, cutoffs, and output checksums. Keep raw files immutable outside Git. Write processed datasets to Parquet. Public repo contains only permitted tiny synthetic fixtures and scripts, not bulk copyrighted data.

## 7. Compliance and data privacy

Inspect provider terms before redistribution, training use, publication or hosting images. Review text and user identifiers can create privacy risks even when pseudonymized: minimize retention and avoid displaying identifiable reviewers. Never scrape retailer websites as a shortcut without verifying permission.

## 8. Dataset feasibility exit gate

- [ ] License/terms and file access reviewed
- [ ] Electronics file/subcategory selected based on observed metadata
- [ ] Actual schema and missingness reported
- [ ] Sparsity and positive-event threshold documented
- [ ] Split plan and leakage checks approved
- [ ] Versioned sample manifest produced
- [ ] Demo catalog source and source-label strategy determined
