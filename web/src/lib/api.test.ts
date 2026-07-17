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
