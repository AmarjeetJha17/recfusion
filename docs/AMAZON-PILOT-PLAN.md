# Amazon Electronics Pilot Plan

**Status:** Step 2.2B.1 inventory complete; no dataset rows ingested or transformed. **Research use remains blocked** pending terms review.

## Verified local inventory

Files are local-only at the repository root. Relative paths are recorded in the ignored `.env` configuration using `RECFUSION_AMAZON_ELECTRONICS_TRAIN`, `RECFUSION_AMAZON_ELECTRONICS_VALID`, and `RECFUSION_AMAZON_ELECTRONICS_TEST`; application source contains no machine-specific paths.

| Split | Local path | Bytes | SHA-256 | Observed header |
|---|---|---:|---|---|
| Train | `Electronics.train.csv` | 759,602,697 | `c2f45a4031c8dbf564f12cb492665c22db7e91059340af2ccf531983516cf9a8` | `user_id,parent_asin,rating,timestamp` |
| Validation | `Electronics.valid.csv` | 67,377,957 | `2d75a1a9790a360ec6d51c44acab1aba05533d86130fda060be3904a1f161d56` | `user_id,parent_asin,rating,timestamp` |
| Test | `Electronics.test.csv` | 70,498,957 | `ac5166ced7edbba547c9e64206f390583381c5f370a53748ca72da8fa9fcd377` | `user_id,parent_asin,rating,timestamp` |

Inspection was limited to file metadata, SHA-256 streaming reads, and CSV headers; no full-file row scan or transformation was performed. The files are ignored by the repository's `*.csv` rule and are neither tracked nor staged.

## Source and schema

- Official 5-core processing and split documentation: <https://amazon-reviews-2023.github.io/data_processing/5core.html>
- Dataset overview and source field descriptions: <https://amazon-reviews-2023.github.io/>
- Dataset terms discussion: <https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/discussions/1>

The observed four-column headers match the official pre-split pure-ID CSV schema. The official post-split example also shows an optional `history` column; these files omit it. RecFusion must derive history from training events under the selected split protocol, not depend on source-provided history. No other header mismatch or unexpected column was observed.

The official source describes `timestamp` as integer Unix time and shows 13-digit timestamps; its absolute split cutoffs are also 13-digit values. Together with the project contract's millisecond definition, the benchmark representation is Unix epoch **milliseconds**. Convert to canonical UTC time only after validating each value as an integer millisecond timestamp; do not interpret it as seconds.

## Proposed adapter mapping

| Source CSV field | Planned canonical meaning |
|---|---|
| `user_id` | Canonical user identifier, source-scoped and pseudonymized in derived data per the data contract |
| `parent_asin` | Canonical product identifier, source-scoped; not a demo-catalog product ID |
| `rating` | Observed rating, preserving the source value |
| `timestamp` | Canonical UTC timestamp derived from Unix epoch milliseconds; preserve source integer provenance |

These mappings are planned only. No adapter has been created or run.

## Rights gate and pilot entry criteria

The dataset's license/terms status is **unresolved**. The dataset maintainer's discussion does not grant a license or blanket permission. Do not ingest, sample, profile, transform, train on, or redistribute these files until the intended research use and applicable terms have been reviewed and explicitly cleared. Local presence is not authorization.

Before a bounded pilot begins:

1. Record the terms/legal review and permitted use, storage, retention, and derived-data restrictions.
2. Confirm source revision/retrieval provenance and recheck file hashes before processing.
3. Approve the pilot size and protocol, including source split preservation, rating-label policy, duplicate audit, and resource limits.
4. Validate required fields, ratings, timestamp integer/range behavior, split chronology, and counts with auditable rejection reasons; keep raw files immutable.
5. Derive histories and all learned transforms from training data only; treat unobserved items as unknown, not negatives.

The current milestone stops before these processing steps. Step 2.7's synthetic release pipeline is committed as `e9a3360`; its fixture-only evidence does not clear this real-data gate.
