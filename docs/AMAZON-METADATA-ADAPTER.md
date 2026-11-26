# Amazon Electronics Metadata Adapter

**Status:** Synthetic-only implementation complete for Phases 4.2A and 4.2B.1.
No real Amazon metadata or interaction output was opened, scanned, joined, or
profiled by this implementation step. Real-source use remains gated by the separate project-owner review in
[`AMAZON-METADATA-PLAN.md`](./AMAZON-METADATA-PLAN.md).

## Source and contract

The adapter accepts UTF-8 JSON Lines as either `.jsonl` or `.jsonl.gz`, one
object per line. Both forms use the same record validation, mapping, duplicate,
and conflict policies. It can target the raw Amazon Reviews 2023 Electronics
metadata representation documented by the [official dataset project](https://amazon-reviews-2023.github.io/).
The source is a snapshot: it has no trustworthy per-field effective timestamps.
The source metadata is not an interaction event and its aggregate ratings,
rating counts, and prices are not review-time signals.

The adapter reuses the interaction adapter's exact product key:
`ar23:Electronics:item:{parent_asin}`. It accepts only a non-empty string and
does not trim, case-fold, or otherwise rewrite the identifier. Matching uses an
attested Step 2.5 `vocabulary.items.jsonl` generated from training interactions
only. Validation/test items do not expand the join pool, and their labels do
not select or fit metadata features.

| Source field | Canonical handling |
|---|---|
| `parent_asin` | Exact shared Electronics item key; never join on child `asin`. |
| `title`, `main_category` | Nullable text fields, validated and retained without inference. |
| `categories`, `description`, `features` | Accept only documented text/list shapes; unsupported values are counted, not guessed. |
| `details` | Retain the JSON-compatible original under `details_raw`; parse a JSON object only (never Python `eval`) and expose one-level attributes for the existing normalizer. |
| `store`, `bought_together` | Retain as source attributes; `store` is not treated as brand. |
| `average_rating`, `rating_number` | Preserve raw source values and provenance as snapshot aggregates; canonical predictive fields remain null. |
| `price` | Preserve raw value and parse status; a valid positive numeric amount is represented as source USD context, never as a current price or model feature. |
| `images`, `videos` | Count presence, but omit references and bytes from canonical outputs; never fetch media. |
| Unknown source fields | Count field occurrences in the aggregate manifest; do not copy them into product output. |

Unsupported optional values become field issues and null canonical values; they
do not reject an otherwise valid source object. Invalid JSON lines, non-object
records, oversized records, and missing/invalid `parent_asin` values are
rejected with reason counts. Missing metadata for a train item is reported as
unmatched; no placeholder product is fabricated.

## Streaming, duplicates, and outputs

`recfusion-ingest-amazon-metadata` reads one bounded JSONL record at a time
(8 MiB default, configurable), hashes the exact source bytes in
bounded-memory chunks, and uses a temporary disk-backed SQLite index for the
train-only item vocabulary, fingerprints, duplicate counts, and matched
records. The temporary database is removed after the run. The metadata input,
vocabulary, and temporal manifest are checksummed before/after processing to
detect changes during the run.

Exact source-record fingerprints are counted. For matched products, exact
duplicate occurrences are omitted from canonical output and counted in the
manifest. Distinct source fingerprints for one item key are all retained in
stable `(item_key, fingerprint)` order and marked `conflict_retained` by the
normalization sidecar; the adapter does not pick a winner or merge conflicting
records. Reconciliation requires:

- source records read = valid source records + rejected records;
- valid source records = matched source records + unmatched source records;
- matched source records = unique matched source records + exact duplicate
  matched occurrences; and
- train vocabulary items = matched distinct item keys + missing target items.

The versioned manifest separates declared provenance (URL, retrieval time and
method, publisher hash) from locally verified facts (file representation,
byte size, and SHA-256). Unprovided declared facts remain null. A publisher hash
is compared to the locally computed hash when supplied. The manifest records
the repository commit and whether tracked/untracked Git state was dirty when
the run began, the normalization schema, verified train vocabulary fingerprint,
and explicit snapshot-only/effective-time status. A declared URL or retrieval
method is not treated as independently verified provenance.

The adapter also verifies and reads the three checksummed Step 2.5 split
outputs to calculate per-split interaction join coverage. It reports all-row
and unique-item totals, train-known versus train-cold cohorts, metadata-matched
counts, conflict-excluded counts, and missing train-known counts. Event counts
are row-weighted; unique-item counts are distinct keys. Metadata matches are
restricted to the train-only vocabulary. Reading held-out item keys for
aggregate coverage does not use held-out labels, fit vocabularies, change
candidate pools, or recompute split membership. A matched key with conflicting
metadata is counted as matched and separately excluded from feature-ready
coverage, consistent with the feature generator.

Outputs are `products.jsonl`, `products.normalized.jsonl`, and `manifest.json`.
They are assembled in a temporary sibling directory and atomically published
only to a new child of ignored `data/processed/`; existing destinations are
never overwritten. Output rows are sorted by binary item key and source
fingerprint. The manifest includes input and output checksums, vocabulary and
temporal-manifest attestations, counts, rejection reasons, field issues,
duplicate/conflict totals, interaction join-coverage denominators, provenance
status, and snapshot limitations. It omits local source paths and row-level
identifiers.

Example invocation syntax (use only synthetic inputs until the rights gate is
cleared):

```powershell
uv run recfusion-ingest-amazon-metadata `
  --adapter amazon-reviews-2023-electronics-metadata `
  --metadata tests\fixtures\amazon_metadata\synthetic.jsonl.gz `
  --train-vocabulary data\processed\synthetic-temporal\vocabulary.items.jsonl `
  --temporal-manifest data\processed\synthetic-temporal\manifest.json `
  --source-id synthetic-amazon-electronics `
  --source-version fixture-v1 `
  --output-dir data\processed\synthetic-amazon-metadata-v1
```

The test suite builds all source and temporal inputs synthetically in ignored
temporary directories; it does not include or access real Amazon metadata.

## Rights, privacy, and limits

The dataset maintainers have not provided a blanket license. The documented
limited academic research-use assessment is not independent legal clearance,
and interaction-data review does not automatically authorize this separate
metadata source. Applicable law, source terms, and institutional requirements
still govern. Keep raw metadata and all row-level derived outputs local and
ignored; do not publish raw data, source identifiers, source media references,
or original images. No commercial deployment or redistribution is permitted
without separate rights review. The adapter does not establish metadata
coverage, temporal validity, or feature-release readiness.
