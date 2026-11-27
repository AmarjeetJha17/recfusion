import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { FIXTURE_ARTIFACT_FINGERPRINT, FIXTURE_CATALOG_FINGERPRINT } from "@/lib/fixture-manifest";

describe("synthetic fixture manifest", () => {
  it("matches the exact checked-in catalog and ranking fixture checksums", () => {
    const checksum = (path: string) =>
      createHash("sha256").update(readFileSync(path)).digest("hex");

    expect(checksum(resolve("features/catalog/catalog-data.json"))).toBe(
      FIXTURE_CATALOG_FINGERPRINT,
    );
    expect(checksum(resolve("features/recommendations/recommendation-fixtures.json"))).toBe(
      FIXTURE_ARTIFACT_FINGERPRINT,
    );
  });
});
