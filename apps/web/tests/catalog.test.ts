import { describe, expect, it } from "vitest";
import {
  allCatalogProducts,
  catalog,
  getProduct,
  getProductByRouteId,
  getProductRouteId,
  getRequestableProducts,
  getSimilarProducts,
  searchCatalog,
  sortProducts,
} from "@/lib/catalog";

describe("synthetic catalog", () => {
  it("uses stable namespaced product IDs and has versioned synthetic records", () => {
    const ids = catalog.map((product) => product.id);

    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toEqual([...ids].sort());
    expect(ids.every((id) => /^synthetic-electronics-v1:item:\d{6}$/.test(id))).toBe(true);
    expect(catalog.every((product) => product.synthetic === true)).toBe(true);
    expect(new Set(catalog.map((product) => product.category))).toEqual(
      new Set(["laptop", "audio", "smartphone", "monitor", null]),
    );
    expect(catalog.map((product) => product.id)).toHaveLength(9);
    expect(allCatalogProducts).toHaveLength(10);
    expect(getProduct("synthetic-electronics-v1:item:000010")).toBeUndefined();
    expect(allCatalogProducts.find((product) => product.id.endsWith(":000010"))?.visible).toBe(
      false,
    );
    expect(getProduct("synthetic-electronics-v1:item:000009")?.catalogEligible).toBe(false);
    expect(getProduct("synthetic-electronics-v1:item:000008")?.contentEligible).toBe(false);
    expect(catalog.some((product) => product.id.endsWith(":000011"))).toBe(false);
    expect(getRequestableProducts().map((product) => product.id.slice(-6))).toEqual([
      "000001",
      "000002",
      "000003",
      "000004",
      "000005",
      "000006",
      "000007",
    ]);
  });

  it("searches approved display attributes and filters by category", () => {
    expect(searchCatalog("usb-c", "audio").length).toBeGreaterThan(0);
    expect(searchCatalog("usb-c", "audio").every((product) => product.category === "audio")).toBe(
      true,
    );
    expect(searchCatalog("no such device")).toEqual([]);
  });

  it("sorts deterministically and breaks equal-name ties by stable ID", () => {
    const first = sortProducts(catalog, "name").map((product) => product.id);
    const second = sortProducts([...catalog].reverse(), "name").map((product) => product.id);

    expect(first).toEqual(second);
  });

  it("resolves details and keeps similar-item lists in the fixture catalog", () => {
    const product = catalog[0];
    expect(getProduct(product.id)).toEqual(product);
    expect(getProductRouteId(product)).not.toContain(":");
    expect(getProductByRouteId(getProductRouteId(product))).toEqual(product);
    expect(getProduct("synthetic-electronics-v1:item:999999")).toBeUndefined();
    expect(getSimilarProducts(product.id).every((candidate) => candidate.id !== product.id)).toBe(
      true,
    );
  });

  it("preserves incomplete records without fabricating feature values", () => {
    expect(getProduct("synthetic-electronics-v1:item:000008")?.features).toEqual([]);
  });
});
