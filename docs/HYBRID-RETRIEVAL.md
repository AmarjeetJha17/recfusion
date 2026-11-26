# Phase 4.4A synthetic hybrid retrieval

**Status:** Deterministic synthetic integration of the existing TF-IDF content
retriever with caller-supplied collaborative rankings and the existing RRF
engine. This adds no collaborative model, training loop, checkpoint loading,
real-data evaluation, or serving endpoint. Phase 4.2C remains ON HOLD.

## Interface and identity

`recfusion_ml.retrieval.hybrid.retrieve_hybrid` accepts a
`HybridUserContext`, an existing fitted `ContentIndex`, ranked collaborative
source lists, the exact train-known item set, an explicit candidate policy,
explicit `RRFConfig` weights/depths, and final K. It either generates the
TF-IDF source list from the `ContentIndex` and the user's training history or
accepts a precomputed `content_ranking` from that same approved content
interface. An explicit empty sequence means the content source has no results;
omitting it asks the adapter to generate the list.

Each non-content source name configured in `HybridConfig` identifies a
collaborative ranking source. Synthetic or future callers can keep names such
as `item_cf`, `bpr`, and `two_tower`; this interface consumes ordered item
keys and does not load or train those models. Callers are responsible for
fitting collaborative representations on training records only. The adapter
enforces the train-known candidate restriction on every collaborative list.

Rankings must use the canonical `item_key` strings already present in the
`ContentIndex` and train outputs. This adapter does not remap source IDs or
mix variant and parent-product identifiers. Raw scores are not accepted or
added: content similarity is used only to order content candidates, and each
source's rank is then fused independently.

`HybridUserContext` contains a private user key, training interactions,
prediction time in Unix milliseconds, and an optional target key for masking.
The result carries local ranked IDs and provenance so the caller can serve or
inspect that query. `summarize_hybrid` emits aggregate counts and metrics only;
it has no persistence path and returns no user or item identifiers.

## Candidate policies

| Policy | Global candidate set | Collaborative source set | Content source set |
| --- | --- | --- | --- |
| `warm_hybrid` | All supplied train-known items | Train-known items only | Warm items in `ContentIndex.candidate_keys` |
| `content_eligible_hybrid` | Train-known items plus cold items in `ContentIndex.candidate_keys` | Train-known items only | Warm and cold items in `ContentIndex.candidate_keys` |

`ContentIndex.candidate_keys` contains only catalog-eligible products with
nonzero vectors under its already-fitted reference vocabulary. Missing,
conflicted, unsupported, and zero-vector content therefore cannot enter from
the content source. A content-eligible cold product can enter policy B, but
the collaborative source pool always remains train-known. Train-seen items are
removed from every source before fusion. The global policy pool is fixed
without held-out relevance labels; target labels are not an input to the
interface.

RRF now accepts optional per-source candidate pools. It applies source depth
first, then global candidate, source-specific candidate, and seen-item
filters, retaining the original one-based source rank throughout. It reports
separate depth-truncated, outside-global-pool, source-pool-excluded, and
seen-excluded counts. With this option omitted, existing Phase 3 RRF callers
keep their original global-pool behavior. Duplicate or malformed ranked IDs,
unknown source names, invalid weights/depths, and invalid K fail explicitly;
out-of-pool ranked items are filtered and counted. Missing configured lists
become empty lists. Zero-weight sources are audited but cannot contribute a
score or introduce a recommendation. No popularity fallback exists.

Weights must be explicit, finite, and non-negative; source depths must be
explicit positive integers and do not depend on final K. The default RRF
constant remains 60. Scores are
`sum(weight[source] / (60 + one_based_source_rank))`. Final ties use ascending
canonical item key. Source order, input mapping order, and set iteration do
not change the output.

## Temporal and data safeguards

The content adapter builds profiles using only `DataSplit.TRAIN` interactions
strictly earlier than prediction time. It excludes the target from positive
profile construction and retains strictly prior observations for seen-item
filtering. Equal-time and future interactions are not profile history; a
validation/test interaction supplied as training input is rejected. Empty
profiles produce no TF-IDF candidates. There is no fallback candidate
fabrication. The content vocabulary and IDF are not refit by hybrid retrieval
or by cold candidates.

Collaborative rankings are passed in by the caller because this step trains no
model and loads no real checkpoint. Only train-known IDs survive the
collaborative source pool, which prevents collaborative lists from introducing
cold catalog products. The interface cannot independently prove how an
external collaborative ranking was produced; the caller's train-only
representation contract and synthetic tests cover that boundary.

## Diagnostics

`HybridRetrievalResult` retains query-local RRF results, source provenance,
source contributions, and counts in memory. `summarize_hybrid` combines the
existing aggregate `summarize_fusion` diagnostics with:

- Candidate-pool sizes for warm, cold, and content-eligible items.
- Raw and eligible source counts; depth truncation, global-pool, source-pool,
  and seen exclusions.
- Per-source warm/cold eligible-list occurrence counts.
- Warm/cold final recommendation counts, unique products, and catalog
  coverage at each K.
- Existing source overlap, final coverage, short lists, and attribution
  counts, with exclusive attribution distinguished from shared attribution.
- Sum of RRF score contributions from collaborative sources and the content
  source in the final lists. These contributions can overlap for an item
  ranked by multiple sources and are not relevance metrics.

The summary requires every result to share the same policy and candidate pool,
so denominators cannot drift across users. It persists nothing and does not
emit source IDs, user IDs, item IDs, or row-level rankings.

## Synthetic end-to-end smoke test

`tests/integration/test_hybrid_smoke.py` creates the versioned synthetic
electronics benchmark at seed 44041, fits the existing TF-IDF index on its 24
warm reference products, creates synthetic user contexts, supplies fixed
invented `item_cf` and `bpr` ranked lists, includes an empty zero-weight
`two_tower` source, and fuses at K=20 using rank constant 60. Collaborative
lists are deterministic slices of sorted train item keys, not rankings from
trained collaborative models. No evaluation label or real dataset file is
passed to retrieval.

| Aggregate | Result |
| --- | ---: |
| Synthetic products / metadata source records | 42 / 44 |
| Training interactions / validation events / query users | 70 / 27 / 16 |
| Content-eligible policy pool | 32 (24 warm + 8 cold) |
| Content profiles with empty history | 2 |
| Raw candidates: item-CF / BPR / Two-Tower / content | 32 / 48 / 0 / 280 |
| Eligible source occurrences: item-CF / BPR / Two-Tower / content | 29 / 44 / 0 / 280 |
| Seen exclusions: item-CF / BPR | 3 / 4 |
| Global-pool and source-pool exclusions | 0 / 0 |

| K | Recommendations (warm + cold) | Unique warm / cold | Overall coverage | Short users | Source attributions (item-CF / BPR / content) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 80 (66 + 14) | 6 / 8 | 14/32 (43.75%) | 0 | 27 / 37 / 49 |
| 10 | 150 (118 + 32) | 23 / 8 | 31/32 (96.875%) | 2 | 29 / 44 / 110 |
| 20 | 290 (219 + 71) | 24 / 8 | 32/32 (100%) | 2 | 29 / 44 / 250 |

The content path contributed eligible cold candidates, and all eight appeared
across the 16 users' final lists at each reported K. The source attribution
counts overlap when multiple sources support an item; they are not exclusive
shares. The source overlap mean Jaccard was 0.000 for BPR/item-CF, 0.0602 for
BPR/content, and 0.0400 for item-CF/content. Source-score contribution sums at
K=20 were 1.1807 collaborative and 3.6153 content.

The measured run took 0.0154 seconds on the local environment from synthetic
generation through index fitting, 16 retrievals, and aggregate summarization.
This timing is a single tiny synthetic run, not a latency benchmark or
capacity estimate. The frozen vocabulary SHA-256 was
`47a26db13bd4ae4236d0391fc443c78502299985940b40fef0b01c1b43c088d2`. The run
used seed 44041 and base revision `9d0c71c`; code under test was uncommitted.

Unit/integration tests also show that a cold item may be ranked by content and
reach final top K; a collaborative list cannot introduce it independently;
missing, conflicted, and unseen-vocabulary products stay out of content
candidates; train-seen, equal-time, future, and non-training rows remain
excluded; source counts reconcile; and repeat execution is deterministic.
These are interface/integrity checks, not hybrid quality evaluation.

## Limitations and next step

This is an interface and eligibility smoke test with one fixed synthetic
scenario. It does not compare relevance labels or establish a quality gain,
optimal source weights, real user behavior, product metadata coverage,
commercial suitability, serving latency, or production resource needs. It
uses no metadata acquisition and makes no change to Phase 4.2C.

Phase 4.4B should define and freeze a synthetic hybrid evaluation protocol
before any tuning: user/query cohorts, relevance and denominators, source
controls, candidate policies, metrics, multiple deterministic seeds, and
aggregate manifests. Weight selection must remain separate from final
evaluation. Any real metadata or Amazon interaction use remains subject to its
separate rights and owner-review gates.
