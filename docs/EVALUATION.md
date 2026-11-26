# EVALUATION — Recommender and agent assessment

**Status:** Planned protocol. All example thresholds or charts are hypothetical until measured.

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

Metrics must include `K`, user count, item universe, exclusions, split manifest, source and seed. Compare full-catalog ranking when feasible; explicitly label sampled candidate/negative evaluation and use the *same* candidate policy for models.

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
