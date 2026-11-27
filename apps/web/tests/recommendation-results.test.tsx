import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RecommendationResults } from "@/components/RecommendationResults";
import type { RecommendationResponse } from "@/lib/recommendation-provider";

const hybridResponse: RecommendationResponse = {
  schema_version: "recfusion.recommendation-response.v1",
  request_id: "request-synthetic-01",
  mode: "hybrid",
  algorithm_id: "weighted_rrf",
  algorithm_version: "1",
  candidate_policy: "content_eligible_hybrid",
  policy_id: "synthetic-hybrid-content-v1",
  catalog_id: "synthetic-electronics-v1",
  catalog_fingerprint: "catalog-fingerprint-test",
  artifact_fingerprint: "artifact-fingerprint-test",
  status: "ok",
  result_count: 1,
  diagnostics: {
    candidate_count: 1,
    eligible_count: 1,
    returned_count: 1,
    history_event_count: 0,
    seen_exclusion_count: 0,
  },
  recommendations: [
    {
      product_id: "synthetic-electronics-v1:item:000099",
      rank: 1,
      source_names: ["synthetic_item_cf", "tfidf_content"],
      reason_codes: ["hybrid_rrf"],
    },
  ],
  warnings: [],
};

describe("recommendation results presentation", () => {
  it("shows v1 provenance without treating it as a causal explanation or item cohort", () => {
    render(
      <RecommendationResults
        presentationSource="local_api"
        requestedK={5}
        response={hybridResponse}
      />,
    );

    expect(screen.getByText(/weighted_rrf v1/i)).toBeInTheDocument();
    expect(screen.getByText(/content-eligible hybrid/i)).toBeInTheDocument();
    expect(screen.getByText(/synthetic-hybrid-content-v1/i)).toBeInTheDocument();
    expect(screen.getByText(/catalog-fingerprint-test/i)).toBeInTheDocument();
    expect(screen.getByText(/artifact-fingerprint-test/i)).toBeInTheDocument();
    expect(screen.getByText(/synthetic item-cf/i)).toBeInTheDocument();
    expect(screen.getByText(/weighted rrf over source-list positions/i)).toBeInTheDocument();
    expect(screen.getByText(/source membership does not explain preference/i)).toBeInTheDocument();
    expect(
      screen.getByText(/per-item warm\/cold status: not provided by api v1/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/canonical synthetic item id: synthetic-electronics-v1:item:000099/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByText(/ZenBook|wireless headphones/i)).not.toBeInTheDocument();
  });

  it("states the actual returned count and explains a short list without adding items", () => {
    render(
      <RecommendationResults
        presentationSource="local_api"
        requestedK={5}
        response={hybridResponse}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(/1 of 5 requested/i);
    expect(
      screen.getByText(/available eligible candidates can produce a shorter list/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("list", { name: "Recommendations" }).querySelectorAll(":scope > li"),
    ).toHaveLength(1);
  });

  it("distinguishes a valid empty response from an unavailable request", () => {
    const emptyResponse: RecommendationResponse = {
      ...hybridResponse,
      status: "no_results",
      result_count: 0,
      recommendations: [],
      diagnostics: { ...hybridResponse.diagnostics, returned_count: 0 },
      warnings: ["no_eligible_results"],
    };
    render(
      <RecommendationResults
        presentationSource="local_api"
        requestedK={5}
        response={emptyResponse}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(/0 of 5 requested/i);
    expect(screen.getByRole("status")).toHaveTextContent(/request completed/i);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
  });

  it("omits optional provenance fields when the response does not provide them", () => {
    const responseWithoutOptionalFields: RecommendationResponse = {
      ...hybridResponse,
      request_id: "",
      catalog_fingerprint: "",
      artifact_fingerprint: "",
    };
    render(
      <RecommendationResults
        presentationSource="local_api"
        response={responseWithoutOptionalFields}
      />,
    );

    const provenance = within(screen.getByLabelText("Recommendation provenance"));
    expect(provenance.getByText("synthetic-electronics-v1")).toBeInTheDocument();
    expect(provenance.queryByText(/fingerprint/i)).not.toBeInTheDocument();
    expect(provenance.queryByText(/request id/i)).not.toBeInTheDocument();
  });
});
