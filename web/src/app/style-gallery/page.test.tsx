// ENH-005-T3: page-render regression test for the Style Gallery page's image-
// provider dropdown. The data-layer helpers are unit-tested in
// web/src/lib/api.test.ts; this test pins the page-level wiring unique to
// style-gallery: getProviders() fetch on mount → setState → imageProviderOptions
// prop threaded into BOTH ProviderColumn instances → <option> children rendered
// with the labelMap-overridden labels. A future refactor that forgot to pass
// the new prop to ProviderColumn, or dropped IMAGE_LABEL_MAP, would fail here.
//
// Mocking: globalThis.fetch is stubbed to answer GET /api/providers with a
// small registry envelope. Stubs the real fetch rather than @/lib/api so the
// getProviders → toProviderOptions → ProviderColumn pipeline runs end-to-end.
// Matches the vi.stubGlobal("fetch", ...) pattern used in api.test.ts.
//
// Registry labels: the fixture returns the FULL backend label for gemini
// ("Google Gemini (Nano Banana 2/Pro)") so the assertion on the shortened
// "Google Gemini" actually verifies the page's IMAGE_LABEL_MAP override.

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import StyleGalleryPage from "./page";
import type { ProvidersResponse } from "@/lib/api";

const PROVIDERS_FIXTURE: ProvidersResponse = {
  // style-gallery only consumes image_providers; text_providers is unused but
  // kept empty to match the real envelope shape.
  text_providers: [],
  image_providers: [
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
    {
      id: "zai",
      label: "Z.AI GLM-image",
      kind: ["image"],
      key_env_var: "ZAI_API_KEY",
      default_model: null,
      default_base_url: "https://api.z.ai/api/paas/v4/",
      allows_loopback_base_url: false,
      supports_reference_images: false,
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
};

describe("StyleGalleryPage provider dropdowns (ENH-005)", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const u = String(input);
        if (u.endsWith("/api/providers")) {
          return { ok: true, status: 200, json: async () => PROVIDERS_FIXTURE };
        }
        throw new Error(`unexpected fetch in StyleGalleryPage test: ${u}`);
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders image-provider <option>s in both ProviderColumn selects from GET /api/providers (labelMap applied)", async () => {
    render(<StyleGalleryPage />);

    // Each image option renders in TWO ProviderColumn selects, so use
    // findAllByText and assert the count is exactly 2 — pins that the prop is
    // threaded into both columns (a regression that hardcoded one column's
    // options or dropped the prop would fail here).
    expect((await screen.findAllByText("OpenAI gpt-image", { selector: "option" })).length).toBe(2);
    expect(screen.getAllByText("Google Gemini", { selector: "option" }).length).toBe(2);
    expect(screen.getAllByText("Z.AI GLM-image", { selector: "option" }).length).toBe(2);
    expect(screen.getAllByText("Ollama (local)", { selector: "option" }).length).toBe(2);

    // Pin the id-derived value attribute on one column's gemini option.
    const geminiOption = screen.getAllByText("Google Gemini", { selector: "option" })[0];
    expect(geminiOption).toHaveValue("gemini");

    // Negative assertion: the full registry label must NOT appear — if it did,
    // IMAGE_LABEL_MAP was bypassed.
    expect(screen.queryByText("Google Gemini (Nano Banana 2/Pro)", { selector: "option" })).toBeNull();
    expect(screen.queryByText("Ollama (local, macOS-only)", { selector: "option" })).toBeNull();
  });
});
