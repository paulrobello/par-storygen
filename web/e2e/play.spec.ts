import { expect, test, type Page } from "@playwright/test";

/**
 * ARC-015: hermetic Playwright e2e for the web frontend.
 *
 * Drives the core play surface (the largest, most complex route) against a
 * mocked backend. The play page seeds its Zustand store from
 * `GET /api/games/:id` and renders the current node's narration + choices; the
 * canned root node below already carries both, so no WebSocket streaming is
 * required for the initial render. The WebSocket is still mocked so the play
 * page's reconnect-on-close loop never fires.
 *
 * Payload shapes mirror the interfaces in `web/src/lib/api.ts`
 * (`GameSave`, `SettingsResponse`) and the WS contract in `ws-types.ts`.
 */

const GAME_ID = "g-e2e";

const NARRATION = "The morning sun peeked over the hills as Mira set out toward the shimmering cavern.";
const CHOICE_A = "Enter the cavern boldly";
const CHOICE_B = "Listen carefully before moving";

const game = {
  version: 4,
  id: GAME_ID,
  theme: {
    title: "The Shimmering Cavern",
    setting: "A crystal cave beneath the hills",
    premise: "A young explorer discovers a glowing secret.",
    keywords: ["cave", "crystal", "exploration"],
  },
  tone: { preset: "whimsical", custom_descriptor: null },
  narration_style: "third_person",
  art_style: "children's story book",
  target_major_beats: 8,
  reader_level: "ages_6_10",
  pacing: "moderate",
  text_config: { provider: "openai", model: "gpt-4o-mini", base_url: null },
  image_config: { provider: "openai", model: "gpt-image-2", base_url: null },
  character_image_config: { provider: "openai", model: "gpt-image-2", base_url: null },
  characters: [],
  relationships: [],
  nodes: {
    root: {
      id: "root",
      parent_id: null,
      chosen_choice_id: null,
      chosen_at: null,
      narration: NARRATION,
      choices: [
        { id: "c1", text: CHOICE_A, child_node_id: null },
        { id: "c2", text: CHOICE_B, child_node_id: null },
      ],
      is_major: false,
      is_ending: false,
      image_prompt: null,
      image_path: null,
      image_status: "not_planned",
      illustration_reasoning: null,
      featured_character_ids: [],
      summary_to_here: null,
      recap_text: null,
      tts_audio_path: null,
      created_at: "2026-07-16T00:00:00.000Z",
    },
  },
  root_node_id: "root",
  current_node_id: "root",
  endings_reached: [],
  total_image_cost_usd: 0,
  text_total_input_tokens: 0,
  text_total_output_tokens: 0,
  text_total_requests: 0,
  text_calls_by_model: {},
  created_at: "2026-07-16T00:00:00.000Z",
  updated_at: "2026-07-16T00:00:00.000Z",
};

const settings = {
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
    tone_preset: "whimsical",
    tone_descriptor: "",
    narration_style: "third_person",
    art_style: "children's story book",
    target_major_beats: 8,
    reader_level: "ages_6_10",
    pacing: "moderate",
    characters: "",
    save_to_catalog: false,
  },
  tts_prefs: { provider: "openai", voice: "", auto_read: false, auto_read_recap: false },
  art_enabled: true,
  prefetch_enabled: true,
  prefetch_images_enabled: false,
  image_streaming_enabled: true,
  llm_cache_enabled: false,
  auto_select_enabled: false,
  auto_open_art_enabled: false,
  auto_recap_enabled: false,
  resume_recap_enabled: false,
  recap_interval: 3,
  graphics_mode: "high",
};

/** Mock the REST + WebSocket surface the play page touches on mount. */
async function mockBackend(page: Page): Promise<void> {
  // A single route handler that dispatches by URL. (Multiple overlapping
  // globs rely on Playwright route precedence, which is fragile; one handler
  // is unambiguous and keeps the canned payloads in one place.)
  await page.route("**/api/**", (route) => {
    const url = route.request().url();
    if (url.includes(`/api/games/${GAME_ID}/path`)) return route.fulfill({ json: [] });
    if (url.endsWith(`/api/games/${GAME_ID}`)) return route.fulfill({ json: game });
    if (url.includes("/api/settings")) return route.fulfill({ json: settings });
    // Any other /api call the play page fires (button-triggered ones aren't
    // in this test): return an inert 200 so nothing throws.
    return route.fulfill({ json: {} });
  });

  // Hold the WS open so the hook's 3s reconnect-on-close never fires; answer
  // any ping with pong (the hook does not auto-ping, but this is cheap).
  await page.routeWebSocket("**/api/ws/**", (ws) => {
    ws.onMessage((data) => {
      try {
        const msg = JSON.parse(data as string) as { type?: string };
        if (msg?.type === "ping") ws.send(JSON.stringify({ type: "pong" }));
      } catch {
        /* ignore non-JSON frames */
      }
    });
  });
}

test.describe("play surface (ARC-015 e2e)", () => {
  test("renders the current beat's narration and choices from a canned save", async ({
    page,
  }) => {
    // Capture client-side errors so a render crash surfaces a real stack
    // instead of a silent "element not found".
    const clientErrors: string[] = [];
    page.on("pageerror", (e) => clientErrors.push(`pageerror: ${e.stack ?? e.message}`));
    page.on("console", (m) => {
      if (m.type() === "error") clientErrors.push(`console.error: ${m.text()}`);
    });

    await mockBackend(page);
    await page.goto(`/play/${GAME_ID}`);

    if (clientErrors.length > 0) {
      throw new Error(`client errors during render:\n${clientErrors.join("\n")}`);
    }

    // Game loaded: the theme title renders in the top bar.
    await expect(page.getByRole("heading", { name: /the shimmering cavern/i })).toBeVisible();
    // Narration renders (react-markdown); assert the text is present in main.
    await expect(page.locator("main")).toContainText(/Mira set out toward the shimmering cavern/i);
    // Both choices render as buttons.
    await expect(page.getByRole("button", { name: new RegExp(CHOICE_A, "i") })).toBeVisible();
    await expect(page.getByRole("button", { name: new RegExp(CHOICE_B, "i") })).toBeVisible();
  });
});
