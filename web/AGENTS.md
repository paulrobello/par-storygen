# par-storygen web frontend — Agent Guide

Agent-oriented guide for working in `web/` (Next.js 16 App Router frontend for par-storygen). The frontend is a thin client over the FastAPI server in `src/storygen_api/` — it owns no game logic.

## Layout

```text
web/
├── src/
│   ├── app/              # App Router pages (one folder per route)
│   │   ├── page.tsx      # splash + redirect
│   │   ├── menu/         # main menu
│   │   ├── wizard/       # 8-step new-story wizard
│   │   ├── play/         # main gameplay loop
│   │   ├── load/         # browse / resume saves
│   │   ├── characters/   # cross-game character catalog
│   │   ├── presets/      # story templates + saved presets
│   │   ├── settings/     # provider defaults, art toggles, TTS, dev options
│   │   └── style-gallery/  # image Style Gallery
│   ├── components/       # scene panel, choice list, roster, modals
│   ├── hooks/
│   │   └── useWebSocket.ts  # /api/ws/{game_id} event dispatcher
│   ├── lib/
│   │   ├── api.ts        # typed fetch wrapper (REST)
│   │   └── ws-types.ts   # WebSocket event contract (mirrors storygen_api ws.py)
│   └── stores/
│       └── game-store.ts # Zustand: active GameSave, current node, image/TTS status
└── package.json
```

## API client

`web/src/lib/api.ts` is the single source of truth for HTTP. The backend base lives in `web/src/lib/config.ts` (ARC-016) — it reads `NEXT_PUBLIC_API_BASE` (default `http://localhost:8101`) and exports both `API_BASE` and a derived `WS_BASE`. Every route, hook, and component imports from `config.ts` so no port is hard-coded in more than one place. `api.ts` re-exports `API_BASE` and provides:

- `apiGet<T>`, `apiPost<T>`, `apiPut<T>`, `apiPostForm<T>`, `apiDelete` — typed fetch wrappers used by every page.
- Domain interfaces (`GameSave`, `StoryNode`, `Character`, `Relationship`, `SettingsResponse`, `WizardThemeResponse`, …) that mirror the Pydantic models in `src/storygen/core/models.py` and `src/storygen_api/schemas.py`. When you change a Python model, update the matching interface here.
- `imageUrl(gameId, imagePath)` and `characterPortraitUrl(libraryId, portraitPath)` — build URLs against the API's `/api/games/.../images/...` and `/api/library/...` static mounts.

`web/src/lib/ws-types.ts` mirrors the WebSocket event schema emitted by `src/storygen_api/ws.py` (`narration_delta`, `beat_committed`, `image_committed`, `image_failed`). Keep these in sync with the server side — the ARC-001 alignment in Phase 1 made the contract explicit.

## Data flow

```text
Browser ──HTTP──▶ api.ts ──▶ FastAPI (:8101) ──▶ pipeline / storage / llm / images
   ▲                                                            │
   └──── game-store (Zustand) ◀── useWebSocket ◀── /api/ws/{game_id} ┘
```

- **Page load** — a route fetches initial state via `api.ts` (e.g. `GET /api/games/{id}`) and seeds `game-store`.
- **Live play** — choices `POST /api/games/{id}/advance`; beat narration, image status, and new-character events arrive as WebSocket frames via `useWebSocket`, which writes them into `game-store`. Components re-render off the store, not off local state.
- **Cost-incurring actions** (portrait regen, scene edit, advance) require the bearer token when `STORYGEN_API_TOKEN` is configured; for local loopback dev the token is typically unset.

## Commands

```bash
make web-install    # cd web && npm install
make web-dev        # next dev on :8100 (run alongside `make api-dev` on :8101)
make web-build      # next build
npm run lint        # eslint (run inside web/)
```

`web/` is excluded from pyright (`tool.pyright.exclude = ["web"]`); TypeScript's own checker runs via `next build` / `tsc`.

## Conventions

- Add a new field to a Python model → update the matching interface in `api.ts` in the same change.
- Add a new WebSocket event → add it to `ws-types.ts` and to the server's emit contract together.
- Keep ports aligned across `API_BASE` (`web/src/lib/api.ts`), CORS (`src/storygen_api/main.py`), and `useWebSocket.ts`. The defaults are `:8100` (web) and `:8101` (API); do not drift them.
- This repo uses Next.js 16 with breaking changes versus earlier training data — heed the nextjs-agent-rules block below before writing any Next.js code.

<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->
