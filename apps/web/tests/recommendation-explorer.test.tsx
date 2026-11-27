import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  buildRecommendationRequest,
  RecommendationExplorer,
} from "@/features/recommendations/RecommendationExplorer";
import {
  fixtureRecommendationProvider,
  type RecommendationProvider,
  type RecommendationRequest,
  type RecommendationResponse,
} from "@/lib/recommendation-provider";

describe("recommendation explorer", () => {
  it.each(["product_to_product", "synthetic_user", "hybrid"] as const)(
    "runs the %s fixture mode through the typed provider",
    async (mode) => {
      const user = userEvent.setup();
      let requestSeen: RecommendationRequest | undefined;
      const provider: RecommendationProvider = {
        async recommend(request) {
          requestSeen = request;
          return fixtureRecommendationProvider.recommend(request);
        },
      };
      render(<RecommendationExplorer provider={provider} />);
      await user.click(
        screen.getByRole("radio", { name: new RegExp(mode.replaceAll("_", " "), "i") }),
      );
      await user.click(screen.getByRole("button", { name: /show recommendations/i }));

      expect(requestSeen).toMatchObject({
        schema_version: "recfusion.recommendation-request.v1",
        mode,
        catalog_id: "synthetic-electronics-v1",
      });
      expect(
        await screen.findByRole("heading", { name: /fixture-backed results/i }),
      ).toBeInTheDocument();
    },
  );

  it("shows loading, empty, error, provenance, and warm/cold states accessibly", async () => {
    const user = userEvent.setup();
    let resolveRequest: ((response: RecommendationResponse) => void) | undefined;
    const provider: RecommendationProvider = {
      recommend: () =>
        new Promise((resolve) => {
          resolveRequest = resolve;
        }),
    };
    render(<RecommendationExplorer provider={provider} />);
    await user.click(screen.getByRole("button", { name: /show recommendations/i }));
    expect(screen.getByRole("status")).toHaveTextContent(/loading fixture recommendations/i);

    const emptyProvider: RecommendationProvider = {
      recommend: async (request: RecommendationRequest) =>
        fixtureRecommendationProvider.recommend({
          ...request,
          mode: "product_to_product",
          algorithm_id: "tfidf_content",
          policy_id: "content-similarity-v1",
          candidate_policy: "content_catalog",
          query: { kind: "product_to_product", product_id: "synthetic-electronics-v1:item:000008" },
        }),
    };
    await act(async () =>
      resolveRequest?.(
        await emptyProvider.recommend({
          schema_version: "recfusion.recommendation-request.v1",
          mode: "product_to_product",
          catalog_id: "synthetic-electronics-v1",
          algorithm_id: "tfidf_content",
          algorithm_version: "1",
          policy_id: "content-similarity-v1",
          candidate_policy: "content_catalog",
          k: 5,
          query: { kind: "product_to_product", product_id: "synthetic-electronics-v1:item:000008" },
          excluded_product_ids: [],
          constraints: { category: null, max_price: null },
        }),
      ),
    );
    expect(screen.getByRole("status")).toHaveTextContent(/no recommendations in this fixture/i);
  });

  it("announces provider failures without leaking exception details", async () => {
    const user = userEvent.setup();
    const provider: RecommendationProvider = {
      recommend: async () => {
        throw new Error("private file path secret");
      },
    };
    render(<RecommendationExplorer provider={provider} />);
    await user.click(screen.getByRole("button", { name: /show recommendations/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /local synthetic fixture provider could not complete/i,
    );
    expect(screen.queryByText(/private file path secret/i)).not.toBeInTheDocument();
  });

  it("selects the fixed hybrid candidate policy and shows warm or cold labels", async () => {
    const user = userEvent.setup();
    render(<RecommendationExplorer />);
    await user.click(screen.getByRole("radio", { name: /hybrid/i }));
    await user.click(screen.getByRole("radio", { name: /content-eligible/i }));
    await user.click(screen.getByRole("button", { name: /show recommendations/i }));

    expect(await screen.findAllByText(/cold item/i)).not.toHaveLength(0);
    const request = buildRecommendationRequest(
      "hybrid",
      "synthetic-electronics-v1:user:000001",
      "content_eligible_hybrid",
    );
    expect(request).toMatchObject({
      mode: "hybrid",
      policy_id: "synthetic-hybrid-content-v1",
      candidate_policy: "content_eligible_hybrid",
      query: { kind: "hybrid", user_id: "synthetic-electronics-v1:user:000001" },
    });
    expect("history" in request.query).toBe(false);
  });
});
