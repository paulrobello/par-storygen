/**
 * ARC-016: single source of truth for the backend base URL.
 *
 * Pre-ARC-016 the API base was hard-coded as `"http://localhost:8101"` in
 * eight separate frontend files (api.ts, useWebSocket.ts, game-store.ts,
 * four page components, and two story components). The audit's SEC-008 fix
 * introduced `NEXT_PUBLIC_API_BASE` for `api.ts` only; ARC-016 extends the
 * pattern so every frontend route/hook/component derives from this one
 * module. Operators point the frontend at a non-default API by setting
 * `NEXT_PUBLIC_API_BASE` at build time; no other file needs to change.
 *
 * The WS endpoint lives on the same host:port as the REST API — see
 * `create_app()` in `src/storygen_api/main.py` (both are mounted on the
 * one uvicorn server, and `make api-dev` serves :8101 for both).
 */

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8101";

/**
 * Derive the WebSocket base URL from {@link API_BASE} by swapping the scheme.
 * `http://` → `ws://`, `https://` → `wss://`. Anything else falls back to the
 * dev default so a misconfigured `NEXT_PUBLIC_API_BASE` surfaces as a
 * connection failure rather than a malformed-URL exception at module load.
 */
export const WS_BASE: string = (() => {
  if (API_BASE.startsWith("https://")) {
    return "wss://" + API_BASE.slice("https://".length);
  }
  if (API_BASE.startsWith("http://")) {
    return "ws://" + API_BASE.slice("http://".length);
  }
  return "ws://localhost:8101";
})();
