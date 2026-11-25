# Phase 2 Synthetic Pipeline Report

## Status

**Synthetic pipeline readiness: PASS for the bounded synthetic release workflow.**
The end-to-end test covers the existing Phase 2 ingestion, preprocessing,
trusted temporal split, and feature-generation stages. It does not establish
real-data quality, license/terms approval, production capacity, or Phase 3
model-training readiness.

**Real-data pilot status:** Separate local 100-user and 10,000-user Electronics
5-core pilots have since completed under the limited owner-scoped coursework
decision. See `AMAZON-PILOT-PLAN.md` for aggregate findings. This synthetic
release report does not include or publish their row-level outputs, establish
legal clearance, or establish recommender-model readiness. **Phase 3 readiness
with real data is not established.**

## Reproduction

From the repository root, run:

```powershell
uv run recfusion-synthetic-release --output-dir data\processed\phase2-synthetic-release
```

The command runs the existing stages in order:

1. Synthetic canonical JSONL ingestion with opt-in product normalization.
2. Interaction preprocessing from the ingestion outputs.
3. Trusted pre-split validation using UTC millisecond cutoffs.
4. Feature generation from the verified temporal outputs and normalized
   product sidecar.
5. Cross-stage contract, checksum, boundary, vocabulary, history, and
   privacy-surface checks.
6. Atomic publication of an immutable output directory under ignored
   `data/processed/`.

The output directory must not already exist. The versioned
`release-manifest.json` includes input checksums, configuration and its hash,
schema versions, stage manifest references, aggregate counts, validation
results, and checksums/sizes for derived outputs. It excludes its own checksum
to avoid a self-referential manifest. Run-specific timing and memory readings
are printed by the CLI and returned to callers, rather than embedded in the
deterministic manifest.

## Synthetic evidence

The committed fixture set contains three interaction split files and one
product metadata file. The accepted interaction counts are:

| Stage / split | Input rows | Accepted / retained | Rejected or duplicate |
|---|---:|---:|---:|
| Ingestion train | 7 | 4 | 2 rejected, 1 exact duplicate |
| Ingestion validation | 4 | 4 | 0 |
| Ingestion test | 3 | 3 | 0 |
| Interaction preprocessing | 11 | 11 | 0 |
| Trusted temporal output train | — | 4 | 0 |
| Trusted temporal output validation | — | 4 | 0 |
| Trusted temporal output test | — | 3 | 0 |

Product ingestion received 6 rows: 4 output records, 1 exact duplicate
skipped, 1 malformed record rejected, and 1 conflicting item represented in
the retained metadata accounting. Normalization reported ambiguous and
unsupported fields. Feature generation retained all 11 interaction records,
including all 7 held-out records, and reported one training-catalog item with
conflicting product metadata without merging its conflicting records.

The two UTC cutoffs are 5,000 ms and 10,000 ms. The record exactly at 5,000 ms
is validation; records exactly at 10,000 ms are test. Both synthetic test
events at 10,000 ms remain in test and receive two prior training interactions
in their histories; neither sees the other simultaneous event.

The train-only vocabularies contain 2 users and 3 items, with unknown index
`0` reserved. The candidate pool contains exactly the 3 training-observed
items. Of 7 held-out records, 3 are warm positive metric candidates and 4 are
excluded from warm-only metrics (2 cold items and 2 non-positive observed
ratings). No unobserved item is labeled negative. The fixture has zero
cross-split duplicate groups, fingerprint conflicts, and timestamp boundary
mismatches.

The final feature artifacts omit raw user and item keys. Identifiers present
in intermediate local artifacts are synthetic fixture identifiers only; the
release manifest contains aggregate counts and hashes, not record-level
identifiers.

## Reproducibility and resource measurements

Two independent CLI runs with identical configuration produced:

- Byte-identical `release-manifest.json` files with SHA-256
  `f85a63e4364aeb5803d569fbe43391ce74532aaccff1df60645dd1ed12d315ae`.
- Identical hashes for all 23 listed derived files.
- The same configuration SHA-256:
  `89a6cc5e290159879eaa2e4bca70e910948003feed7a545129acd9a0278b750a`.
- 94,674 bytes of hashed stage artifacts, excluding the release manifest;
  110,901 bytes for one complete published directory including the manifest.
- Measured pipeline-stage elapsed times of 0.374 s and 0.406 s. Peak traced
  Python allocations were 1,226,915 and 1,227,067 bytes.

The memory number is from `tracemalloc`; it does not measure native allocator
usage or process RSS. These measurements describe only this tiny synthetic
fixture on the recorded local environment. They must not be extrapolated to
real datasets or production capacity.

The failure-injection integration test raises during ingestion and verifies
that neither a final release directory nor a leftover staging directory is
published.

## Validation results

The following repository validation commands completed successfully:

| Command | Result |
|---|---|
| `uv sync --frozen` | Passed; 44 packages checked. |
| `uv run ruff check .` | Passed. |
| `uv run ruff format --check .` | Passed; 77 files already formatted. |
| `uv run mypy packages apps/api/src` | Passed; no issues in 37 source files. |
| `uv run pytest` | Passed; 74 tests in 5.93 seconds. |
| `uv run pre-commit run --all-files` | Passed; all configured hooks passed. |
| `uv build --offline` | Passed; source distribution and wheel built. |
| `uv run recfusion-synthetic-release --help` | Passed; packaged command is discoverable, and its entry appears in wheel metadata. |
| `git diff --cached --check` | Checked against the final staged files; see final staged-file audit. |

The focused release integration tests cover reproducible end-to-end execution,
failure-injection atomicity, and refusal to overwrite an existing output
directory.

## Limitations and unresolved gates

- The fixture is deliberately small; it is a contract/integration check, not
  evidence of real-world source compatibility or data quality.
- The orchestrator is intentionally fixed to committed synthetic fixtures.
  Existing stages use disk-backed processing where applicable, but the
  release audit reads intermediate JSONL outputs into Python lists and
  cardinality-dependent sets. Memory grows with the rows inspected and the
  distinct user/item/event keys; this audit is not a large-data runner.
- The pipeline depends on local generated files and SQLite-backed stage
  behavior; filesystem throughput and temporary disk availability were not
  stress-tested.
- Product metadata lacks historical effective timestamps. Snapshot metadata
  cannot establish past item availability.
- External source formats, product catalog availability, source-specific
  event identity, and dataset terms are not validated here.
- No recommender model, embedding, negative sampler, database, or API was
  built or run.

The synthetic release may be reviewed as a reproducible pipeline artifact.
The separate bounded real-data pilots provide technical evidence only for the
tested source snapshot and sample sizes; they do not establish legal clearance,
capacity beyond the measured run, or model quality. Synthetic success alone
does not authorize additional data processing and does not advance Phase 3.
