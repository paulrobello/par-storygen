// SEC-102: tests for the web client bearer-token plumbing.
//
// Pins the opt-in auth contract: when NEXT_PUBLIC_API_TOKEN is set,
// `authHeaders()` returns `Authorization: Bearer <token>` for spreading into
// every fetch wrapper; when unset, it returns `{}` (preserving local-dev
// loopback-trust behavior). Also pins `API_TOKEN` deriving from the env var.
//
// Because `API_TOKEN` is a module-level const read from `process.env` at
// import time, each test stubs the env var and uses a dynamic `import()`
// after `vi.resetModules()` so the module re-evaluates under the new value.

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

describe("API_TOKEN config (SEC-102)", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("reads NEXT_PUBLIC_API_TOKEN into API_TOKEN when set", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_TOKEN", "tok-abc123");
    vi.resetModules();
    const { API_TOKEN } = await import("./config");
    expect(API_TOKEN).toBe("tok-abc123");
  });

  it("defaults to empty string when NEXT_PUBLIC_API_TOKEN is unset", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_TOKEN", "");
    vi.resetModules();
    const { API_TOKEN } = await import("./config");
    expect(API_TOKEN).toBe("");
  });

  it("defaults to empty string when NEXT_PUBLIC_API_TOKEN is absent", async () => {
    delete process.env.NEXT_PUBLIC_API_TOKEN;
    vi.resetModules();
    const { API_TOKEN } = await import("./config");
    expect(API_TOKEN).toBe("");
  });
});

describe("authHeaders (SEC-102)", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("returns the Authorization Bearer header when a token is configured", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_TOKEN", "configured-token-XYZ");
    vi.resetModules();
    const { authHeaders } = await import("./api");
    expect(authHeaders()).toEqual({ Authorization: "Bearer configured-token-XYZ" });
  });

  it("returns an empty object when the token is unset (loopback-trust mode)", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_TOKEN", "");
    vi.resetModules();
    const { authHeaders } = await import("./api");
    expect(authHeaders()).toEqual({});
  });

  it("is safe to spread: no Authorization key leaks when unset", async () => {
    // Spreading `{}` into a headers object must not add an Authorization key
    // (a stale/empty `Authorization` would break loopback-trust requests).
    delete process.env.NEXT_PUBLIC_API_TOKEN;
    vi.resetModules();
    const { authHeaders } = await import("./api");
    const merged = { "Content-Type": "application/json", ...authHeaders() };
    expect(merged).toEqual({ "Content-Type": "application/json" });
    expect("Authorization" in merged).toBe(false);
  });
});

// QA-013: sceneImageUrl centralizes the /api/images/<game>/scene/<node> URL
// shape and — critically — returns null unless image_status === "done", so the
// UI renders a placeholder/spinner instead of fetching a 404. Pinning both the
// null-vs-URL branch and the URL shape guards against a regression that would
// re-introduce the pre-QA-013 five-site duplication (and the 404-on-pending
// flashes that motivated it).
describe("sceneImageUrl (QA-013)", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
  });

  it("returns null for every non-done image_status", async () => {
    const { sceneImageUrl } = await import("./api");
    for (const status of ["not_planned", "generating", "failed"] as const) {
      expect(sceneImageUrl("g1", { id: "n1", image_status: status })).toBeNull();
    }
  });

  it("returns the canonical scene URL when image_status is done", async () => {
    // API_BASE defaults to http://localhost:8101 in the vitest env.
    const { sceneImageUrl } = await import("./api");
    expect(sceneImageUrl("g1", { id: "n1", image_status: "done" })).toBe(
      "http://localhost:8101/api/images/g1/scene/n1",
    );
  });
});

// Error propagation: every wrapper funnels non-2xx through handleResponse,
// which throws `new Error("API <status>: <body>")`. Pinning the message shape
// so UI error displays (game-store's `error` field) keep rendering the status
// code + body instead of an opaque "request failed".
describe("apiGet error propagation", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("throws an Error carrying the status code and response body on non-2xx", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        text: async () => "internal boom",
      }),
    );
    const { apiGet } = await import("./api");

    await expect(apiGet("/api/games/g1")).rejects.toThrow(/API 500: internal boom/);
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
  });

  it("falls back to 'Unknown error' when the response body cannot be read", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        text: async () => {
          throw new Error("read failed");
        },
      }),
    );
    const { apiGet } = await import("./api");

    await expect(apiGet("/api/games/g1")).rejects.toThrow(/API 502: Unknown error/);
  });
});
