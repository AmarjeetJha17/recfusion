import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import recommendationFixtures from "@/features/recommendations/recommendation-fixtures.json";
import {
  FIXTURE_ARTIFACT_FINGERPRINT,
  FIXTURE_CATALOG_FINGERPRINT,
  RECOMMENDATION_FIXTURE_SHA256,
} from "@/lib/fixture-manifest";
import catalog from "../../../packages/recfusion_core/data/synthetic-electronics-v2.json";
import catalogManifest from "../../../packages/recfusion_core/data/synthetic-electronics-v2.manifest.json";

describe("synthetic fixture manifest", () => {
  it("matches the exact checked-in catalog and ranking fixture checksums", () => {
    const checksum = (path: string) =>
      createHash("sha256").update(readFileSync(path)).digest("hex");

    expect(
      checksum(resolve("../../packages/recfusion_core/data/synthetic-electronics-v2.json")),
    ).toBe(catalogManifest.asset_fingerprint);
    expect(FIXTURE_CATALOG_FINGERPRINT).toBe(catalogManifest.asset_fingerprint);
    const compatibilityProjection = catalog.products.map((product) => ({
      catalog_eligible: product.catalog_eligible,
      category: product.category,
      description: product.description,
      features: product.features,
      id: product.id,
      source_record_fingerprint: product.source_record_fingerprint,
      title: product.title,
      visible: product.visible,
    }));
    expect(createHash("sha256").update(JSON.stringify(compatibilityProjection)).digest("hex")).toBe(
      catalogManifest.compatibility_fingerprint,
    );
    expect(checksum(resolve("features/recommendations/recommendation-fixtures.json"))).toBe(
      RECOMMENDATION_FIXTURE_SHA256,
    );
    expect(FIXTURE_ARTIFACT_FINGERPRINT).toBe(recommendationFixtures.artifact_fingerprint);
  });
});
