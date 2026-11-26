# Evaluation correctness and performance infrastructure

**Status:** Phase 5.1A synthetic-only infrastructure. Workload sizes are test
configurations, not throughput targets, serving budgets, or quality evidence.

## Correctness contracts

`recfusion_ml.evaluation.metrics` remains the authority for the warm-start
ranking protocol. Candidate items must equal the train-known item set; model
rankings must contain unique candidate IDs and exclude each user's train-seen
items. Positive validation observations use the existing rating threshold and
are deduplicated to user-item target pairs. Cold-user, cold-item, and seen-item
positives remain audited exclusions. Macro Recall@K, binary NDCG@K, HitRate@K,
MRR@K, and candidate coverage retain the definitions in
[`EVALUATION.md`](./EVALUATION.md). Empty eligible cohorts report undefined
metrics as `null`; they do not become zero-valued observations.

The unit tests include a separately calculated two-user oracle: one user has
two positive targets and retrieves one at rank 2; the other retrieves its
single target at rank 1. At K=2 the expected macro Recall is 0.75, NDCG is
approximately 0.693426, HitRate is 1.0, MRR is 0.75, and catalog coverage is
2/4. Existing metric tests cover zero-hit and empty-result users, short lists,
duplicate positives, train-seen filtering, and cold-user/item exclusions.
Content-eligible versus warm-only candidate policies remain separate protocols
in the Phase 4 content and hybrid benchmark tests; this workload intentionally
uses the train-known warm-only pool.

## Workload schema and profiles

The generator schema is `sparse-ranking-workload.v1`; the aggregate report
schema is `recfusion.synthetic-evaluation.v1`. The default seed is `51001`.
SMALL, MEDIUM, and LARGE resolve to 20/100, 200/5,000, and 1,000/25,000
evaluation users/warm candidate items. LARGE requires `--allow-large`; only
SMALL is run in the Phase 5.1A smoke check. The seed rotates the deterministic
warm-target and source-list assignment. Candidate identity is a stable,
zero-padded synthetic key. No dataset or model artifacts are read.

The candidate policy is the exact train-known item pool with train-seen items
excluded per user. Each eligible user has one train-history interaction and one
warm unseen positive target. A cold positive is added for each five users (at
least one); it is not in the train candidate pool and therefore remains in the
cohort's cold-item exclusion audit. Ratings are all 5. There are no timestamps,
malformed rows, duplicate rows, or product metadata in this synthetic fixture;
those dimensions are reported as absent or zero rather than fabricated.
Recommendation source depth is 20, and evaluation uses K=5/10/20. User records
are assembled in batches of 64 by default. The generator is sparse: it stores
O(candidate items + interactions + users × source depth), never a dense
user-by-item score matrix.

| Profile | Eligible users | Warm candidate items | Approx. generated interaction records | Default execution |
|---|---:|---:|---:|---|
| SMALL | 20 | 100 | 144 | Explicit smoke / lightweight tests |
| MEDIUM | 200 | 5,000 | 5,440 | Opt-in |
| LARGE | 1,000 | 25,000 | 27,200 | Explicit opt-in; outside CI |

The counts include one catalog-seeding train record per candidate, one train
history record per eligible user, one warm validation target per eligible
user, and one cold validation target per five users. They are generated fixture
records, not source dataset records.

## Bounds and failure behavior

`get_workload_config` validates profile, user/candidate counts, generated
records, batch size, intermediate batch allocation, source-list depth, K
values/count, and report-byte limit before generation. Defaults cap at 1,000
users, 25,000 candidate items, 100,000 generated records, batch size 500,
source depth 100, 3 cutoffs with K no larger than 20, a 10,000-record
intermediate batch bound, and a 1 MB serialized report. The chosen profiles
use batch size 64 and depth 20. Empty catalogs/cohorts and malformed rankings
are covered by existing evaluator contracts and focused tests without allocating
large arrays.

Report publication requires an existing output directory and refuses to
overwrite an existing report. It writes a bounded temporary file, flushes it,
then atomically replaces an exclusively claimed destination. An optional
`--temp-dir` must already exist on the same filesystem as the output directory.
Interrupted publication removes its temporary and destination-claim files.
The default output should be an ignored path such as
`data/processed/evaluation-performance-small-v1/report.json`.

## Measurements and deterministic report

Each evaluation repetition measures evaluator-call monotonic wall time with
`time.perf_counter`, process CPU time with `time.process_time`, and Python
allocation peak with `tracemalloc`. If tracing was already active, the utility
leaves it untouched and reports its own traced peak as unavailable. Process
lifetime peak RSS is reported only when the platform exposes
`resource.getrusage` with known units (Linux and macOS); on Windows this field
is explicitly unavailable. This is the process lifetime maximum, not a peak
delta for the measured call. The measurement is for the current process and
excludes child processes. It is not current RSS and does not claim a peak when
only a current reading exists.

The stable projection includes schema/workload versions, seed, evaluation
contract, metric configuration, candidate policy, input/output counts,
training/validation workload and recommendation checksums, an evaluation-code
fingerprint, aggregate metrics, Git revision and dirty-state indicator,
Python/OS/machine and relevant package versions. Its `stable_sha256` excludes
the `resources` and `resource_summary` fields, which contain volatile runtime
measurements. `output_sha256` identifies generated recommendation rows;
the CLI also prints the checksum of the serialized report file. JSON uses
sorted keys, compact separators, and rejects non-finite numeric values. Reports
contain aggregates only, not user/item keys or per-user rankings.

The report explicitly identifies synthetic-only data, records rating and
cohort audit counts, and marks timestamp range and metadata unavailable. The
performance figures characterize only the local synthetic evaluator call;
workload construction and report publication are outside the timed interval.
They are not real-catalog latency, production throughput, capacity estimates,
or recommendation-quality claims.

## Phase 5.1A SMALL smoke check

Command (from the repository root):

```powershell
uv run python -m recfusion_ml.evaluation.synthetic_workload --profile small --seed 51001 --repetitions 3 --output data/processed/evaluation-performance-small-v1/output/report.json --temp-dir data/processed/evaluation-performance-small-v1/tmp
```

Observed on CPython 3.13.11 / Windows 11 AMD64, Git revision
`484cd56e203000bc3808d87e4a5d252547e3d767`:

- 20 train-eligible users; 100 warm candidate products; 4 synthetic cold items.
- 120 train records and 24 validation records (20 warm positives + 4 cold
  positives); 144 generated records total; 0 rejected rows.
- 20 eligible user-target pairs; 4 cold-item positives explicitly excluded;
  0 cold-user, seen-positive, or duplicate-positive observations.
- 400 recommendation rows at source depth 20. Candidate-pool denominator is
  100; recommendation coverage was 0.24/0.29/0.39 at K=5/10/20.
- Ratings were all 5; timestamp range and product metadata were unavailable by
  construction. Metrics are fixture outputs, not quality evidence.
- Three evaluator calls averaged 0.001732 seconds wall time (population
  standard deviation 0.000112 seconds). All per-call process-time samples were
  marked unavailable because they were zero or exceeded the wall interval.
- Traced Python allocation peak averaged 6,160 bytes (population standard
  deviation 482 bytes). Process lifetime peak RSS was unavailable on this
  Windows runtime; no current-RSS substitute was reported.
- Serialized metric payload was 614 bytes; the aggregate report was 5,903
  bytes. The local ignored report is at
  `data/processed/evaluation-performance-small-v1/output/report.json`.
- Workload SHA-256:
  `adf96bcb0db6ee8de8041f15b35da4b9c9b00836c209f48208aa3f3807827631`.
  Training event SHA-256:
  `43872dcd274c244d3e6fb6b36c54fd8a2fc5033366d530af5323c3551182e3bf`.
  Validation event SHA-256:
  `5bf003a2a29a4fbe3c8ddebc106264b76809b62653a3247b3ababca6b766d5de`.
  Recommendation output SHA-256:
  `544519c0b5c282733dea12cb441f723b3a705ee9f4e6dad2e67b862519a342dd`.
  Evaluation code SHA-256:
  `74d253bf9a96dc64e4a1eebef8f743e2a9612a107ff52ef81ba0d489e8095de4`.
  Stable projection SHA-256:
  `7d58b8fe75b9074e9af0980fb431ec51fddd7b9372497282f6e639299b25d77f`.
  Serialized report SHA-256:
  `900010c84427895babbb7db1139d78ffb383c21d4758c7fc43636ff6d55dcc01`.

The stable fingerprint excludes volatile `resources`, `resource_summary`, the
stable fingerprint field itself, and the local artifact path. Only SMALL was
run; MEDIUM and LARGE were not run. This millisecond-scale fixture does not
measure end-to-end workload generation, retrieval serving, or real-data
throughput.

## Proposed Phase 5.1B experiment design

After owner review, a separate checkpoint may run explicitly selected MEDIUM
workloads and repeat them under a documented, controlled environment. It
should preserve the evaluator and candidate contract, report repeated-run
variance and resource method/scope, and compare sparse implementation paths
only when profiling identifies a bottleneck. LARGE should require a separate
explicit invocation and resource review. No synthetic measurements should be
extrapolated to real Electronics data or online serving; any real-data run
remains subject to the independent data-use and pilot gates.
