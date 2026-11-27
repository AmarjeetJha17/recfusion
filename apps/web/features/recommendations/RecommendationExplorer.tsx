"use client";

import { useState } from "react";
import { RecommendationResults } from "@/components/RecommendationResults";
import { getRequestableProducts } from "@/lib/catalog";
import {
  type CandidatePolicy,
  fixtureRecommendationProvider,
  REQUEST_SCHEMA,
  type RecommendationMode,
  type RecommendationProvider,
  type RecommendationRequest,
  type RecommendationResponse,
} from "@/lib/recommendation-provider";

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

  async function runRecommendation() {
    setLoading(true);
    setError(undefined);
    setResponse(undefined);
    try {
      const contextId = mode === "product_to_product" ? productId : userId;
      const request = buildRecommendationRequest(mode, contextId, candidatePolicy, k);
      setResponse(await provider.recommend(request));
    } catch {
      setError("The local synthetic fixture provider could not complete this example.");
    } finally {
      setLoading(false);
    }
  }

  const contextLabel =
    mode === "product_to_product"
      ? "Product similarity · fixture source"
      : mode === "synthetic_user"
        ? "Synthetic profile context · history stays private"
        : `${candidatePolicy === "warm_hybrid" ? "Warm-only" : "Content-eligible"} hybrid fixture`;

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
                    setMode(item.value);
                    setResponse(undefined);
                    setError(undefined);
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
        </fieldset>

        <div className="form-divider" />
        {mode === "product_to_product" ? (
          <label className="field-label" htmlFor="context-product">
            <span>Starting product</span>
            <select
              id="context-product"
              onChange={(event) => setProductId(event.target.value)}
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
              onChange={(event) => setUserId(event.target.value)}
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
          <fieldset className="field-label policy-fieldset">
            <legend>Candidate policy</legend>
            <label className="policy-option">
              <input
                checked={candidatePolicy === "warm_hybrid"}
                name="candidate-policy"
                onChange={() => setCandidatePolicy("warm_hybrid")}
                type="radio"
              />
              <span>
                <strong>Warm-only</strong>
                <small>Training-known catalog items</small>
              </span>
            </label>
            <label className="policy-option">
              <input
                checked={candidatePolicy === "content_eligible_hybrid"}
                name="candidate-policy"
                onChange={() => setCandidatePolicy("content_eligible_hybrid")}
                type="radio"
              />
              <span>
                <strong>Content-eligible</strong>
                <small>May include synthetic cold-item fixtures</small>
              </span>
            </label>
          </fieldset>
        )}

        <label className="field-label result-count-field" htmlFor="result-count">
          <span>Number of results</span>
          <select
            id="result-count"
            onChange={(event) => setK(Number(event.target.value))}
            value={k}
          >
            <option value={5}>5 results</option>
            <option value={10}>10 results</option>
            <option value={20}>20 results</option>
          </select>
        </label>
        <button className="button button--primary explorer-submit" disabled={loading} type="submit">
          {loading ? "Preparing fixtures…" : "Show recommendations"}
          <span aria-hidden="true">↗</span>
        </button>
        <p className="explorer-private-note">
          Local fixtures only <span aria-hidden="true">·</span> no network request
        </p>
      </form>

      <div className="explorer-results">
        <div className="explorer-results__topline">
          <span>REC · EXPLORER</span>
          <span>Schema v1</span>
        </div>
        <RecommendationResults
          contextLabel={contextLabel}
          error={error}
          loading={loading}
          response={response}
        />
      </div>
    </div>
  );
}
