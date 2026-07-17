// ENH-005-T3: page-render regression test for the settings page's provider
// dropdowns. The data-layer helpers (getProviders / toProviderOptions) are
// unit-tested in web/src/lib/api.test.ts, but that suite does not exercise the
// page-level wiring: getProviders() fetch on mount → setState →
// SelectField options → <option> children. This test pins that wiring so a
// future refactor (dropping the prop, swapping the text/image arrays, removing
// IMAGE_LABEL_MAP) would fail here instead of silently breaking the dropdowns.
//
// Mocking: globalThis.fetch is stubbed to route by URL so both mount-time
// fetches answer with minimal fixtures — GET /api/settings (drives the form
// via useSettingsStore) and GET /api/providers (drives the option arrays).
// Stubs the real fetch rather than @/lib/api so the getProviders →
// toProviderOptions → SelectField pipeline runs end-to-end. Matches the
// vi.stubGlobal("fetch", ...) pattern used in api.test.ts.
//
// Registry labels: the image_providers fixture returns the FULL backend
// labels ("Google Gemini (Nano Banana 2/Pro)", "Ollama (local, macOS-only)")
// so the assertions on the shortened labels ("Google Gemini", "Ollama (local)")
// actually verify the page's IMAGE_LABEL_MAP override is applied — the
// pre-ENH-005 web display labels documented in the page source.

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import SettingsPage from "./page";
import type { ProvidersResponse, SettingsResponse } from "@/lib/api";

const PROVIDERS_FIXTURE: ProvidersResponse = {
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
      suggested_models: ["gpt-4o-mini"],
    },
    {
      id: "openrouter",
      label: "OpenRouter",
      kind: ["text"],
      key_env_var: "OPENROUTER_API_KEY",
      default_model: null,
      default_base_url: "https://openrouter.ai/api/v1",
      allows_loopback_base_url: false,
      supports_reference_images: false,
      suggested_models: [],
    },
    {
      id: "ollama",
      label: "Ollama (local)",
      kind: ["text"],
      key_env_var: null,
      default_model: null,
      default_base_url: "http://localhost:11434/v1/",
      allows_loopback_base_url: true,
      supports_reference_images: false,
      suggested_models: [],
    },
  ],
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

const SETTINGS_FIXTURE: SettingsResponse = {
  text_provider: { provider: "openai", model: "gpt-4o-mini", base_url: null },
  image_provider: {
    provider: "openai",
    model: "gpt-image-2",
    base_url: null,
    fallback_provider: "",
    fallback_model: "",
  },
  character_image_provider: { provider: "openai", model: "gpt-image-2", base_url: null },
  wizard_defaults: {
    theme: "",
    tone_preset: "serious",
    tone_descriptor: "",
    narration_style: "third_person",
    art_style: "",
    target_major_beats: 5,
    reader_level: "ages_11_15",
    pacing: "moderate",
    characters: "",
    save_to_catalog: false,
  },
  tts_prefs: { provider: "openai", voice: "alloy", auto_read: false, auto_read_recap: false, pregenerate_prefetch_audio: false },
  art_enabled: true,
  prefetch_enabled: true,
  prefetch_images_enabled: false,
  image_streaming_enabled: true,
  llm_cache_enabled: false,
  auto_select_enabled: false,
  auto_open_art_enabled: false,
  auto_recap_enabled: true,
  resume_recap_enabled: true,
  recap_interval: 3,
  graphics_mode: "standard",
};

describe("SettingsPage provider dropdowns (ENH-005)", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const u = String(input);
        if (u.endsWith("/api/settings")) {
          return { ok: true, status: 200, json: async () => SETTINGS_FIXTURE };
        }
        if (u.endsWith("/api/providers")) {
          return { ok: true, status: 200, json: async () => PROVIDERS_FIXTURE };
        }
        throw new Error(`unexpected fetch in SettingsPage test: ${u}`);
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders text + image provider <option>s from GET /api/providers (labelMap overrides applied)", async () => {
    render(<SettingsPage />);

    // Text-provider select: TEXT_LABEL_MAP is empty on the page, so registry
    // labels pass through verbatim. Use getAllByText throughout because some
    // labels also appear in other selects (the TTS select ships a literal
    // "OpenAI" option; "Ollama (local)" is also the labelMap output for the
    // image ollama entry, so it shows up in the text select AND the three
    // image selects). We assert presence, not uniqueness — the negative
    // assertions below pin the labelMap behavior.
    expect(
      (await screen.findAllByText("OpenAI", { selector: "option" })).length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("OpenRouter", { selector: "option" }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Ollama (local)", { selector: "option" }).length).toBeGreaterThan(0);

    // Image-provider options appear in three selects (image provider, fallback
    // provider, character portrait provider), so use findAllByText. The
    // fixture returns the long registry labels; the assertions verify the
    // page's IMAGE_LABEL_MAP shortened them to the pre-ENH-005 web display.
    expect((await screen.findAllByText("OpenAI gpt-image", { selector: "option" })).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Google Gemini", { selector: "option" })).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Z.AI GLM-image", { selector: "option" }).length).toBeGreaterThan(0);

    // Pin the id-derived value attribute too, not just the visible label, so a
    // regression that decoupled label↔value would fail.
    const geminiOption = screen.getAllByText("Google Gemini", { selector: "option" })[0];
    expect(geminiOption).toHaveValue("gemini");

    // Negative assertion: the full registry label must NOT appear — if it did,
    // IMAGE_LABEL_MAP was bypassed.
    expect(screen.queryByText("Google Gemini (Nano Banana 2/Pro)", { selector: "option" })).toBeNull();
    expect(screen.queryByText("Ollama (local, macOS-only)", { selector: "option" })).toBeNull();
  });
});
