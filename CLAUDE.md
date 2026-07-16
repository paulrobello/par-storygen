# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

par-storygen is a Python 3.13 Textual TUI choose-your-own-adventure. A configurable LLM (via pydantic-ai → OpenAI-compatible endpoints) drives theme, characters, narration, and choices; image providers render portraits + scene illustrations. Game state is a content-addressed tree persisted as JSON; revisiting a sequence of choices replays cached content byte-for-byte. Original v1.0 design spec (historical): `docs/superpowers/specs/2026-04-18-storygen-design.md`. Architecture details: `docs/ARCHITECTURE.md`.

## Commands

All targets are defined in the `Makefile`:

```sh
make build            # uv sync
make run              # uv run storygen
make resume           # uv run storygen run --resume
make test             # uv run pytest
make lint             # uv run ruff check .
make fmt              # uv run ruff format .
make typecheck        # uv run pyright
make checkall         # fmt + lint + typecheck + test  (run before committing)
make precommit        # Run pre-commit hooks on all files
make package          # uv build (sdist + wheel)
make clean            # Remove .pytest_cache, .ruff_cache, .pyright, build, dist, *.egg-info, __pycache__
make api-dev          # uvicorn storygen_api.main:app --reload --port 8101  (requires `uv sync --extra api`)
make api-prod         # uvicorn ... --port 8101 --workers 1
make web-install      # cd web && npm install  (Next.js frontend deps)
make web-dev          # Next.js dev server on :8100
make web-build        # Next.js production build
```

Single test or pattern:
```sh
uv run pytest tests/unit/test_pipeline.py -v
uv run pytest -k "test_walk_branch_reload_replay"
```

The CLI: `uv run storygen run [--resume|-r]`. Bare `uv run storygen` is equivalent to `run` with no flags.

## Toolchain

- **Python 3.13**, `uv` for everything (no pip/poetry/pipenv).
- **pyright strict mode** — ground truth. Run `uv run pyright src/ tests/`. IDE `reportMissingImports` for storygen/textual/pydantic are false positives from missing venv — ignore IDE noise, trust `uv run pyright`.
- **ruff** for format + lint (E/F/I/B/UP/SIM/RUF; line length 100; `E501` ignored).
- **pytest** with `asyncio_mode = "auto"` (per-test timeout 10 s).
- **pyfiglet** for ASCII art titles. Font "blocky" for intro, "big" for endings.

## Provider configuration

Configured via environment variables (see `.env.example`) or in-app Settings. **Priority:** env vars > `.env` file > Settings prefs > hardcoded defaults.

**Text** (all OpenAI-compatible): OpenAI (`OPENAI_API_KEY`, default `gpt-4o-mini`), OpenRouter (`OPENROUTER_API_KEY` + `STORYGEN_TEXT_PROVIDER=openrouter`), Ollama (local, no key). Config via `STORYGEN_TEXT_MODEL` and optional `STORYGEN_TEXT_BASE_URL`.

**Image**: OpenAI (`gpt-image-2`, ref-portrait aware), Gemini (ref-aware), Z.AI (text-to-image only), Ollama (local, no refs). Config via `STORYGEN_IMAGE_MODEL`, `STORYGEN_IMAGE_BASE_URL`, `STORYGEN_IMAGE_API_KEY`. Settings supports a fallback provider. Prompt builders in `images/_prompts.py` use structured 5-part format for gpt-image-2, classic paragraph format for others.

## Architecture

```
storage  →  llm + images  →  widgets  →  screens  →  app
```

Lower layers never import higher ones. `app.py` wires concrete providers/agents/pipelines into screens. See `docs/ARCHITECTURE.md` for full implementation details.

**Optional web surface:** the package also ships a FastAPI server (`src/storygen_api/`, installed via the `[api]` extra; console script `storygen-api`) and a Next.js frontend (`web/`). The API is a second composition root over the same `storage`/`llm`/`images`/`pipeline` layers — see the "Web surface" section of `docs/ARCHITECTURE.md`. `web/` is excluded from pyright (`tool.pyright.exclude = ["web"]`). The API carries no auth and binds `0.0.0.0` by default — localhost/single-worker only unless hardened (see `AUDIT.md`).

Key concepts: **3-stage beat pipeline** (cache → beat gen → concurrent illustration + portraits), **choice schema split** (`Choice` for LLM vs `StoredChoice` for storage), **tree graph** (not DAG, frozen nodes), **branch prefetch** (background-generates pending choices), **cross-game character library** (export/import with optional backstory adaptation via `adapt_backstory_system_prompt`), **TTS player** (4-state machine wrapping `par_tts`, per-node audio caching), **export book** (HTML with 3D page-turn rendering via `export/book.py`), **relationship tracking** (pairwise character relationships extracted inline during beat generation).

**Screen flow:** `intro` (splash, auto-dismiss) → `menu` → `wizard` (8 steps) → `play` (main loop). From `play`: `portraits` (modal), `graph` (modal with `replay` sub-modal), `endings` (modal), `load`, `settings`. All screens reachable from `play` re-render on `on_screen_resume`.

**TTS providers:** OpenAI, ElevenLabs, Deepgram, Gemini, Kokoro (local). Configured via `TTSPrefs` in settings. Audio stored as MP3 at `$XDG_DATA_HOME/storygen/games/<game-id>/audio/<node-id>-<provider>-<voice-id>.mp3`.

**Important:** `_textual_patches.py` monkey-patches `Header._on_mount` to catch a Textual startup race. It's imported for side effects from `app.py` and **must be imported before any Header is constructed**.

## Testing patterns

- **conftest.py fixtures:** `xdg_tmp` (isolated XDG_DATA_HOME + XDG_CONFIG_HOME via `monkeypatch` + `tmp_path`) and `reset_dotenv_cache` (autouse — clears `.env` caching between tests). Use `xdg_tmp` in any test that touches storage or config.
- Screen tests use a `_Harness(App[None])` that pushes the screen-under-test in `on_mount` — see existing tests for the shape.
- LLM-dependent code uses a `_Result` wrapper with an `output` attribute and Fake agent classes returning canned data. See `tests/unit/test_wizard_flow.py` and `tests/unit/test_pipeline.py`.
- Image-provider tests pass `AsyncMock`-equipped `client=` directly to `OpenAIImageProvider(...)`.
- Filesystem tests: `monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))` and/or `XDG_CONFIG_HOME`.
- Smoke test:
  ```sh
  OPENAI_API_KEY=sk-test uv run python -c "
  import asyncio
  from storygen.app import StoryGenApp
  async def t():
      app = StoryGenApp()
      async with app.run_test() as pilot:
          await pilot.pause()
          print('OK:', type(app.screen).__name__)
  asyncio.run(t())
  "
  ```

## Conventions

- Pydantic models in strict pyright: use `Field(default_factory=list[Character])` (parameterized) instead of bare `list`.
- Loose-typed pydantic-ai adapters in `app.py` carry `# type: ignore[no-untyped-def]` — preserve that style.
- `Header` on every screen: set title/sub_title via `_apply_header()`, call from both `on_mount` and state-change methods. PlayScreen sub_title: `"$X.XXXX  ·  N↑/N↓ tok"`.
- During beat generation: `PlayScreen._loading=True` blocks all actions except `menu`. Call `self._image.show_generating()` and `self._choices.clear()` on pick.
- Long-running LLM/image work: `@work(exit_on_error=False)`, `notify(...)` for progress (60–120s), errors with `severity="error", timeout=10-15`.
- Footer binding labels: short, verb-first. `check_action` returns False to hide irrelevant bindings.
- Prefer `Sequence[Choice]` over `list[Choice]` for covariance with `StoredChoice`.
- **Concurrent operation guards:** Use a `_regen_busy: set[str]` to track in-flight regenerations; disable all regen buttons while any is running (see `portraits.py`, `library_browser.py`).
- **`on_screen_resume` race:** When a modal dismisses, `on_screen_resume` fires and can clobber UI state before a worker starts. Guard with a flag (e.g. `_image_regen_active`, `_edit_regen_active`) checked in `on_screen_resume` to skip re-rendering.
- **Save migrations** are cumulative in `storage/save.py`. Current schema version is 4 (v1→v2: `recap_text`, v2→v3: `relationships`, v3→v4: `backstory_summary` auto-population).
