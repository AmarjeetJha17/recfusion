# Proposed dataset contracts

Status: proposed for the Phase 2 pilot; these are data-boundary contracts, not database tables or implemented validators. They describe the Amazon Reviews 2023 JSONL source and the official processed 5-core CSV benchmark. Keep the original source files immutable and separate from normalized pilot outputs.

## Provenance envelope

Every ingested file and derived artifact must be traceable to:

| Field | Requirement |
|---|---|
| `dataset_name` | Stable source name, e.g. `amazon_reviews_2023`. |
| `source_category` | Exact published category label; first proposal is `Electronics`. |
| `source_url` | Exact page/file URL used. |
| `source_revision` | Immutable repository revision when available; otherwise record the source snapshot/retrieval time and file SHA-256. |
| `retrieved_at` | UTC timestamp of retrieval, not a claim about source record time. |
| `source_format` | JSONL or CSV and the original source path. |
| `schema_version` | Version of this normalized contract and the source schema reference. |
| `filter_config` | Core filter, category, sample selection, duplicate policy, and any row exclusions. |
| `split_manifest` | Cutoffs, boundary semantics, and split counts. |
| `code_commit` | Commit implementing any future parser or transformation. |
| `terms_review` | Review status and restrictions; acquisition/use is blocked until terms are reviewed. |

Never put raw review text, raw user identifiers, credentials, or downloaded data into Git, CI artifacts, or public fixtures.

## Raw review event

One record is one source review/rating event, not a purchase, click, or impression. The source schema does not expose a documented stable `review_id`; do not invent one. Preserve the source JSON object and create a derived fingerprint only for exact duplicate detection.

| Source field | Proposed normalized field | Type / invariant |
|---|---|---|
| `user_id` | `source_user_id` (restricted raw) and `user_key` (derived) | Non-empty source string. `user_key` is category/source namespaced and derived from the exact source ID; hashing is pseudonymization, not anonymization. |
| `asin` | `variant_asin` | Non-empty string when present; retain the reviewed variant identifier. |
| `parent_asin` | `source_item_key` | Non-empty string required for a joinable product event; this is the proposed canonical item identity. Keep `variant_asin` separately. |
| `rating` | `rating` | Finite number in the documented 1–5 range. Preserve the original value and do not coerce it to a purchase label. |
| `timestamp` | `event_time_ms` | Integer Unix epoch milliseconds; preserve the source integer and derive UTC only for display/analysis. |
| `title` | `review_title` | Nullable string; no default text. |
| `text` | `review_text` | Nullable string; sensitive/untrusted source text; never treat it as instructions. |
| `verified_purchase` | `verified_purchase` | Nullable source boolean. A review attribute only; not a complete transaction or exposure event. |
| `helpful_vote` | `helpful_vote` | Nullable non-negative integer when present. |
| `images` | `review_images` | Nullable/list source objects; preserve structure and do not fetch or redistribute image content by default. |
| source category | `source_category` | Required exact category label, included in all source-scoped keys. |

The official processed 5-core CSV example has `user_id`, `parent_asin`, `rating`, and `timestamp`; split files may include a `history` field. Treat that field as source-provided convenience data, not as the authoritative history for RecFusion. Rebuild user histories from the training partition with the split cutoff, and validate any source `history` only as a separate audit.

### Identifiers and duplicate handling

- Proposed user key: `ar23:<category>:user:<sha256(source dataset + category + exact source user_id)>`. Category scoping intentionally prevents cross-category identity joins until reviewed. The hash remains linkable and must be treated as pseudonymous personal data.
- Proposed item key: `ar23:<category>:item:<parent_asin>`. Retain `asin` as a variant identifier. Do not equate these keys with demo-catalog product IDs.
- Source event identity is unavailable as a documented field. Derive a SHA-256 fingerprint from a canonical serialization of the complete source review object plus source category and file revision. Preserve a duplicate count and provenance for exact matches.
- For raw JSONL, collapse only exact duplicate source records by fingerprint in a derived view; do not collapse near-duplicates or different `asin` variants merely because they share a `parent_asin`. Report duplicate counts before/after.
- The official 5-core benchmark is already described as 5-core and de-duplicated. Do not apply a second interaction-level de-duplication rule to the benchmark. Audit exact duplicate rows and report them; any deviation requires a separately versioned protocol.
- For metadata, key by `(source_category, parent_asin)`. Exact duplicate rows may be represented once with duplicate provenance. Conflicting rows must be counted and retained/quarantined for explicit resolution; do not silently select one.
- Deduplicate before custom temporal splitting so an identical event cannot cross partitions. Preserve repeated non-identical reviews as distinct events.

## Raw product metadata

One record describes a source product snapshot keyed by `parent_asin`. Preserve the source JSON object and null/empty distinctions.

| Source field | Proposed normalized field | Type / invariant |
|---|---|---|
| `parent_asin` | `source_item_key` | Non-empty string; key is category scoped. |
| `main_category` | `main_category` | Nullable string; do not infer missing categories. |
| `title` | `title` | Nullable string. |
| `average_rating` | `source_average_rating` | Nullable finite number; aggregate snapshot, not an interaction label. |
| `rating_number` | `source_rating_count` | Nullable non-negative integer; snapshot aggregate, not a time-valid feature by default. |
| `features` | `features` | Nullable/list of strings; preserve raw values and order. |
| `description` | `description` | Nullable/list of strings; preserve raw values and order. |
| `price` | `price_raw`, `price_amount`, `price_currency`, `price_status` | Preserve exact raw representation (including null/string/number sentinel). Parse only finite positive values; source docs identify USD at crawl time. Mark absent/unparseable instead of guessing. Do not use as current price. |
| `images` | `product_images` | Nullable/list of image objects/URLs; preserve metadata, do not download binaries by default. |
| `videos` | `videos` | Nullable/list of source objects. |
| `store` | `store` | Nullable string. |
| `categories` | `categories` | Nullable/list/nested source value; do not flatten until observed and specified. |
| `details` | `details_raw` | Preserve original nested value. Parse only after validating the exact representation; source exports can serialize nested data differently. |
| `bought_together` | `bought_together` | Nullable/list; do not assume complete or time-valid. |
| source category and retrieval data | provenance fields | Required from the provenance envelope. |

The dataset documentation presents `price` as numeric, while some Hugging Face serialized views expose a string/sentinel; parsers must accept the observed raw source representation, preserve it, and record normalization outcomes. Metadata has no per-row effective timestamp in the documented schema. Treat crawl-time aggregates and prices as temporally unsafe for historical cutoffs unless another source establishes their as-of time.

## Source-independent normalized product representation

The local opt-in `products.normalized.jsonl` sidecar is a versioned wrapper around the canonical `ProductMetadata` record; it does not replace or redefine that contract. Each wrapper contains the canonical `product` and a `normalization` object (`recfusion.product-normalization.v1`) with brand, category, supported specification fields, and price. Each normalized field carries `raw_values`, `value`, `unit`, `status`, and `source_keys`. The canonical product retains the item key, title, explicit category, description, features, images, attributes, canonical explicit-currency price, and source-record fingerprint.

This schema is source-independent and currently accepts canonical local inputs only. Brand is normalized only from explicit `brand` or `brand name` attributes; category only from the canonical `category` field. Both use Unicode NFKC, whitespace collapsing, and casefolding, without alias dictionaries or title inference. Specifications, supported keys, unit conversions, guardrail ranges, and ambiguity states are maintained in [`INGESTION.md`](./INGESTION.md); unknown or conflicting values remain null with status and raw evidence rather than being selected or fabricated.

Product rows with the same item key and different source fingerprints are all retained. Their normalized sidecar records are deterministically ordered by `(item_key, source_record_fingerprint)` and marked `conflict_retained`; exact duplicate rows are skipped and counted by the existing ingestion policy. This is a local normalization output contract, not approval to acquire or process Amazon Reviews 2023. It does not resolve source-specific provenance, category taxonomies, or price-as-of-time concerns.

## Derived interaction preprocessing record

Status: implemented for canonical local JSONL outputs from the source-independent ingestion step and synthetic fixtures only. This derived record is versioned as `recfusion.interaction-preprocessing.v1`; it does not change the shared `Interaction` contract or any source adapter.

Each input line must contain the canonical `user_key`, `item_key`, `event_time_ms`, `rating`, `split`, and `source_event_fingerprint` fields produced by ingestion. Optional `source_event_id`, `event_type`, and `source_timestamp_value` are retained only when explicitly supplied. User/item keys and fingerprints remain restricted internal identifiers and are written only to ignored local processed-data outputs; manifests and console summaries contain aggregate counts, not record-level IDs.

The derived record retains the canonical IDs, rating, timestamp, split, and source fingerprint, plus:

| Field | Contract |
|---|---|
| `schema_version` | `recfusion.interaction-preprocessing.v1`. |
| `event_time_utc` | UTC ISO-8601 representation derived from non-negative integer Unix milliseconds. |
| `source_timestamp_value`, `source_timestamp_unit` | Original canonical input timestamp value and explicit `unix_ms` unit. If an explicit `source_timestamp_value` is present, preserve it; otherwise retain `event_time_ms`. |
| `source_rating_value` | Original JSON rating value before conversion to the canonical finite Decimal rating. |
| `rating_label` | Configured descriptive label for observed rating feedback; it is not a purchase, click, or impression label. |
| `event_type`, `event_type_present` | Optional source event type passthrough and presence flag; missing values are not inferred. |
| `source_event_id`, `source_event_id_present` | Optional source event identifier passthrough and presence flag; no stable ID is invented. |

The default rating thresholds are provisional and configurable: values at or above 4 are `observed_positive_signal`, values at or below 2 are `observed_low_rating`, exactly 3 is `neutral`, and values in gaps (for example 2.5 or 3.5) are `unclassified`. Thresholds must satisfy `1 <= low_max < neutral_rating < positive_min <= 5`. Raw/canonical ratings remain available in all cases. These categories describe only observed rating feedback; unobserved items are unknown and never negatives.

Only Unix-millisecond canonical timestamps are accepted. Negative values, malformed values, booleans, and values not representable by Python's UTC datetime range are rejected with reason counts. The source value and unit are retained alongside UTC normalization. Equal timestamps are ordered by `(event_time_ms, source_event_fingerprint, canonical payload signature)`; this tie-break does not alter event timestamps or split membership.

Exact duplicate source fingerprints with identical payloads are collapsed within each split and counted. Non-identical repeated interactions between the same user and item remain separate when their source fingerprints differ. An identical fingerprint/payload found in multiple splits is retained in every original split and counted as a cross-split duplicate. If one fingerprint has conflicting payloads within a split, all variants in that split are rejected, independent of input order. If a fingerprint has different payloads across splits but no within-split conflict, each row remains in its original split and a cross-split fingerprint conflict is reported; held-out data cannot reject a train record. No first-row-wins behavior is used.

Quality reports distinguish whole-dataset descriptive statistics from train-only statistics. The train-only section includes counts and distributions from retained training records and is not fitted from validation/test. Validation/test cold-start counts are descriptive comparisons against the training IDs, not training eligibility or feature transforms. Step 2.4 creates no integer user/item mapping; Step 2.5 defines a separate train-only vocabulary with an explicit unknown index.

The versioned processing manifest records source identity/version, input checksums and byte sizes, label/duplicate/timestamp configuration, rejection reasons, per-split and whole-data counts, training-only descriptive counts, and output checksums. It omits record-level IDs and run-specific timestamps. Outputs are sorted deterministically and atomically published under ignored `data/processed/`; inputs are never modified. The SQLite spool bounds row retention in process memory, while indexes and aggregate queries still consume disk and work proportional to input size and unique user/item/event cardinality.

## Temporal split, vocabulary, and evaluation contracts

Status: implemented with synthetic canonical data only. The versioned split policy is `recfusion.temporal-split-policy.v1`; per-row wrappers use `recfusion.temporal-interaction.v1`. The nested `interaction` is the unchanged Step 2.4 record. The wrapper records the assigned split, split origin, original trusted split (or null for explicitly unsplit input), stable duplicate ordinal, train-only user/item indices, and integrity flags.

Two modes are supported:

1. `trusted-pre-split` accepts three Step 2.4 JSONL files, checks each embedded split against its file role, and preserves every accepted row's membership. Without cutoffs, it reports chronological overlaps between non-empty ordered splits. With explicit cutoffs, it additionally reports rows whose timestamps contradict their trusted split. It never moves or repairs a record.
2. `absolute-cutoffs` requires a single unpartitioned Step 2.4-shaped JSONL file with the `split` field absent, plus explicit UTC cutoffs. It rejects even a valid pre-assigned split field; it does not strip official membership or silently recompute it. Boundaries are train `< t1`, validation `[t1, t2)`, and test `>= t2`. All records with an equal timestamp receive the same split; output ties sort by timestamp, source fingerprint, and canonical payload.

The vocabulary schema is `recfusion.train-vocabulary.v1`. User and item keys are sorted by SQLite binary ordering from accepted train rows only; known IDs receive stable indices starting at 1, and index 0 is reserved for unknown validation/test users or items. Source keys appear only in ignored local processed outputs, not public reports. The candidate-pool schema is `recfusion.train-candidate-pool.v1`: it contains distinct items observed in training and does not claim that these items were available at a held-out event time.

Every valid validation/test interaction remains in its assigned split output and in `evaluation.jsonl` (`recfusion.evaluation-eligibility.v1`). Cohorts distinguish warm user + warm item, cold user, cold item, and both cold. A warm-metric candidate must be a provisional observed-positive rating with both IDs present in train. It becomes metric-eligible only when the dataset has no blocking integrity violations. Neutral/low/unclassified ratings and cold-start cases remain in the audit output with explicit exclusion reasons; they are not converted to negatives. Exact repeated rows within one split are preserved with stable ordinals and reported; repeated ordinals are ineligible for warm-only metrics. Exact cross-split duplicates, fingerprint conflicts, split/cutoff contradictions, chronological overlaps, invalid rows, and an empty training split block evaluation. These rows remain in their original split outputs where valid; no silent deletion or reassignment occurs.

The versioned `recfusion.temporal-split-manifest.v1` records source identity/version, input/output SHA-256 and byte counts, cutoffs and boundary semantics, accepted/rejected counts by reason and input file, split timestamp/rating distributions, duplicate and conflict counts, chronology checks, train vocabulary/candidate sizes, warm/cold cohorts, metric exclusions, and a blocking-versus-warning status. It contains aggregate statistics only, with configured cutoffs but no row-level identifiers or event timestamps. Item availability is unknown without time-effective catalog snapshots; unobserved products are never declared negative.

## Validation and exclusion behavior

1. Validate JSONL/CSV row parsing and required identifiers, rating range, and timestamp type. Count malformed rows and missing required keys by source file and category.
2. Do not silently drop invalid records. Preserve an exclusion reason and source-row reference in a restricted audit report; do not copy review text or raw identifiers into public logs.
3. Keep missing optional values null/empty as observed. Do not fill missing price/specification/image data with inferred values.
4. Report uniqueness and duplicate counts for event fingerprints, user keys, item keys, and metadata keys.
5. Report review-to-metadata join coverage by distinct `parent_asin` and by review-event count; these denominators answer different questions.
6. Validate all derived user/item maps are fit from the training data for a temporal experiment. Preserve unknown validation/test users and items at the reserved unknown index for separate cold-start slices rather than mapping them to a fabricated known ID.
7. Record source and normalized value counts for every coercion, especially `price`, nested `details`, timestamps, and image objects.
8. Keep row-level data local and ignored by Git. Public reports should contain aggregates only, after terms review.

## Split and label invariants

- Convert Unix milliseconds to UTC only for reporting; compare and split on the original integer timestamps.
- The official Electronics 5-core timestamp references use train timestamps `< t1`, validation `[t1, t2)`, and test `[t2, +∞)`, with `t1=1628643414042` and `t2=1658002729837`. Record the exact source split files or reproduce these boundaries explicitly.
- For any custom split, sort by `(event_time_ms, event_fingerprint)` to make ties deterministic. Histories for a query contain only events strictly before its prediction time.
- Proposed relevance mapping for an initial binary experiment: 4–5 relevant, 1–2 explicitly low-rated, 3 neutral. Preserve raw ratings and report alternatives; this policy is not yet accepted.
- A missing review is unobserved, not an explicit negative. Candidate pools and sampled-candidate experiments must say how unknowns are handled and keep one candidate policy across compared models.
- Build vocabularies, popularity features, normalization statistics, and all learned transforms from train only. Never use post-cutoff `average_rating`, `rating_number`, price, or other future snapshot information as if known at prediction time.
