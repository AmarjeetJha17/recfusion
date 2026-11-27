import fixtures from "@/features/recommendations/recommendation-fixtures.json";
import { CATALOG_ID, getProduct, type ProductCategory } from "@/lib/catalog";
import { FIXTURE_ARTIFACT_FINGERPRINT, FIXTURE_CATALOG_FINGERPRINT } from "@/lib/fixture-manifest";

export const REQUEST_SCHEMA = "recfusion.recommendation-request.v1" as const;
export const RESPONSE_SCHEMA = "recfusion.recommendation-response.v1" as const;
export const ERROR_SCHEMA = "recfusion.recommendation-error.v1" as const;

export type RecommendationMode = "product_to_product" | "synthetic_user" | "hybrid";
export type CandidatePolicy = "content_catalog" | "warm_hybrid" | "content_eligible_hybrid";
export type SourceName = "tfidf_content" | "synthetic_item_cf" | "synthetic_bpr_control";
export type ReasonCode = "content_similarity" | "hybrid_rrf";

type ProductQuery = { kind: "product_to_product"; product_id: string };
type UserQuery = {
  kind: "synthetic_user" | "hybrid";
  user_id: string;
  target_product_id?: string | null;
};

export type RecommendationRequest = {
  schema_version: typeof REQUEST_SCHEMA;
  mode: RecommendationMode;
  catalog_id: typeof CATALOG_ID;
  algorithm_id: "tfidf_content" | "weighted_rrf";
  algorithm_version: "1";
  policy_id:
    | "content-similarity-v1"
    | "synthetic-user-content-v1"
    | "synthetic-hybrid-warm-v1"
    | "synthetic-hybrid-content-v1";
  candidate_policy: CandidatePolicy;
  k: number;
  query: ProductQuery | UserQuery;
  excluded_product_ids: string[];
  constraints: {
    category: ProductCategory | null;
    max_price: { amount: string; currency: string } | null;
  };
};

export type RecommendationItem = {
  product_id: string;
  rank: number;
  source_names: SourceName[];
  reason_codes: ReasonCode[];
};

export type RecommendationResponse = {
  schema_version: typeof RESPONSE_SCHEMA;
  request_id: string;
  mode: RecommendationMode;
  algorithm_id: RecommendationRequest["algorithm_id"];
  algorithm_version: "1";
  candidate_policy: CandidatePolicy;
  policy_id: RecommendationRequest["policy_id"];
  catalog_id: typeof CATALOG_ID;
  catalog_fingerprint: string;
  artifact_fingerprint: string;
  status: "ok" | "no_results";
  result_count: number;
  diagnostics: {
    candidate_count: number;
    eligible_count: number;
    returned_count: number;
    history_event_count: number;
    seen_exclusion_count: number;
  };
  recommendations: RecommendationItem[];
  warnings: string[];
};

export type RecommendationProvider = {
  recommend(
    request: RecommendationRequest,
    options?: { signal?: AbortSignal },
  ): Promise<RecommendationResponse>;
};

type FixtureCandidate = {
  id: string;
  sources: SourceName[];
  reason: ReasonCode;
};
type FixtureList = {
  candidates: FixtureCandidate[];
  candidate_count: number;
  history_count: number;
  seen_count: number;
};
type HybridFixtureList = { warm: FixtureList; content: FixtureList };

const productResults = fixtures.product_results as Record<string, FixtureList>;
const userResults = fixtures.user_results as Record<string, FixtureList>;
const hybridResults = fixtures.hybrid_results as Record<string, HybridFixtureList>;

if (fixtures.schema_version !== "recfusion.synthetic-recommendation-fixtures.v1") {
  throw new Error("The synthetic recommendation fixture version is unsupported.");
}

export const fixtureRecommendationProvider: RecommendationProvider = Object.freeze({
  async recommend(request) {
    validateRequest(request);
    const reference =
      request.query.kind === "product_to_product"
        ? request.query.product_id.slice(-6)
        : request.query.user_id.slice(-6);
    const selected =
      request.mode === "product_to_product"
        ? productResults[reference]
        : request.mode === "synthetic_user"
          ? userResults[reference]
          : hybridResults[reference]?.[
              request.candidate_policy === "warm_hybrid" ? "warm" : "content"
            ];
    const candidateSet = selected ?? {
      candidates: [],
      candidate_count: 0,
      history_count: 0,
      seen_count: 0,
    };
    const queryProduct =
      request.query.kind === "product_to_product"
        ? request.query.product_id
        : request.query.target_product_id;
    const recommendations = candidateSet.candidates
      .map((candidate) => ({
        ...candidate,
        product_id: `synthetic-electronics-v1:item:${candidate.id}`,
      }))
      .filter((candidate) => candidate.product_id !== queryProduct)
      .filter((candidate) => !request.excluded_product_ids.includes(candidate.product_id))
      .filter((candidate) => {
        const product = getProduct(candidate.product_id);
        if (!product) return false;
        return (
          product.recommendationEligible &&
          (request.candidate_policy !== "warm_hybrid" || product.cohort === "warm") &&
          (!request.constraints.category || product.category === request.constraints.category)
        );
      })
      .slice(0, request.k)
      .map((candidate, index) => ({
        product_id: candidate.product_id,
        rank: index + 1,
        source_names: [...candidate.sources],
        reason_codes: [candidate.reason],
      }));
    const response: RecommendationResponse = {
      schema_version: RESPONSE_SCHEMA,
      request_id: `fixture-${request.mode}-${reference}`,
      mode: request.mode,
      algorithm_id: request.algorithm_id,
      algorithm_version: request.algorithm_version,
      candidate_policy: request.candidate_policy,
      policy_id: request.policy_id,
      catalog_id: CATALOG_ID,
      catalog_fingerprint: FIXTURE_CATALOG_FINGERPRINT,
      artifact_fingerprint: FIXTURE_ARTIFACT_FINGERPRINT,
      status: recommendations.length ? "ok" : "no_results",
      result_count: recommendations.length,
      diagnostics: {
        candidate_count: candidateSet.candidate_count,
        eligible_count: Math.min(candidateSet.candidate_count, recommendations.length),
        returned_count: recommendations.length,
        history_event_count: candidateSet.history_count,
        seen_exclusion_count: candidateSet.seen_count,
      },
      recommendations,
      warnings: ["fixture_backed_demo"],
    };
    return parseRecommendationResponse(response);
  },
});

export function parseRecommendationResponse(value: unknown): RecommendationResponse {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "schema_version",
      "request_id",
      "mode",
      "algorithm_id",
      "algorithm_version",
      "candidate_policy",
      "policy_id",
      "catalog_id",
      "catalog_fingerprint",
      "artifact_fingerprint",
      "status",
      "result_count",
      "diagnostics",
      "recommendations",
      "warnings",
    ])
  ) {
    throw new Error("The recommendation response shape is invalid.");
  }
  if (value.schema_version !== RESPONSE_SCHEMA) {
    throw new Error("The recommendation response version is unsupported.");
  }
  if (
    typeof value.request_id !== "string" ||
    !value.request_id ||
    value.request_id.length > 64 ||
    value.catalog_id !== CATALOG_ID ||
    !isHexFingerprint(value.catalog_fingerprint) ||
    !isHexFingerprint(value.artifact_fingerprint) ||
    !isMode(value.mode) ||
    !isSourceAlgorithm(value.algorithm_id) ||
    value.algorithm_version !== "1" ||
    !isCandidatePolicy(value.candidate_policy) ||
    !isPolicy(value.policy_id) ||
    !Array.isArray(value.recommendations) ||
    !Array.isArray(value.warnings) ||
    !value.warnings.every((warning) => typeof warning === "string" && warning.length <= 80) ||
    !isRecord(value.diagnostics) ||
    !hasExactKeys(value.diagnostics, [
      "candidate_count",
      "eligible_count",
      "returned_count",
      "history_event_count",
      "seen_exclusion_count",
    ])
  ) {
    throw new Error("The recommendation response does not match the v1 contract.");
  }
  const diagnostics = value.diagnostics;
  if (
    !isNonNegativeInteger(diagnostics.candidate_count) ||
    !isNonNegativeInteger(diagnostics.eligible_count) ||
    !isNonNegativeInteger(diagnostics.returned_count) ||
    !isNonNegativeInteger(diagnostics.history_event_count) ||
    !isNonNegativeInteger(diagnostics.seen_exclusion_count) ||
    diagnostics.eligible_count > diagnostics.candidate_count ||
    value.recommendations.length > 20 ||
    value.result_count !== value.recommendations.length ||
    !isNonNegativeInteger(value.result_count) ||
    diagnostics.returned_count !== value.result_count ||
    (value.status !== "ok" && value.status !== "no_results") ||
    value.status !== (value.result_count ? "ok" : "no_results")
  ) {
    throw new Error("The recommendation response counts or status are invalid.");
  }
  value.recommendations.forEach((item, index) => {
    if (
      !isRecord(item) ||
      !hasExactKeys(item, ["product_id", "rank", "source_names", "reason_codes"]) ||
      typeof item.product_id !== "string" ||
      !/^synthetic-electronics-v1:item:[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(item.product_id) ||
      item.rank !== index + 1 ||
      !Array.isArray(item.source_names) ||
      !item.source_names.length ||
      item.source_names.some((source) => !isSource(source)) ||
      !Array.isArray(item.reason_codes) ||
      !item.reason_codes.length ||
      item.reason_codes.some((reason) => !isReason(reason))
    ) {
      throw new Error("The recommendation item is invalid.");
    }
  });
  return value as RecommendationResponse;
}

function validateRequest(request: RecommendationRequest): void {
  if (
    request.schema_version !== REQUEST_SCHEMA ||
    request.catalog_id !== CATALOG_ID ||
    !Number.isInteger(request.k) ||
    request.k < 1 ||
    request.k > 20 ||
    request.excluded_product_ids.length > 64 ||
    request.mode !== request.query.kind
  ) {
    throw new Error("The recommendation request is invalid.");
  }
  const validPolicy =
    (request.mode === "product_to_product" &&
      request.policy_id === "content-similarity-v1" &&
      request.algorithm_id === "tfidf_content" &&
      request.candidate_policy === "content_catalog") ||
    (request.mode === "synthetic_user" &&
      request.policy_id === "synthetic-user-content-v1" &&
      request.algorithm_id === "tfidf_content" &&
      request.candidate_policy === "content_catalog") ||
    (request.mode === "hybrid" &&
      request.algorithm_id === "weighted_rrf" &&
      ((request.policy_id === "synthetic-hybrid-warm-v1" &&
        request.candidate_policy === "warm_hybrid") ||
        (request.policy_id === "synthetic-hybrid-content-v1" &&
          request.candidate_policy === "content_eligible_hybrid")));
  if (!validPolicy) throw new Error("The recommendation policy is unsupported.");
}

function hasExactKeys(value: Record<string, unknown>, expected: string[]): boolean {
  const keys = Object.keys(value).sort();
  return (
    keys.length === expected.length &&
    keys.every((key, index) => key === [...expected].sort()[index])
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isHexFingerprint(value: unknown): value is string {
  return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isMode(value: unknown): value is RecommendationMode {
  return value === "product_to_product" || value === "synthetic_user" || value === "hybrid";
}

function isSourceAlgorithm(value: unknown): value is RecommendationRequest["algorithm_id"] {
  return value === "tfidf_content" || value === "weighted_rrf";
}

function isCandidatePolicy(value: unknown): value is CandidatePolicy {
  return (
    value === "content_catalog" || value === "warm_hybrid" || value === "content_eligible_hybrid"
  );
}

function isPolicy(value: unknown): value is RecommendationRequest["policy_id"] {
  return (
    value === "content-similarity-v1" ||
    value === "synthetic-user-content-v1" ||
    value === "synthetic-hybrid-warm-v1" ||
    value === "synthetic-hybrid-content-v1"
  );
}

function isSource(value: unknown): value is SourceName {
  return (
    value === "tfidf_content" || value === "synthetic_item_cf" || value === "synthetic_bpr_control"
  );
}

function isReason(value: unknown): value is ReasonCode {
  return value === "content_similarity" || value === "hybrid_rrf";
}
