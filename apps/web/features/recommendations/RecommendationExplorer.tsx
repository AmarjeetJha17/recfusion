"use client";

import { useEffect, useRef, useState } from "react";
import { RecommendationResults } from "@/components/RecommendationResults";
import { getRequestableProducts } from "@/lib/catalog";
import { localApiRecommendationProvider } from "@/lib/local-api-provider";
import {
  type CandidatePolicy,
  fixtureRecommendationProvider,
  REQUEST_SCHEMA,
  type RecommendationMode,
  type RecommendationProvider,
  type RecommendationRequest,
  type RecommendationResponse,
} from "@/lib/recommendation-provider";

const modeExplanations: Record<RecommendationMode, string> = {
  product_to_product:
    "Ranks eligible products by similarity over available product-content features using TF-IDF. Similarity is not proof of preference.",
  synthetic_user:
    "Uses prior synthetic training interactions and product content to form a temporary retrieval context. No history is displayed; this is not proof of preference.",
  hybrid:
    "Combines separately ranked synthetic collaborative and content lists using weighted Reciprocal Rank Fusion. Source membership is not causal.",
};

const users = [
  { id: "synthetic-electronics-v1:user:000001", label: "Synthetic profile 01" },
  { id: "synthetic-electronics-v1:user:000002", label: "Synthetic profile 02" },
  { id: "synthetic-electronics-v1:user:000003", label: "Synthetic profile 03" },
];

const modes: { value: RecommendationMode; label: string; detail: string }[] = [
  {
    value: "product_to_product",
    label: "Product to product",
    detail: "Explore a similar-item fixture",
  },
  {
    value: "synthetic_user",
    label: "Synthetic user",
    detail: "Explore an invented profile context",
  },
  { value: "hybrid", label: "Hybrid", detail: "View an explicit combined-source fixture" },
];

export function buildRecommendationRequest(
  mode: RecommendationMode,
  contextId: string,
  candidatePolicy: CandidatePolicy,
  k = 5,
): RecommendationRequest {
  const common = {
    schema_version: REQUEST_SCHEMA,
    catalog_id: "synthetic-electronics-v1",
    algorithm_version: "1",
    k,
    excluded_product_ids: [] as string[],
    constraints: { category: null, max_price: null },
  } as const;
  if (mode === "product_to_product") {
    return {
      ...common,
      mode,
      algorithm_id: "tfidf_content",
      policy_id: "content-similarity-v1",
      candidate_policy: "content_catalog",
      query: { kind: mode, product_id: contextId },
    };
  }
  if (mode === "synthetic_user") {
    return {
      ...common,
      mode,
      algorithm_id: "tfidf_content",
      policy_id: "synthetic-user-content-v1",
      candidate_policy: "content_catalog",
      query: { kind: mode, user_id: contextId },
    };
  }
  const warm = candidatePolicy === "warm_hybrid";
  return {
    ...common,
    mode,
    algorithm_id: "weighted_rrf",
    policy_id: warm ? "synthetic-hybrid-warm-v1" : "synthetic-hybrid-content-v1",
    candidate_policy: warm ? "warm_hybrid" : "content_eligible_hybrid",
    query: { kind: mode, user_id: contextId },
  };
}

export function RecommendationExplorer({
  provider = fixtureRecommendationProvider,
}: {
  provider?: RecommendationProvider;
}) {
  const products = getRequestableProducts();
  const [mode, setMode] = useState<RecommendationMode>("product_to_product");
  const [productId, setProductId] = useState(products[0]?.id ?? "");
  const [userId, setUserId] = useState(users[0].id);
  const [candidatePolicy, setCandidatePolicy] = useState<CandidatePolicy>("warm_hybrid");
  const [k, setK] = useState(5);
  const [response, setResponse] = useState<RecommendationResponse>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [sourceMode, setSourceMode] = useState<"fixture" | "local_api">("fixture");
  const requestSequence = useRef(0);
  const activeRequest = useRef<AbortController | undefined>(undefined);
  const localApiAvailable = process.env.NODE_ENV !== "production";

  useEffect(() => () => activeRequest.current?.abort(), []);

  function clearCurrentRequest() {
    requestSequence.current += 1;
    activeRequest.current?.abort();
    activeRequest.current = undefined;
    setLoading(false);
    setResponse(undefined);
    setError(undefined);
  }

  async function runRecommendation() {
    const sequence = ++requestSequence.current;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setLoading(true);
    setError(undefined);
    setResponse(undefined);
    try {
      const contextId = mode === "product_to_product" ? productId : userId;
      const request = buildRecommendationRequest(mode, contextId, candidatePolicy, k);
      const activeProvider =
        provider !== fixtureRecommendationProvider
          ? provider
          : sourceMode === "local_api"
            ? localApiRecommendationProvider
            : fixtureRecommendationProvider;
      const result = await activeProvider.recommend(request, { signal: controller.signal });
      if (sequence === requestSequence.current) setResponse(result);
    } catch (caught) {
      if (!controller.signal.aborted && sequence === requestSequence.current) {
        setError(
          sourceMode === "local_api" && caught instanceof Error
            ? caught.message
            : "The local synthetic fixture provider could not complete this example.",
        );
      }
    } finally {
      if (sequence === requestSequence.current) {
        setLoading(false);
        activeRequest.current = undefined;
      }
    }
  }

  const contextLabel =
    mode === "product_to_product"
      ? `Product similarity · ${sourceMode === "fixture" ? (products.find((product) => product.id === productId)?.name ?? productId) : productId}`
      : mode === "synthetic_user"
        ? `Synthetic profile context · history stays private · ${users.find((user) => user.id === userId)?.label ?? "Synthetic profile"}`
        : `${candidatePolicy === "warm_hybrid" ? "Warm-only" : "Content-eligible"} hybrid · ${users.find((user) => user.id === userId)?.label ?? "Synthetic profile"}`;

  return (
    <div className="explorer-layout">
      <form
        className="explorer-controls"
        onSubmit={(event) => {
          event.preventDefault();
          void runRecommendation();
        }}
      >
        <fieldset className="mode-fieldset">
          <legend>Recommendation source</legend>
          <div className="mode-options source-options">
            <label className={sourceMode === "fixture" ? "mode-option is-selected" : "mode-option"}>
              <input
                checked={sourceMode === "fixture"}
                name="recommendation-source"
                onChange={() => {
                  clearCurrentRequest();
                  setSourceMode("fixture");
                }}
                type="radio"
                value="fixture"
              />
              <span className="mode-option__radio" aria-hidden="true" />
              <span className="mode-option__copy">
                <strong>Fixture</strong>
                <small>Offline, deterministic examples</small>
              </span>
            </label>
            {localApiAvailable && (
              <label
                className={sourceMode === "local_api" ? "mode-option is-selected" : "mode-option"}
              >
                <input
                  checked={sourceMode === "local_api"}
                  name="recommendation-source"
                  onChange={() => {
                    clearCurrentRequest();
                    setSourceMode("local_api");
                  }}
                  type="radio"
                  value="local_api"
                />
                <span className="mode-option__radio" aria-hidden="true" />
                <span className="mode-option__copy">
                  <strong>Local API</strong>
                  <small>Explicit local development opt-in</small>
                </span>
              </label>
            )}
          </div>
        </fieldset>
        <fieldset aria-describedby="mode-explanation" className="mode-fieldset">
          <legend>Choose an exploration mode</legend>
          <div className="mode-options">
            {modes.map((item) => (
              <label
                className={mode === item.value ? "mode-option is-selected" : "mode-option"}
                key={item.value}
              >
                <input
                  checked={mode === item.value}
                  name="recommendation-mode"
                  onChange={() => {
                    clearCurrentRequest();
                    setMode(item.value);
                  }}
                  type="radio"
                  value={item.value}
                />
                <span className="mode-option__radio" aria-hidden="true" />
                <span className="mode-option__copy">
                  <strong>{item.label}</strong>
                  <small>{item.detail}</small>
                </span>
              </label>
            ))}
          </div>
          <p aria-live="polite" className="mode-explanation" id="mode-explanation">
            {modeExplanations[mode]} Different candidate sets can produce different list lengths;
            there is no shared score scale.
          </p>
        </fieldset>

        <div className="form-divider" />
        {mode === "product_to_product" ? (
          <label className="field-label" htmlFor="context-product">
            <span>Starting product</span>
            <select
              id="context-product"
              onChange={(event) => {
                clearCurrentRequest();
                setProductId(event.target.value);
              }}
              value={productId}
            >
              {products.map((product) => (
                <option key={product.id} value={product.id}>
                  {product.name ?? "Title unavailable"}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <label className="field-label" htmlFor="context-user">
            <span>Synthetic context</span>
            <select
              id="context-user"
              onChange={(event) => {
                clearCurrentRequest();
                setUserId(event.target.value);
              }}
              value={userId}
            >
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.label}
                </option>
              ))}
            </select>
            <small>No raw history or user preference details are shown.</small>
          </label>
        )}

        {mode === "hybrid" && (
          <fieldset
            aria-describedby="candidate-policy-explanation"
            className="field-label policy-fieldset"
          >
            <legend>Candidate policy</legend>
            <label className="policy-option">
              <input
                checked={candidatePolicy === "warm_hybrid"}
                name="candidate-policy"
                onChange={() => {
                  clearCurrentRequest();
                  setCandidatePolicy("warm_hybrid");
                }}
                type="radio"
              />
              <span>
                <strong>Warm-only</strong>
                <small>Only train-known synthetic items.</small>
              </span>
            </label>
            <label className="policy-option">
              <input
                checked={candidatePolicy === "content_eligible_hybrid"}
                name="candidate-policy"
                onChange={() => {
                  clearCurrentRequest();
                  setCandidatePolicy("content_eligible_hybrid");
                }}
                type="radio"
              />
              <span>
                <strong>Content-eligible</strong>
                <small>
                  Eligible cold products may enter through content retrieval; collaborative
                  candidates stay train-known.
                </small>
              </span>
            </label>
            <p className="policy-explanation" id="candidate-policy-explanation">
              {candidatePolicy === "warm_hybrid" ? (
                <>
                  Warm-only <code>warm_hybrid</code> includes items known in synthetic training
                  interactions.
                </>
              ) : (
                <>
                  Content-eligible <code>content_eligible_hybrid</code> may include cold products
                  with content; collaborative candidates remain train-known.
                </>
              )}{" "}
              Cold means no permitted synthetic training interactions. It is not a quality or
              inventory label.
            </p>
          </fieldset>
        )}

        <label className="field-label result-count-field" htmlFor="result-count">
          <span>Number of results</span>
          <select
            id="result-count"
            onChange={(event) => {
              clearCurrentRequest();
              setK(Number(event.target.value));
            }}
            value={k}
          >
            <option value={5}>5 results</option>
            <option value={10}>10 results</option>
            <option value={20}>20 results</option>
          </select>
        </label>
        <button className="button button--primary explorer-submit" disabled={loading} type="submit">
          {loading ? "Loading recommendations…" : "Show recommendations"}
          <span aria-hidden="true">↗</span>
        </button>
        <p className="explorer-private-note">
          {sourceMode === "fixture"
            ? "Fixture mode · offline · no network request"
            : "Local API mode · loopback development service"}
        </p>
      </form>

      <div className="explorer-results">
        <div className="explorer-results__topline">
          <span>REC · EXPLORER · {sourceMode === "fixture" ? "FIXTURE" : "LOCAL API"}</span>
          <span>Schema v1</span>
        </div>
        <RecommendationResults
          contextLabel={contextLabel}
          error={error}
          loading={loading}
          onRetry={sourceMode === "local_api" ? () => void runRecommendation() : undefined}
          requestedK={k}
          response={response}
          presentationSource={sourceMode}
        />
      </div>
    </div>
  );
}
