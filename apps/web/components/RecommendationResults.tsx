import Link from "next/link";
import { ProductArt } from "@/components/ProductArt";
import { getProduct, getProductRouteId } from "@/lib/catalog";
import type { RecommendationResponse } from "@/lib/recommendation-provider";

type RecommendationResultsProps = {
  response?: RecommendationResponse;
  loading?: boolean;
  error?: string;
  contextLabel?: string;
  presentationSource?: "fixture" | "local_api";
};

const sourceLabels: Record<string, string> = {
  tfidf_content: "Content source",
  synthetic_item_cf: "Synthetic item-CF source",
  synthetic_bpr_control: "Synthetic BPR control",
};

export function RecommendationResults({
  response,
  loading = false,
  error,
  contextLabel,
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
      <div className="empty-state empty-state--compact" role="status">
        <span className="empty-state__mark" aria-hidden="true">
          ↗
        </span>
        <h3>No recommendations for this synthetic request</h3>
        <p>
          The current synthetic example has no eligible ranked items. Nothing was added as a
          fallback.
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
        <span className="result-total">{response.result_count} items</span>
      </div>
      <p className="fixture-explanation">
        {presentationSource === "fixture"
          ? "Prewritten synthetic ordering for interface testing. It does not claim validated personalization or model quality."
          : "Synthetic local API output. The API catalog fingerprint differs from the display catalog, so this view shows canonical IDs and provenance without joining product details."}
      </p>
      <ol className="recommendation-list">
        {response.recommendations.map((recommendation) => {
          const provenance = `${recommendation.source_names
            .map((source) => sourceLabels[source])
            .join(" + ")} · ${recommendation.reason_codes[0].replaceAll("_", " ")}`;
          if (presentationSource === "local_api") {
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
                  <p className="recommendation-item__source">{provenance}</p>
                </div>
              </li>
            );
          }

          const product = getProduct(recommendation.product_id);
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
                <p className="recommendation-item__category">{product.category}</p>
                <Link href={`/products/${getProductRouteId(product)}`}>
                  {product.name ?? "Title unavailable"}
                </Link>
                <p className="recommendation-item__source">
                  {recommendation.source_names.map((source) => sourceLabels[source]).join(" + ")}
                  <span aria-hidden="true"> · </span>
                  {recommendation.reason_codes[0] === "hybrid_rrf"
                    ? "Hybrid fixture"
                    : "Content fixture"}
                </p>
              </div>
              <span className={`cohort cohort--${product.cohort}`}>
                {product.cohort === "unknown" ? "Eligibility unknown" : `${product.cohort} item`}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="response-contract-note">
        {response.mode.replaceAll("_", " ")} · {response.algorithm_id} v{response.algorithm_version}{" "}
        ·{response.candidate_policy.replaceAll("_", " ")} · contract v1
      </p>
    </section>
  );
}
