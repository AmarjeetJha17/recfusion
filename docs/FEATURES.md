# Feature generation

The Phase 4.3A TF-IDF retriever is a separate synthetic-only implementation;
it does not change this temporal feature-generation pipeline or its artifact
contracts. See `docs/CONTENT-RETRIEVAL.md` for its content inputs, train-only
fitting boundary, user-profile cutoff, and artifact format.

**Status:** Implemented against synthetic canonical data only. This pipeline does
not train or evaluate a recommendation model and does not authorize external
dataset use.

## Run

Generate features from a Step 2.5 output directory and a Step 2.3 normalized
product sidecar:

```powershell
uv run recfusion-generate-features `
  --temporal-dir data/processed/temporal-run `
  --product-ingestion-dir data/processed/product-run `
  --output-dir data/processed/features-run
```

Both inputs must have their original `manifest.json`. The temporal manifest must
report evaluation eligibility and match its output checksums. The ingestion
manifest must record `normalize_products: true`; its normalized sidecar checksum
is also verified. Outputs are written atomically to a new child directory under
ignored `data/processed/`. Existing output directories are never replaced.

## Output contracts

The generator publishes:

| File | Contract |
|---|---|
| `interactions.features.jsonl` | `recfusion.feature-interaction.v1`: encoded train/validation/test events, original observed rating and provisional label, timestamps and split provenance, source event fingerprint, integrity flags, and as-of history aggregates. It omits raw user and item keys. |
| `items.features.jsonl` | `recfusion.item-feature.v1`: unknown item index 0 and one row per Step 2.5 training-candidate item, with source-backed metadata, encodings, normalized values, provenance and missingness. |
| `feature-schema.json` | Typed `recfusion.feature-schema.v1` definitions, boundaries, units and missing-value semantics. |
| `transformers.json` | `recfusion.feature-transformers.v1` train-only categorical vocabularies and numerical fit parameters. |
| `manifest.json` | Versioned feature dataset ID, source identities/checksums, configuration hash, output hashes, counts, exclusions, missingness and integrity assertions. |

Item features are a separate sidecar joined by `item_index`; they are not copied
into each interaction row. The unknown user/item index remains 0. No user or item
source keys are emitted in these feature artifacts. Source event fingerprints
and normalized product source fingerprints are retained for internal audit.

## Temporal interaction features

User history and item aggregates use only training interactions that Step 2.5
marks eligible, and only events with `event_time_ms < target_event_time_ms`.
All events sharing a timestamp are processed as one group, so simultaneous
events cannot appear in one another's features. The target event is therefore
excluded. Exact repeated rows flagged by Step 2.5 are preserved in the output
but excluded from history aggregates.

Validation and test features use training interactions only; held-out events
never update history, even when a prior validation event is chronologically
earlier than a later validation or test target. The aggregates are:

- User prior interaction count and mean observed rating.
- Item prior training-interaction count and mean observed rating. The count is
  observed-review popularity, not impressions, exposure, availability or a
  negative-sampling pool.

An empty prior history has count 0 and a null mean with a true missing indicator.
Observed ratings remain review-feedback signals; no purchase, click, impression
or unobserved-item negative labels are inferred. Step 2.5 blocking integrity
violations stop feature generation rather than being repaired here.

## Product metadata features

The item sidecar uses normalized brand, category, storage type, processor name,
GPU name, RAM bytes, storage bytes, display millimetres, weight grams, and
battery capacity in separate mAh and Wh channels. Category encoders and numeric
standardizers fit only on unique, non-conflicting normalized product records
whose items are present in the Step 2.5 training candidate pool. Held-out
interactions and products outside that pool do not affect fitting.

Categorical IDs start at 1; ID 0 means missing, unavailable or an unseen
category, with distinct `missing`, `unknown` and `unavailable` flags. Raw source
values, source attribute keys, normalization status and units are retained in
the local item feature artifact. Numerical fields use population z-scores with
mean and scale recorded in `transformers.json`. A zero-variance field uses scale
1; if no training observations exist, the transformed value remains null.
Missing or unsupported values are never imputed. Battery mAh and Wh are not
converted into each other because voltage is unknown; a value in the other unit
is marked `not_applicable` for that channel.

If a training-catalog item has multiple distinct product records, or its
normalization decision is `conflict_retained`, all of that item's product
features are excluded. The item and its interactions remain in the artifacts;
the item feature row is marked `conflict_excluded`. Records are never merged or
chosen by input order. Missing product records remain explicitly missing.

These normalized metadata values have no documented historical effective
timestamps. The sidecar is labeled `source_snapshot_effective_time_unknown`;
it must be treated as a snapshot-metadata experiment and cannot support
point-in-time product availability claims. Product metadata is kept separate
from the strictly as-of interaction features. Prices and rating aggregates are
not generated as features.

## Reproducibility, validation and resource use

The feature dataset ID is derived from the feature schema version,
configuration hash and input checksums. Each derived file has a SHA-256 hash in
the manifest. No run timestamp or absolute path is included. Inputs are
checksummed before processing and rechecked before publication. Reordered
equivalent interactions produce identical feature records; source manifests
still preserve the actual input checksums.

Rows, vocabularies, product records, and timestamp-ordered history aggregates
are spooled through SQLite with a bounded page cache and disk-backed temporary
storage. Memory does not scale with the full interaction or product catalog;
SQLite indexes and disk usage scale with event count and distinct IDs, while
category vocabularies and the generated artifacts scale with observed feature
cardinality.

The synthetic unit, contract and integration tests cover schema and status
semantics, exact as-of boundaries, simultaneous timestamps, train-only fitting,
held-out-label invariance, unknown IDs, missing specifications, conflicting
metadata, reordered inputs and CLI execution. Test outcomes describe only
synthetic fixtures; they are not dataset quality, rights, model, or resource
claims.
