# Amazon Electronics Metadata Use Assessment and Acquisition Preflight

**Assessment date:** 2026-11-26
**Status:** Source-specific assessment prepared; **PENDING OWNER REVIEW**.
**Recommendation:** **NO-GO for Phase 4.2C acquisition at this time.** The
synthetic adapter checks pass, but the owner has not recorded a decision for
this separate metadata source, and the official linked file returned HTTP 404
to a HEAD-only request. No metadata was downloaded or opened.

## 1. Scope and decision status

The proposed use is RecFusion's local, non-commercial MCA Recommendation
Systems coursework: metadata preprocessing and joining, followed by offline
training and offline evaluation. Public reporting is limited to reviewed
aggregates with attribution. Raw metadata, copied product text collections,
source identifiers, row-level outputs, and original images will not be
published. Commercial service use, redistribution, or broader research use are
outside the proposed scope.

This is a description of the owner's intended project scope, not a decision
made on the owner's behalf. The existing [ADR-014](./DECISIONS.md) documents a
narrow academic-use assessment for the Electronics interaction files. It does
not clear product metadata. No explicit project-owner decision for this exact
metadata source and scope was found; status remains **PENDING OWNER REVIEW**.

## 2. Source provenance and authoritative statements

| Property | Finding |
|---|---|
| Dataset | Amazon Reviews'23 / Amazon Reviews 2023, collected by McAuley Lab. |
| Source publisher | McAuley Lab, University of California San Diego. |
| Category and release | Electronics category, 2023 dataset release. The metadata stream is category-wide, not limited to the 5-core interaction items. |
| Documented format | Gzipped JSON Lines, one metadata object per line; expected filename `meta_Electronics.jsonl.gz`. |
| Official file URL | `https://datarepo.eng.ucsd.edu/mcauley_group/data/amazon_2023/raw/meta_categories/meta_Electronics.jsonl.gz` (linked from the official project page). |
| Documentation | [Official project page](https://amazon-reviews-2023.github.io/), [metadata schema and loader example](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023), and [repository metadata files](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/tree/main/raw/meta_categories). |
| Research citation | Hou et al., [“Bridging Language and Items for Retrieval and Recommendation: Benchmarking LLMs as Semantic Encoders”](https://aclanthology.org/2026.acl-long.147/), ACL 2026; the project page also links the [2024 arXiv preprint](https://arxiv.org/abs/2403.03952). |
| Retrieval date | 2026-11-26 for the documentation review and HEAD request in this preflight. No dataset bytes were retrieved. |

The official project page describes review text and item metadata including
descriptions, prices, and raw images. Its documented metadata fields include
`main_category`, `title`, `average_rating`, `rating_number`, `features`,
`description`, `price`, `images`, `videos`, `store`, `categories`, `details`,
`parent_asin`, and `bought_together`. It instructs users to use `parent_asin`
to find product metadata. Examples are not evidence of Electronics field
coverage. The page also says item counts are based on review items and that
some items lack metadata.

### Rights evidence and limits

**Explicit source statements:** the official project page documents the data
and links its files but contains no license or usage-terms statement. The
McAuley Lab [dataset-license discussion](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/discussions/1)
says the maintainers cannot assign a license or dictate use terms, that the
dataset was made available primarily for research, and that users remain
responsible for ethical guidelines and applicable law. The maintainer's
favorable response to a different student's thesis question was specific to
that student's description; it is not a license or permission for RecFusion.
The Hugging Face dataset card displays no license statement.

**Project-owner scope:** local, non-commercial academic preprocessing,
training, and offline evaluation are the intended use. The earlier
interaction-data assessment does not automatically include this separate
metadata source.

**Technical risk assessment:** metadata contains product titles/descriptions,
seller/store strings, crawl-time aggregate ratings and prices, and image/video
references. The source documentation does not grant a blanket right to
republish those materials. Product text may contain third-party content, and
image references do not establish rights to fetch or publish the original
images. Keep processing local; omit image/video references and bytes from
canonical outputs; do not publish raw collections or row-level derivatives;
publish only reviewed aggregate findings with attribution. Price and aggregate
ratings remain excluded from predictive features.

**Unresolved:** no blanket license; no source-specific terms establishing the
proposed use or redistribution rights; possible third-party content rights;
and institution-specific policy/applicable law have not been independently
verified. No specific mandatory university approval requirement or source
prohibition for this narrowly scoped local coursework use was identified in
the repository documents reviewed, but that is not proof that none applies.
The project owner remains responsible for resolving those questions. This
assessment is not legal advice or legal clearance.

## 3. Official host and file preflight

On 2026-11-26, a HEAD-only request was sent to the exact official file URL
above, with redirects enabled and no response body requested. It returned:

```text
HTTP/1.1 404 Not Found
Server: Apache/2.4.29 (Ubuntu)
Content-Type: text/html; charset=iso-8859-1
```

There was no redirect and no `Content-Length`, checksum, or `Accept-Ranges`
header in the response. The response is an HTML error, not the dataset. The
host resolved from the local environment for this request, but the file is not
currently verified as downloadable. The documentation does not state an
authentication requirement; the 404 response does not establish whether the
file would require authentication if restored. Range and resume support are
unknown. No checksum published alongside the official link was found.

The Hugging Face repository has a separate Parquet representation under
`raw_meta_Electronics`; its current listing reports a 1.96 GB directory across
ten shards. This is not the official compressed JSONL.GZ file, is not a local
transfer measurement, and is not a substitute source for the implemented
adapter. Its mutable `main` branch would require an immutable revision and
separate format/loader review. Existing repository notes about the size of an
uncompressed JSONL listing likewise do not determine the gzipped transfer
size.

**File-size status:** official compressed size unknown. **Published checksum:**
not found. **Acquisition/resume:** not verified; no download, byte range, or
sample request was made. Resolve the 404 through the official source before
any acquisition is considered. Do not silently switch to a mirror.

## 4. Local resource preflight

Observed local environment on 2026-11-26:

| Resource | Observation |
|---|---|
| OS | Windows, reported version `10.0.26300.0`, x64. |
| Python / uv | Python 3.13.11 64-bit; uv 0.13.1. |
| Project/output volume | Repository and ignored `data/processed/` output are on D:. Free space observed: 185,890,217,984 bytes (about 173.1 GiB). `data/processed/` is Git-ignored. |
| Temporary volume | The system temporary directory is on C:. Free space observed: 21,413,064,704 bytes (about 19.94 GiB). |
| Proposed raw location | `data/raw/amazon-reviews-2023/electronics/metadata/`; `data/raw/` is Git-ignored. This path does not currently exist. |
| SQLite location | Use a distinct, run-specific temporary directory on D: under ignored `data/processed/`, passed with `--temp-dir`. The CLI requires this directory to exist. This avoids relying on C:'s smaller free-space pool. No directory was created. |
| Memory | Physical RAM could not be queried because the local CIM request was denied. No RAM/capacity claim is made. |

The adapter uses an 8 MiB maximum decompressed JSONL record by default and an
8 MiB SQLite page cache; these bound parts of process memory, not total disk
requirements. Its SQLite state contains target keys, source fingerprints, and
matched canonical product records. The output directory is first written as a
temporary sibling and then atomically renamed, so the two output files are
staged once rather than copied into a second complete output tree.

No reliable total capacity requirement can be calculated before the official
compressed size and matched/output cardinality are known. Use this budget
equation after the source is accessible:

```text
additional D: free space >= C + T + Ocanonical + Onormalized + R
```

Here `C` is the retained compressed input, `T` is measured/planned temporary
SQLite state, `Ocanonical` and `Onormalized` are the two generated JSONL files,
and `R` is an owner-approved recovery reserve. The source has no verified
`C`, and `T`/output expansion cannot be inferred from synthetic fixtures.
For sensitivity only (not source-size estimates), raw input alone would use
1, 2, or 5 GiB in those respective scenarios; each full scenario must add
`T + Ocanonical + Onormalized + R`. Current D: free space can hold those raw
input-only scenarios, but does not establish that a full run fits. Before any
future run, inspect the actual file, both volumes, and chosen temp/output
directories again. Do not reserve disk space in this checkpoint.

## 5. Canonical join and synthetic CLI verification

The shared helper returns
`ar23:Electronics:item:{exact parent_asin}`. Both the interaction and metadata
adapters use it. It rejects blank identifiers without trimming/case-folding
valid values. The metadata adapter requires `parent_asin`; a child `asin` alone
cannot be used as a join key. Train-only vocabulary and temporal-manifest
checks are required; validation/test items do not expand the target vocabulary
or select metadata records. Synthetic fixture `SYNTH_C` appears only in held-out
interactions and is not emitted by the metadata join.

The CLI name and flags below were checked using the installed
`recfusion-ingest-amazon-metadata --help`. Its exact adapter selector is
`amazon-reviews-2023-electronics-metadata`; it accepts `--metadata`,
`--train-vocabulary`, `--temporal-manifest`, `--source-id`, `--source-version`,
`--output-dir`, optional `--temp-dir`, and optional `--max-record-bytes`.
No network downloader is implemented in this CLI.

The synthetic integration test ran the actual CLI `main()` with invented gzip
JSONL and generated Step 2.5 artifacts. It covers valid matched items,
train-vocabulary misses, missing attributes, an exact duplicate, a conflicting
record, a child-only identifier, malformed JSON, and a non-object row. Results:

| Audit count | Synthetic result |
|---|---:|
| Source rows read | 8 |
| Valid source rows | 5 |
| Rejected rows | 3: invalid source identifier 1, malformed JSON 1, non-object 1 |
| Matched source rows | 4 |
| Unmatched valid source rows | 1 |
| Unique matched source records | 3 |
| Exact duplicate matched occurrences | 1 |
| Distinct matched products | 2 |
| Missing train target products | 1 of 3 target items |
| Conflicting matched item keys | 1, with both distinct source records retained |
| Canonical product output rows | 3 |
| Field observations | one missing title; one malformed `details` field |

The tested reconciliations are `8 = 5 + 3`, `5 = 4 + 1`, `4 = 3 + 1`, and
`3 train targets = 2 matched + 1 missing`. Reversing source row order produced
identical canonical and normalized output hashes and sorted rows. The manifest
source-file hash changes when the compressed input order changes, as expected;
the entire manifest is therefore not byte-identical across those inputs.
Configured temporary SQLite state was removed. A corrupt gzip run published no
output and left no temporary state. A mismatched vocabulary checksum is
rejected. A focused test now also proves that an existing output directory is
preserved and never overwritten. The source-processing code contains no HTTP,
URL, or downloader calls; this synthetic path requires no external connection.

Validation for these adapter checks: **28 focused unit/integration tests
passed** after adding the child-ASIN and overwrite tests.

## 6. Snapshot, privacy, and leakage audit

- Metadata is snapshot-only; no reliable per-record effective timestamp exists.
  Retrieval time is provenance, not historical product-valid time.
- `average_rating` and `rating_number` are retained only as raw source context;
  they are not predictive item features. Historical price is preserved with
  source status but is not generated as a feature.
- `store` is retained as a source attribute and is not treated as verified
  brand. No values are inferred from title text.
- Image/video references and bytes are excluded from canonical output; no
  remote media fetch exists.
- Matching uses the Step 2.5 train-only item vocabulary. The metadata adapter
  does not modify official split membership or add held-out-only products to
  training candidates. The existing feature generator excludes all features
  for conflicted items and labels their rows `conflict_excluded`.
- No automatic cold-item evaluation is performed. Metadata match readiness is
  not content-model readiness: actual coverage, text quality, and usable
  feature availability remain unknown.
- Keep raw metadata and row-level outputs local and ignored. Do not stage
  source identifiers, raw files, derived rows, images, or model/user artifacts.

## 7. Phase 4.2C runbook proposal (not authorized or executed)

1. Obtain an explicit project-owner decision for this separate metadata source
   and the described local academic scope. Record remaining legal, source-term,
   and institution uncertainties; do not characterize the result as a license.
2. Recheck the official source URL. Stop if it remains unavailable. Capture
   HTTP status, final URL, `Content-Length`, ETag/Last-Modified, published
   checksum, authentication behavior, and byte-range support before planning
   transfer. If no official checksum exists, hash the complete local file with
   SHA-256 after transfer. Do not substitute the Parquet mirror without a
   separately reviewed immutable revision and format decision.
3. Recheck free space on D: and C:, then create distinct ignored paths for
   immutable raw input, temporary SQLite state, and a new output run. Ensure
   the chosen output does not exist. Preserve the downloaded raw file
   read-only; record exact URL, retrieval time, size, hash, and source response
   headers in a private provenance record.
4. Only after source verification, transfer to a `.partial` file and verify
   byte count and hash before atomically renaming it to the immutable raw
   filename. Resume only if range support was observed and the transfer client
   verifies the existing partial; otherwise restart from the beginning. No
   download/resume command is prescribed while host behavior is unknown.
5. Before the real join, close the audit gaps below: include source URL,
   retrieval date, and code commit in provenance; provide item- and
   interaction-level aggregate coverage by official split without fitting on
   held-out data; record measured runtime/RSS/temp/output sizes; and preserve
   the rights-decision reference in a private manifest or adjacent report.
6. Use the supported adapter invocation shape below only after separate
   Phase 4.2C authorization. The command name and option names are verified;
   angle-bracket values are placeholders, not an executable command:

   ```text
   uv run recfusion-ingest-amazon-metadata
     --adapter amazon-reviews-2023-electronics-metadata
     --metadata <immutable-local-meta_Electronics.jsonl.gz>
     --train-vocabulary <verified-Step-2.5-vocabulary.items.jsonl>
     --temporal-manifest <verified-Step-2.5-manifest.json>
     --source-id amazon-reviews-2023-electronics-metadata
     --source-version <pinned-source-revision-or-retrieval-id>
     --temp-dir <existing-ignored-temporary-directory>
     --output-dir <new-ignored-data-processed-run-directory>
   ```

7. Require source-row reconciliation, duplicate/conflict counts, matched and
   missing distinct item counts, split-specific interaction coverage,
   rejection and optional-field status counts, timestamp limitation, source
   and output checksums, and resource measurements. Do not report unavailable
   fields as observed zero coverage. Keep all row-level products private.
8. On checksum, count, split, capacity, or publication failure, stop; do not
   promote partial output. Preserve failure diagnostics without source IDs.
   Remove only temporary artifacts owned by that run after retaining the
   aggregate failure report. Retry only into a new output directory after the
   cause is resolved. Do not publish or upload the raw data or row-level
   outputs.

## 8. Owner decision checklist and blockers

Before a later controlled pilot, the owner should explicitly confirm:

- The local, non-commercial coursework purpose and specific metadata source.
- Understanding that the maintainer grants no blanket license and that this
  assessment is not legal clearance.
- Applicable source terms, institution policy, and law have been considered.
- Local-only handling, attribution, aggregate-only public reporting, no image
  reuse, no raw/row-level republication, and no commercial/redistribution use.
- Whether to proceed only after the official file URL is restored and a fresh
  capacity/provenance preflight passes.

**Current blockers:** owner decision pending; official direct file URL returned
404; compressed file size, checksum, authentication, range support, and resume
behavior remain unknown; physical RAM could not be queried; current adapter
manifest lacks source URL/retrieval date/code commit and event-level join
coverage. These do not invalidate the synthetic join tests, but they prevent a
fully auditable real-data pilot from starting now.

**Recommendation:** **NO-GO for Phase 4.2C now.** Reconsider a conditional GO
only after the owner reviews this record, the official source is reachable and
its provenance/rights conditions are documented, the audit gaps above are
closed, and an actual local capacity check passes. This report does not
authorize acquisition or real-data processing.
