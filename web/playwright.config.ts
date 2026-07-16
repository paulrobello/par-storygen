import { defineConfig, devices } from "@playwright/test";

/**
 * ARC-015: end-to-end coverage for the web frontend.
 *
 * The suite is fully hermetic — no live LLM, no real FastAPI backend. Each
 * test mocks the REST surface via `page.route` and the WebSocket via
 * `page.routeWebSocket`, so it exercises the real Next.js components, App
 * Router navigation, and Zustand/WebSocket data flow against canned payloads.
 * The webServer boots `next dev` on :8100 (matching `make web-dev`).
 *
 * Run locally with `npm run e2e` (reuses a running dev server if present).
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  // Next dev compiles each route on first visit (10–20s), so give assertions
  // and navigation a generous window. Production (`next start`) is far faster.
  timeout: 90_000,
  expect: { timeout: 30_000 },
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://localhost:8100",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    navigationTimeout: 60_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npx next dev --port 8100",
    url: "http://localhost:8100",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
