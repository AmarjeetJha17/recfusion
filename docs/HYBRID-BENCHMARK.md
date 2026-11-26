# Phase 4.4B frozen synthetic hybrid benchmark

**Status:** Complete, synthetic-only comparison of the Phase 4.4A retrieval
interface. This experiment does not use real Amazon data, product metadata,
or model checkpoints. It is not evidence of real-world quality or deployment
readiness. **Phase 4.2C remains ON HOLD.**

## Research objective and scope

Compare the existing TF-IDF profile ranking and train-only synthetic popularity
ranking alone and in fixed weighted Reciprocal Rank Fusion (RRF). The benchmark
reuses the Phase 4.3B generator and its seed `43031`, 24 warm reference/train
items, 18 synthetic cold items, 16 evaluation users, and 70 training
interactions. The versioned source manifest reports 27 evaluation events. All
records and labels are invented. There are 8 cold items with usable content;
8 unseen-vocabulary items, one missing-metadata item, and one conflicted item
are ineligible.

The only methods are content-only, popularity-only, Hybrid A, and Hybrid B.
The source depths and RRF rank constant are fixed before evaluation; no tuning,
retraining, learned reranking, or fallback is performed. Standalone controls
use a single active source through RRF, which preserves that source's order.

| Method | TF-IDF weight | Popularity weight | Rank constant | Each source depth | Reported K |
| --- | ---: | ---: | ---: | ---: | --- |
| Content-only | 1.0 | 0.0 | 60 | 20 | 5, 10, 20 |
| Popularity-only | 0.0 | 1.0 | 60 | 20 | 5, 10, 20 |
| Hybrid A | 1.0 | 1.0 | 60 | 20 | 5, 10, 20 |
| Hybrid B | 2.0 | 1.0 | 60 | 20 | 5, 10, 20 |

Popularity counts distinct positive (`rating >= 4`) training user/item pairs,
then orders by descending count and canonical item key. Per-user seen items are
filtered. Validation labels do not affect popularity or content ranking.
Content vocabulary and IDF are fit on the frozen warm reference catalog only;
profiles use strictly prior positive training events. The existing binary
relevance, macro-user metric, and eligible-cold recall conventions are retained
from [CONTENT-BENCHMARK.md](./CONTENT-BENCHMARK.md).

The two hybrid candidate policies preserve one candidate universe across all
four methods:

| Policy | Eligible candidates | Evaluated users | Warm targets | Eligible cold targets/users |
| --- | ---: | ---: | ---: | ---: |
| `warm_hybrid` | 24 warm | 16 | 16 | 0 / 0 |
| `content_eligible_hybrid` | 24 warm + 8 cold = 32 | 16 | 16 | 8 / 8 |

All users remain in the macro denominator, including two users with no usable
content history. Seen items are excluded. Collaborative-source candidate pools
contain only train-known items; cold items can enter through content only.
Missing, conflicted, and zero-vector products do not become candidates.

## Ranking results

Recall, NDCG, HitRate, and MRR are macro means over all 16 users. Catalog
coverage is unique final items divided by the policy candidate count before
user-specific seen filtering. List length and short-list counts include every
user. `Unique` is the number of distinct final recommendations pooled across
users at that K. Values are rounded to four decimals; calculations use full
precision.

### Warm-only candidate policy

| Method | K | Recall | NDCG | HitRate | MRR | Catalog coverage | Unique | Mean list length | Short lists |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Content-only | 5 | .8750 | .7366 | .8750 | .6875 | 1.0000 | 24 | 4.38 | 2 |
| Content-only | 10 | .8750 | .7366 | .8750 | .6875 | 1.0000 | 24 | 8.75 | 2 |
| Content-only | 20 | .8750 | .7366 | .8750 | .6875 | 1.0000 | 24 | 17.50 | 2 |
| Popularity-only | 5 | .0000 | .0000 | .0000 | .0000 | .2917 | 7 | 5.00 | 0 |
| Popularity-only | 10 | .0000 | .0000 | .0000 | .0000 | .5417 | 13 | 10.00 | 0 |
| Popularity-only | 20 | .7500 | .1807 | .7500 | .0450 | .9583 | 23 | 20.00 | 0 |
| Hybrid A | 5 | .1875 | .0823 | .1875 | .0490 | .6667 | 16 | 5.00 | 0 |
| Hybrid A | 10 | .6250 | .2231 | .6250 | .1067 | .9167 | 22 | 10.00 | 0 |
| Hybrid A | 20 | 1.0000 | .3102 | 1.0000 | .1266 | 1.0000 | 24 | 20.00 | 0 |
| Hybrid B | 5 | .4375 | .2205 | .4375 | .1500 | .8750 | 21 | 5.00 | 0 |
| Hybrid B | 10 | .6250 | .2858 | .6250 | .1798 | .9583 | 23 | 10.00 | 0 |
| Hybrid B | 20 | 1.0000 | .3729 | 1.0000 | .1997 | 1.0000 | 24 | 20.00 | 0 |

### Content-eligible candidate policy

| Method | K | Recall | NDCG | HitRate | MRR | Catalog coverage | Unique | Mean list length | Short lists |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Content-only | 5 | .8750 | .6739 | .8750 | .6250 | .9063 | 29 | 4.38 | 2 |
| Content-only | 10 | .8750 | .6739 | .8750 | .6250 | 1.0000 | 32 | 8.75 | 2 |
| Content-only | 20 | .8750 | .6739 | .8750 | .6250 | 1.0000 | 32 | 17.50 | 2 |
| Popularity-only | 5 | .0000 | .0000 | .0000 | .0000 | .2188 | 7 | 5.00 | 0 |
| Popularity-only | 10 | .0000 | .0000 | .0000 | .0000 | .4063 | 13 | 10.00 | 0 |
| Popularity-only | 20 | .5625 | .1459 | .7500 | .0450 | .7188 | 23 | 20.00 | 0 |
| Hybrid A | 5 | .2500 | .1295 | .3125 | .1031 | .5625 | 18 | 5.00 | 0 |
| Hybrid A | 10 | .4688 | .2102 | .6250 | .1496 | .7188 | 23 | 10.00 | 0 |
| Hybrid A | 20 | .9688 | .3530 | 1.0000 | .1742 | 1.0000 | 32 | 20.00 | 0 |
| Hybrid B | 5 | .4688 | .2594 | .6250 | .2208 | .7188 | 23 | 5.00 | 0 |
| Hybrid B | 10 | .4688 | .2594 | .6250 | .2208 | .7188 | 23 | 10.00 | 0 |
| Hybrid B | 20 | .9688 | .4037 | 1.0000 | .2462 | 1.0000 | 32 | 20.00 | 0 |

These results show a trade-off within this constructed scenario. Content-only
has higher warm/content-eligible recall at K=5 than either hybrid. Hybrid B
has higher NDCG than Hybrid A at each reported K, and both hybrids recover
more eligible positives by K=20 than popularity alone. No significance test or
claim of general superiority is appropriate for this small engineered fixture.

## Cold items, attribution, and robustness

The cold-recall denominator is the existing macro over users with at least one
eligible cold positive: 8 users and 8 positive targets. Three additional
positive cold user/item targets are ineligible (one missing-metadata, one
conflicted-metadata, one unseen-vocabulary item). They remain outside the
candidate pool. The 8 eligible cold candidates are not the same thing as
recommendation exposure:

| Method | Cold Recall @5 | @10 | @20 | Cold-positive hits @5/@10/@20 | Unique cold candidates exposed @5/@10/@20 |
| --- | ---: | ---: | ---: | --- | --- |
| Content-only | .8750 | .8750 | .8750 | 7 / 7 / 7 | 8 / 8 / 8 |
| Popularity-only | .0000 | .0000 | .0000 | 0 / 0 / 0 | 0 / 0 / 0 |
| Hybrid A | .0000 | .0000 | .8750 | 0 / 0 / 7 | 0 / 0 / 8 |
| Hybrid B | .0000 | .0000 | .8750 | 0 / 0 / 7 | 0 / 0 / 8 |

At K=20, content-only and both hybrids include all 8 eligible cold items across
the user lists; 7 of those correspond to eligible positives. The hybrids rank
these cold positives below K=10 in this fixture. Popularity has zero cold
source-eligible items at either policy, and cannot introduce a cold item.

Mean per-user Jaccard overlap between the content and popularity source lists
is `0.7775` for warm-only and `0.4231` for content-eligible. These source lists
are held fixed across the four configurations, so the overlap does not vary by
weight. Mean per-user top-10 recommendation-list Jaccard uses all 16 users,
including empty lists:

| Policy | Hybrid A vs content | Hybrid A vs popularity | Hybrid B vs content | Hybrid B vs popularity | Hybrid A vs B |
| --- | ---: | ---: | ---: | ---: | ---: |
| Warm-only | .4837 | .6858 | .6092 | .5639 | .8144 |
| Content-eligible | .3298 | .5996 | .3666 | .5433 | .9091 |

The mean per-user eligible source-union sizes are:

| Policy | Content-only | Popularity-only | Hybrid A | Hybrid B |
| --- | ---: | ---: | ---: | ---: |
| Warm-only | 17.50 | 20.00 | 21.06 | 21.06 |
| Content-eligible | 17.50 | 20.00 | 26.13 | 26.13 |

These are source-list unions after source-specific eligibility and seen-item
filtering, averaged over users; they are not final-list catalog coverage. At
K=5, pooled recommendation HHI is `0.0478` for warm content-only,
`0.1572` for warm popularity-only, and `0.0697` for warm Hybrid B. Under the
content-eligible policy it is `0.0392`, `0.1572`, and `0.0597`, respectively.
HHI is a descriptive exposure concentration statistic over this small catalog.

The manifest records each method's source contribution sums for K=5/10/20.
For example, at warm K=10 Hybrid A contributes `2.4022` popularity and
`2.0827` TF-IDF RRF score mass; Hybrid B contributes `2.3608` and `4.2239`.
These sums overlap when both sources rank an item and are not relevance shares.
At K=20, the summed source contributions are:

| Policy | Method | Popularity | TF-IDF content |
| --- | --- | ---: | ---: |
| Warm-only | Content-only | 0.0000 | 3.9985 |
| Warm-only | Popularity-only | 4.5697 | 0.0000 |
| Warm-only | Hybrid A | 4.4072 | 3.9302 |
| Warm-only | Hybrid B | 4.3319 | 7.9970 |
| Content-eligible | Content-only | 0.0000 | 3.9985 |
| Content-eligible | Popularity-only | 4.5697 | 0.0000 |
| Content-eligible | Hybrid A | 3.7707 | 3.4952 |
| Content-eligible | Hybrid B | 3.1892 | 7.9970 |

The full source contributions at each K and source-union summaries are in the
ignored local manifest.

The predefined synthetic mechanisms were all present: strong warm-content
targets (16), content-bearing cold positives (8), unseen-vocabulary cold items
(8), one missing and one conflicted cold item, two empty histories, and
popularity source lists shorter than depth 20 for zero users. Source overlap
and disagreement are measured by source-list Jaccard; held-out labels did not
choose or tune a scenario. These mechanisms are not representative user
segments.

## Reproduction and artifacts

Runner: `recfusion_ml.evaluation.hybrid_benchmark.run_hybrid_benchmark`, using
`generate_synthetic_benchmark(seed=43031)`. The source synthetic manifest SHA-256
is `f2963fed0ea272093eb2be2b1384686c1ef4ac28f1b44cdace1f417edd737db6`; the
synthetic catalog fingerprint is
`c4dfcbc75554ce167fcd3da2c68abc914276c8766b98097004fd57a1b3de7219`; and the
reference-fitted TF-IDF vocabulary fingerprint is
`47a26db13bd4ae4236d0391fc443c78502299985940b40fef0b01c1b43c088d2`.
Training-interaction, evaluation-label, and synthetic metadata-source hashes
are included in the local manifest.

The deterministic aggregate manifest is written only to the ignored local
path `data/processed/hybrid-benchmark-4.4b/aggregate-manifest.json`; user/item
rankings are held in memory and are not serialized. The report checksum,
runtime, and traced allocation peak are recorded below. Runtime covers the
benchmark runner after synthetic fixture generation and is not serving latency.
The Windows environment has neither `psutil` nor Python's `resource` module, so
process RSS was unavailable; peak traced Python allocation was measured.

| Reproduction field | Value |
| --- | --- |
| Benchmark version / seed | 4.4B / 43031 |
| Code revision | `ea8c948` (worktree dirty during experiment) |
| Aggregate manifest SHA-256 | `65be6e0dc821afad0de911099b97d9f089ba75a127171f743fcab6ea529cf011` |
| Manifest size | 34,108 bytes |
| Runtime | 0.1462 seconds |
| Peak traced Python allocation | 1,415,466 bytes |
| Process RSS | unavailable in this environment |

Two repeated executions produced byte-identical aggregate manifests. The unit
suite verifies frozen methods/policies, macro denominators, the seed and
configuration, cold-source eligibility, held-out-label independence of
popularity ranks, and the RRF rank-3 regression: filtering out original rank 2
does not compress original rank 3 to rank 2.

## Relationship, limitations, and next questions

Phase 4.3B remains the content-only baseline protocol. Phase 4.4A remains the
retrieval interface and smoke-test contract. This Phase 4.4B report compares
fixed source rankings through that interface; “popularity” is a non-neural
train-only source control, not a trained collaborative model. The frozen
weights are not selected as optimal. No real Amazon metadata, interaction
records, model checkpoints, or publication decisions are involved. Phase 4.2C
remains ON HOLD.

Future research may ask whether the trade-off persists with more than one
synthetic design, whether real eligible metadata changes cold ranking, and how
trained collaborative rankings complement content. Those questions require a
separately reviewed protocol and data-use gate; this benchmark does not answer
them.
