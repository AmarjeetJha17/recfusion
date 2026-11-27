import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ExplorePage from "@/app/explore/page";
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
  it("describes synthetic discovery and the optional development API accurately", () => {
    render(<ExplorePage />);

    expect(
      screen.getByText(/product discovery uses invented frontend fixtures/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/optional local synthetic api mode during development/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/fixture-backed until api integration/i)).not.toBeInTheDocument();
  });

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

  it.each([
    ["product_to_product", /similarity over available product-content features/i],
    ["synthetic_user", /prior synthetic training interactions and product content/i],
    [
      "hybrid",
      /ranked synthetic collaborative and content lists.*weighted reciprocal rank fusion/i,
    ],
  ] as const)("explains the %s mode without claiming preference", async (mode, explanation) => {
    const user = userEvent.setup();
    render(<RecommendationExplorer />);
    await user.click(
      screen.getByRole("radio", { name: new RegExp(mode.replaceAll("_", " "), "i") }),
    );
    expect(screen.getByText(explanation)).toBeInTheDocument();
    expect(
      screen.getByText(/different candidate sets.*no shared score scale/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: /fixture.*offline, deterministic examples/i }),
    ).toBeChecked();
  });

  it("explains hybrid candidate policies and keeps their stable IDs visible", async () => {
    const user = userEvent.setup();
    render(<RecommendationExplorer />);
    await user.click(screen.getByRole("radio", { name: /hybrid/i }));

    expect(screen.getByText("Warm-only", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText("warm_hybrid")).toBeInTheDocument();
    expect(screen.getByText(/train-known synthetic items/i)).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /content-eligible/i }));
    expect(screen.getByText("Content-eligible", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText("content_eligible_hybrid")).toBeInTheDocument();
    expect(
      screen.getByText(/cold means no permitted synthetic training interactions/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/not a quality or inventory label/i)).toBeInTheDocument();
  });

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
    expect(
      screen.getByRole("heading", { name: /no recommendations for this synthetic request/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/0 of 5 requested recommendations/i);
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

  it("retries only the selected Local API request and does not switch to fixtures", async () => {
    const user = userEvent.setup();
    const expected = await fixtureRecommendationProvider.recommend(
      buildRecommendationRequest(
        "product_to_product",
        "synthetic-electronics-v1:item:000001",
        "warm_hybrid",
      ),
    );
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce(new Response(JSON.stringify(expected), { status: 200 }));
    render(<RecommendationExplorer />);
    await user.click(screen.getByRole("radio", { name: /local api/i }));
    await user.click(screen.getByRole("button", { name: /show recommendations/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/local api is unavailable/i);
    expect(
      screen.queryByRole("heading", { name: /fixture-backed results/i }),
    ).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: /retry request/i }));

    expect(await screen.findByRole("heading", { name: /local api results/i })).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("radio", { name: /local api/i })).toBeChecked();
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

  it("keeps fixture mode default and explicitly renders API results without a metadata join", async () => {
    const user = userEvent.setup();
    const apiResponse = await fixtureRecommendationProvider.recommend(
      buildRecommendationRequest(
        "product_to_product",
        "synthetic-electronics-v1:item:000001",
        "warm_hybrid",
      ),
    );
    const unknownResult = apiResponse.recommendations[0];
    if (!unknownResult) throw new Error("The fixture response had no recommendation.");
    unknownResult.product_id = "synthetic-electronics-v1:item:999999";
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(apiResponse), { status: 200 }));
    render(<RecommendationExplorer />);

    expect(screen.getByText(/fixture mode · offline/i)).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
    await user.click(screen.getByRole("radio", { name: /local api/i }));
    await user.click(screen.getByRole("button", { name: /show recommendations/i }));

    expect(await screen.findByRole("heading", { name: /local api results/i })).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/catalog fingerprint differs/i)).toBeInTheDocument();
    expect(
      screen.getByText(/canonical synthetic item id: synthetic-electronics-v1:item:999999/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /synthetic/i })).not.toBeInTheDocument();
  });

  it("does not let a superseded response replace newer selections", async () => {
    const user = userEvent.setup();
    const pending: Array<(value: RecommendationResponse) => void> = [];
    const provider: RecommendationProvider = {
      recommend: () =>
        new Promise((resolve) => {
          pending.push(resolve);
        }),
    };
    render(<RecommendationExplorer provider={provider} />);
    await user.click(screen.getByRole("button", { name: /show recommendations/i }));
    await user.click(screen.getByRole("radio", { name: /hybrid/i }));
    await user.click(screen.getByRole("button", { name: /show recommendations/i }));

    const hybridResponse = await fixtureRecommendationProvider.recommend(
      buildRecommendationRequest("hybrid", "synthetic-electronics-v1:user:000001", "warm_hybrid"),
    );
    const productResponse = await fixtureRecommendationProvider.recommend(
      buildRecommendationRequest(
        "product_to_product",
        "synthetic-electronics-v1:item:000001",
        "warm_hybrid",
      ),
    );
    await act(async () => pending[1]?.(hybridResponse));
    await act(async () => pending[0]?.(productResponse));

    expect(screen.getByText(/warm-only hybrid · synthetic profile 01/i)).toBeInTheDocument();
  });
});
