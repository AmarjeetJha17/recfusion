import { describe, expect, it } from "vitest";
import {
  catalog,
  getProduct,
  getProductByRouteId,
  getProductRouteId,
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
      new Set(["laptop", "headphones", "smartphone", "monitor", "accessory"]),
    );
  });

  it("searches approved display attributes and filters by category", () => {
    expect(searchCatalog("usb-c", "accessory").length).toBeGreaterThan(0);
    expect(
      searchCatalog("usb-c", "accessory").every((product) => product.category === "accessory"),
    ).toBe(true);
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

  it("represents unavailable specifications as missing values", () => {
    expect(catalog.some((product) => Object.values(product.specifications).includes(null))).toBe(
      true,
    );
  });
});
