# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Text-to-speech** — Read story narration aloud via `par-cli-tts` (OpenAI, ElevenLabs, Deepgram, Gemini, Kokoro). Settings: provider, API key, voice selection with refresh, auto-read toggle. Play screen: `t` pause/resume, `T` restart, `s` stop. Per-node audio caching in `audio/` directory avoids redundant API calls.
- **Auto-select** — Press `a` to auto-play the story with random choices. Waits for image display (5s viewing delay) and TTS playback to finish before advancing. Stops at endings or when toggled off with `a`.
- **Deferred illustration fix** — Prefetched nodes that have an illustration plan but no image now trigger scene generation when picked. The `i` (retry image) key also works for `not_planned` nodes with prompts.

### Security

- Exclude `api_key` from `GameSave` serialization (`Field(exclude=True)` on `ImageProviderConfig.api_key`); keys are re-resolved from env on load. Tighten permissions on saved games and library/cache files (`0o600` files, `0o700` directories).
- Disable Rich markup rendering on gameplay widgets (`StoryPanel`, `ChoiceList`, `CharacterSheet`) to prevent injection via LLM-authored narration or imported character fields.
- Add `paths.safe_join` helper and apply at every join of `game_dir` + persisted `portrait_path` / `image_path` to block path traversal from crafted save files.
- Log exception detail at DEBUG and present fixed user-facing messages in UI notifications (no more `str(exc)` leaking provider HTTP bodies).
- Remove unused `pyyaml` dependency.
- Resolve `.env` via `find_dotenv(usecwd=True)` instead of strict CWD-relative `Path(".env")`.

### Added

- New `storygen.core.models` package — canonical home for shared domain types (`Character`, `StoryNode`, `Choice`, `IllustrationPlan`, `TextProviderConfig`, `ImageProviderConfig`, `NarrationStyle`, `ReaderLevel`, …). Resolves the `storage`/`llm` circular import.
- New `storygen.images.constants` module — provider-agnostic image-size / quality constants (`Final[Literal[...]]`).
- New `storygen.widgets._image_util.render_image_thumbnail` helper with optional `on_click` callback (now used by `portraits`, `library_browser`, and `endings`).
- New `storygen.widgets._header_util.format_cost_subtitle` helper (used by `play` and `portraits`).
- `BeatPipeline` now tracks fire-and-forget tasks in a module-level `background_tasks` set (eliminates GC risk and the `# noqa: RUF006` suppression).
- `_migrate(data, from_version)` stub in `storage.save` for future `GameSave` schema migrations.
- `storage.app_state` now memoizes `read_app_state` with a (path, mtime) cache invalidated on write.
- `storage.tree.children_index(save)` helper for O(n) parent→children lookup.
- `WizardFlow.image_provider` public property; `WizardScreen` no longer reaches into `_flow._image_provider`.
- Parameterized `action_pick(n)` key binding in `PlayScreen` (replaces 9 identical methods).
- Tests: `test_library_edit_modal.py` (6 tests), expanded `test_story_import_modal.py` (+5), and `pending_ref_writes` coverage in `test_wizard_flow.py` (+2).
- Repo metadata: `LICENSE` (MIT), `CHANGELOG.md`, `.pre-commit-config.yaml`, `docs/README.md`.
- `make setup` and `make Checkall` Makefile targets.

### Changed

- `BeatPipeline.advance` / `retry_scene` / `_stage_3_scene` now take an explicit `callbacks: PipelineCallbacks | None` parameter; `PlayScreen._pick` passes callbacks per-call instead of mutating a private field. Extracted shared `_render_scene` helper.
- Renamed `_StreamingBeatAgent` → `_BeatAgentAdapter`; renamed `BeatAgentLike.run_stream` → `run` (the implementation never actually streamed).
- `save_library_character` returns a new `LibraryCharacter` via `model_copy` instead of mutating its input.
- `WizardDefaults.reader_level` and related callsites now typed as `ReaderLevel` (previously `str`); added `coerce_reader_level` for legacy values.
- `StoryImportModal._do_import` now collects checked characters across all saves (previously silently dropped selections from non-first saves).
- Provider allow-lists in `config.py` now import from the factory modules that derive them from `Literal[...]` via `get_args()`.
- Replaced `getattr(screen, "_apply_header", None)` patterns with `@runtime_checkable` Protocols (`_HeaderUpdatable`, `_RenderCurrentable`).
- Moved deferred stdlib/`storygen` imports out of `@work` methods to the module top.
- Replaced `assert self._theme is not None` flow-control in `WizardScreen._advance_worker` with explicit `notify` + `return` guards (safe under `python -O`).
- `PortraitsScreen` now imports `ImageProvider` from `images.base` (removed duplicate local Protocol).
- Added `pipeline` to the layered module diagram; converted ARCHITECTURE.md layer diagram to Mermaid.
- Design spec at `docs/superpowers/specs/2026-04-18-storygen-design.md` now carries an explicit v1.0 historical banner.

### Removed

- Dead aliases `_PLACEHOLDER_PNG` and `LibraryBrowserScreen` in `library_browser.py`.
- Local `ImageProviderLike` Protocol in `portraits.py` (import the real one).
- Local `_ClickablePortrait` class in `portraits.py` (replaced by shared helper).
- `NarrationStyle = str` workaround in `llm/prompts.py`.
- `.env~` vim backup file (gitignored, but was still on disk).

## [0.1.0] - 2026-04-23

### Added

- **3-stage beat pipeline** — cache-hit short-circuit, LLM beat generation, and concurrent scene illustration + portrait generation
- **Multi-provider text** — OpenAI, OpenRouter, and Ollama (all OpenAI-compatible via pydantic-ai) with per-save provider pinning
- **Multi-provider images** — OpenAI `gpt-image-2` (ref-aware), Google Gemini (ref-aware), Z.AI GLM-image (text-to-image), and Ollama (local) with automatic fallback via `RoutedImageProvider`
- **Interactive 8-step wizard** — theme, tone, narration style, art style, length (target major beats), reader level, characters, and confirmation; pre-filled from persisted `WizardDefaults`
- **Cross-game character library** — export characters from any story and re-import into new stories with optional AI-powered backstory adaptation; portrait PNG copied, no image-provider call
- **Branch prefetch (v2)** — background-generates pending choices while the player reads; configurable per-save; suppressed side-effects prevent narration bleeding into the current view
- **Character outfits (v2.2)** — multiple portrait variants per character; active outfit used as reference image for scene generation; revert-to-base preserves original portrait
- **Streaming image previews** — opt-in OpenAI `partial_images` previews during scene generation (adds ~5% cost; no-op for other providers)
- **Content-addressed tree persistence** — every node is frozen on commit; replaying the same choice sequence returns byte-for-byte identical results; atomic writes throughout
- **XDG-compliant data storage** — saves at `$XDG_DATA_HOME/storygen/games/`, library at `$XDG_DATA_HOME/storygen/library/`, config at `$XDG_CONFIG_HOME/storygen/state.json`
- **Story graph screen** — full tree view with marker legend, current-node arrow, and unexplored-choice leaves
- **Endings gallery** — card-based view of every ending reached, with jump-to-node navigation
- **Branch replay** — read-only slideshow of any path from root to an explored node; press `j` to jump to live play at any step
- **Reader levels** — vocabulary and complexity controls for ages 0-5, 6-10, 11-15, and 15+; steers beat system prompt vocabulary
- **Reference images** — supply your own character image as a portrait anchor; ref-aware providers (OpenAI, Gemini) use it; others silently ignore it
- **Cost and token tracking** — per-save image cost USD, input/output token counts, and per-model call counts; displayed in PlayScreen header
- **Settings screen** — persisted in-app configuration for provider defaults, art toggle, streaming, prefetch options, and wizard defaults
- **Save/resume** — `--resume` flag re-opens the last-played save; full game state persistence

[0.1.0]: https://github.com/paulrobello/par-storygen/releases/tag/v0.1.0
