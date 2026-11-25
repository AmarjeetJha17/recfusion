# Amazon Electronics Pilot Plan

**Status:** Steps 2.2B.1–2.2B.4A are complete. Step 2.2B.4A sampling is verified only with synthetic fixtures. No real dataset rows have been read, sampled, ingested, or transformed. The owner-scoped coursework decision below is limited to local non-commercial academic use and is not legal clearance. This clarification does not execute or authorize the canary by itself; the project owner must review it before real-data execution.

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

## Proposed bounded pilot workflow (sampling implemented in Step 2.2B.4A)

The sequence below is a plan, not an instruction to run now. The Amazon adapter preserves all valid users when `--max-users` is omitted; explicitly passing `--max-users K` enables train-only bounded selection. **Do not run these commands until the project owner has reviewed this scoped-use clarification and the technical preflight is complete.** If applicable law, source terms, or an institution-specific policy is known to require approval or prohibit the activity, stop until it is addressed. This step has not opened or processed the local benchmark CSVs. The raw split files remain read-only and gitignored.

1. Review the owner-scoped decision in [ADR-014](./DECISIONS.md) and confirm the run remains local and within the non-commercial coursework scope. Confirm the three recorded source checksums still match, record the code commit and fixed seed, and confirm adequate destination and temporary disk space. The CLI does not load `.env`; load the ignored path variables into the invoking shell or pass local paths explicitly. Do not place absolute personal paths in source or committed configuration.
2. Run a 100-train-eligible-user canary using all three explicit official split files and explicit `--max-users 100`. The implementation streams valid train users into a temporary SQLite rank index, retaining only the selected keys in memory. Ranking uses SHA-256 over seed, source ID, and pseudonymized `user_key`, with user key as tie-breaker. A user enters the eligible population only through a valid training interaction. Keep every selected user's interaction from train, validation, and test in its original file-assigned split. The bounded selection uses disk proportional to distinct train users, but scans all input files for checksums/validation and does not avoid I/O over unselected rows.
3. Review the canary manifests and aggregate data-quality report. Stop if selection is not exactly 100 users, counts do not reconcile, source checksums change, rows move between splits, held-out data contributes to selection, or trusted split integrity fails. Measure elapsed time, peak process RSS, temporary SQLite size, output size, and free disk before proceeding.
4. If the canary passes and measured resource use leaves the agreed disk/RAM headroom, independently run the 10,000-user sample from the original files with the **same seed and policy**. Since selection takes the lowest stable hash ranks, the canary's 100 users are nested in the 10,000-user selection. Do not select the larger pilot from the canary outputs.
5. Run Step 2.4 preprocessing separately on each sample's three canonical split outputs; preserve its duplicate audit/deduplication policy. Run Step 2.5 `trusted-pre-split` with the official cutoffs (`train < 1628643414042 ms`, `validation [1628643414042, 1658002729837) ms`, `test >= 1658002729837 ms`) to validate membership, never repartition it. Let the temporal step fit user/item vocabularies from train only, retaining held-out unknown IDs under the existing unknown-index policy. Do not fit from validation or test.
6. Keep the canary and 10,000-user outputs in separate new ignored `data/processed/` directories. Preserve the original CSVs. Do not publish row-level output; review any aggregate public report against the terms decision.

Command shape for a future authorized pilot (these commands are **not authorization to run**):

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

### Required manifests and pilot statistics

Retain per-run manifests with source IDs/version, all three input byte sizes and SHA-256 hashes, code commit, adapter/schema versions, seed and selection policy, selected train-user count, explicit split mapping, duplicate/rejection policy, per-split input/valid/selected/output/rejected counts, reason counts, output hashes, and measured runtime/RSS/temp-disk/output-disk usage. Keep absolute local paths and selected IDs out of committed/public reports.

The aggregate quality report must include source rows read; eligible and selected train users; retained interactions by split; rating distributions; invalid/rejected rows by split and reason; exact duplicate occurrences and cross-split duplicate/conflict counts; unique user and item counts by split and overall; warm/cold user and item cohorts; and millisecond plus UTC timestamp ranges by split. Separate whole-file validation counts from counts for selected users, and explicitly label duplicate statistics by their measured scope. Stop on count reconciliation errors, invalid schema/timestamps/ratings, split mismatches or cut-off contradictions, and unexplained fingerprint conflicts. Evaluation eligibility is reported by the temporal layer; it is not implied by passing ingestion.

### Capacity and implementation gaps

The inventoried inputs total **897,479,611 bytes (about 856 MiB)**. The CSV reader is row-streamed and input checksums are computed with bounded-memory reads. Explicit Amazon sampling now uses a disk-backed eligible-user index and a second pass across each split; the duplicate index receives selected interactions only. Whole-source input/valid/rejected counts still cover all rows. The smaller selected-user set and output rows are held/spooled independently of the full eligible-user population; actual disk consumption and runtime have not been measured on the benchmark. The generic canonical sampling path is unchanged and still builds an in-memory set of eligible users. The synthetic release orchestrator is fixture-specific and its cross-stage audit materializes interaction lists; it is not a real-data runner. Synthetic memory figures are not estimates for these files.

Step 2.2B.4A implements the Amazon-specific opt-in sampled-user mode and records whole-source versus selected-user count scopes in its manifest. Synthetic tests validate nesting with small K values, order-independent selection/output hashes, held-out-label invariance, reconciliation, and insufficient-population failure. The 100/10,000 real-data pilot remains blocked by the rights/use gate and requires measured runtime/RSS/disk during the separately authorized canary; no resource-safety claim can be made from file size or synthetic tests alone.

## Rights gate and pilot entry criteria

The status is **owner-scoped local coursework decision documented; legal clearance is not established**. No concrete additional university approval requirement or explicit source-term prohibition for this narrow use was identified in the project documents and maintainer discussion reviewed. This limited finding does not establish that none applies. The project owner must follow applicable law, source terms, and institution policy; no legal requirement is marked satisfied. Do not execute the canary until the project owner has reviewed this clarification and the technical preflight is completed.

Before a bounded pilot begins:

1. Reconfirm the run remains within the owner's local non-commercial coursework scope and that any applicable institution policy or source-term requirement is followed. If an applicable rule requires approval or prohibits the use, stop until it is resolved.
2. Confirm source revision/retrieval provenance and recheck file hashes before processing.
3. Approve the pilot size and protocol, including source split preservation, rating-label policy, duplicate audit, and resource limits.
4. Validate required fields, ratings, timestamp integer/range behavior, split chronology, and counts with auditable rejection reasons; keep raw files immutable.
5. Derive histories and all learned transforms from training data only; treat unobserved items as unknown, not negatives.

This clarification only documents the owner's scope decision and the available evidence. It does not run the 100-user canary, establish legal clearance, or approve 10,000-user processing. Step 2.7 and Step 2.2B.4A synthetic evidence do not establish real-source quality or resource readiness.
