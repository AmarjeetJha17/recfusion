# Dataset feasibility

Status: research only. The three official Electronics 5-core timestamp CSV files are present locally at the repository root. Step 2.2B.1 inspected only their file metadata, checksums, and headers; no dataset rows have been ingested or profiled. The source has not been licensed or cleared for the project's intended use. Facts below are from the cited sources; choices remain proposals pending review.

## Recommended source and scope

Use the [Amazon Reviews 2023 dataset](https://amazon-reviews-2023.github.io/) as a candidate offline research source, subject to resolving its usage terms before acquisition. Start feasibility profiling with the **Electronics** domain only. The overview reports approximately 43.9 million reviews, 18.3 million users, and 1.6 million reviewed items for Electronics; the official [0-core processed table](https://amazon-reviews-2023.github.io/data_processing/0core.html) reports about 43.4 million Electronics reviews. These are rounded figures from distinct source/processing tables and are not reconciled here. Item counts are based on review items, and the authors warn that some items lack metadata.

Across the dataset, the authors report 571.54 million reviews, 54.51 million users, 48.19 million items, and 33 top-level categories, with review timestamps spanning May 1996 through September 2023. These are source-reported totals, not counts recalculated by RecFusion.

Electronics is large enough to support collaborative experiments and has a corresponding product metadata file. Do not combine source categories in the first pilot: category-specific sampling and identifiers avoid cross-domain assumptions. Consider **Cell Phones and Accessories** as a later adjacent category (about 20.8 million reviews, 11.6 million users, and 1.3 million items) and **Appliances** as a possible expansion (about 2.1 million reviews, 1.8 million users, and 94.3 thousand items). These source category labels do not imply a normalized electronics taxonomy.

The official 5-core Electronics data has about 1.6 million users, 368.2 thousand items, and 15.5 million interactions before splitting. Its global timestamp split reports 13.1 million train, 1.2 million validation, and 1.2 million test interactions. This filtered benchmark is useful for a reproducible dense pilot, but 5-core filtering removes sparse users/items and changes the source distribution; it cannot establish long-tail or realistic cold-start performance.

## Available data and schemas

The source publishes category-level raw review JSONL and product metadata JSONL as well as processed benchmark splits. Review examples include `rating` (1–5), `title`, `text`, `images`, `asin`, `parent_asin`, `user_id`, `timestamp` (Unix milliseconds), `verified_purchase`, and `helpful_vote`. Metadata fields include `main_category`, `title`, `average_rating`, `rating_number`, `features`, `description`, `price`, `images`, `videos`, `store`, `categories`, `details`, `parent_asin`, and `bought_together`. Source fields can be optional or empty. See [DATA-CONTRACTS.md](./DATA-CONTRACTS.md) for a proposed normalized boundary and validation rules.

Use raw JSONL schemas as the source contract. Serialized Hugging Face representations can differ: for example, documentation describes `price` as numeric, while a viewer representation may expose it as a string (including a `"None"` sentinel); nested fields such as `details` can also be represented differently. Preserve source values and record normalization rather than assuming one serialized type.

The `verified_purchase` field describes a review attribute. It is not a click/impression log, complete transaction history, or proof that all transactions are observed. Ratings/reviews are selected feedback. An item without a review is **unobserved**, not a negative example.

## Modeling and evaluation feasibility

| Use | Feasibility and limitation |
|---|---|
| Collaborative filtering | Supported by user/item IDs and ratings. 5-core is a convenient dense baseline; it removes sparse users/items and can bias results. |
| Two-Tower retrieval | IDs and review history support collaborative towers; product text/metadata can support an item tower after profiling. No purchase or exposure signal is supplied. |
| Content-based retrieval | Product titles, features, descriptions, categories, and details are available but may be absent or inconsistent. Images are references/metadata, not a complete licensed image corpus. |
| Hybrid retrieval | A combination of learned interaction signals and available product content is plausible. Missing metadata must have explicit behavior; semantic text vectors and collaborative vectors remain distinct. |
| Learning-to-rank | Ratings provide graded judgments only for reviewed items. Without impression/exposure context, these labels are selected and do not support an unbiased production ranking claim. Treat rating-based LTR as exploratory. |
| Cold start | 0-core data can expose sparse and unseen-in-training users/items. A cold item can be tested with content only only if that content was actually available at the prediction time; the metadata snapshot has no per-item effective timestamp, so strict historical catalog availability is not established. |
| Temporal evaluation | Review timestamps support chronological splits. They do not make metadata fields historical: `average_rating`, `rating_number`, price, and other metadata may reflect the later crawl snapshot. Avoid treating them as as-of-cutoff features. |

For review-based relevance, a proposed binary label is rating 4–5 = relevant, rating 1–2 = explicitly low-rated, and rating 3 = neutral/held out of binary labels. Preserve the ordinal rating in raw data. This is a proposed operational definition, not an observed purchase/conversion label. Keep low-rated reviews distinguishable from unobserved products. Report how many queries are eligible under the chosen label and how rating distribution affects results.

For a primary warm-item retrieval comparison, use the same training-time eligible catalog for every model and evaluate against held-out positive review items. Items first appearing after the catalog cutoff belong in a separate cold-item analysis. Full-catalog ranking is preferable when feasible; if a sampled candidate pool is needed, include every target and use a fixed, published seed and identical candidates for every model. Call sampled-pool metrics sampled-pool metrics. Unreviewed candidates remain unknown, not verified negatives.

Fit vocabularies, normalizers, popularity, and other learned transforms on training data only. Construct history strictly before each prediction cutoff. Deduplicate before splitting, preserve equal timestamps with a deterministic tie-breaker, and never let validation/test information influence training features or candidate eligibility. The official global timestamp cutoffs are documented in the profiling plan as a reproducibility reference, not as a decision that all future evaluations must use those dates.

## Data quality, scale, and provenance

The dataset authors explicitly note missing product metadata. The available documentation does not establish Electronics percentages for missing prices/specifications/images, or review-to-metadata join coverage. Do not infer these rates from rounded category totals. Measure them on the pilot before choosing content feature requirements. A present image URL does not establish that the image is reachable, complete, or licensed for reuse.

The Hugging Face repository file listing reports the Electronics raw review JSONL at 22,616,233,652 bytes and the raw metadata JSONL at 5,246,144,134 bytes. These are repository file sizes, not a local measurement or compressed-transfer estimate; together they are about 27.9 GB in the listed JSONL representation. The Hugging Face dataset viewer reports different metadata storage figures for its processed representation. Plan streaming and measure local disk/RAM during the pilot; no RAM estimate is asserted here. The bounded pilot should retain only sampled interactions and their matched metadata, not a full normalized copy.

Record source URL, retrieval date, immutable source revision or file checksum, source schema version, category, filtering/sampling config, split cutoffs, code commit, and license/terms review in the dataset manifest. Do not put source reviews, raw user identifiers, images, secrets, or credentials in Git, CI logs, or public fixtures. Historical product prices are not current prices and must never be shown as INR/current demo prices.

## Download locations and terms

- The [McAuley Lab dataset page](https://amazon-reviews-2023.github.io/) is the primary documentation and links to category downloads and processing recipes.
- The [Hugging Face dataset repository](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023) hosts category/config files and processed benchmark artifacts. Its [dataset card](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023) documents loader usage; inspect remote code and pin a revision before any future automated use.
- Official processing references: [0-core](https://amazon-reviews-2023.github.io/data_processing/0core.html), [5-core](https://amazon-reviews-2023.github.io/data_processing/5core.html), [JSONL loading](https://amazon-reviews-2023.github.io/data_loading/jsonl.html), and [Hugging Face loading](https://amazon-reviews-2023.github.io/data_loading/huggingface.html).
- Paper: [Amazon Reviews 2023: A Large-Scale Dataset for Recommender Systems](https://arxiv.org/abs/2403.03952).

**Usage is an unresolved gate.** In the pinned [Hugging Face licensing discussion](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/discussions/1), a dataset maintainer says the lab is not in a position to assign a license or dictate terms, and that the data was made available primarily for research, with responsibility to follow ethical and legal standards. This is not a dataset license or blanket commercial-use permission. The [companion GitHub repository](https://github.com/hyp1231/AmazonReviews2023) licenses its code; that code license does not license review contents. Obtain a project-appropriate legal/terms review before downloading or using the dataset. Until then, do not redistribute raw reviews, identifiers, images, or record-level derived data. AWS terms for a similarly named Amazon corpus are not presumed to apply to this distinct dataset.

## Demo catalog separation

Keep the historical research corpus isolated from the application/demo catalog. Do not copy Amazon historical prices, review text, ratings, images, or identifiers into the demo catalog. Demo prices must be independently sourced with an explicit as-of date/currency and source, or clearly labeled synthetic values; never imply they are current market prices. Any later source-to-demo mapping requires provenance, terms review, and a separately approved contract.

## Decisions still open

1. Is use of this dataset acceptable under the project owner's intended public/commercial context and applicable terms?
2. Is the Electronics 5-core timestamp benchmark an acceptable first dense pilot, followed by a 0-core cold-start audit?
3. What positive-rating threshold and treatment of ratings 1–3 should be used for each experiment?
4. Is a reviewed-item relevance task sufficient for the first LTR study, or should LTR wait for exposure/impression data?
5. Which product metadata fields are sufficiently complete and temporally defensible after the pilot profile?
