# Local ingestion foundation

Status: implemented for canonical-format local files and synthetic fixtures only. This is a source-independent parsing/validation foundation, not an Amazon Reviews adapter or dataset profile. Amazon Reviews 2023 retrieval and use remain blocked pending the terms review in `DATASETS.md`.

## Setup and fixture run

From the repository root, install the already locked environment and run the committed synthetic data:

```powershell
uv sync --frozen
uv run recfusion-ingest `
  --train tests\fixtures\ingestion\train.jsonl `
  --validation tests\fixtures\ingestion\validation.jsonl `
  --test tests\fixtures\ingestion\test.jsonl `
  --products tests\fixtures\ingestion\products.jsonl `
  --source-id synthetic-fixtures `
  --source-version v1 `
  --seed recfusion-phase2-pilot-v1 `
  --max-users 2 `
  --output-dir data\processed\synthetic-pilot-v1
```

The command accepts `jsonl` or `csv` for the interaction splits and product file (`--input-format` and `--product-format`). Inputs must already use the canonical field names. Source ID, version, and seed are restricted to safe ASCII tokens. The output path must be a new child of the ignored `data/processed/` directory; an existing destination is never overwritten. The CLI has no network or dataset-download behavior.

Add `--normalize-products` to write `products.normalized.jsonl` beside the canonical `products.jsonl`. This is opt-in to preserve the Step 2.2A output contract. Its records wrap the unchanged canonical product with conservative brand/category/specification fields and a normalization schema version. Records are sorted by item key and source fingerprint, so normalized output is independent of product input row order. The manifest adds normalized field-status counts and marks every retained record for a conflicting item as `conflict_retained`; all distinct source records are retained, and exact duplicates remain skipped and counted.

The fixture run produces `interactions.train.jsonl`, `interactions.validation.jsonl`, `interactions.test.jsonl`, `products.jsonl`, and `manifest.json`. The manifest contains source-file SHA-256 hashes and byte counts; schema and source versions; sampling configuration; observed input, output, duplicate, filtered, rejected and warning counts; and output hashes. It deliberately omits run timestamps, absolute source paths, and selected user IDs. Counts describe only the supplied local fixture/input and are not Amazon measurements.

Rerun with a different new output directory to compare deterministic output files and manifest contents. With unchanged inputs, source metadata, seed and limits, those contents are stable. User selection ranks the distinct valid training users by SHA-256 over seed, source ID and user key, so source row order does not affect the selected set. Validation/test users cannot qualify unless they also have a valid training interaction; all records for selected users retain their input split membership. Product rows are retained only for items in selected users' training interactions.

## Validation and failure behavior

- JSONL and CSV reading is row-streamed; decoding/parsing failures are counted as rejected rows. CSV headers must be non-empty and unique, and rows with the wrong number of columns are rejected.
- Canonical required values are non-empty user/item keys, non-negative integer millisecond timestamps, and finite ratings in `[1, 5]`. Product optional values remain null/empty when absent. An invalid optional price is omitted and counted as a warning, not guessed.
- Exact interaction duplicates within one split are skipped and counted. Identical source records present across splits remain in their original splits and are counted as cross-split duplicates. Exact product duplicates are skipped; differing rows for one item are retained and counted as conflicts.
- Fatal file/header or output errors exit non-zero and do not publish a completed output directory. Row-level parsing, adapter, and validation failures do not abort the run; their reason counts are in the manifest. Raw inputs are read-only and never copied into output.
- Processing uses a temporary SQLite index on disk for exact duplicate detection. The first train-only eligibility pass and selected-item set require memory proportional to unique training users and selected training items; this is not constant-memory for all state.

This foundation does not implement Amazon-specific field mapping, source-ID pseudonymization, temporal splitting, feature generation, database insertion, training, or profiling. The JSONL/CSV fixtures are synthetic and are not evidence about real dataset quality, licensing, or resource requirements.

## Product metadata normalization

The opt-in normalized sidecar reuses the canonical `ProductMetadata` record and adds field results containing raw values, normalized value/unit, parse status, and source attribute keys. The original title, category, description, attributes, price, item key, and source fingerprint remain in the nested canonical product. Brand is read only from `brand`/`brand name` attributes; category uses the explicit canonical `category`. Both are Unicode NFKC-normalized, whitespace-collapsed, and casefolded. No aliases, brands, categories, or product attributes are inferred from titles or other fields.

Supported specification keys and conversions:

| Output | Accepted attribute keys | Explicit input values and normalization |
|---|---|---|
| `ram_capacity_bytes` | `ram`, `ram capacity`, `system memory` | MB/GB/TB use decimal SI factors; MiB/GiB/TiB use powers of 1024; output integer bytes. |
| `storage_capacity_bytes` | `storage`, `storage capacity`, `internal storage` | Same explicit SI/binary capacity rules; output integer bytes. Recognized trailing storage type is parsed separately. |
| `storage_type` | `storage type`, `drive type`, or recognized suffix on storage capacity | Conservative values: SSD, HDD, NVMe, eMMC, UFS; aliases such as “solid state drive” are mapped only to SSD. |
| `display_size_mm` | `display size`, `screen size`, `display` | inches × 25.4, centimetres × 10, or explicit millimetres; output millimetres. |
| `weight_g` | `weight`, `item weight`, `product weight` | kilograms × 1000 or explicit grams; output grams. |
| `battery_capacity` | `battery capacity`, `battery` | Ah × 1000 to mAh; mAh stays mAh; mWh ÷ 1000 to Wh; Wh stays Wh. No voltage is assumed, so mAh and Wh are not interconverted. |
| `processor_name`, `gpu_name` | `processor`/`processor model`/`cpu`; `gpu`/`graphics processor`/`graphics` | Source-backed text only; normalize Unicode compatibility and whitespace, without taxonomy or model inference. |

Only explicit numeric values with recognized units are normalized. Missing or explicit-null values stay `missing` and remain represented in `raw_values`; conflicting non-missing aliases stay `ambiguous`; malformed numbers/ranges are `invalid`; unknown units or unsupported formats are `unsupported`. A field with any unresolved conflict has a null normalized value; its raw values and source keys remain available. Broad sanity bounds reject RAM outside 1 MiB–4 TiB, storage outside 1 MB–100 TB, display outside 25–3000 mm, weight outside 1–100,000 g, charge capacity outside 1–1,000,000 mAh, and energy capacity outside 0.001–10,000 Wh. These are parser guardrails, not claims about catalog coverage.

Prices remain as the existing canonical `Money` value only when amount and currency are both explicit. The sidecar preserves the original supplied price value and reports normalized/missing/invalid status. A non-JSON price string (including a sentinel such as `"None"`) is passed to price validation as raw input so it is counted as an invalid optional price rather than rejecting the entire product row. It never infers a currency, converts exchange rates, or treats a historical price as current. Exact product duplicates are skipped by the ingestion pipeline; differing records for an item are not overwritten or merged, are counted, and each is labeled as a retained conflict in the normalized sidecar.

## Interaction preprocessing and quality report

The separate `recfusion-preprocess-interactions` command consumes only canonical per-split JSONL files created by `recfusion-ingest`. It does not read raw source schemas or alter ingestion outputs. For the committed synthetic fixture, run:

```powershell
uv run recfusion-ingest `
  --train tests\fixtures\ingestion\train.jsonl `
  --validation tests\fixtures\ingestion\validation.jsonl `
  --test tests\fixtures\ingestion\test.jsonl `
  --products tests\fixtures\ingestion\products.jsonl `
  --source-id synthetic-fixtures `
  --source-version v1 `
  --seed recfusion-phase2-pilot-v1 `
  --max-users 2 `
  --output-dir data\processed\synthetic-ingestion-v1

uv run recfusion-preprocess-interactions `
  --train data\processed\synthetic-ingestion-v1\interactions.train.jsonl `
  --validation data\processed\synthetic-ingestion-v1\interactions.validation.jsonl `
  --test data\processed\synthetic-ingestion-v1\interactions.test.jsonl `
  --source-id synthetic-fixtures `
  --source-version v1 `
  --output-dir data\processed\synthetic-interactions-v1
```

The preprocessor requires the explicit split and source fingerprint fields written by ingestion. It rejects a row whose embedded split disagrees with its split file; it never reassigns rows. It accepts the existing canonical user/item identifiers, timestamp, and rating, plus optional source event ID/type and raw timestamp provenance fields. Missing event IDs and event types remain absent (represented as null with `*_present: false`); no purchase/click/impression event is inferred.

The output directory contains `interactions.train.processed.jsonl`, `interactions.validation.processed.jsonl`, `interactions.test.processed.jsonl`, and `manifest.json`. JSONL outputs use schema `recfusion.interaction-preprocessing.v1`, preserve each retained record's split and source fingerprint, retain the input rating value and timestamp value, and add normalized UTC time and a configurable rating-feedback label. Defaults classify ratings >=4 as observed positive signals, <=2 as observed low-rating signals, exactly 3 as neutral, and values in gaps as unclassified. Override thresholds with `--positive-min-rating`, `--neutral-rating`, and `--low-max-rating`; non-ordered or out-of-range thresholds fail before output publication. Labels remain provisional review/rating semantics, not purchase relevance or verified negative feedback. Unobserved items are never labeled negative.

Exact repeated source fingerprints with identical payloads are collapsed within each split and counted. Different fingerprints for repeated user-item interactions remain distinct. Identical source events present across splits remain in each original split and are reported. Conflicting payload variants under one fingerprint within the same split are all excluded and counted rather than resolved by row order. If a fingerprint conflicts only across splits, both split records remain in their original partitions and the conflict is reported; held-out data cannot invalidate a training record. Output rows are sorted by timestamp, source fingerprint, and canonical payload signature, so equal-timestamp order and output files are deterministic when input order changes.

The manifest includes input SHA-256/byte counts, source identity/version, schema version, thresholds and policies, output hashes, and a quality report. Whole-data descriptive statistics include per-split input/valid/retained/rejected counts, rating and label distributions, event-type presence, exact duplicate rate/counts and fingerprint-conflict counts, unique IDs, timestamp ranges, and validation/test cold-start counts relative to training. A clearly separated train-only section reports retained training statistics; this step fits no transform and selects no users using held-out data. Integer user/item mappings are deferred until a train-only vocabulary and unknown-ID policy are designed. Manifests do not contain raw IDs or row-level data.

Malformed JSON and schema failures are counted by reason. Unrepresentable/negative timestamps, invalid ratings, missing identifiers/fingerprints, split mismatches, unsupported fields, and conflicting fingerprints are rejected with explicit counts. A fatal file, checksum, SQLite, or output error exits non-zero; an existing output directory is never overwritten. Derived outputs are staged and atomically published only under ignored `data/processed/`; input files are read-only.

Input reading is streamed one JSONL row at a time into a temporary disk-backed SQLite spool, then emitted in stable order. Memory use is bounded relative to total event rows, but disk/index use and aggregate work scale with input size and unique IDs/fingerprints. The committed fixtures are synthetic and validate pipeline behavior only; they are not dataset profiles or model results. This implementation performs no training, feature fitting, negative sampling, source-specific parsing, or data download.
