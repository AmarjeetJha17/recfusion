import { describe, expect, it, vi } from "vitest";
import { catalog } from "@/lib/catalog";
import {
  fixtureRecommendationProvider,
  type RecommendationRequest,
} from "@/lib/recommendation-provider";

const base = {
  schema_version: "recfusion.recommendation-request.v1",
  catalog_id: "synthetic-electronics-v1",
  algorithm_version: "1",
  k: 5,
  excluded_product_ids: [] as string[],
  constraints: { category: null, max_price: null },
} as const;

const requestFor = (mode: RecommendationRequest["mode"]): RecommendationRequest => {
  if (mode === "product_to_product") {
    return {
      ...base,
      mode,
      algorithm_id: "tfidf_content",
      policy_id: "content-similarity-v1",
      candidate_policy: "content_catalog",
      query: { kind: mode, product_id: catalog[0].id },
    };
  }
  if (mode === "synthetic_user") {
    return {
      ...base,
      mode,
      algorithm_id: "tfidf_content",
      policy_id: "synthetic-user-content-v1",
      candidate_policy: "content_catalog",
      query: { kind: mode, user_id: "synthetic-electronics-v1:user:000001" },
    };
  }
  return {
    ...base,
    mode,
    algorithm_id: "weighted_rrf",
    policy_id: "synthetic-hybrid-content-v1",
    candidate_policy: "content_eligible_hybrid",
    query: { kind: mode, user_id: "synthetic-electronics-v1:user:000001" },
  };
};

describe("fixture recommendation adapter", () => {
  it.each(["product_to_product", "synthetic_user", "hybrid"] as const)(
    "returns the versioned serving response for %s",
    async (mode) => {
      const response = await fixtureRecommendationProvider.recommend(requestFor(mode));

      expect(response.schema_version).toBe("recfusion.recommendation-response.v1");
      expect(response.mode).toBe(mode);
      expect(response.status).toBe("ok");
      expect(response.result_count).toBe(response.recommendations.length);
      expect(response.diagnostics.returned_count).toBe(response.result_count);
      expect(response.recommendations.every((item) => getCatalogProduct(item.product_id))).toBe(
        true,
      );
    },
  );

  it("is deterministic and never calls fetch", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const request = requestFor("hybrid");

    await expect(fixtureRecommendationProvider.recommend(request)).resolves.toEqual(
      await fixtureRecommendationProvider.recommend(request),
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  it("returns an explicit no-results contract for an ineligible fixture seed", async () => {
    const request = requestFor("product_to_product");
    request.query = {
      kind: "product_to_product",
      product_id: "synthetic-electronics-v1:item:000008",
    };

    const response = await fixtureRecommendationProvider.recommend(request);

    expect(response.status).toBe("no_results");
    expect(response.recommendations).toEqual([]);
    expect(response.result_count).toBe(0);
  });
});

function getCatalogProduct(productId: string) {
  return catalog.find((product) => product.id === productId);
}
