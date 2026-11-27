# Evaluation correctness and performance infrastructure

**Status:** Phase 5.2A synthetic-only pipeline profiling and optimization decision.
Workload sizes are test configurations, not throughput targets, serving
budgets, or quality evidence.

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
MEDIUM report separately records synthetic fixture generation,
recommendation generation, workload fingerprinting, metric evaluation,
aggregate serialization, and total runner time. Total runner time includes
generation, metric repetitions, and stable-projection serialization, but not
report file publication or `uv` process startup. These measurements are local
synthetic execution observations, not real-catalog latency, production
throughput, capacity estimates, or recommendation-quality claims.

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
stable fingerprint field itself, and the local artifact path. At completion of
the Phase 5.1A checkpoint, only SMALL had run; MEDIUM and LARGE had not run.
This millisecond-scale fixture does not
measure end-to-end workload generation, retrieval serving, or real-data
throughput.

## Phase 5.1B MEDIUM controlled synthetic evaluation

One MEDIUM run was executed from the repository root with seed `51001` and
three evaluator repetitions. The report is local and gitignored at
`data/processed/evaluation-performance-medium-v1/output/report.json`; it is
not committed. The command used the existing CLI and offline project
environment:

```powershell
uv run --offline python -m recfusion_ml.evaluation.synthetic_workload --profile medium --seed 51001 --repetitions 3 --output data/processed/evaluation-performance-medium-v1/output/report.json --temp-dir data/processed/evaluation-performance-medium-v1/tmp
```

Preflight found approximately 12 GiB available RAM and 173 GiB free on the
project drive. The run used conservative 2 GiB available-RAM and 1 GiB free-
disk abort floors; these are safety guards, not estimates of workload capacity.
The output path was absent before execution and ignored by Git. The separate
temporary directory was also ignored. The harness does not use SQLite, so
temporary SQLite size is not applicable. No source-data files were opened.

Observed workload and correctness results:

- 200 train-eligible and evaluated users; 5,000 warm candidate items.
- 5,200 synthetic train records, 240 validation records (200 warm targets and
  40 cold-item positives), 5,440 generated records total, and 0 rejected
  records.
- The warm-start cohort contains 200 eligible positive targets. All 40
  cold-item positives are counted as exclusions; there are 0 cold-user, seen,
  or duplicate-positive observations.
- The exact train-known candidate pool has 5,000 items, with each user's
  train-seen items excluded. The output has 200 recommendation users and
  4,000 recommendation rows at source depth 20 (20 per user).
- Recall/HitRate at K=5/10/20 are 0.25/0.50/1.00; NDCG is
  0.147423/0.227178/0.352013; MRR is 0.114167/0.146448/0.179887; candidate
  coverage is 0.0408/0.0418/0.0438. These are deterministic synthetic fixture
  outcomes, not comparative model evidence.
- All ratings are 5 by construction. Timestamp range and product metadata are
  unavailable. The fixture contains no raw identifiers or row-level report
  output.

Measured stages and resource scope:

- Fixture generation: 0.06970 seconds; recommendation generation: 0.04148
  seconds; workload fingerprinting: 0.01752 seconds.
- Three metric calls averaged 0.02712 seconds (population standard deviation
  0.00124 seconds). Aggregate serialization took 0.000129 seconds. Total
  measured runner time was 0.58386 seconds; it includes those stages and
  report projection work, but excludes final report publication and `uv`
  startup.
- Generation traced Python allocation peak was 3,670,048 bytes. Metric-call
  traced peak averaged 45,592 bytes (population standard deviation 113 bytes).
  These are Python allocation measurements, not total process memory.
- Process CPU time was 0.125 seconds for generation and 0.015625 seconds per
  metric call. Process peak RSS is unavailable because the Windows harness
  does not expose the supported OS peak-memory API. No external RSS substitute
  was used. Input I/O is not applicable because this is a generated fixture.
- The aggregate report is 6,743 bytes with SHA-256
  `20dd752b759f01a356a6167da143c1d25fdec4eac0a68cb8d4064623fef8072f`.
  No SQLite temporary file was created.

Determinism was checked by rebuilding the workload with the same profile and
seed. The replay matched the recorded workload (`b3ecab9b8423c7fbec5fcae975da282baf18f8c96982b97ba5d3603f46afc803`), training
(`d98e55f2c60c4dd00c2415feb22c6efc32935d5f6726fd226c6a0e739c2783dc`),
validation
(`b6453aa72c893fe69fe479f111fcfc6aa39f4dd44c9a92962ba54e915d177355`), and
recommendation output
(`48c62d96b986d9ae59a151b05d525f61608bd768ed9e40a02f3e7cb7c9cfce16`) hashes.
All three metric repetitions returned identical metric payloads. The report
records the pre-run HEAD revision and a dirty worktree because this checkpoint's
timing instrumentation was under review during the run; its evaluation-code
fingerprint identifies the evaluated code.

Compared with the preserved SMALL report, the profile grew from 20 users and
100 candidates to 200 users and 5,000 candidates. The metric-call mean grew
from 1.732 ms to 27.122 ms, while the traced metric-call allocation mean grew
from 6,160 to 45,592 bytes. These local observations have different workload
sizes and are not used to infer asymptotic complexity or extrapolate to a real
catalog. SMALL process RSS and MEDIUM process RSS are both unavailable on this
Windows runtime. Both reports contain only aggregate metrics.

### Phase 5.1B follow-ups proposed before the Phase 5.2A profile

1. Keep the metric correctness oracle and leakage/candidate-contract tests as
   gates for any optimization.
2. Profile larger synthetic cohorts in a controlled environment that can
   measure process peak RSS before changing sparse data structures. MEDIUM did
   not establish a resource bottleneck, and its results do not justify a
   capacity claim.
3. If further profiling identifies serialization or fingerprinting as
   material, measure those stages independently before optimizing them.
4. Keep LARGE explicitly opt-in and subject to a separate resource review.
   Do not use these synthetic measurements to authorize or size real-data
   processing, serving, or model training.

## Phase 5.2A MEDIUM pipeline profile and decision

### Frozen baseline and methodology

The committed SMALL and MEDIUM reports were verified before profiling. Both
use schema `recfusion.synthetic-evaluation.v1` and seed `51001`; the MEDIUM
profile is 200 users, 5,000 warm candidates, depth 20, and K=5/10/20. The
existing MEDIUM report was not overwritten. Its workload SHA-256 is
`b3ecab9b8423c7fbec5fcae975da282baf18f8c96982b97ba5d3603f46afc803`,
recommendation SHA-256 is
`48c62d96b986d9ae59a151b05d525f61608bd768ed9e40a02f3e7cb7c9cfce16`, and
metric payload matches the newly profiled runs. The SMALL report remains at
the same seed and has 20 users and 100 candidates.

Profiling used Python's standard-library `cProfile` and `pstats` around
`run_synthetic_evaluation` for one MEDIUM run with three metric repetitions.
A paired unprofiled run used the same profile, seed, code, and repetitions.
This is one local pair, not a stable multi-run timing distribution. The
profile was disabled for a separate report-publication measurement. Pure JSON
serialization was timed separately on the same aggregate report; it is a
diagnostic submeasurement and must not be added to the end-to-end publication
time. A short `tracemalloc` snapshot run captured positive retained-allocation
deltas by source line; these deltas do not include all transient allocations.
The local `.pstats`, aggregate reports, and profile summary are under the
gitignored directory
`data/processed/evaluation-performance-medium-v1/profile-5-2a-final/`.
No user-level rankings or record contents were written to those artifacts.

### Stage measurements

The paired unprofiled run is used for the stage clocks below. Stage boundaries
are inclusive only where stated; do not add the full publication clock to its
separate JSON serialization submeasurement.

| Stage | Observed time | Share of comparable total | Boundary |
|---|---:|---:|---|
| Synthetic fixture generation | 0.04999 s | 11.4% of runner | Create synthetic IDs and rating events; includes cohort construction |
| Eligibility and seen-item cohort checks | Not independently timed | Included above | `build_validation_cohort` is included in fixture generation; cProfile reports it separately as an inclusive function time |
| Candidate/recommendation construction | 0.03134 s | 7.2% of runner | Build 200 depth-20 rankings and their recommendation digest |
| Workload fingerprints | 0.01413 s | 3.2% of runner | Hash train/validation events, candidate keys, recommendation output, and workload projection |
| Per-user ranking metrics plus macro aggregation | 0.01927 s mean per call; 3 calls | 13.2% of runner across all calls | One `evaluate_rankings` call includes validation checks, user loop, per-user metrics, and macro aggregation; internal sub-stages are not separately observable without invasive instrumentation |
| Stable aggregate projection serialization | 0.000073 s | 0.02% of runner | Existing runner's canonical stable projection serialization |
| Full aggregate JSON serialization | 0.000063 s mean; 5 repetitions | Not additive | Canonical serialization of a 6,593-byte profile report payload; separate micro-measurement included within `publish_report`'s broader boundary |
| Output publication | 0.00687 s | 1.6% of runner plus publication | `publish_report` end-to-end: canonical serialization, bounded temp write/flush/fsync, exclusive destination claim, and atomic replace |
| Total runner | 0.43716 s | 100% of runner | Existing runner boundary; includes generation, three metric calls, provenance/environment collection, and report projection work; excludes final report publication |

Unprofiled process CPU time was 0.1875 s; the cProfile run reported 0.484375 s.
The process-time clock is coarse at these short durations. The stage values do
not sum to total runner time. The remainder includes
runner bookkeeping and provenance/environment collection; cProfile found
approximately 0.083 s cumulative in two Git subprocess calls for revision and
dirty-state metadata. Those calls are visible diagnostic overhead, but at
this workload size they do not establish a meaningful user-facing or resource
problem. cProfile timing is inclusive and nested function timings overlap.

### Function profile and allocation observations

The profiled runner took 0.55929 s versus 0.43745 s unprofiled, an observed
**27.85% cProfile overhead** for this single pair. The profile recorded
134,917 calls (134,899 primitive calls) and 0.553 s total function self time.
Treat these values as diagnostic only; the profiler noticeably changes the
runtime, and no latency threshold has been set.

The leading cProfile cumulative times were:

- `build_synthetic_workload`: 0.273 s; it includes calls below it and therefore
  overlaps its child function timings.
- `evaluate_rankings`: 0.190 s across three calls (0.063 s profiled mean per
  call). This includes candidate and seen-item validation, the per-user loop,
  metric accumulation, and macro aggregation.
- `build_validation_cohort`: 0.057 s once, including warm/cold eligibility,
  positive-pair, and seen-item accounting.
- `RatingEvent.__post_init__`: 5,440 calls / 0.042 s cumulative.
- `_git_worktree_dirty` and `_git_revision`: 0.049 s and 0.035 s cumulative;
  together they run two subprocesses for provenance reporting.
- `_hash_events`: two calls / 0.024 s cumulative; `_hash_lines`: one call /
  0.017 s cumulative.

The largest positive retained generation deltas were 524,504 bytes for the
candidate `frozenset`, 312,136 bytes for seen-item sets built by cohort
construction, and 310,000 bytes for the 5,000 synthetic item keys. These are
source-line snapshot deltas, not exclusive object sizes or peak allocation
totals. The generation traced peak was 3,669,824 bytes; evaluation snapshot
peak was 46,376 bytes; the three-call traced evaluation peak averaged 45,592
bytes. All these measurements cover Python allocations only.

The harness's true process peak RSS probe is unsupported on this Windows
runtime. A short external working-set sampling attempt produced a constant
4.14 MiB reading that could not be independently validated against the live
Python process, so it is excluded; current working set and true peak RSS remain
unavailable. No `psutil` or other dependency was added.

### Correctness, equivalence, and resource safety

The unprofiled run, cProfile run, and saved MEDIUM baseline agree exactly on
profile, seed, configuration, input/output counts, cohort audit, workload,
train, validation, recommendation, and evaluation-code hashes, schema, and
metric payload. The profiled and unprofiled runs also have the same stable
projection hash:
`8a35268a26c9f68a25130fa83c629e49ac1fcc005da0c4504748a05d2ec388c0`.
The historical baseline report has a different stable projection hash because
it records the earlier HEAD and a dirty worktree; its workload and result
fingerprints and metrics are unchanged. Candidate eligibility remains exactly
the train-known pool with train-seen items excluded. The cohort remains 200
warm eligible targets and 40 audited cold-item exclusions. The evaluator's
200-user denominator and per-user macro policy are unchanged. No target,
temporal, or test leakage path was introduced.

The run generated 5,440 records and stayed within the existing bounds: 200 of
1,000 users, 5,000 of 25,000 candidates, 64 of 500 batch rows, and a report
under 7 KB against a 1 MB limit. The two profiling reports were 6,594 and
6,660 bytes; the `.pstats` artifact was 50,586 bytes. The profiling outputs
are ignored locally. No Amazon CSV, trusted real split, model checkpoint, or
metadata was opened.

### Optimization decision

**NO OPTIMIZATION NEEDED.** The existing MEDIUM path is deterministic and
correct, remains comfortably inside its explicit synthetic bounds, and takes
under half a second for the runner in the paired unprofiled observation. No
performance budget or reproducible resource failure demonstrates a material
cost problem. The Git subprocesses and `RatingEvent` validation are possible
future optimization targets only if a later representative workload shows
they matter. The cProfile overhead itself is diagnostic instrumentation, not
a production cost. Do not optimize based only on these synthetic timings.

Recommended next milestone: project-owner review of this profile, then retain
the current evaluator unless a future, predeclared workload budget shows a
specific cost or resource blocker. If deeper resource evidence is needed, run
the same frozen MEDIUM profile in an environment that exposes trustworthy
current working set and peak RSS before proposing code changes. No optimization
was implemented in Phase 5.2A. ADR-018 remains Proposed; Phase 4.2C remains ON
HOLD. No real Electronics data was read, sampled, trained on, or evaluated.
