import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RecommendationResults } from "@/components/RecommendationResults";
import { FIXTURE_CATALOG_FINGERPRINT } from "@/lib/fixture-manifest";
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
      product_id: "synthetic-electronics-v1:item:000001",
      rank: 1,
      source_names: ["synthetic_item_cf", "tfidf_content"],
      reason_codes: ["hybrid_rrf"],
    },
  ],
  warnings: [],
};

describe("recommendation results presentation", () => {
  it("keeps fingerprint-mismatched items ID-only without per-item cohort labels", () => {
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
    expect(screen.getByText(/synthetic-electronics-v1:item:000001/i)).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByText(/ZenBook|wireless headphones/i)).not.toBeInTheDocument();
  });

  it("joins a known API item only when catalog ID and exact asset fingerprint match", () => {
    const response: RecommendationResponse = {
      ...hybridResponse,
      catalog_fingerprint: FIXTURE_CATALOG_FINGERPRINT,
      recommendations: [
        {
          ...hybridResponse.recommendations[0],
          product_id: "synthetic-electronics-v1:item:000001",
        },
      ],
    };
    render(<RecommendationResults presentationSource="local_api" response={response} />);

    expect(
      screen.getByRole("link", { name: /synthetic laptop 16gb ram 512gb ssd/i }),
    ).toHaveAttribute("href", "/products/synthetic-electronics-v1-item-000001");
  });

  it("renders verified catalog fields while preserving rank, sources, and safe navigation", () => {
    const item = {
      ...hybridResponse.recommendations[0],
      rank: 3,
      product_id: "synthetic-electronics-v1:item:000002",
    };
    const response: RecommendationResponse = {
      ...hybridResponse,
      catalog_fingerprint: FIXTURE_CATALOG_FINGERPRINT,
      recommendations: [item],
      result_count: 1,
      diagnostics: { ...hybridResponse.diagnostics, returned_count: 1 },
    };
    render(<RecommendationResults presentationSource="local_api" response={response} />);

    expect(screen.getByLabelText("Rank 3")).toHaveTextContent("03");
    expect(
      screen.getByRole("link", { name: /synthetic laptop 8gb ram 256gb ssd/i }),
    ).toHaveAttribute("href", "/products/synthetic-electronics-v1-item-000002");
    expect(screen.getByText("invented portable computer example")).toBeInTheDocument();
    const features = screen.getByRole("list", { name: "Recorded synthetic features" });
    expect(within(features).getByText("8GB memory")).toBeInTheDocument();
    expect(within(features).getByText("256GB SSD")).toBeInTheDocument();
    expect(screen.getByText("synthetic-electronics-v1:item:000002")).toBeInTheDocument();
    expect(screen.getByText(/source attribution/i)).toBeInTheDocument();
    expect(screen.queryByText(/\$|₹|price|review|in stock|buy now/i)).not.toBeInTheDocument();
  });

  it("preserves unknown and restricted results with their original ranks and safe diagnostics", () => {
    const response: RecommendationResponse = {
      ...hybridResponse,
      catalog_fingerprint: FIXTURE_CATALOG_FINGERPRINT,
      result_count: 3,
      recommendations: [
        {
          ...hybridResponse.recommendations[0],
          rank: 1,
          product_id: "synthetic-electronics-v1:item:000099",
        },
        {
          ...hybridResponse.recommendations[0],
          rank: 2,
          product_id: "synthetic-electronics-v1:item:000010",
        },
        {
          ...hybridResponse.recommendations[0],
          rank: 3,
          product_id: "synthetic-electronics-v1:item:000009",
        },
      ],
      diagnostics: { ...hybridResponse.diagnostics, returned_count: 3 },
    };
    render(
      <RecommendationResults presentationSource="local_api" requestedK={5} response={response} />,
    );

    const list = screen.getByRole("list", { name: "Recommendations" });
    const items = Array.from(list.children) as HTMLElement[];
    expect(items).toHaveLength(3);
    expect(within(items[0]).getByLabelText("Rank 1")).toHaveTextContent("01");
    expect(within(items[0]).getByText(/item:000099/i)).toBeInTheDocument();
    expect(within(items[1]).getByText(/restricted result was returned/i)).toBeInTheDocument();
    expect(within(items[1]).queryByText(/item:000010/i)).not.toBeInTheDocument();
    expect(within(items[1]).queryByRole("link")).not.toBeInTheDocument();
    expect(within(items[2]).getByText(/policy integrity issue/i)).toBeInTheDocument();
    expect(within(items[2]).queryByText(/synthetic laptop|invented/i)).not.toBeInTheDocument();
    expect(screen.getByText(/3 of 5 requested/i)).toBeInTheDocument();
  });

  it("withholds incomplete product metadata when the returned product is not display eligible", () => {
    const response: RecommendationResponse = {
      ...hybridResponse,
      catalog_fingerprint: FIXTURE_CATALOG_FINGERPRINT,
      recommendations: [
        {
          ...hybridResponse.recommendations[0],
          product_id: "synthetic-electronics-v1:item:000008",
        },
      ],
    };
    render(<RecommendationResults presentationSource="local_api" response={response} />);

    expect(screen.getByText(/policy integrity issue/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/title unavailable|category unavailable|description unavailable/i),
    ).not.toBeInTheDocument();
  });

  it("states the actual returned count and explains a short list without adding items", () => {
    render(
      <RecommendationResults
        presentationSource="local_api"
        requestedK={5}
        response={hybridResponse}
      />,
    );

    expect(screen.getByText(/1 of 5 requested/i)).toBeInTheDocument();
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
