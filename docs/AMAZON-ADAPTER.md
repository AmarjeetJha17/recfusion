# Amazon Electronics CSV Adapter

**Status:** Implemented and validated only with synthetic fixtures. The adapter does not resolve or bypass the dataset's external usage-rights gate.

## Source boundary

The adapter targets the Amazon Reviews 2023 Electronics 5-core absolute-timestamp CSV files documented by the [official 5-core processing page](https://amazon-reviews-2023.github.io/data_processing/5core.html). The expected source header is `user_id,parent_asin,rating,timestamp`. The official page also describes `history` in some processed split examples; this adapter accepts exactly the four columns above. RecFusion derives downstream histories from training records.

Select the adapter explicitly with `--adapter amazon-reviews-2023-electronics --input-format csv`. Pass each split's file explicitly with `--train`, `--validation`, and `--test`; the CLI does not discover files. The file-role mapping is trusted and recorded in the manifest. The adapter does not infer or recalculate split membership from timestamps or row contents. Use repository-relative or absolute paths as CLI arguments; the adapter does not read `.env` automatically and contains no machine-specific paths.

## Mapping and timestamp behavior

| Source field | Canonical field | Policy |
|---|---|---|
| `user_id` | `user_key` | SHA-256 pseudonymized with the `amazon_reviews_2023` and `Electronics` namespace; raw ID is never written to canonical output or rejection reports. |
| `parent_asin` | `item_key` | Kept source-scoped as `ar23:Electronics:item:<parent_asin>`; not joined to a demo catalog. |
| `rating` | `rating` | Passed unchanged to shared finite 1–5 Decimal validation. It remains observed rating feedback, not a purchase/click/impression label. |
| `timestamp` | `event_time_ms` | Parsed as a non-negative integer Unix epoch millisecond value and retained as that integer in the canonical contract. |

The adapter calls `unix_ms_to_utc`, which adds an integer-millisecond `timedelta` to the timezone-aware UTC Unix epoch and rejects values outside Python's datetime range. It does not use the machine's local timezone. The canonical `Interaction` contract stores `event_time_ms`; the existing preprocessing stage derives `event_time_utc` and retains `source_timestamp_value`/`source_timestamp_unit`. The adapter does not emit invented event types, true source event IDs, or relevance labels.

The shared source-record fingerprint hashes the complete parsed source row together with source identity and dataset version. It is a deterministic audit fingerprint, not an Amazon event ID. The manifest separately stores source identity/version and input file checksums and byte sizes.

## Validation and duplicate policy

- Header names must be nonblank, unique, and exactly the expected set. Header column order is immaterial. Missing, duplicate, unexpected, or zero-byte headers fail the file and prevent output publication.
- A data row with a different column count is rejected and counted. Invalid UTF-8 fails the input file closed; no partial release is published.
- Blank `user_id`/`parent_asin`, malformed/negative/out-of-range timestamps, and ratings outside finite `[1, 5]` are rejected through source-adapter or shared canonical validation errors.
- Invalid rows are written to per-split `rejections.*.jsonl` with split, source row number, fingerprint when parseable, and reason codes/fields. Reports contain no raw IDs or source text. Valid exact duplicates are not rejections.
- Ingestion retains every valid Amazon source row, including exact repeated rows with the same fingerprint. The manifest reports `exact_duplicate_occurrences` and `duplicate_rows_retained` per split; `duplicate_rows_skipped` remains zero for this adapter. No unique event IDs or duplicate-specific fingerprints are fabricated. Identical rows in different input splits remain assigned to those explicit splits and are counted as cross-split duplicates.
- Step 2.4 interaction preprocessing applies its existing within-split duplicate policy: it counts exact duplicate occurrences and emits one canonical processed row per identical fingerprint/payload. This separation preserves the source rows for audit at ingestion while keeping downstream processed data consistent with the established preprocessing contract. Different timestamps or other payload changes have distinct fingerprints and remain separate.
- Accepted interaction outputs are sorted by fingerprint using a SQLite spool, keeping row storage off the Python heap and making canonical output bytes independent of input row ordering. Input checksums still differ when source file bytes/order differ; manifests correctly retain those different source checksums.

The adapter retains all valid records and does not run user sampling, fit vocabularies/features, perform negative sampling, join product metadata, or modify source files. Products and normalization options are rejected for this adapter. Output is atomically published under ignored `data/processed/`; existing destinations are refused.

## Synthetic fixture command

```powershell
uv run recfusion-ingest `
  --adapter amazon-reviews-2023-electronics `
  --input-format csv `
  --train tests\fixtures\amazon_electronics\train.csv `
  --validation tests\fixtures\amazon_electronics\validation.csv `
  --test tests\fixtures\amazon_electronics\test.csv `
  --source-id amazon-reviews-2023-electronics `
  --source-version synthetic-fixture-v1 `
  --output-dir data\processed\amazon-electronics-synthetic-v1
```

The train fixture contains 11 data rows: 4 pass canonical validation, including 1 exact duplicate; 7 invalid rows are rejected, and all 4 valid rows are retained in ingestion output. Step 2.4 then reports 1 exact duplicate occurrence and emits 3 unique train outputs. Validation and test each contain one valid row, including exact official timestamp cutoffs. These are invented identifiers and synthetic timestamps; these counts say nothing about the downloaded dataset.

## Rights and limitations

Amazon Reviews 2023 usage terms remain unresolved for the project's intended research use. The official site and repository availability are not authorization. Do not ingest, sample, profile, transform, train on, or redistribute the downloaded files until applicable terms and intended use are reviewed and cleared. Synthetic adapter tests neither read nor validate those files, and do not establish real-source compatibility or data quality. See [DATASETS.md](./DATASETS.md) and the [Amazon pilot plan](./AMAZON-PILOT-PLAN.md).
