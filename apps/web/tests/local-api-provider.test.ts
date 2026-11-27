import { describe, expect, it, vi } from "vitest";
import { localApiRecommendationProvider } from "@/lib/local-api-provider";
import {
  fixtureRecommendationProvider,
  type RecommendationRequest,
} from "@/lib/recommendation-provider";

const request: RecommendationRequest = {
  schema_version: "recfusion.recommendation-request.v1",
  mode: "product_to_product",
  catalog_id: "synthetic-electronics-v1",
  algorithm_id: "tfidf_content",
  algorithm_version: "1",
  policy_id: "content-similarity-v1",
  candidate_policy: "content_catalog",
  k: 5,
  query: { kind: "product_to_product", product_id: "synthetic-electronics-v1:item:000001" },
  excluded_product_ids: [],
  constraints: { category: null, max_price: null },
};

describe("local synthetic API provider", () => {
  it("posts the existing v1 request only to the fixed loopback API", async () => {
    const expected = await fixtureRecommendationProvider.recommend(request);
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(expected), { status: 200 }));

    const result = await localApiRecommendationProvider.recommend(request);

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/v1/recommendations",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
        cache: "no-store",
      }),
    );
    expect(result).toEqual(expected);
  });

  it("maps typed local capacity saturation to a safe explanation", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          schema_version: "recfusion.recommendation-error.v1",
          request_id: "request-1",
          error: { code: "CONCURRENCY_LIMIT_EXCEEDED", message: "safe server message" },
        }),
        { status: 503 },
      ),
    );

    await expect(localApiRecommendationProvider.recommend(request)).rejects.toThrow(
      "temporarily at capacity",
    );
  });

  it("preserves unknown canonical IDs for safe ID-only rendering", async () => {
    const response = await fixtureRecommendationProvider.recommend(request);
    const firstRecommendation = response.recommendations[0];
    if (!firstRecommendation) throw new Error("The fixture response had no recommendation.");
    firstRecommendation.product_id = "synthetic-electronics-v1:item:999999";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(response), { status: 200 }),
    );

    const parsed = await localApiRecommendationProvider.recommend(request);
    expect(parsed.recommendations[0]).toMatchObject({
      product_id: "synthetic-electronics-v1:item:999999",
      rank: 1,
    });
  });

  it("surfaces unavailable API errors without fixture fallback", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("offline"));

    await expect(localApiRecommendationProvider.recommend(request)).rejects.toThrow(
      /switch to fixtures/,
    );
  });

  it("bounds API calls with an abort timeout", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    );
    const pending = localApiRecommendationProvider.recommend(request);
    const rejected = expect(pending).rejects.toThrow(/timed out/i);
    await vi.advanceTimersByTimeAsync(8_000);

    await rejected;
    vi.useRealTimers();
  });

  it("propagates cancellation from a superseding UI request", async () => {
    const caller = new AbortController();
    let observedSignal: AbortSignal | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          observedSignal = init?.signal as AbortSignal;
          observedSignal.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    );
    const pending = localApiRecommendationProvider.recommend(request, { signal: caller.signal });
    caller.abort();

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(observedSignal?.aborted).toBe(true);
  });
});
