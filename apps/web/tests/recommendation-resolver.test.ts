import { describe, expect, it } from "vitest";
import { allCatalogProducts, CATALOG_ID, type Product } from "@/lib/catalog";
import { FIXTURE_CATALOG_FINGERPRINT } from "@/lib/fixture-manifest";
import type { RecommendationItem, RecommendationResponse } from "@/lib/recommendation-provider";
import { resolveRecommendationProduct } from "@/lib/recommendation-resolver";

const recommendation = (productId: string): RecommendationItem => ({
  product_id: productId,
  rank: 3,
  source_names: ["tfidf_content", "synthetic_item_cf"],
  reason_codes: ["hybrid_rrf"],
});

const responseFor = (
  item: RecommendationItem,
  overrides: Partial<
    Pick<RecommendationResponse, "catalog_id" | "catalog_fingerprint" | "recommendations">
  > = {},
) => ({
  catalog_id: CATALOG_ID,
  catalog_fingerprint: FIXTURE_CATALOG_FINGERPRINT,
  recommendations: [item],
  ...overrides,
});

const trustedCatalog = {
  catalogId: CATALOG_ID,
  assetFingerprint: FIXTURE_CATALOG_FINGERPRINT,
  products: allCatalogProducts,
};

function findCatalogProduct(id: string): Product {
  const product = allCatalogProducts.find((candidate) => candidate.id === id);
  if (!product) throw new Error(`Missing test catalog product: ${id}`);
  return product;
}

describe("resolveRecommendationProduct", () => {
  it("resolves exact catalog identities and a round-tripped product route", () => {
    const item = recommendation("synthetic-electronics-v1:item:000002");
    const resolved = resolveRecommendationProduct(item, responseFor(item), trustedCatalog);

    expect(resolved.state).toBe("resolved");
    if (resolved.state !== "resolved") return;
    expect(resolved.product.id).toBe(item.product_id);
    expect(resolved.originalRecommendation).toBe(item);
    expect(resolved.href).toBe(`/products/${item.product_id.replaceAll(":", "-")}`);
  });

  it("keeps metadata withheld when the catalog fingerprint differs", () => {
    const item = recommendation("synthetic-electronics-v1:item:000002");
    const resolved = resolveRecommendationProduct(
      item,
      responseFor(item, { catalog_fingerprint: "0".repeat(64) }),
      trustedCatalog,
    );

    expect(resolved).toMatchObject({ state: "unresolved", reason: "catalog_mismatch", href: null });
  });

  it("keeps an unknown canonical ID as a safe ID-only unresolved result", () => {
    const item = recommendation("synthetic-electronics-v1:item:000099");
    const resolved = resolveRecommendationProduct(item, responseFor(item), trustedCatalog);

    expect(resolved).toMatchObject({
      state: "unresolved",
      reason: "unknown_product_id",
      href: null,
    });
  });

  it("rejects duplicate catalog membership as ambiguous", () => {
    const item = recommendation("synthetic-electronics-v1:item:000002");
    const product = findCatalogProduct(item.product_id);
    const resolved = resolveRecommendationProduct(item, responseFor(item), {
      ...trustedCatalog,
      products: [product, product],
    });

    expect(resolved).toMatchObject({
      state: "unresolved",
      reason: "ambiguous_product_id",
      href: null,
    });
  });

  it("rejects repeated recommendation IDs as ambiguous without dropping either result", () => {
    const item = recommendation("synthetic-electronics-v1:item:000002");
    const resolved = resolveRecommendationProduct(
      item,
      responseFor(item, { recommendations: [item, { ...item, rank: 4 }] }),
      trustedCatalog,
    );

    expect(resolved).toMatchObject({
      state: "unresolved",
      reason: "ambiguous_product_id",
      href: null,
    });
    expect(resolved.originalRecommendation).toBe(item);
  });

  it("withholds all product details for hidden catalog records", () => {
    const item = recommendation("synthetic-electronics-v1:item:000010");
    const resolved = resolveRecommendationProduct(item, responseFor(item), trustedCatalog);

    expect(resolved).toMatchObject({
      state: "unresolved",
      reason: "restricted_hidden",
      href: null,
    });
    expect(resolved).not.toHaveProperty("product");
  });

  it("keeps hidden record identity suppressed when the response repeats its ID", () => {
    const item = recommendation("synthetic-electronics-v1:item:000010");
    const resolved = resolveRecommendationProduct(
      item,
      responseFor(item, { recommendations: [item, { ...item, rank: 4 }] }),
      trustedCatalog,
    );

    expect(resolved).toMatchObject({
      state: "unresolved",
      reason: "restricted_hidden",
      canonicalId: null,
      href: null,
    });
  });

  it("reports returned ineligible records as policy integrity issues", () => {
    const item = recommendation("synthetic-electronics-v1:item:000009");
    const resolved = resolveRecommendationProduct(item, responseFor(item), trustedCatalog);

    expect(resolved).toMatchObject({
      state: "unresolved",
      reason: "policy_integrity_issue",
      href: null,
    });
    expect(resolved).not.toHaveProperty("product");
  });

  it("reports a repeated ineligible record as a policy integrity issue", () => {
    const item = recommendation("synthetic-electronics-v1:item:000009");
    const resolved = resolveRecommendationProduct(
      item,
      responseFor(item, { recommendations: [item, { ...item, rank: 4 }] }),
      trustedCatalog,
    );

    expect(resolved).toMatchObject({
      state: "unresolved",
      reason: "policy_integrity_issue",
      href: null,
    });
  });

  it("exposes permitted metadata gaps without inventing field values", () => {
    const item = recommendation("synthetic-electronics-v1:item:000002");
    const product = findCatalogProduct(item.product_id);
    const partial: Product = { ...product, name: null, description: null, category: null };
    const resolved = resolveRecommendationProduct(item, responseFor(item), {
      ...trustedCatalog,
      products: allCatalogProducts.map((candidate) =>
        candidate.id === product.id ? partial : candidate,
      ),
    });

    expect(resolved.state).toBe("resolved");
    if (resolved.state !== "resolved") return;
    expect(resolved.missingFields).toEqual(["name", "category", "description"]);
    expect(resolved.product.name).toBeNull();
    expect(resolved.product.description).toBeNull();
  });

  it("suppresses navigation if the exact product route is unavailable", () => {
    const item = recommendation("synthetic-electronics-v1:item:000011");
    const prototype = findCatalogProduct("synthetic-electronics-v1:item:000002");
    const unrouteable: Product = { ...prototype, id: item.product_id };
    const resolved = resolveRecommendationProduct(item, responseFor(item), {
      ...trustedCatalog,
      products: [...allCatalogProducts, unrouteable],
    });

    expect(resolved.state).toBe("resolved");
    if (resolved.state !== "resolved") return;
    expect(resolved.href).toBeNull();
    expect(resolved.missingFields).toContain("route");
  });
});
