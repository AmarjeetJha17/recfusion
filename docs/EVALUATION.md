# EVALUATION — Recommender and agent assessment

**Status:** Frozen offline protocol with local validation-only BPR and
Two-Tower Electronics experiments and a paired four-model comparison. Results
below are validation-only, single-seed measurements, not deployment claims.

## 1. Research questions

- Does Two-Tower retrieval outperform collaborative and content baselines under the same candidate universe?
- Does hybrid retrieval improve candidate recall and cold-start coverage?
- Does re-ranking improve top-K relevance after constraints?
- Do agent explanations remain grounded and constraints intact?
- What is the latency/quality trade-off for additional retrieval sources?

## 2. Evaluation cohorts

Track warm users, sparse-history users, new/metadata-only products, category segments and no-matching-constraint queries. Only claim cold-start findings for cohorts actually supported by the test data. Use separate benchmark and temporal split protocols if both are implemented; never mix their numbers in one comparison.

## 3. Metric definitions

For eligible evaluation users/queries `U` and held-out relevant set `Rel(u)`:

- **Recall@K** = mean over eligible users of `|TopK(u) ∩ Rel(u)| / |Rel(u)|`. Define users with zero positives policy; normally exclude from recall denominator but report count.
- **HitRate@K** = mean indicator of at least one relevant item in TopK.
- **NDCG@K** = normalized discounted cumulative gain at K using an explicitly defined gain map (binary or graded). Document ties and zero-IDCG handling.
- **MRR@K** = mean reciprocal rank of first relevant item, 0 when none in TopK (for eligible users).
- **Catalog coverage** = unique recommended eligible items divided by eligible catalog item count.
- **Intra-list diversity** = mean pairwise dissimilarity with fixed item-similarity measure.
- **P50/P95 latency** measured with workload, hardware and traffic shape described.

### Phase 3.1 initial implementation

`recfusion_ml.evaluation.metrics` implements macro Recall@K, binary NDCG@K,
HitRate@K, MRR@K, and candidate coverage. Ratings of 4 or 5 are provisional
positive relevance labels; ratings of 1–3 are not positives, and unobserved
items are never treated as negatives. Repeated validation observations for a
user/item pair contribute one target pair, while repeated positive observations
remain separately counted in the cohort audit. Users without an eligible warm,
unseen positive target are excluded from the macro metric denominator and
reported in the exclusion counts. Binary NDCG uses gain 1 for a relevant item,
discount `1/log2(rank + 1)`, and an ideal denominator for
`min(K, number of eligible targets)`.

The deterministic B0 popularity baseline counts positive training review
records per train-known item, descending by count and then ascending by stable
item key. It excludes each user's train-seen items. This is review activity,
not purchases, conversions, or impressions. Evaluation uses the exact train
candidate pool with no sampled negatives. The first pilot runner validates
Step 2.4 and trusted Step 2.5 manifests and output hashes, reads train and
validation rows only, verifies the test artifact checksum without parsing test
rows, and writes aggregate-only metrics to a new ignored output directory.
Per-user recommendations and identifier-level results are not persisted.
Metadata metrics are unavailable until product metadata is joined under a
separately reviewed contract. Confidence intervals and statistical comparisons
are not implemented by this initial baseline runner.

### Phase 3.2A item-CF comparison

The item-CF comparison reuses the same Step 2.4/2.5 checksum-verified loader,
validation cohort, train-known candidate pool, seen-item policy, and metric
implementation as Phase 3.1. It fits only on train rows and compares against a
saved popularity report only when source identity, train/validation hashes,
temporal-manifest hash, K values, eligible-user count, and eligible-target
count match; it also recomputes popularity metrics and requires exact
agreement with that report. Test artifact bytes are checksum-verified but
test rows are not parsed. The report includes candidate-generation user
coverage, users with fewer than K returned items, fit caps/support counts, and
explicit zero fallback use. Sparse item-CF does not fabricate recommendations
for users with no eligible neighbors. These measurements remain validation
results and do not permit model selection on test.

### Phase 3.2B.2 real Electronics BPR validation

The local 10,000-user Amazon Electronics pilot was trained on the trusted train
split only (81,688 records, 10,000 users, 45,331 train-known items). Ratings
4–5 supplied 65,842 distinct positive user/item pairs. Each of 20 CPU epochs
sampled one permissible train-known unobserved item per positive pair; all
9,847 positive users had at least one permissible negative candidate. The
configuration used seed 42, 32-dimensional embeddings, Adam at 0.001, L2
regularization 0.0001, and batches of 1,024. Validation NDCG@10 selected epoch
13 (earliest-epoch tie rule). Ranking used the same 45,331 train-known
candidate items and train-seen-item exclusion as the saved popularity and
item-CF comparisons.

| K | BPR Recall | BPR NDCG | Popularity NDCG | Item-CF NDCG |
|---:|---:|---:|---:|---:|
| 5 | 0.006574 | 0.003724 | 0.006276 | 0.002521 |
| 10 | 0.011566 | 0.005384 | 0.009878 | 0.003259 |
| 20 | 0.017434 | 0.007025 | 0.011488 | 0.004181 |

BPR exceeded item-CF and remained below popularity at all reported K values.
These are one-run validation measurements, with no confidence intervals,
significance testing, or model-selection use of test data. The validation
cohort had 1,369 eligible warm users and 1,911 warm positive target pairs;
3,153 positive observations involved cold items and were excluded because the
candidate universe is train-known only. The cohort also contained 1,696
non-positive observations. Product metadata was not joined, so metadata
coverage and attribute-based results are unavailable.

The aggregate-only report and private checkpoint are stored locally under
ignored `data/processed/amazon-electronics-pilot-10000-bpr-v1/`. The loader
verified Step 2.4 and Step 2.5 manifests and output hashes, parsed train and
validation only, and checksum-verified the official test artifact without
parsing its rows. Checkpoint reload reproduced the selected validation
rankings exactly. The checkpoint is 18,298,757 bytes and the complete private
report directory totals 18,323,345 bytes. Training-process peak
memory and end-to-end wall time were unavailable because the original run
stopped during report assembly; the report was recovered from its checkpoint
and epoch log. The recovery process peaked at 661,909,504 bytes working set.
Epoch validation durations total 2,552 seconds, but epoch 2 alone reported
1,410 seconds during execution-session disruption, so these durations are not
reliable capacity estimates. The full aggregate report contains split counts,
UTC timestamp ranges, rating counts, provenance hashes, all metrics, and
resource details. It contains no row-level recommendations or identifiers.

### Phase 3.3B Two-Tower validation experiment

The implementation trained on the 10,000-user trusted train split and selected
an epoch using **macro NDCG@10 on validation only**, with ties resolved to the
earliest epoch. Inputs matched the recorded train and validation artifact
hashes. The 10,000 train users, 45,331 train-known items, and 81,688 train
interactions yielded 65,842 distinct rating-4-or-5 targets. Every target used
strictly earlier training observations only; equal timestamps were excluded,
the target item was masked, and item histories were deduplicated and ordered
deterministically. 7,806 targets had empty histories. Each epoch used 263,368
distinct sampled negatives, and no target was skipped. The negative assumption
does not make unobserved items confirmed dislikes.

The frozen cohort contained 1,369 warm-positive users and 1,911 eligible
targets from 6,760 validation interactions. All 45,331 train-known items were
ranked, excluding every item observed by each user in train. 3,153 positive
validation observations involved cold items and remained excluded; there were
no cold users, seen-positive observations, or duplicate positive targets in
the eligible evaluation cohort. Users and item vocabularies came from train
only. Validation labels were used only for evaluation/epoch selection. Test
rows were not parsed or evaluated. Metadata features were unavailable and not
inferred.

The one selected configuration was CPU PyTorch 2.15.0+cpu, seed 42 (dataset
selection seed `recfusion-amazon-electronics-pilot-v1` recorded separately),
32-dimensional embeddings/retrieval vectors, 64-unit hidden layer, 50-item
history cap, batch size 256, four sampled negatives, temperature 0.1, Adam
0.001, L2 0.0001, and 20 epochs. Macro NDCG@10 selected epoch 2 at 0.015572.
Training loss decreased through epoch 20 (1.529707 to 0.074736), while
validation NDCG@10 peaked at epoch 2 and then declined. This pattern is
consistent with overfitting in this single run.

| Model | K | Recall | NDCG | HitRate | MRR | Catalog coverage (unique items) |
|---|---:|---:|---:|---:|---:|---:|
| Two-Tower | 5 | 0.018767 | 0.013173 | 0.024836 | 0.013720 | 0.000353 (16) |
| Popularity | 5 | 0.012284 | 0.006276 | 0.016801 | 0.005101 | 0.000199 (9) |
| Item-CF | 5 | 0.003798 | 0.002521 | 0.005113 | 0.002520 | 0.014449 (655) |
| BPR | 5 | 0.006574 | 0.003724 | 0.007305 | 0.002849 | 0.015773 (715) |
| Two-Tower | 10 | 0.025889 | 0.015572 | 0.033601 | 0.014899 | 0.000684 (31) |
| Popularity | 10 | 0.022784 | 0.009878 | 0.029949 | 0.006866 | 0.000331 (15) |
| Item-CF | 10 | 0.005990 | 0.003259 | 0.008035 | 0.002870 | 0.016545 (750) |
| BPR | 10 | 0.011566 | 0.005384 | 0.013148 | 0.003633 | 0.028943 (1,312) |
| Two-Tower | 20 | 0.029585 | 0.016651 | 0.040906 | 0.015359 | 0.001324 (60) |
| Popularity | 20 | 0.028689 | 0.011488 | 0.037253 | 0.007414 | 0.000551 (25) |
| Item-CF | 20 | 0.009301 | 0.004181 | 0.012418 | 0.003162 | 0.018111 (821) |
| BPR | 20 | 0.017434 | 0.007025 | 0.022644 | 0.004239 | 0.053760 (2,437) |

Two-Tower's metrics were higher than the three saved baselines on this
validation cohort, but it concentrated recommendations on only 31 unique
items at K=10 and 60 at K=20. That low catalog coverage is a material failure
mode and prevents interpreting ranking metrics alone as a useful retrieval
result. Results have no confidence intervals or significance test and do not
establish generalization. The model is ID-only and cannot retrieve cold items.

The 3.3B resource preflight measured one train epoch at 8.745 s and one full
catalog validation pass at 29.560 s. The experiment recorded 813.209 s for
data setup, 20 epochs, and per-epoch validation; reloaded-checkpoint inference
over the full cohort took 26.981 s. Peak working set was 780,886,016 bytes,
and the best weights-only checkpoint was 18,212,678 bytes. These are local
observations, not capacity guarantees. The aggregate-only report and private
checkpoint live in ignored
`data/processed/amazon-electronics-pilot-10000-twotower-v1/`; no per-user
rankings or identifier mappings were published.

The existing owner-scoped research-use decision remains local,
non-commercial coursework only; legal clearance is not established. This
experiment did not alter that decision.

Metrics must include `K`, user count, item universe, exclusions, split manifest, source and seed. Compare full-catalog ranking when feasible; explicitly label sampled candidate/negative evaluation and use the *same* candidate policy for models.

### Phase 3.3B.1 Two-Tower diagnostics

Diagnostics used the saved epoch-2 checkpoint (`a9521c9035660a5f1d8c796595c7a796b9f8c85c74ea586fd181514ddf99a46f`) and verified it against the train/validation fingerprints and preprocessing/temporal manifests. The frozen cohort and exact train-known candidate policy were unchanged: 1,369 evaluated users, 1,911 eligible targets, 45,331 candidates, and train-seen exclusion. No model was retrained and test rows were not parsed or evaluated. Deterministic representation and overlap samples use seed 33031.

Two-Tower and popularity were recomputed on the same users, candidate set, and seen-item exclusions. Coverage and concentration include all 45,331 candidates, including zero-frequency items. Entropy is Shannon entropy divided by `log(candidate_count)`; Gini is computed over the full frequency vector. Sampled pairwise list overlap is intersection size divided by the shorter list length, using 128 SHA-256-selected users (8,128 pairs).

| K | Two-Tower unique / coverage | Popularity unique / coverage | Normalized entropy (TT / pop) | Gini (TT / pop) | Mean pairwise overlap (TT / pop) |
|---:|---:|---:|---:|---:|---:|
| 5 | 16 / 0.000353 | 9 / 0.000199 | 0.1680 / 0.1573 | 0.999882 / 0.999887 | 0.857 / 0.948 |
| 10 | 31 / 0.000684 | 15 / 0.000331 | 0.2293 / 0.2200 | 0.999770 / 0.999776 | 0.900 / 0.961 |
| 20 | 60 / 0.001324 | 25 / 0.000551 | 0.2937 / 0.2830 | 0.999542 / 0.999554 | 0.903 / 0.970 |

At K=10 the top 1/5/10 items account for 9.88%/49.15%/93.02% of Two-Tower recommendation placements; popularity's shares are 9.91%/49.41%/98.24%. Exact ordered K=10 lists were not identical across models. Their mean per-user overlap was 0.791; their unique-item sets shared 11 items (Jaccard 0.314). Two-Tower K=10 recommendation frequency had Pearson correlation 0.593 with train positive-review counts across the candidate pool. Top items reached 98.76% of evaluated users in Two-Tower and 99.05% in popularity. These results show somewhat greater coverage and list variation than popularity, alongside strong concentration in both systems.

The inference-only empty-history ablation kept model weights, candidates, and seen-item filtering fixed. At K=10, normal-history versus empty-history Recall/NDCG/coverage were 0.025889/0.015572/31 unique items versus 0.026254/0.015737/15 items. Mean normal-versus-empty K=10 list overlap was 0.973. Across 256 deterministic sampled users, user-vector cosine between normal and empty-history inference averaged 0.972; mean vector coordinate absolute difference was 0.0172. History changes the vectors but had limited effect on these rankings. The ablation is not a separately trained baseline and was not used to select a checkpoint.

Representation statistics were computed for 256 users and 1,024 items selected by seeded SHA-256 ordering; identifiers and vectors were not written. Mean pairwise cosine was 0.812 for normal-history users (median 0.864, p95 0.976), 0.911 for empty-history users (median 0.931, p95 0.985), and 0.250 for items (median 0.501, p95 0.943). Sampled scores over 262,093 permitted user/item pairs had mean -0.0268, variance 0.00211, median -0.0308, p05 -0.0865, and p95 0.0431. Near-equal adjacent sorted scores within 1e-6 occurred in 1.17% of comparisons; exact ties were 0.0034%. These summaries alone do not establish representation collapse.

The saved 20-epoch logs show training loss decreasing from 1.529707 to 0.074736. Validation NDCG@10 was 0.005708, 0.015572, and 0.009573 at epochs 1, 2, and 3; it was 0.001794 at epoch 20. Epoch 2 remains the best saved validation epoch. Per-epoch catalog coverage was not recorded. This supports an overfitting hypothesis for this run, but does not identify its cause. No ranking correctness defect was found: cached multi-user output matched single-user output on a deterministic sample, candidate indexing and user-specific vectors were preserved, and the evaluator validated train-seen exclusions. The cache is per-call rather than global. Training history audits covered all 65,842 positive targets; a separate deterministic sample of 256 targets passed negative-item/seen-item exclusion checks. The aggregate diagnostic artifact is ignored under `data/processed/amazon-electronics-pilot-10000-twotower-diagnostics-v1/` and contains no identifiers, embeddings, or row-level recommendations.

### Phase 3.3C four-model controlled comparison

Popularity, item-CF, BPR, and the saved epoch-2 Two-Tower checkpoint were
reproduced on the same 1,369-user, 1,911-target warm validation cohort and
45,331 train-known candidates. Recomputed metrics at K=5/10/20 matched the
saved reports exactly. The comparison parsed only trusted train and validation
artifacts; the test artifact was checksum-verified through its manifest and
its rows were not read.

Paired per-user Recall, NDCG, HitRate, and MRR differences use 2,000 seeded
user-bootstrap percentile resamples. At K=10 Two-Tower has the highest
observed macro metrics; it covers only 31 unique items (0.068% of candidates)
and has 0.904 mean pairwise overlap in a deterministic 128-user list sample.
Popularity covers 15 items with 0.961 overlap. Item-CF and BPR cover 750 and
1,312 items, with lower sampled overlap (0.016 and 0.071), and much lower
ranking metrics. The BPR versus item-CF NDCG@10 interval includes zero.

These intervals are unadjusted and conditional on checkpoints selected using
the same validation cohort; they do not remove selection optimism or seed
variation. Results justify a **conditional** next validation-only experiment
with deterministic rank fusion to test whether broader coverage and stronger
ranking can be combined. They do not justify model promotion. See
[MODEL-COMPARISON.md](./MODEL-COMPARISON.md) for paired results, uncertainty,
concentration statistics, limitations, and the private ignored aggregate
report location.

The aggregate report is `data/processed/amazon-electronics-pilot-10000-twotower-diagnostics-v1/diagnostics-v3.json`. The next minimal experiment should change one training factor at a time while fixing the data, seed, candidate policy, and evaluation cohort; retain per-epoch catalog coverage and compare against the same popularity control. Those diagnostics alone did not provide a four-model comparison or deployment recommendation; Phase 3.3C is documented below.

## 4. Core experiments

| Experiment | Control | Treatment | Output |
|---|---|---|---|
| E01 | Popularity | Content baseline | Warm/cold Recall@K/NDCG@K |
| E02 | Collaborative baseline | Two-Tower | Ranking vs model size/latency |
| E03 | Two-Tower alone | Two-Tower + semantic fusion | Candidate recall, coverage, quality |
| E04 | Deterministic fusion | LambdaRank (if label-valid) | NDCG, robustness, feature importance |
| E05 | No metadata | Metadata-enhanced item tower | Cold-start metrics |
| E06 | Single retrieval source | Multiple sources | Ablation + operational costs |
| E07 | Fixed preferences | Conversationally extracted preferences | Human-reviewed constraint capture/grounding; **not CTR claims** |

Use multiple seeds and bootstrap confidence intervals across evaluation users/queries where meaningful. Adjust for multiple hypotheses where necessary. Include negative findings.

## 5. Leakage prevention

- The Step 2.5 temporal layer supports either trusted pre-split inputs, whose membership it verifies and preserves, or explicitly unpartitioned interactions assigned by UTC cutoffs. An input carrying split membership is rejected by cutoff mode.
- Cutoffs use train `< t1`, validation `[t1, t2)`, and test `>= t2`; equal timestamps are assigned together. Pre-split temporal contradictions and chronological overlaps block evaluation without repairing the records.
- User/item vocabularies and the candidate pool use train interactions only. Unknown held-out IDs map to reserved index 0; cold-start rows stay in the evaluation audit. The candidate pool is the set of train-observed items, not a set of confirmed negatives or proof of historical availability.
- Exact cross-split duplicates and conflicting source-event fingerprints are retained for audit but block metric eligibility. Warm-only metric candidates require a provisional positive rating and both IDs in train; report all neutral, low-rating, cold-start, duplicate, and integrity exclusions separately.
- Catalog snapshots without effective timestamps cannot establish which items were available at each prediction time. Temporal eligibility does not solve catalog-availability bias.
- Never build training user history using held-out events.
- Normalize features / build vocab on train only; document item metadata time validity.
- Step 2.6 builds user/item histories from eligible training events strictly
  before each event timestamp. Equal-timestamp events do not contribute to one
  another, and validation/test histories use training events only. Held-out
  labels do not update a later held-out event's features.
- Step 2.6's product-feature sidecar is explicitly snapshot-only because the
  normalized metadata has no effective timestamp. It is not point-in-time
  evidence of product availability and must be treated as a separately labeled
  snapshot-metadata experiment, not silently included in strict temporal
  results. Prices and rating aggregates are excluded.
- Keep interactions from train/validation/test in their designated windows; never silently move or delete an official-split record.
- Candidate pools must not embed future popularity or test-positive lists.
- Pretrained text models may use external data; document their source and do not equate them with test interaction leakage.
- Avoid choosing final hyperparameters based on test performance; test only after validation-based selection.

## 6. Agent evaluation suite

A manually reviewed set of at least 50 diverse example intents is a **proposed initial scope**; scale after failure analysis. Include cases such as hard budgets, conflicting requirements, missing catalog fields, adversarial product reviews, ambiguous usage, empty results and repeated feedback.

| Metric | Method |
|---|---|
| Structured intent accuracy | per-field exact match / F1 against reviewed annotations |
| Hard-constraint violation | automated deterministic check over returned items |
| Tool-call correctness | compare sequence/arguments with expected legal tool graph |
| Unsupported claim rate | check assertions against catalog evidence and provenance |
| Conversation consistency | state regression tests after preference updates |
| Cost + latency | tokens, provider cost, time to first token, end-to-end |

Report both automated and sampled human-review outcomes. LLM-as-judge can assist triage but must not be the sole source of grounding truth.

## 7. Performance benchmark procedure

Define test hardware, catalog/index sizes, concurrency, warm/cold cache state, number of queries, timeout and percentile method. Measure each stage separately: user context, retrieval, DB lookup, hard filtering, reranking, explanation. Do not blend LLM latency into ranking latency.

## 8. Required experiment report

```text
Experiment ID:
Research question / hypothesis:
Dataset version + provenance:
Split manifest / cutoff:
Feature schema + candidate policy:
Baselines and model configs:
Seeds, environment, commit:
Metrics with uncertainty:
Slice/cold-start results:
Latency and resource use:
Ablation, negative findings and limitations:
Reproduction command and artifact paths:
Deployment recommendation / no-go:
```

## 9. Gates for v1

Before claiming evaluation-driven quality, publish at least B0/B1/B2 comparisons, a neural candidate model, a hybrid ablation, and data leakage tests. Report measured results as measured, targets as targets, and missing measurements as unknown. No fabricated improvement percentages.

## Phase 3.4A deterministic fusion contract

Phase 3.4A adds a synthetic-tested RRF utility; it does not change cohort
construction, relevance labels, denominators, metrics, candidate eligibility,
or test-set policy. Fuse each source's ranked list using
`weight / (60 + one_based_source_rank)` and sum contributions. Source depth is
independent of final K; the proposed Phase 3.4B depth is 100, frozen before
validation inspection. Ties use canonical item ID order. Duplicate IDs within
a source list are invalid. Filtering preserves original ranks.

Supply the exact train-known candidate pool and each user's training-seen set.
Filter out-of-pool and seen items; never add items from validation targets or
the test split. A missing/empty model list contributes nothing. There is no
automatic fallback, including popularity; report an empty or short list as it
is. Record per-source raw counts, eligible counts, depth truncation, exclusion
counts, contributions, provenance, and Jaccard overlap over candidates
remaining after depth, train-known-pool, and seen-item filters. Eligible
source-union coverage is diagnostic only. Ranking metrics and catalog coverage
must use the actual final top-K lists over the unchanged evaluator cohort and
candidate pool. Also report short-list counts, item-frequency buckets, top-item
placement shares, per-source attribution, and mean source disagreement
(`1 - Jaccard`) as aggregates.

The proposed Phase 3.4B configurations are equal-weight RRF across all four
existing ranked models and a Two-Tower+BPR ablation, both with rank constant
60 and source depth 100. No validation-based weight search is planned. No real
fusion experiment has been run as part of Phase 3.4A. Fusion cannot create
cold-item candidates, calibrate raw model scores, or remove checkpoint
selection optimism; the reserved test split remains untouched until a single
validation-selected protocol is frozen.
