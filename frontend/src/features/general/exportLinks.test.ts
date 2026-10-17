import { describe, expect, it } from "vitest";

import {
  analysisExportUrl,
  everythingExportUrl,
  generalExportUrl,
  monologueExportUrl,
} from "./exportLinks";

describe("where analyses are downloaded from", () => {
  it("is the backend, one address per kind of document", () => {
    expect(analysisExportUrl("abc123")).toBe("http://localhost:4321/api/analyses/abc123/export");
    expect(monologueExportUrl("mono1")).toBe(
      "http://localhost:4321/api/export?scope=monologue&monologue=mono1",
    );
    expect(generalExportUrl()).toBe("http://localhost:4321/api/export?scope=general");
    expect(everythingExportUrl()).toBe("http://localhost:4321/api/export?scope=all");
  });

  it("keeps an ID with odd characters in it from changing the address", () => {
    expect(analysisExportUrl("a/b?c")).toBe(
      "http://localhost:4321/api/analyses/a%2Fb%3Fc/export",
    );
    expect(monologueExportUrl("a&scope=all")).toBe(
      "http://localhost:4321/api/export?scope=monologue&monologue=a%26scope%3Dall",
    );
  });
});
