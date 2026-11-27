import recommendationFixtures from "@/features/recommendations/recommendation-fixtures.json";
import fixture from "../../../packages/recfusion_core/data/synthetic-electronics-v2.json";
import assetManifest from "../../../packages/recfusion_core/data/synthetic-electronics-v2.manifest.json";

export const CATALOG_SCHEMA = "recfusion.synthetic-catalog.v2" as const;
export const CATALOG_ID = "synthetic-electronics-v1" as const;
export const CATALOG_VERSION = "2" as const;

export type ProductCategory = "laptop" | "audio" | "smartphone" | "monitor" | "accessory";
export type Product = {
  id: string;
  name: string | null;
  category: ProductCategory | null;
  description: string | null;
  features: readonly string[];
  catalogEligible: boolean;
  contentEligible: boolean;
  visible: boolean;
  synthetic: true;
};
export type ProductSort = "featured" | "name" | "category";
export type CategoryFilter = "all" | ProductCategory;

const expectedProductKeys = [
  "catalog_eligible",
  "category",
  "description",
  "features",
  "id",
  "source_record_fingerprint",
  "synthetic",
  "title",
  "visible",
].sort();
const validCategories = new Set<ProductCategory>([
  "laptop",
  "audio",
  "smartphone",
  "monitor",
  "accessory",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

if (
  !isRecord(fixture) ||
  fixture.schema_version !== CATALOG_SCHEMA ||
  fixture.catalog_id !== CATALOG_ID ||
  fixture.catalog_version !== CATALOG_VERSION ||
  assetManifest.catalog_id !== fixture.catalog_id ||
  assetManifest.catalog_version !== fixture.catalog_version ||
  !Array.isArray(fixture.products) ||
  fixture.products.length !== 10
) {
  throw new Error("The shared synthetic catalog envelope is incompatible.");
}

const seenIds = new Set<string>();
const validatedProducts = fixture.products.map((candidate) => {
  if (!isRecord(candidate)) throw new Error("The shared catalog product is invalid.");
  const keys = Object.keys(candidate).sort();
  const category = candidate.category;
  const id = candidate.id;
  const valid =
    keys.length === expectedProductKeys.length &&
    keys.every((key, index) => key === expectedProductKeys[index]) &&
    typeof id === "string" &&
    /^synthetic-electronics-v1:item:\d{6}$/.test(id) &&
    !seenIds.has(id) &&
    (candidate.title === null || typeof candidate.title === "string") &&
    (category === null ||
      (typeof category === "string" && validCategories.has(category as ProductCategory))) &&
    Array.isArray(candidate.description) &&
    candidate.description.every((value) => typeof value === "string" && value.length > 0) &&
    Array.isArray(candidate.features) &&
    candidate.features.every((value) => typeof value === "string" && value.length > 0) &&
    typeof candidate.source_record_fingerprint === "string" &&
    /^[a-f0-9]{64}$/.test(candidate.source_record_fingerprint) &&
    typeof candidate.catalog_eligible === "boolean" &&
    typeof candidate.visible === "boolean" &&
    candidate.synthetic === true;
  if (!valid) throw new Error("The shared catalog product data is invalid.");
  seenIds.add(id as string);
  return candidate;
});

if (
  [...seenIds].sort().join(",") !==
  Array.from(
    { length: 10 },
    (_, index) => `synthetic-electronics-v1:item:${String(index + 1).padStart(6, "0")}`,
  ).join(",")
) {
  throw new Error("The shared catalog identity set is invalid.");
}
if (validatedProducts.map((product) => product.id).join(",") !== [...seenIds].sort().join(",")) {
  throw new Error("The shared catalog product order is invalid.");
}

export const allCatalogProducts: readonly Product[] = Object.freeze(
  validatedProducts.map((record) => ({
    id: record.id as string,
    name: record.title as string | null,
    category: record.category as ProductCategory | null,
    description: record.description.length ? record.description.join(" ") : null,
    features: Object.freeze([...record.features]) as readonly string[],
    catalogEligible: record.catalog_eligible as boolean,
    contentEligible: (record.catalog_eligible as boolean) && record.features.length > 0,
    visible: record.visible as boolean,
    synthetic: true as const,
  })),
);

export const catalog: readonly Product[] = Object.freeze(
  allCatalogProducts.filter((product) => product.visible),
);

const byId = new Map(catalog.map((product) => [product.id, product]));
const byRouteId = new Map(catalog.map((product) => [getProductRouteId(product), product]));

const productResults = recommendationFixtures.product_results as Record<
  string,
  { candidates: { id: string }[] }
>;

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
    const searchable = [product.name, product.category, product.description, ...product.features]
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
      return compare(left.category ?? "", right.category ?? "") || compare(left.id, right.id);
    }
    return compare(left.id, right.id);
  });
}

export function getSimilarProducts(id: string): Product[] {
  return (productResults[id.slice(-6)]?.candidates ?? []).flatMap((candidate) => {
    const product = byId.get(`${CATALOG_ID}:item:${candidate.id}`);
    return product?.contentEligible ? [product] : [];
  });
}

export function getRequestableProducts(): Product[] {
  return catalog.filter((product) => product.catalogEligible && product.contentEligible);
}

function compare(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}
