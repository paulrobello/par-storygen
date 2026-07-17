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

// ENH-005: getProviders / toProviderOptions — registry-derived provider
// dropdowns. Pins: getProviders hits `/api/providers` (no other path) and
// threads auth headers; toProviderOptions preserves registry order/ids and
// applies the optional labelMap verbatim, including the pre-ENH-005 web
// display-name overrides the settings + style-gallery pages pass.
describe("getProviders / toProviderOptions (ENH-005)", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("getProviders GETs /api/providers and returns the parsed registry", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_TOKEN", "registry-token");
    vi.resetModules();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        text_providers: [
          {
            id: "openai",
            label: "OpenAI",
            kind: ["text"],
            key_env_var: "OPENAI_API_KEY",
            default_model: "gpt-4o-mini",
            default_base_url: "https://api.openai.com/v1",
            allows_loopback_base_url: false,
            supports_reference_images: false,
            suggested_models: ["gpt-4o-mini", "gpt-4o"],
          },
        ],
        image_providers: [],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const { getProviders, API_BASE } = await import("./api");

    const registry = await getProviders();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE}/api/providers`);
    expect(init.method).toBeUndefined(); // apiGet uses default GET
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer registry-token",
    );
    expect(registry.text_providers).toHaveLength(1);
    expect(registry.text_providers[0].id).toBe("openai");
  });

  it("toProviderOptions mirrors the registry's id order verbatim when no labelMap", async () => {
    const { toProviderOptions } = await import("./api");
    const options = toProviderOptions([
      {
        id: "openai",
        label: "OpenAI gpt-image",
        kind: ["image"],
        key_env_var: "OPENAI_API_KEY",
        default_model: "gpt-image-2",
        default_base_url: "https://api.openai.com/v1",
        allows_loopback_base_url: false,
        supports_reference_images: true,
        suggested_models: ["gpt-image-2"],
      },
      {
        id: "gemini",
        label: "Google Gemini (Nano Banana 2/Pro)",
        kind: ["image"],
        key_env_var: "GEMINI_API_KEY",
        default_model: null,
        default_base_url: null,
        allows_loopback_base_url: false,
        supports_reference_images: true,
        suggested_models: [],
      },
    ]);
    expect(options).toEqual([
      { label: "OpenAI gpt-image", value: "openai" },
      { label: "Google Gemini (Nano Banana 2/Pro)", value: "gemini" },
    ]);
  });

  it("toProviderOptions applies labelMap overrides (pre-ENH-005 web labels)", async () => {
    // Pins the labelMap the settings + style-gallery pages pass — these
    // overrides are what keeps the visible dropdown options byte-identical
    // to the pre-ENH-005 hardcoded arrays while ids + order come from the
    // registry.
    const { toProviderOptions } = await import("./api");
    const options = toProviderOptions(
      [
        {
          id: "gemini",
          label: "Google Gemini (Nano Banana 2/Pro)",
          kind: ["image"],
          key_env_var: "GEMINI_API_KEY",
          default_model: null,
          default_base_url: null,
          allows_loopback_base_url: false,
          supports_reference_images: true,
          suggested_models: [],
        },
        {
          id: "ollama",
          label: "Ollama (local, macOS-only)",
          kind: ["image"],
          key_env_var: null,
          default_model: null,
          default_base_url: "http://localhost:11434/v1/",
          allows_loopback_base_url: true,
          supports_reference_images: false,
          suggested_models: [],
        },
      ],
      { gemini: "Google Gemini", ollama: "Ollama (local)" },
    );
    expect(options).toEqual([
      { label: "Google Gemini", value: "gemini" },
      { label: "Ollama (local)", value: "ollama" },
    ]);
  });

  it("toProviderOptions returns an empty list for an empty registry", async () => {
    const { toProviderOptions } = await import("./api");
    expect(toProviderOptions([])).toEqual([]);
  });
});
