# Phase 3.3C — Controlled validation comparison

**Status:** Completed as an exploratory, validation-only comparison. No model
was retrained, no test rows were parsed, and no model is promoted for serving.

## Protocol and provenance

The comparison reproduced the saved Popularity, item-CF, BPR, and history-aware
Two-Tower recommendations against the same checksum-verified Step 2.5 data.
The dataset is the Amazon Reviews 2023 Electronics 5-core timestamp benchmark;
source references and research-use limits are recorded in [DATASETS.md](./DATASETS.md).
It used 1,369 warm users with 1,911 distinct eligible positive validation
user/item targets and the full 45,331-item train-known candidate pool. Ratings
4–5 were relevant; all train-seen items were excluded. Test artifact hashes
were checked through trusted manifests; test rows were not read. User and item
vocabularies, baseline fits, BPR, and Two-Tower parameters came from training
data only. Checkpoints selected at BPR epoch 13 and Two-Tower epoch 2 were
selected using this validation cohort.

Before analysis, source reports, train/validation checksums, split manifest,
candidate policy, and selected checkpoint checksums were checked. Each
model's recomputed macro metrics and recommendation counts matched its saved
report exactly. Recommendation lists and per-user metric records were held in
memory only and are not in the report.

The comparison uses binary per-user Recall, NDCG, HitRate, and MRR at K=5, 10,
and 20. Pairwise differences are model A minus model B on the same users. The
95% intervals are percentile intervals from 2,000 paired user bootstrap
resamples (seed 33033; linear percentile interpolation). The win/loss/tie
counts compare unrounded per-user values. These are unadjusted exploratory
intervals across many model/metric/K comparisons. They do not account for
checkpoint selection on validation, seed variation, or model-selection
optimism; they are not confirmatory significance tests.

## Aggregate results

Macro ranking metrics at K=10:

| Model | Recall@10 | NDCG@10 | HitRate@10 | MRR@10 |
|---|---:|---:|---:|---:|
| Popularity | 0.022784 | 0.009878 | 0.029949 | 0.006866 |
| Item-CF | 0.005990 | 0.003259 | 0.008035 | 0.002870 |
| BPR | 0.011566 | 0.005384 | 0.013148 | 0.003633 |
| Two-Tower | 0.025889 | 0.015572 | 0.033601 | 0.014899 |

Paired NDCG@10 differences:

| Comparison (A − B) | Mean difference | Paired bootstrap 95% CI | A wins / losses / ties |
|---|---:|---:|---:|
| Popularity − Two-Tower | −0.005694 | [−0.008101, −0.003474] | 0.1% / 3.0% / 96.9% |
| Item-CF − Popularity | −0.006619 | [−0.010151, −0.003127] | 0.4% / 2.8% / 96.7% |
| BPR − Popularity | −0.004494 | [−0.007845, −0.001347] | 0.7% / 2.6% / 96.6% |
| Item-CF − Two-Tower | −0.012313 | [−0.017578, −0.007391] | 0.4% / 3.4% / 96.2% |
| BPR − Two-Tower | −0.010188 | [−0.014750, −0.006042] | 0.6% / 3.2% / 96.2% |
| BPR − Item-CF | 0.002126 | [−0.001161, 0.005406] | 1.2% / 0.6% / 98.2% |

At K=10, Two-Tower has the highest observed ranking metrics, while the paired
intervals do not make its validation-selected checkpoint an unbiased estimate
of future performance. BPR and item-CF rank below popularity on this cohort;
the BPR versus item-CF NDCG interval includes zero. Nearly all user-level
comparisons tie because the eligible targets and successful recommendations
are sparse.

## Catalog concentration and personalization

The next table counts recommendations over the complete candidate pool.
Gini and normalized entropy use all 45,331 candidates, including items with
zero recommendations. Mean list overlap is intersection size divided by the
shorter list size across all 8,128 pairs in a deterministic 128-user sample
(seed 33033); no sampled user identifiers are retained.

| Model | Unique items at 10 | Catalog coverage | Normalized entropy | Gini | Mean sampled list overlap |
|---|---:|---:|---:|---:|---:|
| Popularity | 15 | 0.000331 | 0.2200 | 0.999776 | 0.9611 |
| Item-CF | 750 | 0.016545 | 0.5624 | 0.992288 | 0.0160 |
| BPR | 1,312 | 0.028943 | 0.5477 | 0.992817 | 0.0709 |
| Two-Tower | 31 | 0.000684 | 0.2293 | 0.999770 | 0.9035 |

Two-Tower combines the strongest measured K=10 ranking metrics with catalog
concentration close to popularity: 31 unique items and 0.068% coverage. BPR
and item-CF return broader, less overlapping lists, though with substantially
lower ranking metrics; item-CF also returns fewer than ten items for many
users. These are different operating trade-offs, not proof that any model is
best for an application.

## Recommendation and limits

**Conditional GO** for a later, bounded deterministic hybrid/fusion research
step on validation. The complementary coverage and ranking behavior gives a
testable reason to try rank-based fusion, while the current results do not
establish that a hybrid will improve quality. Keep the rule simple, preserve
source provenance and seen-item exclusions, and compare against the same
baselines and users. Do not promote or deploy any model based on this step.

Before making a final quality claim, freeze model selection and the candidate
policy on validation, then evaluate the selected protocol once on the reserved
test split. Additional seeds and multiplicity-aware analysis are needed for
stronger comparative claims. This warm-item, review-rating experiment has no
product metadata, impression data, cold-start coverage, or evidence of
commercial performance. Amazon source use remains limited to the documented
local non-commercial academic assessment; applicable terms and law govern.

## Reproduction

From the repository root, run:

```powershell
uv run python -m recfusion_ml.evaluation.model_comparison `
  --output-dir data/processed/amazon-electronics-pilot-10000-comparison-reproduction-v1
```

Each invocation requires a new, not-yet-existing output directory; the runner
refuses to overwrite a previous report.

The aggregate-only result is local and ignored by Git at
`data/processed/amazon-electronics-pilot-10000-comparison-v1/four-model-comparison.json`.
It records source report/checkpoint hashes, cohort, protocol, bootstrap
settings, per-K aggregate metrics, concentration, overlap, and paired
uncertainty. It contains no row-level output, source identifier, or raw review.

## Phase 3.4B deterministic fusion experiment

The predeclared experiment completed on the unchanged validation-only cohort:
1,369 evaluable users, 1,911 eligible targets, and 45,331 train-known items.
The four standalone recommendation lists were recomputed and matched their
saved reports. The source CSVs were checked by recorded size only; their
contents were not opened. Train and validation artifacts were verified and
used; the test artifact was checksum-verified without parsing or evaluation.
No models were trained, no weights were tuned, and no per-user rankings were
persisted.

Both configurations use RRF rank constant 60, source depth 100, and equal
source weights. Config A combines popularity, item-CF, BPR, and Two-Tower;
Config B combines Two-Tower and BPR. The evaluator, relevance definition,
cohort, candidate pool, train-seen exclusions, metrics, and 2,000 paired user
bootstrap resamples (seed 33033) are unchanged. Missing source outputs receive
no fallback.

Macro metrics and catalog coverage at K=10:

| Ranking source | Recall@10 | NDCG@10 | Unique items | Catalog coverage |
|---|---:|---:|---:|---:|
| Popularity | 0.022784 | 0.009878 | 15 | 0.0331% |
| Item-CF | 0.005990 | 0.003259 | 750 | 1.6545% |
| BPR | 0.011566 | 0.005384 | 1,312 | 2.8943% |
| Two-Tower | 0.025889 | 0.015572 | 31 | 0.0684% |
| Equal four-model RRF | 0.016521 | 0.009649 | 106 | 0.2338% |
| Two-Tower + BPR RRF | 0.017981 | 0.009890 | 299 | 0.6596% |

Paired NDCG@10 differences (fusion minus baseline):

| Comparison | Mean difference | Paired bootstrap 95% CI | Wins / losses / ties |
|---|---:|---:|---:|
| Equal four-model RRF − Popularity | −0.000229 | [−0.003338, 0.002843] | 19 / 29 / 1,321 |
| Equal four-model RRF − Two-Tower | −0.005923 | [−0.009267, −0.002944] | 11 / 37 / 1,321 |
| Two-Tower + BPR RRF − Popularity | 0.000012 | [−0.003230, 0.003250] | 21 / 30 / 1,318 |
| Two-Tower + BPR RRF − Two-Tower | −0.005682 | [−0.009168, −0.002327] | 14 / 36 / 1,319 |

The measured result is a coverage/quality trade-off, not a demonstrated
quality improvement. At K=10 the equal four-model configuration did not
improve NDCG over popularity; the Two-Tower+BPR result was effectively tied
with popularity under the paired interval and below Two-Tower. Both fusions
covered more distinct train-known items than popularity or Two-Tower. Most
paired users tied, reflecting sparse eligible targets and overlapping lists.
These are exploratory validation results conditional on BPR epoch 13 and
Two-Tower epoch 2, both selected using this cohort. The intervals are
unadjusted for the many comparisons and do not remove selection optimism.

The aggregate-only report is local and ignored by Git at
`data/processed/amazon-electronics-pilot-10000-fusion-v1/fusion-report.json`.
It contains all K=5/10/20 metrics, relative/absolute metric differences,
paired comparisons, candidate-union and final-list diagnostics, source
attribution and overlap, manifests and checkpoint hashes, and runtime/memory
measurements. It contains no user IDs, item IDs, reviews, or row-level
rankings. The report SHA-256 is
`4a5c8d2b374687a837a2331eb6cedbeb26edc1c1a5f56d1446bea6348c5c550c` (88,836
bytes). The run took 1,475.35 seconds (24m 35s) and peaked at 2,049,433,600
bytes process working set. Evaluation and bootstrap accounted for 1,239.70
seconds; no capacity guarantee is inferred from this one run.

This experiment does not establish cold-item coverage, metadata quality, or
commercial utility. The source-use decision remains the documented narrow,
local non-commercial academic assessment, not blanket legal clearance;
applicable terms and law still govern. The test split remains reserved.

Reproduce with the same ignored inputs and a fresh output directory:

```powershell
uv run python -m recfusion_ml.evaluation.fusion_pilot `
  --output-dir data/processed/amazon-electronics-pilot-10000-fusion-reproduction-v1
```
