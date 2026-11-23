# PRD — Product Requirements Document

**Product:** RecFusion · **Stage:** Proposed, pre-implementation · **Domain:** Electronics · **Approach:** Hybrid recommender + bounded AI assistant.

## 1. Problem

Customers struggle to choose electronics across technical specifications, budgets, compatibility and personal preferences. Standard search matches keywords but may miss user-specific relevance; chatbots can sound helpful while inventing products, specs and prices. RecFusion will combine learned retrieval, deterministic constraints and source-grounded explanations.

## 2. Goal and success criteria

**Primary goal:** Demonstrate that an evaluated hybrid retrieval/ranking pipeline can generate relevant electronic-product recommendations, and that conversational preference collection makes the experience easier without weakening truthfulness.

**User outcomes:** discover relevant items, narrow through natural language, compare verifiable attributes, save/like/dislike suggestions, and understand why they appear.

**Engineering outcomes:** reproducible dataset pipeline; classical baselines; trained PyTorch two-tower model; hybrid search; optional learned ranker; tests, versioned artifacts, observable APIs; app demo.

**Research outcomes:** comparative offline Recall@K/NDCG@K; cold-start and coverage/diversity breakdown; controlled ablations; separate agent grounding and constraint tests. There is no promised metric improvement.

## 3. Target personas and jobs

- **Guest explorer:** “Find headphones with my stated preferences without creating an account.”
- **Returning user:** “Show products based on my prior, consented behavior.”
- **Budget-conscious buyer:** “Show laptops under my budget, and explain trade-offs.”
- **Technical evaluator:** “Compare baseline models and verify reported metrics.”

## 4. First-release functional requirements

| ID | Requirement | Acceptance test |
|---|---|---|
| F-01 | Search and browse electronics catalog | Search/filter return only catalog items, graceful empty states |
| F-02 | Guest preferences/session | No account required; guest state can be cleared |
| F-03 | Saved user preferences | User can inspect/change/delete consented preferences |
| F-04 | Top-K recommendation endpoint | Returns versioned ranks, candidate IDs and provenance |
| F-05 | Hard budget/category constraints | Every returned item passes verifiable mandatory filters |
| F-06 | Cold-start fallback | New user/product paths don't crash; fallback is labeled |
| F-07 | Conversational refinement | Structured intent → tool calls → validated results |
| F-08 | Product comparison | Side-by-side only for comparable, available attributes |
| F-09 | Feedback collection | Impression context and likes/dislikes/saves are logged with timestamps |
| F-10 | Explanation | No unsourced facts or invented stock/price assertions |
| F-11 | ML explorer / evaluation | Public demo shows model names, dataset versions, and reproducible experimental results |
| F-12 | User transparency | Historical vs synthetic vs verified/live catalog provenance shown |

## 5. Non-functional requirements

- **Correctness:** hard constraints validated in code independent of agent output; contract and authorization checks on all APIs.
- **Performance targets (not measurements):** cached feed P95 <300 ms; retrieval+rerank P95 <800 ms on explicitly specified test hardware/load. Report agent latency separately.
- **Security:** no exposed API keys; per-user access; bounded LLM tool usage; data deletion and retention policy.
- **Reliability:** deterministic fallback on model/vector/LLM failure; structured monitoring; bounded retries; idempotent feedback writes.
- **Reproducibility:** pinned dependencies, dataset and code versions, recorded seeds/metrics.
- **Accessibility:** keyboard navigation, accessible labels and contrast, responsive design.

## 6. Release boundary

**MVP:** searchable curated catalog, guest sessions, baseline recommendations, basic feedback, FastAPI/Next.js demo.

**v1:** trained Two-Tower, hybrid candidate fusion, ranker when labels allow, constrained conversational agent, product comparisons, evaluation dashboard, versioned deployment.

**Later:** image-to-product search, sequential/graph recommendation, contextual bandits, verified live merchant integration and online A/B tests (only if sufficient traffic and consent).

**Out of scope now:** checkout/payment, automatically buying items, unrestricted product crawling, claims of live availability without an actual source, distributed microservice deployment, full production personalization at large scale.

## 7. Essential user journeys

1. **Guest:** open landing → choose category → set budget/preferences → retrieve products → inspect explanation → save/clear session.
2. **Returning:** sign in → view consented profile → personalized feed → dislike item → next request reflects feedback (fast re-ranking; offline retraining is separate).
3. **Chat:** enter request → parse structured constraints → retrieve/rank → compare grounded attributes → revise preference with user approval.
4. **No match:** strict query → zero eligible items → explicit no-match message, *never* silently increase price cap.
5. **Evaluator:** choose model/dataset/split → inspect stored metrics, ablation and reproducible commands.

## 8. Data trust boundaries and limitations

Amazon Reviews 2023 is an offline dataset of historical review/rating events plus metadata. Do **not** claim it represents impressions, click-through rates, confirmed purchases, current inventory or Indian pricing. Define a separate curated demo catalog. Label synthetic data clearly and show source/update times when actual product data are used. Never derive claims of real-world conversion uplift from offline ranking metrics.

## 9. Decisions to approve before build

Initial user-facing category (laptops vs cross-category); real versus synthetic demo catalog policy; first identity/auth mechanism; hosting budget; minimum available machine specification; actual dataset licensing/usage conditions; definition of positive interactions. See `DECISIONS.md`.
