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
