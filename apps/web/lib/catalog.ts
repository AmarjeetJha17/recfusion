import fixture from "@/features/catalog/catalog-data.json";

export const CATALOG_SCHEMA = "recfusion.synthetic-electronics-frontend.v1" as const;
export const CATALOG_ID = "synthetic-electronics-v1" as const;

export type ProductCategory = "laptop" | "headphones" | "smartphone" | "monitor" | "accessory";
export type CatalogCohort = "warm" | "cold" | "unknown";
export type Product = {
  id: string;
  name: string | null;
  category: ProductCategory;
  description: string;
  specifications: Record<string, string | null | undefined>;
  cohort: CatalogCohort;
  recommendationEligible: boolean;
  visible: true;
  synthetic: true;
};
export type ProductSort = "featured" | "name" | "category";
export type CategoryFilter = "all" | ProductCategory;

if (
  fixture.schema_version !== CATALOG_SCHEMA ||
  fixture.catalog_id !== CATALOG_ID ||
  fixture.products.some((product) => product.visible !== true || product.synthetic !== true)
) {
  throw new Error("The synthetic frontend catalog fixture is incompatible.");
}

export const catalog: readonly Product[] = Object.freeze(
  [...fixture.products].sort((left, right) => compare(left.id, right.id)) as Product[],
);

const byId = new Map(catalog.map((product) => [product.id, product]));
const byRouteId = new Map(catalog.map((product) => [getProductRouteId(product), product]));

const similarIds: Readonly<Record<string, readonly string[]>> = {
  "synthetic-electronics-v1:item:000001": [
    "synthetic-electronics-v1:item:000006",
    "synthetic-electronics-v1:item:000002",
  ],
  "synthetic-electronics-v1:item:000002": [
    "synthetic-electronics-v1:item:000001",
    "synthetic-electronics-v1:item:000006",
  ],
  "synthetic-electronics-v1:item:000003": [
    "synthetic-electronics-v1:item:000013",
    "synthetic-electronics-v1:item:000001",
  ],
  "synthetic-electronics-v1:item:000004": [
    "synthetic-electronics-v1:item:000007",
    "synthetic-electronics-v1:item:000015",
  ],
  "synthetic-electronics-v1:item:000005": [
    "synthetic-electronics-v1:item:000014",
    "synthetic-electronics-v1:item:000012",
  ],
  "synthetic-electronics-v1:item:000006": [
    "synthetic-electronics-v1:item:000001",
    "synthetic-electronics-v1:item:000002",
  ],
  "synthetic-electronics-v1:item:000007": [
    "synthetic-electronics-v1:item:000004",
    "synthetic-electronics-v1:item:000015",
  ],
  "synthetic-electronics-v1:item:000008": [
    "synthetic-electronics-v1:item:000012",
    "synthetic-electronics-v1:item:000011",
  ],
  "synthetic-electronics-v1:item:000011": [
    "synthetic-electronics-v1:item:000012",
    "synthetic-electronics-v1:item:000008",
  ],
  "synthetic-electronics-v1:item:000012": [
    "synthetic-electronics-v1:item:000011",
    "synthetic-electronics-v1:item:000014",
  ],
  "synthetic-electronics-v1:item:000013": [
    "synthetic-electronics-v1:item:000003",
    "synthetic-electronics-v1:item:000001",
  ],
  "synthetic-electronics-v1:item:000014": [
    "synthetic-electronics-v1:item:000005",
    "synthetic-electronics-v1:item:000012",
  ],
  "synthetic-electronics-v1:item:000015": [
    "synthetic-electronics-v1:item:000004",
    "synthetic-electronics-v1:item:000007",
  ],
};

export function getProduct(id: string): Product | undefined {
  return byId.get(id);
}

export function getProductRouteId(product: Product): string {
  return product.id.replaceAll(":", "-");
}

export function getProductByRouteId(routeId: string): Product | undefined {
  return byRouteId.get(routeId);
}

export function searchCatalog(query: string, category: CategoryFilter = "all"): Product[] {
  const normalizedQuery = query.trim().toLowerCase();
  return catalog.filter((product) => {
    if (category !== "all" && product.category !== category) return false;
    if (!normalizedQuery) return true;
    const searchable = [
      product.name,
      product.category,
      product.description,
      ...Object.entries(product.specifications).flat(),
    ]
      .filter((value): value is string => typeof value === "string")
      .join(" ")
      .toLowerCase();
    return searchable.includes(normalizedQuery);
  });
}

export function sortProducts(products: readonly Product[], sort: ProductSort): Product[] {
  return [...products].sort((left, right) => {
    if (sort === "name") {
      return compare(left.name ?? "", right.name ?? "") || compare(left.id, right.id);
    }
    if (sort === "category") {
      return compare(left.category, right.category) || compare(left.id, right.id);
    }
    return compare(left.id, right.id);
  });
}

export function getSimilarProducts(id: string): Product[] {
  return (similarIds[id] ?? []).flatMap((similarId) => {
    const product = byId.get(similarId);
    return product ? [product] : [];
  });
}

export function getRequestableProducts(): Product[] {
  return catalog.filter((product) => product.recommendationEligible);
}

function compare(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}
