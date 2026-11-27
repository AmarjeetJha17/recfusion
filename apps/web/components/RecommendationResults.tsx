import Link from "next/link";
import { ProductArt } from "@/components/ProductArt";
import {
  RecommendationItemProvenance,
  RecommendationProvenance,
} from "@/components/RecommendationProvenance";
import { CATALOG_ID, getProduct, getProductRouteId } from "@/lib/catalog";
import { FIXTURE_CATALOG_FINGERPRINT } from "@/lib/fixture-manifest";
import type { RecommendationResponse } from "@/lib/recommendation-provider";

type RecommendationResultsProps = {
  response?: RecommendationResponse;
  loading?: boolean;
  error?: string;
  contextLabel?: string;
  requestedK?: number;
  onRetry?: () => void;
  presentationSource?: "fixture" | "local_api";
};

export function RecommendationResults({
  response,
  loading = false,
  error,
  contextLabel,
  requestedK,
  onRetry,
  presentationSource = "fixture",
}: RecommendationResultsProps) {
  if (loading) {
    return (
      <div aria-busy="true" className="recommendation-state" role="status">
        <span className="loading-dot" aria-hidden="true" />
        <span>
          Loading {presentationSource === "fixture" ? "fixture" : "local API"} recommendations…
        </span>
      </div>
    );
  }
  if (error) {
    return (
      <div className="recommendation-error" role="alert">
        <strong>Recommendations unavailable.</strong>
        <span>{error}</span>
        {onRetry && (
          <button
            className="button button--secondary recommendation-retry"
            onClick={onRetry}
            type="button"
          >
            Retry request
          </button>
        )}
      </div>
    );
  }
  if (!response) {
    return (
      <div className="recommendation-placeholder" role="status">
        <span className="placeholder-number">01</span>
        <p>Choose a synthetic context and run the selected recommendation source.</p>
      </div>
    );
  }
  if (response.status === "no_results") {
    return (
      <div className="empty-state empty-state--compact">
        <span className="empty-state__mark" aria-hidden="true">
          ↗
        </span>
        <p aria-live="polite" className="recommendation-result-count" role="status">
          {requestedK === undefined
            ? "Request completed: 0 recommendations returned."
            : `Request completed: 0 of ${requestedK} requested recommendations returned.`}
        </p>
        <h3>No recommendations for this synthetic request</h3>
        <p>
          The request completed successfully, but the active policy and available eligible
          candidates produced no ranked items. Nothing was added as a fallback.
        </p>
      </div>
    );
  }

  return (
    <section aria-labelledby="recommendation-results-heading" className="recommendation-output">
      <div className="recommendation-output__heading">
        <div>
          <p className="eyebrow">{contextLabel ?? "Static fixture ordering"}</p>
          <h3 id="recommendation-results-heading">
            {presentationSource === "fixture" ? "Fixture-backed results" : "Local API results"}
          </h3>
        </div>
        <span className="result-total">{response.result_count} returned</span>
      </div>
      <p aria-live="polite" className="recommendation-result-count" role="status">
        {requestedK === undefined
          ? `${response.result_count} recommendations returned.`
          : `${response.result_count} of ${requestedK} requested recommendations returned.`}
      </p>
      <p className="fixture-explanation">
        {presentationSource === "fixture"
          ? "Prewritten synthetic ordering for interface testing. It does not claim validated personalization or model quality."
          : "Synthetic local API output. Product details appear only when the API catalog identity and exact asset fingerprint match this display catalog."}
      </p>
      {requestedK !== undefined && response.result_count < requestedK && (
        <p className="recommendation-short-list-note">
          The active policy and available eligible candidates can produce a shorter list. No filler
          items are added.
        </p>
      )}
      <RecommendationProvenance response={response} />
      <ol aria-label="Recommendations" className="recommendation-list">
        {response.recommendations.map((recommendation) => {
          const catalogMatches =
            response.catalog_id === CATALOG_ID &&
            response.catalog_fingerprint === FIXTURE_CATALOG_FINGERPRINT;
          if (presentationSource === "local_api" && !catalogMatches) {
            return (
              <li className="recommendation-item" key={recommendation.product_id}>
                <span
                  aria-label={`Rank ${recommendation.rank}`}
                  className="recommendation-item__rank"
                >
                  {String(recommendation.rank).padStart(2, "0")}
                </span>
                <div className="recommendation-item__body">
                  <p className="recommendation-item__canonical-id">
                    Canonical synthetic item ID: {recommendation.product_id}
                  </p>
                  <RecommendationItemProvenance recommendation={recommendation} />
                </div>
              </li>
            );
          }

          const product = getProduct(recommendation.product_id);
          if (!product && presentationSource === "local_api") {
            return (
              <li className="recommendation-item" key={recommendation.product_id}>
                <span
                  aria-label={`Rank ${recommendation.rank}`}
                  className="recommendation-item__rank"
                >
                  {String(recommendation.rank).padStart(2, "0")}
                </span>
                <div className="recommendation-item__body">
                  <p className="recommendation-item__canonical-id">
                    Canonical synthetic item ID: {recommendation.product_id}
                  </p>
                  <RecommendationItemProvenance recommendation={recommendation} />
                </div>
              </li>
            );
          }
          if (!product) return null;
          return (
            <li className="recommendation-item" key={recommendation.product_id}>
              <span
                aria-label={`Rank ${recommendation.rank}`}
                className="recommendation-item__rank"
              >
                {String(recommendation.rank).padStart(2, "0")}
              </span>
              <ProductArt category={product.category} />
              <div className="recommendation-item__body">
                <p className="recommendation-item__category">
                  {product.category ?? "Category unavailable"}
                </p>
                <Link href={`/products/${getProductRouteId(product)}`}>
                  {product.name ?? "Title unavailable"}
                </Link>
                <RecommendationItemProvenance recommendation={recommendation} />
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
