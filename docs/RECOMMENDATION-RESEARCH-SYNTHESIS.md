# Recommendation research synthesis and architecture readiness

**Status:** Phase 4.4C evidence synthesis. This document assesses documented
results; it does not run experiments, promote a model, authorize data use, or
close a project phase gate. Phase 4.2C remains **ON HOLD**.

## Executive summary

RecFusion has a working offline research path for deterministic ingestion,
temporal validation, collaborative baselines, TF-IDF content retrieval, and
source-scoped RRF. The strongest measured real interaction result is the
validation-selected Two-Tower checkpoint at NDCG@10 `0.015572` on one
10,000-user Electronics 5-core pilot. Its K=10 catalog coverage was only
`0.000684` (31 of 45,331 candidates), with high list concentration. BPR and
item-CF return broader lists but have lower validation ranking metrics. The
real-data RRF comparisons widened coverage without establishing a relevance
gain over popularity or Two-Tower.

The content retriever and hybrid benchmark have only synthetic evidence.
In Phase 4.4B, content-only retrieved 7 of 8 eligible cold positives at K=5;
both hybrids retrieved none by K=10 and seven by K=20. This is a property of
the fixed synthetic setup, not evidence of real-world cold-start effectiveness.

No model is promoted for serving. The recommended next research milestone is
evaluation and resource-bound hardening using synthetic fixtures, without
training another model or acquiring metadata. The real metadata-use gate stays
closed pending separate project-owner review.

## Project objective and evidence rules

RecFusion is an academic electronics recommendation-system project. Its
intended product direction combines verified catalog retrieval, collaborative
and content signals, deterministic constraints, and grounded explanations.
The implemented work to date is offline experimentation; the recommendation
serving path and production promotion controls are not complete.

This synthesis keeps the evidence types separate:

- **Real interaction evidence:** local, non-commercial academic processing of
  the bounded Electronics 5-core interaction pilot. The documented model
  results are validation-only. They do not include independent test-set
  evaluation.
- **Synthetic evidence:** invented products, users, histories, and labels used
  to test content and hybrid contracts. It establishes behavior for those
  fixtures only.
- **Implementation evidence:** unit/contract/integration tests and stable
  manifests. Passing tests establish tested invariants, not predictive quality.

For Phase 3, ratings 4–5 are positive relevance labels; ratings 1–3 are not
positive, and unobserved items are not confirmed negatives. Users without an
eligible warm unseen positive target are excluded from the real validation
metric denominator and reported separately. The synthetic content/hybrid
benchmark uses its own fixed macro-user and cold-positive denominators. Do not
rank models across these different datasets or protocols.

## Evidence inventory

| Experiment | Phase / status | Data and candidate policy | Cohort / denominator | Results and diagnostics | Evidence strength and limits |
| --- | --- | --- | --- | --- | --- |
| Popularity B0 | 3.1, implemented and evaluated | Authorized local Electronics 5-core interactions; train-known, 45,331 candidates; train-seen exclusion | Validation cohort later frozen at 1,369 users / 1,911 positive targets | K=10 Recall `.022784`, NDCG `.009878`, HitRate `.029949`, MRR `.006866`; 15 unique items / `.000331` coverage | One local pilot; ranking by positive training review-record counts. Reviews are not purchases, impressions, or conversions. No test evaluation. |
| Item-CF | 3.2A, implemented and evaluated | Same train-known pool and frozen validation cohort; train-only sparse positive co-occurrence | 1,369 users / 1,911 targets | K=10 Recall `.005990`, NDCG `.003259`, HitRate `.008035`, MRR `.002870`; 750 unique / `.016545` coverage; no fallback | One validation run; sparse users may receive short lists. Broader catalog reach than popularity/Two-Tower did not yield higher measured ranking metrics. |
| BPR matrix factorization | 3.2B.2, implemented and evaluated | Train-only implicit positives and sampled unobserved negatives; same warm train-known pool | 1,369 users / 1,911 targets; trained from 10,000 users, 81,688 train rows, 45,331 items | K=10 Recall `.011566`, NDCG `.005384`, HitRate `.013148`, MRR `.003633`; 1,312 unique / `.028943` coverage; validation selected epoch 13 | One seed and one validation-selected checkpoint; BPR NDCG was below popularity at K=5/10/20. Unobserved sampling is a training assumption, not confirmed dislike. |
| History-aware Two-Tower | 3.3B, implemented and evaluated | Train-known warm items; train-only vocabularies, histories, and candidate pool | Same 1,369 users / 1,911 targets; 7,806 of 65,842 train positive targets had empty histories | K=10 Recall `.025889`, NDCG `.015572`, HitRate `.033601`, MRR `.014899`; 31 unique / `.000684` coverage; epoch 2 selected | Highest observed validation metrics in this cohort, but severe concentration and validation checkpoint-selection optimism. Not statistically superior in new populations. |
| Two-Tower history ablation | 3.3B.1, diagnostic only | Same saved model and candidate policy; inference history removed, no retraining | Same validation setup; sampled user-vector and list diagnostics | Empty-history Recall/NDCG at K=10 `.026254` / `.015737` vs normal `.025889` / `.015572`; 15 vs 31 unique items; mean list overlap `.973`; sampled user-vector cosine `.972` | Removing history barely changed lists in this single experiment and reduced coverage. It does not establish that history is generally unhelpful. |
| Four-model controlled comparison | 3.3C, completed validation comparison | Popularity, item-CF, BPR, and saved epoch-2 Two-Tower; same warm candidate set | 1,369 users / 1,911 targets; 2,000 paired user-bootstrap resamples, seed 33033 | Recomputed K=10 values match saved reports. Two-Tower is highest; BPR vs item-CF NDCG difference `0.002126`, CI `[−0.001161, 0.005406]`. | Same validation cohort selected the neural checkpoints. Bootstrap intervals are unadjusted and do not remove selection optimism or seed variation. Test was not parsed/evaluated. |
| Four-model RRF | 3.4A implementation; 3.4B evaluated | Equal-weight popularity + item-CF + BPR + Two-Tower; RRF constant 60, depth 100; warm train-known pool | Same validation cohort; 2,000 paired resamples, seed 33033 | At K=10 Recall `.016521`, NDCG `.009649`, 106 unique / `.2338%` coverage. NDCG difference vs popularity `−.000229`, CI `[−.003338, .002843]`. | Coverage rose substantially; relevance did not improve over popularity. Validation-selected source models and one cohort constrain interpretation. |
| Two-Tower + BPR RRF | 3.4B, completed validation comparison | Equal-weight Two-Tower + BPR; RRF constant 60, depth 100; same policy | Same validation cohort | At K=10 Recall `.017981`, NDCG `.009890`, 299 unique / `.6596%` coverage. NDCG difference vs popularity `.000012`, CI `[−.003230, .003250]`; vs Two-Tower `−.005682`, CI `[−.009168, −.002327]`. | A coverage/relevance trade-off, not a demonstrated quality improvement. Intervals are unadjusted and checkpoint-selected. |
| TF-IDF content retrieval | 4.3A, implemented; synthetic tests | Synthetic product text; vocabulary/IDF fit only on eligible reference products; explicit eligible candidates | Unit/integration fixtures; no real catalog cohort | Deterministic sparse TF-IDF; product-to-product and temporal positive-history profiles; seen-item and time filtering | Implementation contracts are tested. No real metadata coverage, real-catalog ranking, or real content-model validation. |
| Synthetic cold-item benchmark | 4.3B, completed | Seed 43031; 24 warm reference items, 18 cold items, 16 synthetic users; warm-only or content-eligible policy | 70 train interactions, 27 evaluation events; warm policy 16 users / 16 targets; eligible policy 16 users / 24 targets, including 8 cold targets over 8 users | Content-only Recall `.875` under both policies; eligible cold Recall `.875` at K=5/10/20 (7/8 hits). Eight cold items have usable vocabulary; eight are unseen-vocabulary, one missing, one conflicted. | Strongly controlled toy benchmark; results are not estimates of real catalog behavior. Manifest and hashes are deterministic. |
| Hybrid integration | 4.4A, implemented and synthetically tested | Seed 44041 smoke fixture; warm and content-eligible policies; source-specific pools | Synthetic interface contracts; no relevance-quality claim | Tests source eligibility, no cold collaborative injection, original-rank preservation, seen-item exclusion, attribution, and aggregate diagnostics | The smoke test verifies integration behavior only; source lists were invented, not trained collaborative rankings. |
| Hybrid A: equal-weight content + popularity | 4.4B, completed frozen benchmark | Seed 43031; RRF constant 60, source depth 20; content weight 1, popularity weight 1 | Both policies, 16 synthetic users; 16 warm targets; content-eligible cold denominator 8 users / 8 targets | At K=10 warm Recall/NDCG/HitRate/MRR `.6250/.2231/.6250/.1067`, coverage `.9167`; content-eligible `.4688/.2102/.6250/.1496`, coverage `.7188`. Cold hits `0/0/7` at K=5/10/20. | Fixed synthetic popularity control uses distinct positive training user/item pairs. No weight selection or real model. |
| Hybrid B: content-weighted RRF | 4.4B, completed frozen benchmark | Same fixture/policies/constant/depth; content weight 2, popularity weight 1 | Same denominators as Hybrid A | At K=10 warm `.6250/.2858/.6250/.1798`, coverage `.9583`; content-eligible `.4688/.2594/.6250/.2208`, coverage `.7188`. Cold hits `0/0/7` at K=5/10/20. | Fixed weight comparison only. No tuning, significance claim, or promotion decision. |

The Phase 4.4B values above are synthetic and must not be combined with
Phase 3 validation values. Exact K=5/10/20 tables, source contributions,
coverage, concentration, overlap, and reproduction details are in
[HYBRID-BENCHMARK.md](./HYBRID-BENCHMARK.md).

## Real collaborative findings

### Two-Tower quality and concentration

The strongest observed validation NDCG@10 is Two-Tower `0.015572`, selected at
epoch 2. Validation NDCG@10 then fell to `0.009573` at epoch 3 and `0.001794`
at epoch 20 while training loss continued to decrease. This is consistent
with overfitting in this run but does not establish its cause.

The result is highly concentrated: at K=10 the 31 unique Two-Tower items cover
`0.0684%` of 45,331 candidates. The top 1/5/10 items account for
`9.88% / 49.15% / 93.02%` of recommendation placements. Normalized entropy is
`0.2293`, Gini `0.999770`, and sampled list overlap `.9035`. Popularity is
similarly concentrated: 15 items, `.0331%` coverage, normalized entropy
`.2200`, Gini `.999776`, and overlap `.9611`.

The history ablation changed the model inputs but barely changed aggregate
rankings. Empty-history inference was marginally higher in Recall/NDCG in the
reported cohort, but produced half as many unique K=10 items and had `.973`
mean list overlap with normal inference. This is weak evidence of history
sensitivity for the one selected checkpoint, not evidence that user history
has no value.

### Collaborative coverage and fusion trade-offs

At K=10, item-CF covers `1.6545%` of the candidate pool and BPR `2.8943%`,
compared with Two-Tower `0.0684%` and popularity `.0331%`. That breadth comes
with lower measured NDCG: item-CF `.003259`, BPR `.005384`, popularity `.009878`,
and Two-Tower `.015572`. Item-CF and BPR had lower sampled list overlap than
Two-Tower/popularity, indicating different coverage/concentration behavior,
not greater relevance.

On the same validation cohort, four-model RRF reached NDCG@10 `.009649` and
Two-Tower+BPR RRF `.009890`; their coverage was `.2338%` and `.6596%`. The
four-model result did not exceed popularity NDCG. Two-Tower+BPR was effectively
tied with popularity under its paired interval and below Two-Tower. RRF thus
showed a measured coverage/relevance trade-off, not a validated quality gain.

All these results use one sample/cohort and one selected neural checkpoint per
model. The saved test artifact was not parsed or independently evaluated.
Checkpoint selection and the comparison share validation evidence. The paired
bootstrap intervals are exploratory and unadjusted across many comparisons.

## Synthetic content and hybrid findings

The TF-IDF content path uses deterministic tokenization and sparse vector
operations. Vocabulary and IDF fit only on an explicit reference catalog;
candidates are transformed with those frozen statistics. User profiles use
strictly prior positive training interactions, exclude the target, and remove
all previously seen items from recommendations. Product-to-product retrieval
uses the same fitted content space. Missing, conflicted, empty, and zero-vector
content have explicit candidate behavior. The implementation is bounded and
has deterministic artifact fingerprints. These are technical guarantees
tested on synthetic data, not verified against real metadata.

Phase 4.4B preserves 16 evaluated users for both policies. At K=5,
content-only retrieved seven of eight eligible cold positives with `.875`
macro cold recall and exposed eight unique cold candidates across user lists.
Both hybrid weights had zero cold-positive hits at K=5 and K=10, then reached
seven hits and `.875` cold recall at K=20. Popularity-only never introduced a
cold candidate. This is an observed outcome of the fixed constructed source
rankings; it is not a universal hybrid property.

One hypothesis is that unweighted or weighted RRF can rank items supported by
multiple source lists above a cold item present only in content. The benchmark
does not identify that as the cause, and the synthetic popularity list is not
a learned collaborative source. It should be treated as a testable explanation
for future experiments, not a diagnosis.

The source-rank regression confirms that filtering a source-ineligible item at
original rank 2 does not compress original rank 3. Zero-weight sources do not
vote, source depths are fixed independently of final K, and the manifest is
deterministic and aggregate-only. Full concentration and source-attribution
results remain in the Phase 4.4B report.

The Phase 4.4B report records code revision `ea8c948` with a dirty worktree at
run time. The benchmark implementation and report were subsequently committed
as `443df19`; these are distinct provenance facts, not a claim that the
manifest was generated from a clean checkout of `443df19`.

## Architecture readiness matrix

| Area | Evidence status | Readiness assessment |
| --- | --- | --- |
| Canonical item identity | Implemented and synthetically tested; used in the authorized local interaction pilot | Source-scoped item identifiers and stable mappings support interaction processing. A metadata join has not been verified. |
| Data ingestion and normalization | Evaluated on authorized local interaction data | Amazon interaction adapter, duplicate auditing, pseudonymous IDs, timestamp handling, split integrity, and deterministic quality reports are implemented. Raw source data remains private/local. |
| Metadata adapter and provenance | Blocked by metadata-use decision | Synthetic-only metadata adapter/provenance contracts exist. No real metadata acquisition or join coverage was measured. |
| TF-IDF content feature representation | Implemented and synthetically tested | Reference-only vocabulary, deterministic vectors, and missing/conflict behavior are covered by fixtures. |
| Content retrieval | Implemented and synthetically tested | Product-to-product and temporal profile retrieval work in synthetic fixtures; no real catalog quality evidence. |
| Collaborative retrieval | Evaluated on authorized local interaction data | Popularity, item-CF, BPR, and Two-Tower produce validation rankings over warm train-known items. No independent test result or serving evidence. |
| Deterministic hybrid candidate integration | Implemented and synthetically tested | RRF, explicit source pools, provenance, no fallback, stable tie-breaking, and source-rank preservation are implemented. Real-source hybrid quality remains unverified. |
| Source eligibility and cold-item handling | Implemented and synthetically tested | Cold content candidates can enter only through content; collaborative pools remain train-known. The real Phase 3 evaluation excluded cold items. |
| Offline evaluation | Evaluated on authorized local interaction data; synthetic test coverage implemented | Leakage-aware validation cohorts, fixed candidate universes, macro metrics, and aggregate reports exist. Independent held-out test evaluation is absent. |
| Reproducibility and provenance | Implemented and tested for documented runs | Seeds, hashes, configs, code revisions, and aggregate manifests are recorded. Single-seed neural runs and selected local artifacts limit inference. |
| Resource bounds | Designed but not empirically verified for deployment | Algorithms have input/candidate caps and the synthetic content runner is small. Local pilot timings/resource measures are incomplete or not representative of serving. |
| Real metadata coverage | Blocked by metadata-use decision | No real product metadata was acquired or joined; coverage is unknown. Do not claim feature-release readiness. |
| Real content-model validation | Blocked by metadata-use decision | All content ranking evidence is synthetic. A real-data content comparison has not run. |
| Serving readiness | Not implemented | There is no promoted recommendation endpoint, online index lifecycle, production latency SLO evidence, or end-to-end serving authorization test. |
| Legal/governance readiness | Blocked by metadata-use decision; interaction-use scope documented, legal clearance not established | ADR-014 records a narrow owner-scoped local coursework decision. Applicable law, source terms, and institution rules remain controlling and partly unverified. Metadata stays ON HOLD under Phase 4.2C. |

Technical implementation, measured model quality, data rights, and deployment
readiness are separate questions. A positive status in one row does not imply
readiness in another.

## Risks and threats to validity

- **Pilot selection and sparsity:** the 10,000-user sample is not the full
  Electronics population. The validation cohort has 1,369 users and 1,911
  eligible targets; many positive observations concern cold items excluded by
  the warm train-known protocol.
- **Warm-only evaluation:** Phase 3 ranking metrics cover train-known items
  only. They do not measure cold-user or cold-item retrieval.
- **Snapshot metadata:** no effective-time metadata snapshots are present.
  Even future metadata joins cannot establish historical product availability
  without suitable temporal provenance.
- **Metadata join and source rights:** real metadata coverage, join rates,
  conflicts, and feature quality are unknown. Phase 4.2C remains ON HOLD.
- **Validation selection:** BPR epoch 13 and Two-Tower epoch 2 were selected
  on the same validation context used for model comparison. This creates
  selection optimism; no independent test results are available.
- **Single-seed neural experiments:** the documented runs do not establish
  seed robustness. Bootstrap intervals do not replace independent runs and are
  unadjusted for multiple comparisons.
- **Synthetic construction bias:** content/hybrid users, items, labels, and
  scenarios are deliberately engineered and small. Their results are not
  population estimates.
- **Hybrid rank trade-off:** Phase 4.4B hybrids demote eligible cold positives
  below K=10 in its fixture. Whether source overlap or RRF support effects
  explain this requires a separate predeclared experiment.
- **Unverified capacity and serving:** synthetic runner timing is not serving
  latency; local ML pilot resource measurements do not establish production
  limits. Online authorization, index lifecycle, availability, and load remain
  untested.
- **Governance scope:** the owner's narrow academic-use decision is not a
  license or legal opinion. The dataset maintainers have not provided a
  blanket license, and a favorable response to another student's thesis
  question is not permission for RecFusion. Institution-specific rules,
  applicable law, and source terms govern. No new data use is approved by this
  synthesis.

## Next milestone options

| Option | Architectural benefit | Prerequisites | Complexity | Evaluation feasibility | Research value and risks |
| --- | --- | --- | --- | --- | --- |
| 1. Synthetic semantic retrieval infrastructure | Adds a separate semantic feature path and reusable index contracts | Define synthetic text corpus, tokenizer/model boundary, bounds, and provenance | High if a new embedding model is introduced; moderate for a deterministic fixture interface | High for contract tests, low for claims about useful semantics | Useful for feature-space architecture; risks duplicating TF-IDF before real metadata is available and conflating vectors with collaborative embeddings. |
| 2. Synthetic cold-aware hybrid ranking diagnostics | Directly investigates cold-item demotion, overlap, and coverage objectives | Freeze scenarios, candidate definitions, metrics, and no-tuning protocol before runs | Moderate | High on synthetic fixtures | Directly follows 4.4B; conclusions remain construction-specific, and changing weights against the same fixture risks overfitting. |
| 3. Evaluation and performance infrastructure hardening without new model training | Improves reproducibility, resource observability, protocol checks, and confidence boundaries across existing pipelines | Use committed aggregate contracts; define representative synthetic workloads and budgets as proposals, not SLAs | Low to moderate | High for deterministic synthetic tests and bounded resource probes | Strengthens future evidence without another model; risk is mistaking synthetic throughput for real-data/serving capacity. |
| 4. Real metadata integration (Phase 4.2C) | Could enable catalog joins and real content evaluation | Separate metadata rights/use review and project-owner authorization; source provenance and acquisition safety plan | High | Not available until gate and data are cleared | Potentially high research value, but explicitly blocked. This synthesis does not authorize acquisition. |

### Recommendation

Recommend **Option 3: evaluation and performance infrastructure hardening**
as the next proposed synthetic milestone. Freeze the metric and artifact
contracts, add deterministic repeated-run and aggregate-integrity checks where
gaps remain, and characterize bounded synthetic execution costs without
calling them serving SLOs. Do not train models, tune fusion weights, read real
interaction artifacts, or acquire metadata as part of that proposal.

Option 2 is a reasonable later experiment after its scenarios and objectives
are predeclared independently of 4.4B outcomes. Option 1 is premature until
the semantic representation contract is justified. Option 4 remains blocked
under Phase 4.2C.

This document makes no model-promotion decision: popularity, item-CF, BPR,
Two-Tower, and RRF outputs are research baselines only. No model is approved
for production serving.

## References

- [PRD.md](./PRD.md) and [ARCHITECTURE.md](./ARCHITECTURE.md) — project goal,
  modular boundaries, and offline/online separation.
- [EVALUATION.md](./EVALUATION.md) and
  [MODEL-COMPARISON.md](./MODEL-COMPARISON.md) — exact real validation cohort,
  metrics, paired comparisons, concentration, and fusion results.
- [CONTENT-RETRIEVAL.md](./CONTENT-RETRIEVAL.md) and
  [CONTENT-BENCHMARK.md](./CONTENT-BENCHMARK.md) — synthetic content feature
  and cold-item contracts.
- [HYBRID-RETRIEVAL.md](./HYBRID-RETRIEVAL.md) and
  [HYBRID-BENCHMARK.md](./HYBRID-BENCHMARK.md) — source-pool contracts and
  complete Phase 4.4B aggregate results.
- [DATASETS.md](./DATASETS.md), [DATA-CONTRACTS.md](./DATA-CONTRACTS.md),
  [SECURITY.md](./SECURITY.md), and [TESTING.md](./TESTING.md) — rights,
  identity, privacy, and verification boundaries.
- [DECISIONS.md](./DECISIONS.md) and [ROADMAP.md](./ROADMAP.md) — proposed
  next-step decision and project gates.
