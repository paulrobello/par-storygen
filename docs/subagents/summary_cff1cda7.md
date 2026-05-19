# Web Architecture Recommendation: Next.js + FastAPI for par-storygen

## Executive Summary

This document recommends adding a FastAPI web API layer and Next.js frontend to the existing par-storygen repo. The design reuses **all** existing Python modules (`core`, `storage`, `llm`, `images`, `pipeline`, `config`) without modification — the web API imports the same code paths the TUI uses today, just wired through HTTP/WebSocket endpoints instead of Textual screens.

---

## 1. Proposed Project Structure

```
par-storygen/
├── src/
│   ├── storygen/                  # EXISTING — untouched
│   │   ├── core/                  # Domain models (Theme, Character, StoryBeat, etc.)
│   │   ├── storage/               # GameSave, app_state, paths, tree, library
│   │   ├── llm/                   # Agents, prompts, provider_factory, usage
│   │   ├── images/                # Providers, pricing, constants, prompts
│   │   ├── pipeline.py            # BeatPipeline — the 3-stage beat flow
│   │   ├── config.py              # AppConfig resolution (env + .env + prefs)
│   │   ├── export/                # Book export
│   │   ├── tts/                   # TTS player
│   │   ├── screens/               # Textual screens (unchanged)
│   │   ├── widgets/               # Textual widgets (unchanged)
│   │   ├── app.py                 # Textual app (unchanged)
│   │   └── main.py                # Typer CLI (unchanged)
│   │
│   └── storygen_api/              # NEW — FastAPI web layer
│       ├── __init__.py
│       ├── main.py                # FastAPI app factory, CORS, lifespan
│       ├── deps.py                # Dependency injection (config, pipeline, providers)
│       ├── routers/
│       │   ├── __init__.py
│       │   ├── games.py           # CRUD for game saves + advance
│       │   ├── wizard.py          # Theme/characters/blurb generation
│       │   ├── images.py          # Image serving + regeneration
│       │   ├── settings.py        # Read/write app_state
│       │   ├── characters.py      # Character library CRUD
│       │   ├── tts.py             # TTS generation + audio serving
│       │   └── export.py          # Book export endpoint
│       ├── schemas.py             # Pydantic request/response models (API surface)
│       ├── ws.py                  # WebSocket manager + event types
│       └── session.py             # Per-session pipeline management
│
├── web/                           # NEW — Next.js frontend
│   ├── package.json
│   ├── next.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── src/
│   │   ├── app/                   # Next.js App Router pages
│   │   │   ├── layout.tsx         # Root layout (dark theme, providers)
│   │   │   ├── page.tsx           # Landing / redirect to menu
│   │   │   ├── menu/
│   │   │   │   └── page.tsx       # Main menu (New / Load / Settings)
│   │   │   ├── wizard/
│   │   │   │   └── page.tsx       # 8-step story creation wizard
│   │   │   ├── play/
│   │   │   │   └── [gameId]/
│   │   │   │       └── page.tsx   # Main gameplay screen
│   │   │   ├── load/
│   │   │   │   └── page.tsx       # Saved games browser
│   │   │   ├── settings/
│   │   │   │   └── page.tsx       # Settings screen
│   │   │   ├── characters/
│   │   │   │   └── page.tsx       # Character library browser
│   │   │   └── api/               # Next.js API route proxy (optional BFF)
│   │   │       └── [...slug]/
│   │   │           └── route.ts
│   │   ├── components/
│   │   │   ├── ui/                # Shadcn/ui primitives
│   │   │   ├── story/
│   │   │   │   ├── StoryPanel.tsx       # Narration display
│   │   │   │   ├── ChoiceList.tsx       # Player choices
│   │   │   │   ├── ImagePanel.tsx       # Scene illustration
│   │   │   │   ├── CharacterSheet.tsx   # Character roster
│   │   │   │   └── StoryGraph.tsx       # Story tree visualization
│   │   │   ├── wizard/
│   │   │   │   ├── WizardStepper.tsx    # Step indicator
│   │   │   │   ├── ThemeStep.tsx
│   │   │   │   ├── ToneStep.tsx
│   │   │   │   ├── StyleStep.tsx
│   │   │   │   ├── ArtStyleStep.tsx
│   │   │   │   ├── LengthStep.tsx
│   │   │   │   ├── ReaderLevelStep.tsx
│   │   │   │   ├── CharactersStep.tsx
│   │   │   │   └── ConfirmStep.tsx
│   │   │   ├── portraits/
│   │   │   │   ├── PortraitGrid.tsx
│   │   │   │   └── OutfitManager.tsx
│   │   │   ├── settings/
│   │   │   │   ├── ProviderSettings.tsx
│   │   │   │   ├── ImageSettings.tsx
│   │   │   │   ├── WizardDefaults.tsx
│   │   │   │   └── TTSSettings.tsx
│   │   │   └── layout/
│   │   │       ├── Header.tsx
│   │   │       ├── Sidebar.tsx
│   │   │       └── GameLayout.tsx    # Wraps all play-mode pages
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts       # WebSocket connection manager
│   │   │   ├── useGame.ts            # Game state fetching + mutations
│   │   │   ├── usePipeline.ts        # Beat advance + generation progress
│   │   │   └── useSettings.ts        # Settings read/write
│   │   ├── lib/
│   │   │   ├── api.ts                # Typed fetch wrapper for FastAPI
│   │   │   ├── ws-types.ts           # WebSocket event type definitions
│   │   │   └── constants.ts
│   │   └── stores/
│   │       ├── game-store.ts          # Zustand store for current game state
│   │       └── settings-store.ts      # Zustand store for app settings
│   └── public/
│       └── favicon.ico
│
├── pyproject.toml                  # ADD: storygen_api entry point + fastapi deps
└── Makefile                        # ADD: web-dev, web-build, api-dev targets
```

---

## 2. FastAPI API Design

### 2.1 Core Principles

- **Zero changes to existing `storygen/` modules** — the API layer imports and calls them directly.
- The `BeatPipeline` class is the same instance used by the TUI; the API just provides HTTP-shaped wrappers.
- All config resolution goes through the existing `storygen.config.load_config()` path.
- Storage paths use the same XDG layout the TUI uses — games saved via web are loadable via TUI and vice versa.

### 2.2 Dependency Injection (`src/storygen_api/deps.py`)

```python
from functools import lru_cache
from storygen.config import load_config, AppConfig
from storygen.pipeline import BeatPipeline
from storygen.images.provider_factory import build_routed_image_provider
from storygen.images.split_provider import SplitImageProvider
from storygen.llm.provider_factory import build_text_model
from storygen.llm import agents as agent_mod
from storygen_api.session import PipelineSessionManager

@lru_cache
def get_app_config() -> AppConfig:
    return load_config()

def get_session_manager() -> PipelineSessionManager:
    """Manages per-game pipeline instances."""
    ...

# Per-request FastAPI Depends:
def get_pipeline(game_id: str) -> BeatPipeline:
    """Build or retrieve the BeatPipeline for a given game."""
    ...
```

The key insight: **`app.py` already shows exactly how to wire providers into a pipeline.** The API layer replicates that wiring in `deps.py` but uses FastAPI's DI instead of Textual's app lifecycle.

### 2.3 API Routes

#### Games Router (`/api/games`)

| Method | Path | Description | TUI Equivalent |
|--------|------|-------------|----------------|
| `GET` | `/api/games` | List all saved games (with metadata) | `LoadGameScreen` |
| `POST` | `/api/games` | Create game from wizard output | `WizardScreen` → `build_initial_save` |
| `GET` | `/api/games/{game_id}` | Full game state (nodes, characters, current node) | `PlayScreen` mount |
| `DELETE` | `/api/games/{game_id}` | Delete a game save | LoadScreen Delete button |
| `POST` | `/api/games/{game_id}/advance` | Pick a choice → advance story | `_pick()` on PlayScreen |
| `POST` | `/api/games/{game_id}/prefetch` | Trigger prefetch for current node's choices | `_maybe_start_prefetch` |
| `GET` | `/api/games/{game_id}/graph` | Story tree structure (parent→children edges) | `GraphScreen` |
| `POST` | `/api/games/{game_id}/jump` | Set `current_node_id` to any visited node | Graph/Endings jump |
| `POST` | `/api/games/{game_id}/prune` | Prune subtree at a node | GraphScreen `p` binding |
| `GET` | `/api/games/{game_id}/endings` | List all reached endings with breadcrumbs | `EndingsScreen` |
| `GET` | `/api/games/{game_id}/path` | `path_from_root` for a target node | `ReplayScreen` |

**`POST /api/games/{game_id}/advance` request body:**
```json
{
  "choice_id": "abc123",
  "from_node_id": "def456"
}
```

**Response (immediate — narration ready):**
```json
{
  "node": { "id": "ghi789", "narration": "...", "choices": [...], "is_ending": false, ... },
  "new_characters": [...],
  "image_status": "generating"
}
```

The beat is committed synchronously (Stage 1 blocks). Stage 2+3 (illustration + portraits) runs in the background and streams progress via WebSocket.

#### Wizard Router (`/api/wizard`)

| Method | Path | Description | TUI Equivalent |
|--------|------|-------------|----------------|
| `POST` | `/api/wizard/theme` | Generate theme from prompt | `WizardStep.THEME` |
| `POST` | `/api/wizard/characters` | Generate character cast | `WizardStep.CHARACTERS` |
| `POST` | `/api/wizard/blurb` | Generate blurb for root node | `WizardFlow.build_initial_save` |
| `POST` | `/api/wizard/confirm` | Finalize → create `GameSave` + generate portraits | Wizard CONFIRM step |

This maps the wizard's 8 TUI steps to a multi-step REST flow. The frontend drives it step-by-step, just like the TUI does.

#### Images Router (`/api/images`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/images/{game_id}/scene/{node_id}` | Serve scene PNG |
| `GET` | `/api/images/{game_id}/portrait/{char_id}` | Serve character portrait PNG |
| `POST` | `/api/images/{game_id}/scene/{node_id}/retry` | Retry scene generation |
| `POST` | `/api/images/{game_id}/scene/{node_id}/edit` | Edit scene prompt + regenerate |
| `POST` | `/api/images/{game_id}/portrait/{char_id}/regenerate` | Regenerate portrait |

Images are served as static files from the XDG data directory (`paths.node_image_path`, `paths.character_portrait_path`). The endpoint reads from disk using the same `paths.safe_join` traversal guard the TUI codebase already uses.

#### Settings Router (`/api/settings`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/settings` | Full app state (all prefs + toggles) |
| `PUT` | `/api/settings` | Write all settings (mirrors `write_all_settings`) |

Maps directly to `app_state.read_app_state()` / `write_all_settings()`.

#### Characters Router (`/api/characters`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/characters` | List library characters |
| `GET` | `/api/characters/{library_id}` | Single library character + portrait |
| `POST` | `/api/characters` | Export character to library |
| `DELETE` | `/api/characters/{library_id}` | Remove from library |
| `PUT` | `/api/characters/{library_id}` | Edit library character fields |

Direct wrapper around `storage/library.py` functions.

#### TTS Router (`/api/tts`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/tts/generate` | Generate audio for a node's narration |
| `GET` | `/api/tts/audio/{game_id}/{node_id}` | Serve cached audio file |

#### Export Router (`/api/export`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/export/{game_id}/book` | Generate and return HTML book file |

Direct wrapper around `export/book.py:export_book`.

---

## 3. Next.js Component Hierarchy

### Screen Mapping: TUI → Web

| TUI Screen | Web Route | Key Components |
|-----------|-----------|----------------|
| `IntroScreen` | `/` (splash animation, auto-redirect) | CSS animation, no game logic |
| `MenuScreen` | `/menu` | Button grid → New/Load/Settings/Characters |
| `WizardScreen` (8 steps) | `/wizard` | Multi-step form wizard |
| `PlayScreen` | `/play/[gameId]` | `StoryPanel` + `ChoiceList` + `ImagePanel` |
| `LoadGameScreen` | `/load` | Card grid with cover thumbnails |
| `SettingsScreen` | `/settings` | Multi-section form |
| `CharacterCatalogScreen` | `/characters` | Grid of character cards |
| `PortraitsScreen` (modal) | `/play/[gameId]` sidebar/modal | `PortraitGrid` + `OutfitManager` |
| `GraphScreen` (modal) | `/play/[gameId]` modal | `StoryGraph` (D3/ReactFlow tree viz) |
| `EndingsScreen` (modal) | `/play/[gameId]` modal | Ending cards with jump buttons |
| `ReplayScreen` (modal) | `/play/[gameId]` modal | Slideshow player |

### PlayScreen Component Tree (the most complex)

```
<GameLayout>                          // App shell: header + sidebar + main
  ├── <Header                         // Cost, token count, game title
  │     cost={...}
  │     tokens={...}
  │   />
  ├── <Sidebar>                       // Character roster, quick actions
  │     └── <CharacterSheet            // Cast list with portrait thumbnails
  │           characters={save.characters}
  │           onPortraitClick={...}
  │         />
  │     </Sidebar>
  └── <main>
      ├── <ImagePanel                  // Scene illustration
      │     src={node.image_path}
      │     status={node.image_status}
      │     onRetry={retryScene}
      │     onEdit={openArtEditModal}
      │   />
      ├── <StoryPanel                  // Narration text (Markdown renderer)
      │     narration={node.narration}
      │     isEnding={node.is_ending}
      │     isLoading={pipelineLoading}
      │   />
      └── <ChoiceList                  // Player choices
            choices={node.choices}
            disabled={loading}
            onPick={(choiceId) => advance(choiceId)}
          />
    </main>
</GameLayout>

// Modals (overlay)
<PortraitsModal>                      // Portrait grid + regenerate
<GraphModal>                          // Tree visualization
<EndingsModal>                        // Ending cards
<ArtEditModal>                        // Prompt editor + current-image-as-ref
```

### Wizard Component Tree

```
<WizardStepper currentStep={step} steps={[...8...]} />

// Each step is a conditional render:
{step === 0 && <ThemeStep ... />}       // Prompt input → LLM generates theme
{step === 1 && <ToneStep ... />}        // Tone preset selector + custom descriptor
{step === 2 && <StyleStep ... />}       // Narration style radio buttons
{step === 3 && <ArtStyleStep ... />}    // Art style input
{step === 4 && <LengthStep ... />}      // Target major beats slider (2-30)
{step === 5 && <ReaderLevelStep ... />} // Reader level selector
{step === 6 && <CharactersStep ... />}  // Character cast (LLM gen + manual edit + library import)
{step === 7 && <ConfirmStep ... />}     // Review + confirm → POST /api/wizard/confirm
```

---

## 4. Shared Python Code Strategy

### What gets shared (NO extraction needed)

The key architectural insight: **`storygen/` is already layered correctly for API reuse.** The dependency graph is:

```
core → storage → llm → pipeline → screens → app
                 images → pipeline
```

The API layer sits at the **same level** as `app.py` — it imports `pipeline`, `storage`, `llm/agents`, `images/provider_factory`, and `config`. No refactoring required.

### What the API imports directly

| API Module | Imports From | Purpose |
|-----------|-------------|---------|
| `deps.py` | `config.load_config()` | Resolve provider configuration |
| `deps.py` | `images.provider_factory` | Build image providers |
| `deps.py` | `llm.provider_factory` | Build text model |
| `deps.py` | `llm.agents` | Build pydantic-ai agents |
| `routers/games.py` | `storage.save` (`load_game`, `save_game`, `prune_subtree`, `GameSave`) | Save CRUD |
| `routers/games.py` | `pipeline.BeatPipeline` | Story advancement |
| `routers/wizard.py` | `screens/wizard.WizardFlow` (headless mode) | Story creation |
| `routers/images.py` | `storage.paths` | File serving with traversal protection |
| `routers/settings.py` | `storage.app_state` | Settings read/write |
| `routers/characters.py` | `storage.library` | Character library CRUD |
| `routers/tts.py` | `tts.player.TTSPlayer` | Audio generation |
| `routers/export.py` | `export.book.export_book` | HTML book generation |

### WizardFlow reuse

`WizardFlow` is already a **pure state machine** separable from `WizardScreen` — the TUI screen just drives it step-by-step via `@work` decorators. The API can call the same methods:

```python
# API side
flow = WizardFlow(text_config=..., text_model=model)
theme = await flow.generate_theme(prompt)
characters = await flow.generate_characters(theme, character_prompt)
save = await flow.build_initial_save(theme, tone, characters, ...)
```

### Pipeline session management

The API needs a `PipelineSessionManager` that mirrors `app.py`'s `_build_pipeline` logic:

```python
class PipelineSessionManager:
    """One BeatPipeline instance per active game."""

    _instances: dict[str, BeatPipeline] = {}

    def get_or_create(self, game_id: str, save: GameSave) -> BeatPipeline:
        if game_id not in self._instances:
            config = load_config()
            text_model = build_text_model(save.text_config)
            beat_agent = _BeatAgentAdapter(agent=build_beat_agent(text_model, ...))
            illustration_agent = _IllustrationAdapter(agent=build_illustration_agent(text_model))
            image_provider = SplitImageProvider(...)
            pipeline = BeatPipeline(
                beat_agent=beat_agent,
                illustration_agent=illustration_agent,
                summary_agent=...,
                image_provider=image_provider,
            )
            self._instances[game_id] = pipeline
        return self._instances[game_id]
```

This is a **direct port** of what `StoryGenApp._start_game` already does, with the same adapter classes.

---

## 5. Real-Time Communication: WebSocket Design

### 5.1 Protocol Choice: WebSocket (not SSE)

**Why WebSocket over SSE:**
- Bidirectional — the client needs to send commands (advance choice, cancel) and receive streaming updates.
- The pipeline already has multi-stage progress (beat → illustration → scene render) that benefits from a persistent connection.
- Prefetch status updates need push from server to client.
- SSE is simpler for unidirectional streams, but the interactive nature of story play (choice → immediate feedback → background image progress) favors WebSocket.

### 5.2 WebSocket Endpoint

```
WS /api/ws/{game_id}
```

A single persistent WebSocket per active game. All real-time events flow through it.

### 5.3 Event Types (Client → Server)

```typescript
// Client sends these to the server
type ClientEvent =
  | { type: "advance"; choice_id: string; from_node_id: string }
  | { type: "cancel_advance" }
  | { type: "retry_scene"; node_id: string }
  | { type: "edit_scene"; node_id: string; prompt: string; use_current_as_ref: boolean }
  | { type: "start_prefetch" }
  | { type: "tts_generate"; node_id: string }
  | { type: "tts_stop" }
  | { type: "ping" };
```

### 5.4 Event Types (Server → Client)

```typescript
// Server sends these to the client
type ServerEvent =
  | { type: "narration_delta"; text: string }              // Full narration on beat resolve
  | { type: "beat_committed"; node: StoryNode }            // Node persisted
  | { type: "new_characters"; characters: Character[] }    // Mid-story intros
  | { type: "image_status"; node_id: string; status: ImageStatus }  // Scene progress
  | { type: "image_committed"; node_id: string }           // Scene render done
  | { type: "image_failed"; node_id: string }              // Scene render failed
  | { type: "image_partial"; node_id: string; url: string } // Streaming partial preview
  | { type: "prefetch_started"; keys: [string, string][] }
  | { type: "prefetch_complete"; parent_id: string; choice_id: string }
  | { type: "prefetch_failed"; parent_id: string; choice_id: string }
  | { type: "tts_audio_ready"; node_id: string; url: string }
  | { type: "error"; message: string }
  | { type: "pong" };
```

### 5.5 WebSocket Handler Implementation

The WebSocket handler bridges the existing `PipelineCallbacks` to WebSocket events:

```python
@router.websocket("/ws/{game_id}")
async def game_ws(websocket: WebSocket, game_id: str):
    await websocket.accept()
    manager = get_session_manager()
    save = load_game(game_id)

    async def on_narration_delta(text: str):
        await websocket.send_json({"type": "narration_delta", "text": text})

    async def on_beat_committed(node: StoryNode):
        await websocket.send_json({"type": "beat_committed", "node": node.model_dump()})

    async def on_image_committed(node: StoryNode):
        await websocket.send_json({"type": "image_committed", "node_id": node.id})

    async def on_image_failed(node: StoryNode):
        await websocket.send_json({"type": "image_failed", "node_id": node.id})

    callbacks = PipelineCallbacks(
        on_narration_delta=on_narration_delta,
        on_beat_committed=on_beat_committed,
        on_image_committed=on_image_committed,
        on_image_failed=on_image_failed,
    )

    pipeline = manager.get_or_create(game_id, save)

    while True:
        data = await websocket.receive_json()
        event = ClientEvent(**data)

        if event.type == "advance":
            node = await pipeline.advance(
                save,
                from_node_id=event.from_node_id,
                choice_id=event.choice_id,
                callbacks=callbacks,
            )
            save = load_game(game_id)  # Refresh from disk
```

This is a **1:1 mapping** of `PipelineCallbacks` → WebSocket events. The pipeline doesn't know it's talking to WebSocket instead of Textual — it just calls the callback protocol.

### 5.6 Streaming Partial Images

For OpenAI's `partial_images` streaming (which writes intermediate PNGs to disk), the WebSocket handler can watch for file changes or use the `on_partial` callback in the image provider to stream base64-encoded partial PNGs:

```python
async def on_partial(node_id: str, partial_bytes: bytes):
    import base64
    await websocket.send_json({
        "type": "image_partial",
        "node_id": node_id,
        "data": base64.b64encode(partial_bytes).decode(),
    })
```

The frontend renders these as progressive `<img>` updates.

---

## 6. Settings / Storage / Config Sharing

### 6.1 Same Filesystem, Same State

Both the TUI and web API read/write the same files:

| Concern | File Location | Shared? |
|---------|--------------|---------|
| Game saves | `$XDG_DATA_HOME/storygen/games/<uuid>/game.json` | ✅ Identical |
| App state | `$XDG_CONFIG_HOME/storygen/state.json` | ✅ Identical |
| Scene images | `$XDG_DATA_HOME/storygen/games/<uuid>/images/nodes/` | ✅ Identical |
| Portraits | `$XDG_DATA_HOME/storygen/games/<uuid>/images/characters/` | ✅ Identical |
| Audio cache | `$XDG_DATA_HOME/storygen/games/<uuid>/audio/` | ✅ Identical |
| Character library | `$XDG_DATA_HOME/storygen/library/` | ✅ Identical |
| Presets | `$XDG_CONFIG_HOME/storygen/presets/` | ✅ Identical |

A game created in the web UI is immediately loadable in the TUI and vice versa. Settings changed in one are visible in the other (both read from `state.json`).

### 6.2 Config Resolution

The web API uses the same `config.load_config()` chain: env vars > .env file > persisted prefs > defaults. No special web-only config path.

### 6.3 Concurrent Access Safety

The existing code already uses atomic writes (`.tmp` + `os.replace`) for saves and app state. The main concern is **two processes modifying the same save simultaneously** (TUI + web). Mitigation strategies:

1. **File locking** — `fcntl.flock` on the save JSON before read-modify-write. Simple and sufficient for a single-machine deployment.
2. **Session affinity** — the web API can detect if a game is actively open in another session and warn the user.
3. **Optimistic concurrency** — include a version counter in the save; reject writes with stale versions.

For v1, file locking is sufficient — this is a single-user app.

---

## 7. FastAPI Application Factory

```python
# src/storygen_api/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from storygen_api.routers import games, wizard, images, settings, characters, tts, export
from storygen_api.ws import websocket_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: load config, warm up session manager
    yield
    # Shutdown: cancel all background tasks, close pipelines

app = FastAPI(title="par-storygen API", version="0.1.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], ...)

app.include_router(games.router, prefix="/api/games", tags=["games"])
app.include_router(wizard.router, prefix="/api/wizard", tags=["wizard"])
app.include_router(images.router, prefix="/api/images", tags=["images"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(characters.router, prefix="/api/characters", tags=["characters"])
app.include_router(tts.router, prefix="/api/tts", tags=["tts"])
app.include_router(export.router, prefix="/api/export", tags=["export"])
app.include_router(websocket_router)
```

---

## 8. Dependency Additions

### `pyproject.toml` additions:

```toml
[project.optional-dependencies]
api = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "websockets>=12.0",
    "python-multipart>=0.0.9",
]
```

### `web/package.json` key dependencies:

```json
{
  "dependencies": {
    "next": "^15.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "zustand": "^5.0.0",
    "tailwindcss": "^4.0.0",
    "@radix-ui/react-dialog": "latest",
    "@radix-ui/react-select": "latest",
    "lucide-react": "latest",
    "reactflow": "^12.0.0",
    "react-markdown": "^9.0.0"
  }
}
```

---

## 9. Makefile Targets

```makefile
# Web development (run both API + Next.js dev servers)
api-dev:          ## Start FastAPI dev server on :8000
	uv run uvicorn storygen_api.main:app --reload --port 8000

web-dev:          ## Start Next.js dev server on :3000
	cd web && npm run dev

web-install:      ## Install web dependencies
	cd web && npm install

web-build:        ## Build Next.js for production
	cd web && npm run build
```

---

## 10. Key Design Decisions & Tradeoffs

| Decision | Rationale |
|----------|-----------|
| **Same Python process for API** (not separate service) | Simplicity; the storygen modules aren't designed for distributed access. Single-machine, single-user app. |
| **WebSocket over SSE** | Bidirectional needed for cancel, prefetch control. Pipeline has multi-stage progress. |
| **No API auth** | Single-user local app; auth adds complexity with no benefit for the TUI's target audience. |
| **Shared XDG storage** | TUI ↔ Web parity; a game started on the web continues in the terminal. |
| **`storygen_api/` as separate package** | Clean separation; TUI code never imports API code. API imports TUI's business logic but not its UI layer. |
| **Pipeline instances per-game** | Same pattern as the TUI (one `BeatPipeline` per active game). Memory-bounded by active game count. |
| **Next.js App Router** | Modern React patterns; layout nesting maps well to TUI's screen stack. |
| **Zustand over Redux** | Minimal boilerplate; this app's state shape is simple (one game, one pipeline). |
| **ReactFlow for story graph** | Tree visualization is a natural fit; the TUI uses Textual's `Tree` widget which is a simple indented list — the web can do much better. |

---

## 11. Implementation Order (Recommended)

1. **`storygen_api/deps.py` + `schemas.py`** — Define the API surface models and dependency wiring.
2. **`routers/games.py`** — CRUD + advance endpoint. This is the critical path.
3. **`ws.py`** — WebSocket handler with `PipelineCallbacks` bridge.
4. **`web/` scaffold** — Next.js app with routing, `useWebSocket` hook, `useGame` hook.
5. **Play page** — `StoryPanel` + `ChoiceList` + `ImagePanel` components.
6. **`routers/wizard.py`** — Theme/character/blurb generation endpoints.
7. **Wizard page** — Multi-step form.
8. **`routers/settings.py` + settings page** — Straightforward CRUD.
9. **Remaining routers** — Images, characters, TTS, export.
10. **Polish** — Prefetch, streaming partials, graph visualization, endings/replay modals.
