# Phase 4.3B synthetic content benchmark

**Status:** Synthetic-only benchmark for the Phase 4.3A TF-IDF retriever. No
real Amazon data, product metadata, images, or derived user rows were read,
created, or persisted. This benchmark is not evidence of dataset rights,
real-catalog quality, or deployment readiness. Phase 4.2C remains ON HOLD.

## Purpose and reproduction

The benchmark in `recfusion_ml.evaluation.content_benchmark` exercises cold
item retrieval, candidate eligibility, sparse metadata quality, and fixed
controls against a small deterministic catalog. It reuses the existing
`recfusion_ml.retrieval.content` implementation and its defaults; it does not
retune TF-IDF. The in-memory runner is `generate_synthetic_benchmark(seed=43031)`
followed by `run_content_benchmark(..., code_revision="<revision>")`. It returns
canonical aggregate manifest bytes and their SHA-256; it does not write a
manifest or row-level outputs to disk. The benchmark suite is
`tests/unit/test_content_benchmark.py`.

The generator schema is `recfusion.synthetic-content-generator.v1`, the report
schema is `recfusion.content-benchmark.v1`, and the benchmark version is
`4.3B`. The fixed seed is 43031. The generated catalog has four electronics
categories (laptops, audio, cameras, and networking), overlapping and rare
technical vocabulary, 24 warm products, and 18 held-out cold products. The 18
cold products comprise eight with content in the frozen vocabulary, eight
with only unseen vocabulary, one with missing metadata, and one with
conflicted metadata. The generator also includes one exact repeated metadata
record, one conflicting duplicate, and one malformed product record. Sixteen
synthetic evaluation users have varied histories; two have empty histories.
Synthetic labels are rating 5; the positive threshold is fixed at rating >= 4.

## Partitions and safeguards

The 24 warm products are both the reference catalog and train-known catalog.
Reference selection is independent of held-out labels. Cold products are
absent from all training interactions. There are 70 training interactions and
27 validation events across 16 evaluation users. Every validation event is at
the fixed synthetic timestamp 10,000 milliseconds; training records are
strictly earlier. The benchmark does not construct or recompute a production
split.

Profiles use only strictly prior positive training interactions, mask the
held-out target, and filter each user's previously seen products from the
candidate list. Vocabulary and IDF are fit only on the 24 warm reference
products. Cold product text is transformed using that frozen vocabulary; it
never contributes to fitting. All 16 users, including the two with empty
histories, remain in macro metric denominators. Popularity counts distinct
positive training user/product pairs. The seeded random control is derived
from fixed seed and synthetic identifiers. No validation labels or held-out
interactions affect selection, fitting, profiles, or controls.

Two separate candidate policies are evaluated:

| Policy | Global eligible candidates | Eligible targets | Definition |
| --- | ---: | ---: | --- |
| `warm_only` | 24 | 16 | Warm products with nonzero reference-fitted vectors |
| `content_eligible` | 32 (24 warm + 8 cold) | 24 | Warm products and cold products with nonzero vectors under the frozen vocabulary |

Each user-specific list also excludes that user's seen products. The
content-eligible cold-item result uses a macro denominator of 8 users and 8
eligible cold targets. It reports 3 additional held-out cold positives as
ineligible (one missing-metadata, one conflicted-metadata, and one
unseen-vocabulary product); they are excluded from the candidate pool and
cannot be retrieved. Eight users have no eligible cold positive.

## Metrics

Relevance is binary rating >= 4, deduplicated by user/product for targets.
Recall, NDCG, HitRate, and MRR are macro means over all 16 users. Binary NDCG
uses gain 1, discount `1/log2(rank+1)`, and ideal DCG based on the smaller of K
and the user's eligible target count. MRR is zero when no eligible target is
retrieved. Catalog coverage is unique recommended products divided by the
policy's global eligible candidate count before user-specific seen filtering.
Short-list counts include every evaluated user receiving fewer than K results;
empty prediction lists remain in metric denominators.

The table reports Recall/NDCG/HitRate/MRR at each K and catalog coverage at
K=10. Results are deterministic measurements of this engineered toy scenario,
not estimates for users or products outside it.

| Candidate policy | Model/control | @5 R/N/H/MRR | @10 R/N/H/MRR | @20 R/N/H/MRR | Coverage @10 |
| --- | --- | --- | --- | --- | ---: |
| warm-only | TF-IDF user profile | .875/.7366/.875/.6875 | .875/.7366/.875/.6875 | .875/.7366/.875/.6875 | 1.000 (24/24) |
| warm-only | Item-content nearest neighbor | .875/.7366/.875/.6875 | .875/.7366/.875/.6875 | .875/.7366/.875/.6875 | 1.000 (24/24) |
| warm-only | Training popularity | .000/.000/.000/.000 | .000/.000/.000/.000 | .750/.1807/.750/.0450 | .542 (13/24) |
| warm-only | Deterministic random | .125/.0707/.125/.0521 | .375/.1507/.375/.0846 | .875/.2750/.875/.1177 | 1.000 (24/24) |
| content-eligible | TF-IDF user profile | .875/.6739/.875/.6250 | .875/.6739/.875/.6250 | .875/.6739/.875/.6250 | 1.000 (32/32) |
| content-eligible | Item-content nearest neighbor | .875/.6739/.875/.6250 | .875/.6739/.875/.6250 | .875/.6739/.875/.6250 | 1.000 (32/32) |
| content-eligible | Training popularity | .000/.000/.000/.000 | .000/.000/.000/.000 | .5625/.1459/.750/.0450 | .406 (13/32) |
| content-eligible | Deterministic random | .1875/.1415/.250/.1458 | .3125/.1842/.4375/.1680 | .6875/.2897/.750/.1901 | 1.000 (32/32) |

At K=10, the TF-IDF profile returned 8.75 items/user on average and two users
had short lists under both policies because their histories produced no usable
profile. The item-content nearest-neighbor control also had two short lists.
Popularity and random returned full lists for all users at K=10. The
content-eligible TF-IDF profile retrieved 7 of 8 eligible cold positives by
K=5; macro cold recall is .875 at K=5, 10, and 20.

## Metadata diagnostics and ablations

The 42 synthetic products correspond to 44 metadata source records: one exact
duplicate occurrence and one conflicting duplicate occurrence are counted.
There are 41 metadata-matched products, 1 unmatched product, 1 malformed
metadata product, 32 feature-ready products, and 1 conflict-excluded product.
Eight products have zero vectors under the reference vocabulary, all of them
cold products with unseen vocabulary. Missing metadata is counted separately
from zero-vector content. No metadata values are claimed for any real product.

The predeclared ablations keep evaluation cohorts and candidate policies
fixed:

- **Title-only:** profile ranking metrics matched the standard run in this
  generator. This only shows that the synthetic titles encode the constructed
  interests.
- **No usable text:** fitting correctly reports no usable reference content;
  it returns zero recommendations, zero metrics, and short lists for all 16
  users.
- **Unseen-vocabulary cold:** 8 of 18 cold products transform to zero vectors;
  the before/after vocabulary checksum is unchanged.
- **Empty history:** all users return empty lists; metrics are zero and all 16
  users count as short-list users at each K.

## Determinism and run record

For seed 43031, the source checksums are:

| Synthetic source | SHA-256 |
| --- | --- |
| Metadata source | `400746abb9cc8bad83047581ed29647c002047c3729ec03de80a20ccda481d96` |
| Training interactions | `095ca0805890dd60a26a652a997c8943652489a7ed37613874f25e3584d9ba0c` |
| Evaluation labels | `fda726062c5e567581e3052e9640a4b5de2e68c2927ad39a09b621207a8fb0da` |

The frozen vocabulary has 116 terms and SHA-256
`47a26db13bd4ae4236d0391fc443c78502299985940b40fef0b01c1b43c088d2`. The
content index artifact hash is
`899fcd0bbea8478e195184f70403b9a0ee1fc3baed5a538ba24d0d878b666200`. The
aggregate manifest SHA-256 for this run is
`355a4e38816491aaac0a70e879279b1f1561ad3cab73b7f70b17aadb4a0803ba`.
The manifest identifies base revision `efb6279` and marks the working tree
dirty because this benchmark implementation was still under review. Runtime
was 0.183 seconds and peak traced Python allocations were 586,943 bytes; this
is not process RSS and says nothing about real-catalog resource needs.

Manifest serialization is canonical and deterministic for the same seed,
source code revision, and inputs. It includes schemas, configuration,
partition sizes and policy, source checksums, vocabulary/index checksums,
metric definitions, controls, aggregate metrics, and the code revision. It
excludes runtime, absolute paths, source rows, and per-user rankings. The
runner returns the manifest in memory; no generated report or data file was
persisted by this run.

## Interpretation and next gate

This is one seed, 16 users, 42 products, and deliberately constructed text and
labels. There are no confidence intervals, significance claims, real-user
behavior, real product metadata, images, or external catalog coverage. The
nearest-neighbor control is another deterministic use of the same content
features, not an independently trained model. The popularity and random
controls are benchmark-local implementations, not claims about Phase 3
production code. The results do not establish general content quality or a
benefit over other recommender families.

**Recommendation:** GO for a separately scoped synthetic hybrid-integration
design in Phase 4.4. NO-GO for real metadata acquisition/use or real-data
quality claims while Phase 4.2C remains ON HOLD. Any future data use needs its
own owner review and rights assessment; this benchmark changes neither.
