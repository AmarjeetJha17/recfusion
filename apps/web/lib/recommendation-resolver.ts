import { CATALOG_ID, getProductByRouteId, getProductRouteId, type Product } from "@/lib/catalog";
import { FIXTURE_CATALOG_FINGERPRINT } from "@/lib/fixture-manifest";
import type { RecommendationItem } from "@/lib/recommendation-provider";

export type TrustedCatalogContext = {
  catalogId: string;
  assetFingerprint: string;
  products: readonly Product[];
};

export type RecommendationResponseIdentity = {
  catalog_id: string;
  catalog_fingerprint: string;
  recommendations: readonly RecommendationItem[];
};

export type MissingProductField = "name" | "category" | "description" | "features" | "route";

export type RecommendationProductResolution =
  | {
      state: "resolved";
      originalRecommendation: RecommendationItem;
      product: Product;
      href: string | null;
      missingFields: MissingProductField[];
    }
  | {
      state: "unresolved";
      originalRecommendation: RecommendationItem;
      reason:
        | "catalog_mismatch"
        | "invalid_canonical_id"
        | "unknown_product_id"
        | "ambiguous_product_id"
        | "restricted_hidden"
        | "policy_integrity_issue";
      canonicalId: string | null;
      href: null;
      diagnostic: string;
    };

export function resolveRecommendationProduct(
  recommendation: RecommendationItem,
  response: RecommendationResponseIdentity,
  trustedCatalog: TrustedCatalogContext,
): RecommendationProductResolution {
  const unresolved = (
    reason: Extract<RecommendationProductResolution, { state: "unresolved" }>["reason"],
    canonicalId: string | null,
    diagnostic: string,
  ): RecommendationProductResolution => ({
    state: "unresolved",
    originalRecommendation: recommendation,
    reason,
    canonicalId,
    href: null,
    diagnostic,
  });

  if (
    trustedCatalog.catalogId !== CATALOG_ID ||
    trustedCatalog.assetFingerprint !== FIXTURE_CATALOG_FINGERPRINT ||
    response.catalog_id !== trustedCatalog.catalogId ||
    response.catalog_fingerprint !== trustedCatalog.assetFingerprint
  ) {
    return unresolved(
      "catalog_mismatch",
      recommendation.product_id,
      "Catalog identity could not be verified. Product details and navigation are withheld.",
    );
  }

  if (!/^synthetic-electronics-v1:item:\d{6}$/.test(recommendation.product_id)) {
    return unresolved(
      "invalid_canonical_id",
      null,
      "The returned identifier is not a recognized canonical product ID. Details are withheld.",
    );
  }

  const matches = trustedCatalog.products.filter(
    (product) => product.id === recommendation.product_id,
  );
  if (matches.some((product) => !product.visible)) {
    return unresolved(
      "restricted_hidden",
      null,
      "A restricted result was returned. Its identity and product details are withheld.",
    );
  }
  if (
    matches.some(
      (product) => !product.catalogEligible || !product.contentEligible || !product.synthetic,
    )
  ) {
    return unresolved(
      "policy_integrity_issue",
      recommendation.product_id,
      "A returned result is not eligible for product display. Treat this as a policy integrity issue; details are withheld.",
    );
  }
  if (matches.length > 1) {
    return unresolved(
      "ambiguous_product_id",
      recommendation.product_id,
      "More than one catalog record has this canonical ID. Product details and navigation are withheld.",
    );
  }
  const product = matches[0];
  if (!product) {
    return unresolved(
      "unknown_product_id",
      recommendation.product_id,
      "No matching record exists in the verified display catalog. Product details and navigation are withheld.",
    );
  }
  if (
    response.recommendations.filter((item) => item.product_id === recommendation.product_id)
      .length > 1
  ) {
    return unresolved(
      "ambiguous_product_id",
      recommendation.product_id,
      "The response repeats this canonical ID. Product details and navigation are withheld.",
    );
  }

  const routeId = getProductRouteId(product);
  const routeProduct = getProductByRouteId(routeId);
  const href = routeProduct?.id === product.id ? `/products/${routeId}` : null;
  const missingFields: MissingProductField[] = [];
  if (!product.name) missingFields.push("name");
  if (!product.category) missingFields.push("category");
  if (!product.description) missingFields.push("description");
  if (!product.features.length) missingFields.push("features");
  if (!href) missingFields.push("route");

  return {
    state: "resolved",
    originalRecommendation: recommendation,
    product,
    href,
    missingFields,
  };
}
