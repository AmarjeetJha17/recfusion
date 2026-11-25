# Amazon Electronics Pilot Plan

**Status:** Steps 2.2B.1–2.2B.4C are complete. The 100-user canary and separate 10,000-user local pilot, including Step 2.4 preprocessing and Step 2.5 trusted-split checks, are documented below and in ignored aggregate reports. No recommender model was trained or evaluated. The owner-scoped research-use assessment is limited to local non-commercial academic use and is not legal clearance.

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

The mapping is implemented by an opt-in adapter and exercised only with small synthetic fixtures matching the four-column source schema. It uses `ar23:Electronics:user:<sha256>` pseudonymous user keys and `ar23:Electronics:item:<parent_asin>` item keys; preserve that item mapping for any later metadata join. The downloaded Electronics files remain unprocessed. See [AMAZON-ADAPTER.md](./AMAZON-ADAPTER.md) and the [data contract](./DATA-CONTRACTS.md).

## Declared research scope and publication boundary

The project owner confirms a non-commercial MCA Recommendation Systems coursework project. The limited scope is local academic preprocessing, offline model training, and offline evaluation of the official Electronics 5-core splits. The maintainer says the lab cannot assign a license or dictate terms and that the data was made available primarily for research; a favorable answer to another student's thesis question was specific to that exchange and is not permission for RecFusion. The reviewed project docs and maintainer discussion identify no specific university approval requirement or explicit source term prohibiting this narrow local coursework use. Institution-specific policies and applicable law have not been independently verified; the project owner remains responsible for them. This is an owner-scoped project decision, not a license or legal clearance. See [DATASETS.md](./DATASETS.md) and [ADR-014](./DECISIONS.md).

Keep processing local. Do not commit or publish raw reviews, source user IDs, any benchmark CSV, original product images, or row-level derived data. Academic reports should use appropriate attribution and reviewed aggregate statistics only. Commercial deployment and redistribution are outside this scope and require separate review. Do not claim product-metadata coverage or feature-release readiness: the interaction adapter does not ingest/join product metadata, and no metadata coverage has been measured.

## Bounded pilot workflow and execution record (sampling implemented in Step 2.2B.4A)

The Amazon adapter preserves all valid users when `--max-users` is omitted; explicitly passing `--max-users K` enables train-only bounded selection. The raw split files remain read-only and gitignored. The completed 100-user canary and separate 10,000-user pilot are documented below. Any additional run is a separate decision and must satisfy applicable law, source terms, and institution policy.

1. Review the owner-scoped decision in [ADR-014](./DECISIONS.md) and confirm the run remains local and within the non-commercial coursework scope. Confirm the three recorded source checksums still match, record the code commit and fixed seed, and confirm adequate destination and temporary disk space. The CLI does not load `.env`; load the ignored path variables into the invoking shell or pass local paths explicitly. Do not place absolute personal paths in source or committed configuration.
2. Run a 100-train-eligible-user canary using all three explicit official split files and explicit `--max-users 100`. The implementation streams valid train users into a temporary SQLite rank index, retaining only the selected keys in memory. Ranking uses SHA-256 over seed, source ID, and pseudonymized `user_key`, with user key as tie-breaker. A user enters the eligible population only through a valid training interaction. Keep every selected user's interaction from train, validation, and test in its original file-assigned split. The bounded selection uses disk proportional to distinct train users, but scans all input files for checksums/validation and does not avoid I/O over unselected rows.
3. Review the canary manifests and aggregate data-quality report. Stop if selection is not exactly 100 users, counts do not reconcile, source checksums change, rows move between splits, held-out data contributes to selection, or trusted split integrity fails. Measure elapsed time, peak process RSS, temporary SQLite size, output size, and free disk before proceeding. The completed canary results and measurement limitations are recorded in the local ignored report; its monitor did not retain exact process I/O totals or final peak temporary/output sizes.
4. The separate 10,000-user sample has now been run from the original files with the same seed and ranking policy, never from canary outputs. The 100-user canary set is nested in this larger selection; all 100 users were found in the 10,000-user train sample.
5. Step 2.4 preprocessing and Step 2.5 `trusted-pre-split` validation have completed for both samples. The 10,000-user run used the official cutoffs (`train < 1628643414042 ms`, `validation [1628643414042, 1658002729837) ms`, `test >= 1658002729837 ms`) to validate membership without repartitioning. Its vocabulary and candidate pool were fit from train only; validation/test did not contribute to selection or fitted vocabularies.
6. Keep the canary and 10,000-user outputs in separate new ignored `data/processed/` directories. Preserve the original CSVs. Do not publish row-level output; review any aggregate public report against the terms decision.

Command shape for a future fresh pilot (these commands are **not authorization to run**). Use new output and temporary directories; the recorded canary and 10,000-user output paths already exist and must not be overwritten:

```powershell
uv run recfusion-ingest `
  --adapter amazon-reviews-2023-electronics `
  --input-format csv `
  --train "$env:RECFUSION_AMAZON_ELECTRONICS_TRAIN" `
  --validation "$env:RECFUSION_AMAZON_ELECTRONICS_VALID" `
  --test "$env:RECFUSION_AMAZON_ELECTRONICS_TEST" `
  --source-id amazon-reviews-2023-electronics `
  --source-version electronics-5core-timestamp-v1 `
  --seed recfusion-amazon-electronics-pilot-v1 `
  --max-users 100 `
  --temp-dir data\processed\amazon-electronics-temp `
  --output-dir data\processed\amazon-electronics-canary-100-v1
```

Repeat with the same inputs, `--seed`, and source version, `--max-users 10000`, and output directory `data\processed\amazon-electronics-pilot-10000-v1`. The `--temp-dir` path must already exist. `--min-free-disk-bytes N` can enforce a caller-selected free-space floor on output and temporary volumes; it does not predict required disk capacity.

### Completed 100-user canary (Step 2.2B.4B)

The local ignored report is `data/processed/amazon-electronics-canary-100-report-v1/canary-report.json`; row-level outputs and manifests remain in separate ignored directories. The run selected exactly 100 of 1,604,818 valid train-eligible users and retained 820 train, 54 validation, and 40 test interactions (914 total). Whole-source validation read 15,473,536 rows across the three official files; all were valid and none rejected. The canary had no exact or cross-split duplicate occurrences. Step 2.4 retained all 914 rows and found no duplicates. Step 2.5 preserved source split membership and fit vocabularies on train only, but found no warm-positive held-out targets: all 94 validation/test interactions refer to items unseen in the selected users' train vocabulary. Its general integrity flag was evaluation-eligible, but the warning `no_warm_positive_evaluation_targets` means this canary does not support model-quality evaluation. Product metadata was unavailable and was not inferred.

The observed ingestion duration was about 10m 38s. Sampled process working set peaked at about 4.8 MiB and sampled temporary SQLite use reached about 358 MiB; these are periodic observations, not guaranteed exact peaks. The monitor did not retain exact process I/O totals or final peak combined temporary/output size. The final ingestion, preprocessing, and trusted-split output directories used 282,426, 599,207, and 1,244,014 bytes respectively. Disk and available memory stayed above the selected abort floors. These results do not estimate resource use for 10,000 users.

### Completed 10,000-user pilot (Step 2.2B.4C)

The local aggregate-only report is `data/processed/amazon-electronics-pilot-10000-report-v1/pilot-report.json`; row-level outputs remain in ignored local directories. The run selected exactly 10,000 of 1,604,818 valid train-eligible users. Whole-source validation read 15,473,536 rows; all were valid and none rejected. Selected outputs contained 81,688 train, 6,760 validation, and 6,056 test interactions (94,504 total). Ingestion preserved explicit split membership. The selected sample had zero exact duplicates, cross-split duplicates, or conflicts; Step 2.4 retained all 94,504 rows with zero rejections or duplicate collapses. These duplicate counts describe the selected-user sample; the adapter does not build a whole-source duplicate index for unselected users.

| Split | Interactions | Users | Unique items | Rating counts (1/2/3/4/5) | Timestamp range (UTC) |
|---|---:|---:|---:|---|---|
| Train | 81,688 | 10,000 | 45,331 | 6,534 / 3,671 / 5,641 / 11,708 / 54,134 | 2000-02-18T02:00:46Z–2021-08-11T00:23:56.176Z |
| Validation | 6,760 | 3,317 | 5,569 | 811 / 361 / 524 / 749 / 4,315 | 2021-08-11T01:00:20.840Z–2022-07-16T20:14:55.309Z |
| Test | 6,056 | 2,676 | 5,203 | 578 / 302 / 418 / 747 / 4,011 | 2022-07-16T20:32:09.596Z–2023-08-25T03:38:33.924Z |

The train-only vocabulary contains 10,000 users and 45,331 items. Train density is 0.0180% over 10,000 × 45,331 user/item cells (81,688 distinct user-item pairs). Train interactions per user have min/median/mean/P90/max 1/6/8.17/15/143; 169 users have one train interaction. Per-item counts are 1/1/1.80/3/261; 33,145 train items have one interaction. The train candidate pool contains 45,331 items; its item-interaction frequency has min/median/mean/P90/max 1/1/1.80/3/261.

Validation has 1,911 warm-positive interactions among 5,064 observed-positive interactions (37.7% candidate coverage; 28.3% of all validation rows). They cover 1,369 of 2,654 validation users with any positive target (51.6% user-weighted coverage), averaging 1.40 warm-positive targets per covered user. Test has 1,203 warm-positive interactions among 4,758 observed-positive interactions (25.3% candidate coverage; 19.9% of all test rows). They cover 895 of 2,148 test users with any positive target (41.7% user-weighted coverage), averaging 1.34 warm-positive targets per covered user. There are no cold-user interactions in either held-out split; 4,169 validation and 4,503 test interactions are cold-item interactions. The warm-item subset supports a bounded warm-start evaluation protocol, but this report contains no ranking or model-quality results. Cold-item evaluation needs separately reviewed product features; no product metadata was joined or profiled.

Research-readiness interpretation: training-frequency data can support a popularity baseline. Collaborative filtering and ID-based Two-Tower retrieval have interaction data available, but the train matrix is sparse and no training, negative sampling, or ranking evaluation was run here. Warm-start offline evaluation is feasible only for the warm-positive subset and must state its coverage exclusions. Cold-item evaluation requiring content features is not supported by this pilot because product metadata was not included.

Ingestion took 630.7 seconds, Step 2.4 took 18.6 seconds, and Step 2.5 took 56.1 seconds. Periodic samples observed 388,175,360 bytes in ingestion temporary SQLite storage, 534,257,664 bytes in preprocessing temporary storage, and 628,629,504 bytes in trusted-split temporary storage. Final output directories used 28,667,722, 61,101,842, and 120,095,961 bytes respectively. The monitor sampled the top-level Windows command launcher rather than a verified Python worker process tree, so pipeline peak RSS is unavailable; process I/O totals are also unavailable. These are run-specific observations, not capacity guarantees.

### Required manifests and pilot statistics

Retain per-run manifests with source IDs/version, all three input byte sizes and SHA-256 hashes, code commit, adapter/schema versions, seed and selection policy, selected train-user count, explicit split mapping, duplicate/rejection policy, per-split input/valid/selected/output/rejected counts, reason counts, output hashes, and measured runtime/RSS/temp-disk/output-disk usage. Keep absolute local paths and selected IDs out of committed/public reports.

The aggregate quality report must include source rows read; eligible and selected train users; retained interactions by split; rating distributions; invalid/rejected rows by split and reason; exact duplicate occurrences and cross-split duplicate/conflict counts; unique user and item counts by split and overall; warm/cold user and item cohorts; and millisecond plus UTC timestamp ranges by split. Separate whole-file validation counts from counts for selected users, and explicitly label duplicate statistics by their measured scope. Stop on count reconciliation errors, invalid schema/timestamps/ratings, split mismatches or cut-off contradictions, and unexplained fingerprint conflicts. Evaluation eligibility is reported by the temporal layer; it is not implied by passing ingestion.

### Capacity and implementation gaps

The inventoried inputs total **897,479,611 bytes (about 856 MiB)**. The CSV reader is row-streamed and input checksums are computed with bounded-memory reads. Explicit Amazon sampling now uses a disk-backed eligible-user index and a second pass across each split; the duplicate index receives selected interactions only. Whole-source input/valid/rejected counts still cover all rows. The 10,000-user run measured output and temporary storage use, as summarized above; its launcher-only memory sample is not a valid pipeline RSS measurement, and its observations do not establish capacity beyond this run. The generic canonical sampling path is unchanged and still builds an in-memory set of eligible users. The synthetic release orchestrator is fixture-specific and its cross-stage audit materializes interaction lists; it is not a real-data runner. Synthetic memory figures are not estimates for these files.

Step 2.2B.4A implements the Amazon-specific opt-in sampled-user mode and records whole-source versus selected-user count scopes in its manifest. Synthetic tests validate nesting with small K values, order-independent selection/output hashes, held-out-label invariance, reconciliation, and insufficient-population failure. The 100-user canary and 10,000-user pilot are complete under the documented local coursework scope. Any additional real-data run requires a separate owner decision, fresh preflight, and resource safeguards. These measurements do not establish capacity beyond the observed 10,000-user run.

## Rights gate and pilot entry criteria

The status is **owner-scoped local coursework decision documented; legal clearance is not established**. No concrete additional university approval requirement or explicit source-term prohibition for this narrow use was identified in the project documents and maintainer discussion reviewed. This limited finding does not establish that none applies. The project owner must follow applicable law, source terms, and institution policy; no legal requirement is marked satisfied. Both pilots were executed within the stated local, non-commercial scope after the owner requested them and their technical preflights completed.

Before any additional real-data pilot or model evaluation:

1. Reconfirm the run remains within the owner's local non-commercial coursework scope and that any applicable institution policy or source-term requirement is followed. If an applicable rule requires approval or prohibits the use, stop until it is resolved.
2. Confirm source revision/retrieval provenance and recheck file hashes before processing.
3. Approve the pilot size and protocol, including source split preservation, rating-label policy, duplicate audit, and resource limits.
4. Validate required fields, ratings, timestamp integer/range behavior, split chronology, and counts with auditable rejection reasons; keep raw files immutable.
5. Derive histories and all learned transforms from training data only; treat unobserved items as unknown, not negatives.

This clarification documents the owner's scope decision and the available evidence. The 100-user and 10,000-user results are technical pilot findings, not legal clearance or approval for further use. The 100-user sample had zero warm-positive held-out targets. The 10,000-user sample has warm-positive targets in both held-out splits, but also substantial cold-item coverage and sparse train interactions. Any later evaluation must report the eligible warm subset and exclusions explicitly; no model-quality conclusion follows from data readiness alone.
