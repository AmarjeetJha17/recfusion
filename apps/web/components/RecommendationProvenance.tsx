import type {
  CandidatePolicy,
  RecommendationItem,
  RecommendationResponse,
  SourceName,
} from "@/lib/recommendation-provider";

const algorithmLabels: Record<RecommendationResponse["algorithm_id"], string> = {
  tfidf_content: "TF-IDF product-content retrieval",
  weighted_rrf: "Weighted Reciprocal Rank Fusion",
};

const candidatePolicyLabels: Record<CandidatePolicy, string> = {
  content_catalog: "Content-eligible catalog",
  warm_hybrid: "Warm-only",
  content_eligible_hybrid: "Content-eligible hybrid",
};

const sourceLabels: Record<SourceName, string> = {
  tfidf_content: "Product-content ranking list",
  synthetic_item_cf: "Synthetic item-CF ranking list",
  synthetic_bpr_control: "Synthetic BPR control ranking list",
};

const reasonLabels: Record<RecommendationItem["reason_codes"][number], string> = {
  content_similarity: "Retrieved using product-content similarity.",
  hybrid_rrf: "Ranked by weighted RRF over source-list positions.",
};

const modeLabels: Record<RecommendationResponse["mode"], string> = {
  product_to_product: "Product to product",
  synthetic_user: "Synthetic-user content",
  hybrid: "Hybrid",
};

export function formatCandidatePolicy(policy: CandidatePolicy): string {
  return candidatePolicyLabels[policy];
}

export function RecommendationProvenance({ response }: { response: RecommendationResponse }) {
  return (
    <>
      <dl aria-label="Recommendation provenance" className="recommendation-provenance">
        <div>
          <dt>Mode</dt>
          <dd>{modeLabels[response.mode]}</dd>
        </div>
        <div>
          <dt>Algorithm</dt>
          <dd>
            <span>{algorithmLabels[response.algorithm_id]}</span>
            <code>
              {response.algorithm_id} v{response.algorithm_version}
            </code>
          </dd>
        </div>
        <div>
          <dt>Candidate policy</dt>
          <dd>
            <span>{candidatePolicyLabels[response.candidate_policy]}</span>
            <code>{response.candidate_policy}</code>
            <code>{response.policy_id}</code>
          </dd>
        </div>
        <div>
          <dt>Catalog</dt>
          <dd>
            <code>{response.catalog_id}</code>
            {response.catalog_fingerprint && (
              <code>Catalog fingerprint: {response.catalog_fingerprint}</code>
            )}
          </dd>
        </div>
        {response.artifact_fingerprint && (
          <div>
            <dt>Artifact fingerprint</dt>
            <dd>
              <code>{response.artifact_fingerprint}</code>
            </dd>
          </div>
        )}
        {response.request_id && (
          <div>
            <dt>Request ID</dt>
            <dd>
              <code>{response.request_id}</code>
            </dd>
          </div>
        )}
      </dl>
      <p className="recommendation-provenance-note">
        Source membership does not explain preference or establish causation; it shows which ranked
        lists contained an item. Different modes use different candidate sets and do not share a
        comparable score scale.
      </p>
    </>
  );
}

export function RecommendationItemProvenance({
  recommendation,
}: {
  recommendation: RecommendationItem;
}) {
  return (
    <div className="recommendation-item__provenance">
      <div>
        <span className="recommendation-item__provenance-label">Source attribution</span>
        {recommendation.source_names.length > 0 ? (
          <ul aria-label="Contributing ranked source lists" className="source-attribution-list">
            {recommendation.source_names.map((source) => (
              <li key={source}>
                <span>{sourceLabels[source]}</span>
                <code>{source}</code>
              </li>
            ))}
          </ul>
        ) : (
          <p>Source attribution not provided.</p>
        )}
      </div>
      <div>
        <span className="recommendation-item__provenance-label">Reason code</span>
        {recommendation.reason_codes.length > 0 ? (
          <ul aria-label="Safe reason codes" className="reason-code-list">
            {recommendation.reason_codes.map((reason) => (
              <li key={reason}>
                <span>{reasonLabels[reason]}</span>
                <code>{reason}</code>
              </li>
            ))}
          </ul>
        ) : (
          <p>Reason code not provided.</p>
        )}
      </div>
    </div>
  );
}
