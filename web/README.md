# par-storygen web frontend

Next.js 16 (App Router) frontend for [par-storygen](https://github.com/paulrobello/par-storygen). It drives the optional FastAPI server (`src/storygen_api/`) over REST + WebSocket so the same story engine that powers the Textual TUI can be played in the browser.

This frontend is the reason the API exists — it has no game logic of its own. Every action is a fetch or WebSocket frame against `http://localhost:8101`.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Install](#install)
- [Run](#run)
- [Route map](#route-map)
- [Data flow](#data-flow)
- [Scripts](#scripts)
- [Related documentation](#related-documentation)

## Prerequisites

- Node.js (see `web/package.json` for the pinned Next.js / React versions)
- The par-storygen FastAPI server running on `:8101` — see [Run](#run) below

## Install

From the repository root:

```bash
make web-install     # cd web && npm install
```

Or directly:

```bash
cd web
npm install
```

## Run

The frontend expects the companion API on `:8101`. Start both in separate terminals:

```bash
make api-dev         # FastAPI on :8101 (requires `uv sync --extra api`)
make web-dev         # Next.js dev server on :8100
```

Open [http://localhost:8100](http://localhost:8100).

By default the frontend talks to the API at `http://localhost:8101`. Override that (and optionally send a bearer token) with these build-time variables, set in `web/.env` or your environment before `npm run build` / `make web-build`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE` | `http://localhost:8101` | Base URL of the FastAPI server (REST and WebSocket share it). |
| `NEXT_PUBLIC_API_TOKEN` | _(unset)_ | Bearer token sent on every REST request and offered as the `bearer.<token>` WS subprotocol (SEC-102). Required only when the server has `STORYGEN_API_TOKEN` set; leave unset for loopback dev. Because `NEXT_PUBLIC_*` vars are embedded in the client bundle, treat the value as visible to anyone loading the site. |

> **Security:** The API binds to `127.0.0.1` by default. Auth is two-mode (SEC-001): when `STORYGEN_API_TOKEN` is unset, loopback peers are trusted (local dev works) and off-box clients are rejected with HTTP 503 / WebSocket close 4403; when the token is set, every client — loopback included — must present a matching bearer token. The frontend forwards the token when `NEXT_PUBLIC_API_TOKEN` is set (SEC-102); for local loopback dev, leave both unset. Do not expose the API on `0.0.0.0` without `STORYGEN_API_TOKEN` configured.

The dev server's origin (`http://localhost:8100`) is the one the API allows for CORS by default. To point the frontend at a different API host/port, set `NEXT_PUBLIC_API_BASE` at build time (see [Data flow](#data-flow)); to change the API's CORS or WebSocket origin allowlist, set `STORYGEN_API_ALLOWED_ORIGINS` / `STORYGEN_WS_ALLOWED_ORIGINS` on the server (comma-separated). Both default to `http://localhost:8100,http://127.0.0.1:8100`.

## Route map

App Router pages live under `web/src/app/`:

| Route | Purpose |
| --- | --- |
| `/` (`page.tsx`) | Splash + redirect to menu or wizard |
| `/menu` | Main menu (new / load / quick start / settings) |
| `/wizard` | 8-step new-story wizard (theme, tone, style, art, length, reader level, characters, confirm) |
| `/play` | Main gameplay loop with scene image, narrative, and choices |
| `/load` | Browse and resume existing saves |
| `/characters` | Cross-game character catalog (exported characters from all saves) |
| `/presets` | Story templates and saved presets |
| `/settings` | Provider defaults, art toggles, prefetch, TTS, developer options |
| `/style-gallery` | Image Style Gallery — browse and apply art styles |

## Data flow

- **API client** — `web/src/lib/api.ts` is the typed fetch wrapper. It exposes `apiGet` / `apiPost` / `apiPut` / `apiPostForm` / `apiDelete` helpers plus domain types (`GameSave`, `StoryNode`, `Character`, `Relationship`, `SettingsResponse`, etc.) that mirror the FastAPI Pydantic models. The backend base URL is not hard-coded here: it comes from `web/src/lib/config.ts`, which reads `NEXT_PUBLIC_API_BASE` (default `http://localhost:8101`) and also derives `WS_BASE` and the optional bearer `API_TOKEN` (`NEXT_PUBLIC_API_TOKEN`, SEC-102). Every route, hook, and component imports from `config.ts` so the port lives in one place.
- **WebSocket hook** — `web/src/hooks/useWebSocket.ts` connects to `/api/ws/{game_id}` (offering `bearer.<token>` as a subprotocol when `NEXT_PUBLIC_API_TOKEN` is set) and dispatches server-pushed events into the store: `narration_delta`, `beat_committed`, `image_committed`, `image_failed`, `new_characters`, and `error`. (A `pong` frame is also handled as a keepalive.)
- **Game store** — `web/src/stores/game-store.ts` is a Zustand store holding the active `GameSave`, the current node, and TTS / image status. Components subscribe to slices of this store; the WebSocket hook is the only writer during live play.
- **Components** — `web/src/components/` holds the rendered scene panel, choice list, character roster, and modals.

## Scripts

```bash
make web-install    # npm install
make web-dev        # next dev (port 8100)
make web-build      # next build (production build)
npm run lint        # eslint (from web/)
```

## Related documentation

- [Repository README](../README.md) — project overview, install, provider configuration
- [Architecture reference](../docs/ARCHITECTURE.md) — see the "Web surface (optional API + frontend)" section for the data-flow diagram, WebSocket event contract, and auth model
