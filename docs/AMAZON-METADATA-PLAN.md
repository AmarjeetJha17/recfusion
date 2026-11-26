# Amazon Electronics Product Metadata Plan

**Status:** Phase 4.2B.2 synthetic capacity and safety gate is documented. No real Amazon metadata or interaction output was opened, profiled, or joined. The source-specific rights decision remains **PENDING OWNER REVIEW**. The official gzip URL returned 404 to HEAD; an alternate pinned raw JSONL URL returned HTTP 200 to metadata-only HEAD. See [AMAZON-METADATA-PREFLIGHT.md](./AMAZON-METADATA-PREFLIGHT.md) and the [owner decision template](./AMAZON-METADATA-OWNER-DECISION-TEMPLATE.md).

**Decision:** The synthetic adapter is implemented and tested; capacity checks used invented data only. This plan does not authorize acquisition or processing. The metadata rights decision remains **PENDING OWNER REVIEW** and must be recorded before any real metadata is read.

## 1. Purpose and scope

RecFusion needs to determine whether product metadata can be joined to the existing Amazon Reviews 2023 Electronics interactions and normalized into the current product contract. The intended eventual use is local, non-commercial academic coursework: preprocessing, offline training, and offline evaluation. Phase 4.1 documents source and join feasibility. Phase 4.2A implements and verifies the adapter using synthetic inputs only; it does not download, inspect, or process real metadata or establish source coverage or model readiness.

The dataset paper to cite in later academic reporting is Hou et al., “Bridging Language and Items for Retrieval and Recommendation: Benchmarking LLMs as Semantic Encoders,” *Proceedings of ACL 2026*, [ACL Anthology 2026.acl-long.147](https://aclanthology.org/2026.acl-long.147/). The official project page also links the earlier [arXiv:2403.03952](https://arxiv.org/abs/2403.03952).

## 2. Candidate sources

### Primary candidate: official Amazon Reviews 2023 Electronics metadata

The [McAuley Lab project page](https://amazon-reviews-2023.github.io/) documents category metadata JSONL and links the [Electronics gzip metadata file](https://datarepo.eng.ucsd.edu/mcauley_group/data/amazon_2023/raw/meta_categories/meta_Electronics.jsonl.gz), `meta_Electronics.jsonl.gz`. Its URL returned HTTP 404 on the latest HEAD check. The maintainer's [Hugging Face repository](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023) lists a raw uncompressed `meta_Electronics.jsonl` at pinned revision `2b6d039ed471f2ba5fd2acb718bf33b0a7e5598e`; HEAD redirected to the object and returned 200, `Content-Length: 5246144134`, and `Accept-Ranges: bytes`. The redirect's `X-Linked-ETag` matched the listed publisher SHA-256; the final CDN ETag is the separate Xet object hash. This was a metadata-only check; no body was requested and no local file checksum exists. The owner has not yet selected this alternate source/representation. The documented source record includes `parent_asin` and descriptive, rating-aggregate, price, image, video, store, category, and detail fields. The same documentation describes `parent_asin` as the parent product identifier used to find metadata; review `asin` may refer to a child/variant. Join on `parent_asin`, never substitute a review `asin`.

The file is category-wide. No documented key-selective download or index was found. A later join should therefore expect to scan the compressed Electronics metadata stream once while retaining only keys in the train-derived item set. The official compressed file’s transfer size was not verified. Existing repository documentation records a Hugging Face listing size of 5,246,144,134 bytes for the uncompressed raw Electronics metadata JSONL representation; this is not a local measurement or compressed-size estimate. The current Hugging Face Parquet mirror lists about 1.96 GB across ten shards. These are different serialized representations and mutable repository listings, not verified requirements for a future run.

### Mirror: Hugging Face Parquet representation

The [McAuley-Lab Hugging Face repository](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023) contains a Parquet Electronics metadata representation. The viewer currently indicates that its loader requires arbitrary Python execution, and the repository’s documented loading path uses `trust_remote_code=True`. Do not execute that loader as a shortcut. If this mirror is considered later, first audit the loader, pin an immutable repository revision, record exact shard URLs and SHA-256 hashes, and verify the transformed schema. A mutable `main` listing is not reproducible provenance. Parquet values may have different serialized types or nested shapes than the official raw JSONL schema.

### Alternative catalog: Amazon Berkeley Objects

[Amazon Berkeley Objects (ABO)](https://amazon-berkeley-objects.s3.amazonaws.com/index.html) documents a separate product catalog with `item_id`, `domain_name`, multilingual text, and structured product attributes. Its identifiers are not documented as Amazon Reviews 2023 `parent_asin` join keys, and no matching Electronics coverage is established. It is therefore not a replacement or direct join source for this task.

ABO licensing evidence is inconsistent: the current [official S3 landing page](https://amazon-berkeley-objects.s3.amazonaws.com/index.html) states CC BY 4.0, while the [Amazon Science hosted ABO paper](https://cdn.amazon.science/9d/ca/350b3ef94691a1aedabb8bfb538d/abo-dataset-and-benchmarks-for-real-world-3d-object-understanding.pdf) describes release under CC BY-NC 4.0. Treat its terms as unresolved; do not acquire or use ABO until the discrepancy and identifier/domain suitability have been reviewed. It may be reconsidered only as a distinct catalog/content feasibility task.

## 3. Documented Reviews 2023 metadata schema

The official schema lists `main_category`, `title`, `average_rating`, `rating_number`, `features`, `description`, `price`, `images`, `videos`, `store`, `categories`, `details`, `parent_asin`, and `bought_together`. Optional values can be absent, null, empty, or nested. The documentation’s examples are illustrative and do not establish field availability rates for Electronics.

Do not assume one serialized type across source formats. Existing RecFusion dataset documentation notes that the raw documentation and Hugging Face viewer can represent `price` differently (including a string `"None"` sentinel), and nested `details` can also vary. Preserve and count original values/types during any later parser validation. Do not infer a brand, price, specification, category, or image from a title. No metadata coverage or attribute completeness is known until a separately authorized profile is run.

## 4. Join contract and proposed canonical mapping

The existing interaction adapter creates the stable category-scoped key `ar23:Electronics:item:{exact parent_asin}`. A metadata adapter must reuse that exact key policy so the resulting product records can join both the existing interaction outputs and future metadata sidecars. Preserve the source identifier as a private local join value; do not trim, case-fold, or otherwise rewrite it. Validate that it is a non-empty string. No cross-category or cross-source join is allowed by this key.

| Reviews 2023 metadata source | Contract field | Canonical projection and handling |
| --- | --- | --- |
| `parent_asin` | `source_item_key` | Build `ProductMetadata.item_key` with the exact existing Electronics namespace and identifier bytes. |
| `main_category` | `main_category` | Project to `ProductMetadata.category` only after validating nullable string shape; normalize only through the existing normalizer. |
| `title` | `title` | Project nullable source text to `ProductMetadata.title`. |
| `description` | `description` | Project to `ProductMetadata.description` only after validating the source’s list/string shape; retain raw representation/status. |
| `features` | `features` | Project only validated text-list values to `ProductMetadata.features`; preserve raw values/status. |
| `categories` | `categories` | Project only shapes accepted by the contract to `ProductMetadata.categories`; do not flatten nested objects by guesswork. |
| `average_rating` | `source_average_rating` | Preserve snapshot aggregate and provenance; if represented in `ProductMetadata.average_rating`, exclude it from predictive features. |
| `rating_number` | `source_rating_count` | Preserve snapshot aggregate and provenance; if represented in `ProductMetadata.rating_count`, exclude it from predictive features. |
| `price` | `price_raw`, `price_amount`, `price_currency`, `price_status` | Keep original value/type and parsing status. Populate `ProductMetadata.price` only when valid under the contract. Do not reinterpret sentinels or malformed values. USD is crawl-time context, not a current price; never present as current INR or use as a feature. |
| `images`, `videos` | `product_images`, `videos` | Project accepted values to canonical JSON tuples; preserve metadata references locally; do not fetch image/video bytes or publish original images. |
| `store`, `details`, `bought_together` | `store`, `details_raw`, `bought_together` | Preserve source keys and JSON-compatible raw values in `ProductMetadata.attributes`; do not infer fields from prose. |
| source record | `source_record_fingerprint` | Stable SHA-256 over the adapter’s documented canonical source-record encoding; record the fingerprint algorithm/version. |

The canonical product contract and normalizer already support nullable descriptive fields, JSON attributes, source fingerprints, and normalized-field raw values/status/source keys. Phase 4.2 must prove each source shape against that contract with synthetic fixtures before any real file is opened. If a source value cannot be represented without loss, record the mismatch and propose a contract decision rather than silently coercing it.

## 5. Missing records, duplicates, and conflicts

- A missing metadata row is an unmatched catalog key, not a malformed interaction and not a fabricated product. Keep it explicit in aggregate join coverage.
- Distinguish an absent field, explicit null, empty collection, unsupported type, and invalid value. Do not impute values.
- Exact duplicate source metadata records should be fingerprinted and counted. Conflicting records for one `(source_category, parent_asin)` must all be retained or quarantined per the existing data contract; do not select “first row wins.” Conflicted items must be excluded from normalized item features while their interaction history remains intact.
- Report join coverage using both distinct train item keys and train interaction rows as denominators. Keep validation/test and cold-item audits separate; held-out labels must not choose metadata records, vocabularies, or fitted transforms.
- `average_rating`, `rating_number`, and price are snapshot aggregates. They are not review-time signals and are excluded from model features under the current contract.

## 6. Temporal and feature-use limitations

The source metadata schema does not provide reliable per-field effective timestamps. A retrieval timestamp or file snapshot date does not establish that a title, price, rating aggregate, or other value was available at a historical interaction cutoff. Any later metadata-backed comparison must label the features as snapshot-only and retrospective. It cannot claim strict as-of-time catalog correctness from this source alone.

For the existing warm-item comparison, join and fit feature transforms only for distinct items in the Step 2.5 training candidate vocabulary. The existing train-only fitting and trusted official split membership remain unchanged. Any cold-item coverage analysis is a separate aggregate diagnostic; it must not make held-out items or labels part of train feature fitting. No product metadata presence or coverage is established by this plan.

## 7. Bounded-memory and disk design for a later pilot

The adapter streams either `.jsonl` or `.jsonl.gz` with standard-library line-oriented parsing and a bounded maximum record size. Build a disk-backed SQLite index of the exact train-only item keys from the existing Step 2.5 vocabulary. For each metadata row, validate the record and perform an exact key lookup; retain only matched rows and the minimum audit/provenance needed. Do not materialize the whole metadata file or the complete source key set in Python memory. Avoid Hugging Face `trust_remote_code` until its loader has been independently audited.

The input remains immutable and gitignored. Use separate ignored directories for temporary indexes and outputs. Hash the source file in bounded-memory chunks, record byte counts and source identity, and publish derived outputs atomically only after validation. Sort final records by canonical item key and source-record fingerprint. The manifest should be deterministic and omit wall-clock fields from its hashed canonical payload; operational timing can be recorded in the private run report.

This design reduces retained memory but still scans the whole compressed category file and needs disk for the SQLite key index, matched records, audit data, and final outputs. No measured compressed transfer size, local resource benchmark, or reliable capacity estimate is available from this research-only phase. A future preflight must inspect actual free disk, temp/output locations, and memory, set a safety floor based on the machine, and stop if there is insufficient space. Do not extrapolate capacity from synthetic benchmarks.

## 8. Provenance, manifest, and quality report

A private v2 manifest records declared source URL/retrieval date/method/publisher
checksum separately from locally verified representation, checksum, and bytes;
unknown declared facts remain null. It records code commit and dirty state,
normalization schema, train-vocabulary and temporal-manifest fingerprints,
dataset lineage, and snapshot-only status. It also verifies and reports
interaction-row and distinct-item join coverage by official split, including
train-known/train-cold, metadata matched, conflict-excluded, and missing
train-known cohorts with explicit denominators. This audit reads split item
keys but never uses held-out labels, changes the candidate pool, or recomputes
official split membership.

The manifest should also record at minimum:

- source name/category, exact source URL, source format/schema contract, retrieval date, immutable revision if using a mirror, source size and SHA-256;
- adapter/config version, code commit, input interaction manifest/checksum, exact train-only item-key source, and canonical key policy;
- rows scanned, parsed, accepted, rejected by reason, exact duplicate occurrences, conflicting keys, matched/unmatched distinct keys, and match counts by train/validation/test interactions;
- field presence/status/type counts for title, category, description, features, categories, price, images, videos, and details;
- output record count, output checksum/size, temporary SQLite size, bytes read, wall time, peak RSS where observable, and selected run resource limits;
- an explicit statement that metadata is snapshot-only and that no metadata effective timestamp is available.

All public-facing reports must contain reviewed aggregates only. Keep raw metadata, source identifiers, row-level derived records, source image URLs when considered sensitive, and temporary indexes local and ignored.

## 9. Acceptance criteria for a real metadata pilot

Before any real metadata source is opened, Phase 4.2 should require:

1. A project-owner review explicitly covering the separate metadata source and the specific local academic purpose. The existing interaction-data decision does not automatically clear metadata. Applicable law, source terms, and institution requirements remain the owner’s responsibility.
2. A pinned source and immutable provenance plan, sufficient storage preflight, ignored temp/output paths, and no overwrite of an existing run.
3. Synthetic adapter tests for exact `parent_asin` key reuse, child `asin` non-join, missing metadata, optional field variants, invalid rows, exact duplicates, conflicts, deterministic fingerprints/order, and input-order-invariant output hashes are implemented. Additional real-pilot acceptance checks remain listed below.
4. Reconciliation of scanned = accepted + rejected; accepted records = output records plus explicitly classified exact-duplicate/conflict handling; and exact join denominators. Duplicate and conflict records are not mislabeled as malformed.
5. Train-only vocabulary and transform fitting, unchanged official split membership, no held-out label/model selection, and no use of snapshot aggregates as features.
6. Private aggregate quality report with source row totals, accepted/rejected/duplicate/conflict counts, distinct-key and event-level coverage, field availability/status, missingness, timestamp limitations, resource usage, output hashes, and unavailable metadata explicitly distinguished from observed zero values.
7. No claims of full feature readiness until the actual product metadata has been authorized, inspected, joined, and its coverage and quality reported.

## 10. Existing components reused and remaining Phase 4.2 work

Reuse the `AmazonReviews2023ElectronicsAdapter` item-key namespace, `ProductMetadata` contract, product validation and normalization routines, SQLite-backed ingestion/feature-store patterns, bounded-memory hashing, ignored `data/processed/` storage, atomic publication helpers, and the Step 2.5 train-only item vocabulary. Continue using the existing warm/cold and conflict rules in `DATA-CONTRACTS.md`, `FEATURES.md`, `DATA-PROFILING-PLAN.md`, and `EVALUATION.md`.

Phase 4.2A implements bounded JSONL and JSONL.GZ streaming, schema-specific mapping, disk-backed exact-key join, duplicate/conflict audit, checksummed v2 provenance manifest, normalized sidecar, and per-split interaction join coverage. Phase 4.2B.2 records synthetic capacity and failure-cleanup checks only. `--temp-dir` is required for the SQLite database; because SQLite can place spill files in the OS temp directory, a Windows run must set process-scoped `TMP` and `TEMP` to the same existing D: directory and verify `GetTempPath()` before launch. The publisher SHA-256 is enforced against local bytes before output staging. Real-source processing and actual metadata quality/coverage remain unverified and gated; no feature-release readiness is claimed. See the preflight for measured synthetic usage and explicitly non-predictive disk scenarios.

## 11. Rights and privacy gate

The [McAuley Lab maintainer discussion](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/discussions/1) says the maintainers cannot assign a blanket license or dictate usage terms, that the dataset was made available primarily for research, and that users remain responsible for ethics and applicable law. The maintainer’s favorable response to another student’s specific thesis question is not a binding license or RecFusion-specific legal clearance. Existing documentation records only a narrowly scoped project-owner assessment for the interaction files; metadata is an additional source and remains unreviewed for this proposed join.

If later approved, keep processing local and non-commercial. Do not commit or publish raw metadata, source IDs, row-level derived outputs, dataset CSVs, images, or image bytes. Attribute the dataset and publication appropriately. Exclude commercial deployment and redistribution absent separate rights review. This document is not legal advice, does not establish that all rights are cleared, and does not satisfy any legal, source-term, or institutional requirement. The project owner is responsible for identifying and meeting applicable obligations.

## 12. Phase boundary

Phase 4.1 feasibility and Phase 4.2A synthetic adapter implementation are complete; Phase 4.2B.2 has documented capacity scenarios and temp-path safeguards. The next real-data step must first receive project-owner review of this separate metadata source, then perform a source-specific preflight covering pinned provenance, rights and terms, local ignored storage, actual free space on every volume, and overwrite protection. Until that gate is cleared, do not download, inspect, ingest, or profile real metadata. No real Amazon metadata was opened or processed in Phase 4.2B.2.
