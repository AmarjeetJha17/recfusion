# Amazon Electronics Metadata Use Assessment and Acquisition Preflight

**Assessment date:** 2026-11-26 (source HEAD and local resource recheck)
**Status:** Phase 4.2B.2 capacity and safety review documented using synthetic
inputs only; source-specific assessment remains **PENDING OWNER REVIEW**.
**Recommendation:** **NO-GO for acquisition or real-data processing.** No
metadata or interaction output was downloaded, opened, or processed.

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
| Documented format | The official project documents gzipped JSON Lines; the maintainer's Hugging Face repository also lists an uncompressed `.jsonl` representation. |
| Official file URL | `https://datarepo.eng.ucsd.edu/mcauley_group/data/amazon_2023/raw/meta_categories/meta_Electronics.jsonl.gz` (linked from the official project page). |
| Alternate publisher-hosted representation | [Pinned Hugging Face raw JSONL](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/2b6d039ed471f2ba5fd2acb718bf33b0a7e5598e/raw/meta_categories/meta_Electronics.jsonl); repository revision `2b6d039ed471f2ba5fd2acb718bf33b0a7e5598e`. This is not a downloaded local file or a rights decision. |
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

On 2026-11-26, a HEAD-only request was sent to the exact official gzip URL
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

### Raw JSONL representation metadata-only check

The Hugging Face file listing identifies the raw Electronics metadata as
uncompressed JSONL with displayed size 5.25 GB and publisher-listed SHA-256
`5eb4dabd539586c49654297319ef178b62a2fe8e43108376feda125f04455d93`. This is
a repository listing assertion, not a local file checksum.

On 2026-11-26, `curl.exe --head --location` requests to both the mutable `main`
URL and pinned revision URL returned a redirect followed by HTTP 200. The
final response reported `Content-Length: 5246144134`, `Accept-Ranges: bytes`,
CDN ETag/Xet hash `b975ed977454331d0660ba9c13f5998960a89c60c9068aaf5e757bd379037815`,
and `X-Repo-Commit: 2b6d039ed471f2ba5fd2acb718bf33b0a7e5598e`. The redirect
response exposed `X-Linked-ETag` equal to the repository-listed SHA-256
`5eb4dabd539586c49654297319ef178b62a2fe8e43108376feda125f04455d93`. The
command requested no body and reported `size_download=0`. These are distinct
publisher metadata values. This confirms current HEAD metadata and advertised
range support; it does not verify a full GET, locally acquired bytes, or usage
rights. No GET or range request was made.

The Hugging Face repository also lists a separate Parquet representation under
`raw_meta_Electronics`; its current listing reports a 1.96 GB directory across
ten shards. It is not the raw JSONL or official compressed JSONL.GZ file, not
a local transfer measurement, and not the input format supported by this
adapter. Any Parquet consideration requires separate immutable-revision and
format/loader review.

**File-size status:** official compressed `.jsonl.gz` size unknown; raw JSONL
has a HEAD-advertised size of 5,246,144,134 bytes. **Published checksum:** none
found for the linked gzip; the HF raw JSONL listing/HEAD reports SHA-256
`5eb4dabd539586c49654297319ef178b62a2fe8e43108376feda125f04455d93`.
**Acquisition/resume:** no file was downloaded. HEAD advertises byte-range
support for raw JSONL, but no ranged GET or full GET was tested. The owner must
select the exact source and representation; no automatic source switch is
approved.

## 4. Local resource preflight

Observed local environment on 2026-11-26:

| Resource | Observation |
|---|---|
| OS | Windows, reported version `10.0.26300.0`, x64. |
| Python / uv | Python 3.13.11 64-bit; uv 0.13.1. |
| Project/output volume | Repository and ignored `data/processed/` output are on D:. Free space observed: 185,896,460,288 bytes (about 173.1 GiB) via `System.IO.DriveInfo`; `data/processed/` is Git-ignored. |
| Ambient temporary volume | `System.IO.Path.GetTempPath()` resolves to C:\; free space observed: 21,459,423,232 bytes (about 19.98 GiB). SQLite may use this OS temp location for spill files independently of the adapter's `--temp-dir`. |
| Process temporary override | Process-scoped `$env:TMP` and `$env:TEMP` set to an existing D: directory were verified to make `GetTempPath()` resolve on D:. No persistent environment setting was changed. |
| Proposed raw location | `D:\RecFusionData\AmazonReviews2023\Electronics\metadata\` (proposal only; not created). Keep raw input outside the repository. |
| SQLite location | Use a distinct, run-specific existing temporary directory on D:, passed with required `--temp-dir`. Before launch, set process-scoped `TMP` and `TEMP` to that D: directory and verify `GetTempPath()` is also on D:. No directory was created. |
| Memory | Physical RAM could not be queried because the local CIM request was denied. No RAM/capacity claim is made. |

The adapter uses an 8 MiB maximum JSONL record by default and an
8 MiB SQLite page cache; these bound parts of process memory, not total disk
requirements. Its SQLite state contains target keys, source fingerprints, and
matched canonical product records. The output directory is first written as a
temporary sibling and then atomically renamed, so the two output files are
staged once rather than copied into a second complete output tree.

No reliable total capacity requirement can be calculated before the official
compressed size and matched/output cardinality are known. Use this budget
equation after the source is accessible:

```text
additional free space across the selected raw/temp/output volumes >=
  C + T + Ocanonical + Onormalized + A + R
```

Here `C` is the retained input (4.89 GiB for the HEAD-advertised uncompressed
JSONL, or unknown for gzip), `T` is temporary SQLite state including OS-temp
spill files, `Ocanonical` and
`Onormalized` are the two outputs, `A` is any atomic staging copy (the current
implementation stages one output tree and renames it, so this is not a second
full output copy), and `R` is a separately chosen recovery reserve. `T`,
output expansion, and `R` cannot be inferred reliably from synthetic fixtures.
Current free space exceeds the advertised raw JSONL input size alone, but does
not establish that a complete run fits. Recheck the actual file, both volumes,
and selected directories before processing. Do not reserve disk space here.

### Synthetic capacity probe and planning scenarios

A temporary probe processed 1,000 invented JSONL records (64,560 input bytes)
against a 64-item synthetic train vocabulary. It matched 64 rows (6.4%),
completed in 0.5043 seconds, peaked at 28,315,648 bytes of process working set
(about 27.0 MiB, including the interpreter), used a 188,416-byte SQLite file,
staged 124,780 output bytes, and emitted 21,814 canonical plus 102,966
normalized bytes. Cleanup completed. These measurements validate the probe
instrumentation and cleanup path only; they are not a reliable capacity
estimate for the real source.

The following are planning scenarios, not measured requirements. They use the
advertised 4.89 GiB raw JSONL size, reserve one source-size download `.partial`
file, and apply scenario multipliers to SQLite+spill and each output. Logs and
reports reserve 0.1 GiB; recovery reserve is 25% for low/medium and 50% for
high. Same-volume atomic rename adds no second full output tree.

| Scenario | Source | Download partial | SQLite + spill | Canonical output | Normalized output | Logs/reports | Extra atomic copy | Recovery reserve | Indicative total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Low | 4.89 GiB | 4.89 GiB | 2.45 GiB (0.5x) | 2.45 GiB (0.5x) | 2.45 GiB (0.5x) | 0.10 GiB | 0 | 4.31 GiB | 21.50 GiB |
| Medium | 4.89 GiB | 4.89 GiB | 9.78 GiB (2x) | 4.89 GiB (1x) | 4.89 GiB (1x) | 0.10 GiB | 0 | 7.35 GiB | 36.77 GiB |
| High | 4.89 GiB | 4.89 GiB | 24.45 GiB (5x) | 14.67 GiB (3x) | 14.67 GiB (3x) | 0.10 GiB | 0 | 31.79 GiB | 95.43 GiB |

Totals are rounded planning scenarios only. They do not establish actual
SQLite growth, output expansion, or RAM capacity. D: currently has enough
free space for these scenarios, while ambient C: free space is below the high
scenario. Verify actual free space and temp root immediately before any
separately authorized run.

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
`--output-dir`, required `--temp-dir`, `--max-record-bytes`, and optional
declared-provenance flags `--source-url`, `--retrieved-at`,
`--retrieval-method`, and `--publisher-sha256`. Both `.jsonl` and `.jsonl.gz`
inputs are supported; representation is inferred from the suffix and the
exact local bytes are hashed.
No network downloader is implemented in this CLI. A supplied
`--publisher-sha256` is compared with the locally computed source checksum;
mismatch aborts before output staging is created.

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
output and left no temporary state. Mismatched vocabulary and publisher
checksums are rejected; publisher mismatch is rejected before output staging.
An injected publication failure verified staging/SQLite cleanup and a
deterministic retry. The successful synthetic source-hash test confirms the
input bytes stayed unchanged. An existing output directory is preserved and
never overwritten. The source-processing code contains no HTTP,
URL, or downloader calls; this synthetic path requires no external connection.

Validation for the latest safety additions: **19 focused unit/integration
tests passed** across the metadata CLI integration and adapter unit modules.
The tests cover an injected failure before atomic publication; hard process
termination was not simulated and may require manual cleanup of that run's
temporary/staging files.

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
3. Recheck free space on D: and C:, then create distinct storage paths for
   immutable raw input outside the repository, a run-specific temporary
   directory on D:, a new ignored output run under `data/processed/`, and a
   private D: log/report directory. Ensure the chosen output does not exist. Preserve the downloaded raw file
   read-only; record exact URL, retrieval time, size, hash, and source response
   headers in a private provenance record.
4. Only after owner review and source verification, transfer to a `.partial`
   file and verify byte count and hash before atomically renaming it to the
   immutable raw filename. HEAD advertises range support for the pinned raw
   JSONL, but no ranged GET was tested. Resume only after a transfer client
   validates HTTP 206 and `Content-Range`; otherwise restart. No acquisition
   command has been executed or validated.
5. Before the real join, pass any known declared source URL, retrieval date,
   retrieval method, and publisher checksum to the CLI. The v2 manifest now
   captures declared versus locally verified provenance, code commit/dirty
   state, and checksummed split-level interaction coverage. Also record
   measured runtime/RSS/temp/output sizes in the private run report and retain
   the rights-decision reference there.
6. Set process-scoped `$env:TMP` and `$env:TEMP` to the existing D: temp
   directory, then verify
   `[System.IO.Path]::GetPathRoot([System.IO.Path]::GetTempPath()) -eq 'D:\'`.
   Keep row-level stdout/stderr logs private on D:. Use the supported adapter
   invocation shape below only after separate Phase 4.2C authorization. The
   command name and option names are verified;
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

**Current blockers:** owner decision pending; the official direct gzip URL
returned 404; gzip file size/checksum, authentication, range support, and
resume behavior remain unknown; physical RAM could not be queried; the pinned
raw JSONL representation has metadata-only HEAD verification, and ranged GET
has not been tested. The
alternate raw JSONL HEAD is reachable and advertises size/hash/range metadata,
but its bytes have not been downloaded or locally verified, and the owner has
not selected this alternate representation. Synthetic tests do not resolve
rights or actual source content.

**Recommendation:** **NO-GO for Phase 4.2C now.** Synthetic technical checks
support only a later, separately reviewed preflight. Reconsider after owner
review, exact source selection, verified acquisition behavior, and actual
per-volume capacity checks. This report does not authorize acquisition or
real-data processing.
