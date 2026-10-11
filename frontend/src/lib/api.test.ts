import { describe, expect, it } from "vitest";

import { apiBaseUrl, apiUrl } from "./api";

describe("apiBaseUrl", () => {
  it("falls back to the local backend when unset or blank", () => {
    expect(apiBaseUrl(undefined)).toBe("http://localhost:4321");
    expect(apiBaseUrl("  ")).toBe("http://localhost:4321");
  });

  it("strips trailing slashes from a configured value", () => {
    expect(apiBaseUrl("http://127.0.0.1:9000//")).toBe("http://127.0.0.1:9000");
  });
});

describe("apiUrl", () => {
  it("joins base and path with exactly one slash", () => {
    expect(apiUrl("/api/health", "http://localhost:4321")).toBe(
      "http://localhost:4321/api/health",
    );
    expect(apiUrl("api/health", "http://localhost:4321")).toBe(
      "http://localhost:4321/api/health",
    );
  });
});
