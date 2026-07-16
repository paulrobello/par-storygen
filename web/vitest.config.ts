import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

// ARC-015: minimal vitest layer for the web frontend. jsdom provides the
// browser globals (window, document) the React hook + Zustand store reach
// for; @vitejs/plugin-react transforms JSX in test files. The "@/" alias
// mirrors tsconfig.json so imports resolve identically to the app build.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
