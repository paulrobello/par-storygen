# Autoplay TTS and Split Image Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make autoplay wait for current-beat image readiness and TTS completion, and split character-portrait image generation from scene/cover art generation.

**Architecture:** `PlayScreen` will make autoplay await auto-read inline and explicitly wait for current-node image terminal state. Image configuration will keep `GameSave.image_config` as scene/cover art and add `GameSave.character_image_config` for portraits, with a split provider wrapper that delegates portrait calls to the character router and scene calls to the art router.

**Tech Stack:** Python 3.13, Textual, Pydantic, `uv`, pytest-asyncio, pyright strict.

---

## File Structure

- Modify `src/storygen/screens/play.py`: autoplay wait coordination and inline auto-read flag.
- Modify `tests/unit/test_play_screen.py`: regression coverage for autoplay waiting on TTS and image terminal state.
- Modify `src/storygen/core/models.py`: `ImageProviderConfig` default remains art default `gpt-image-2`; no save model here.
- Modify `src/storygen/storage/save.py`: add `character_image_config` to `GameSave` with default factory.
- Modify `src/storygen/storage/app_state.py`: add character image defaults, prefs dataclass, read/write/serialization, atomic settings write support.
- Modify `src/storygen/config.py`: add `AppConfig.character_image_config` and resolve `STORYGEN_CHARACTER_IMAGE_*` env vars.
- Create `src/storygen/images/split_provider.py`: protocol-compatible wrapper routing portraits to character provider and scenes to art provider.
- Modify `src/storygen/app.py`: build split providers for new and loaded stories; use character config for portrait providers and art config for scene/cover providers.
- Modify `src/storygen/pipeline.py`: use character config for portrait costs, art config for scene costs/streaming decisions.
- Modify `src/storygen/screens/wizard.py`: save `character_image_config`; use character config for portrait costs and art config for cover costs.
- Modify `src/storygen/screens/portraits.py`: use `save.character_image_config` for portrait cost accounting.
- Modify `src/storygen/screens/library_browser.py` only if cost/config is surfaced there; otherwise no change.
- Modify `src/storygen/screens/settings.py`: add character portrait image provider widgets and persistence.
- Modify tests in `tests/unit/test_app_state.py`, `tests/unit/test_config.py`, `tests/unit/test_image_factory.py`, `tests/unit/test_app.py`, `tests/unit/test_pipeline.py`, `tests/unit/test_wizard_flow.py`, `tests/unit/test_portraits_screen.py`, `tests/unit/test_settings_screen.py` as needed.
- Update docs in `README.md` and `docs/ARCHITECTURE.md` if verification shows user-facing config docs are stale.

---

### Task 1: Autoplay waits for image and TTS

**Files:**
- Modify: `src/storygen/screens/play.py`
- Test: `tests/unit/test_play_screen.py`

- [ ] **Step 1: Write failing TTS autoplay test**

Add a test helper TTS player that blocks until released:

```python
class _BlockingTTSPlayer(TTSPlayer):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.spoken: list[str] = []

    async def speak(self, text: str, cache_path: Path | None = None) -> bool:
        self.spoken.append(text)
        self.started.set()
        await self.release.wait()
        return True
```

Add a test that starts `_pick(..., auto_read_inline=True)` on a screen with auto-read enabled and asserts the coroutine does not complete until `release` is set.

- [ ] **Step 2: Verify TTS test fails**

Run:

```bash
uv run python -m pytest tests/unit/test_play_screen.py::test_autoplay_pick_waits_for_auto_read_to_finish -v
```

Expected: fail because `_pick()` has no `auto_read_inline` argument or returns before blocked TTS completes.

- [ ] **Step 3: Write failing image wait test**

Add a test around `_auto_select_next()` with current node `image_status="generating"`, `_auto_selecting=True`, and a fake pipeline whose pick calls are recorded. Assert no pick occurs until the node status is changed to `done` or `failed`.

- [ ] **Step 4: Verify image test fails**

Run:

```bash
uv run python -m pytest tests/unit/test_play_screen.py::test_auto_select_waits_for_current_image_terminal_state -v
```

Expected: fail because `_auto_select_next()` currently skips waiting when `_image_displayed_at` is unset.

- [ ] **Step 5: Implement autoplay coordination**

In `PlayScreen`:

- Change `_pick(self, n: int)` to `_pick(self, n: int, *, auto_read_inline: bool = False)`.
- In the `finally` block, if narration exists:
  - `await self._maybe_auto_read(...)` when `auto_read_inline` is true.
  - otherwise keep `self.run_worker(..., name="auto-read")`.
- Add `_current_node_image_terminal()` and `_wait_for_current_image_ready()` helpers.
- Change `_auto_select_next()` to call `await self._wait_for_current_image_ready(node.id)` before choosing.
- Change autoplay's pick call to `await self._pick(n, auto_read_inline=True)`.

- [ ] **Step 6: Verify autoplay tests pass**

Run:

```bash
uv run python -m pytest tests/unit/test_play_screen.py::test_autoplay_pick_waits_for_auto_read_to_finish tests/unit/test_play_screen.py::test_auto_select_waits_for_current_image_terminal_state -v
```

Expected: both pass.

- [ ] **Step 7: Run existing play tests**

Run:

```bash
uv run python -m pytest tests/unit/test_play_screen.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/storygen/screens/play.py tests/unit/test_play_screen.py
git commit -m "fix: wait for tts before autoplay advances"
```

---

### Task 2: Add character image config defaults, persistence, and env resolution

**Files:**
- Modify: `src/storygen/storage/save.py`
- Modify: `src/storygen/storage/app_state.py`
- Modify: `src/storygen/config.py`
- Test: `tests/unit/test_app_state.py`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/test_save.py`

- [ ] **Step 1: Write failing config/default tests**

Add tests asserting:

```python
def test_game_save_defaults_character_image_config_to_v15() -> None:
    save = _make_save_without_character_image_config()
    assert save.character_image_config.provider == "openai"
    assert save.character_image_config.model == "gpt-image-1.5"
```

```python
def test_load_config_defaults_art_v2_and_character_v15(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_config()
    assert cfg.image_config.model == "gpt-image-2"
    assert cfg.character_image_config.model == "gpt-image-1.5"
```

```python
def test_character_image_env_does_not_change_art_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORYGEN_CHARACTER_IMAGE_MODEL", "gpt-image-1")
    cfg = load_config()
    assert cfg.image_config.model == "gpt-image-2"
    assert cfg.character_image_config.model == "gpt-image-1"
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
uv run python -m pytest tests/unit/test_app_state.py tests/unit/test_config.py tests/unit/test_save.py -k "character_image or defaults_art_v2" -v
```

Expected: fail because character image prefs/config do not exist.

- [ ] **Step 3: Implement config model and app-state support**

Implement:

- `DEFAULT_CHARACTER_IMAGE_PROVIDER = "openai"`
- `DEFAULT_CHARACTER_IMAGE_MODEL = "gpt-image-1.5"`
- `CharacterImageProviderPrefs` dataclass mirroring `ImageProviderPrefs` without fallback fields.
- `read_character_image_provider_prefs()` / `write_character_image_provider_prefs()`.
- `_serialize_character_image_prefs()`.
- `write_all_settings(..., character_image_prefs: CharacterImageProviderPrefs | None = None, ...)` writes `character_image_provider_prefs` when provided.
- `GameSave.character_image_config: ImageProviderConfig = Field(default_factory=lambda: ImageProviderConfig(model=DEFAULT_CHARACTER_IMAGE_MODEL))`.
- `AppConfig.character_image_config`.
- `_resolve_character_image_config()` reading `STORYGEN_CHARACTER_IMAGE_PROVIDER`, `STORYGEN_CHARACTER_IMAGE_MODEL`, `STORYGEN_CHARACTER_IMAGE_BASE_URL`, and `STORYGEN_CHARACTER_IMAGE_API_KEY`.

- [ ] **Step 4: Verify config/default tests pass**

Run:

```bash
uv run python -m pytest tests/unit/test_app_state.py tests/unit/test_config.py tests/unit/test_save.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/storygen/storage/save.py src/storygen/storage/app_state.py src/storygen/config.py tests/unit/test_app_state.py tests/unit/test_config.py tests/unit/test_save.py
git commit -m "feat: add character image config"
```

---

### Task 3: Route portraits and scenes through split providers

**Files:**
- Create: `src/storygen/images/split_provider.py`
- Modify: `src/storygen/app.py`
- Modify: `src/storygen/pipeline.py`
- Modify: `src/storygen/screens/wizard.py`
- Modify: `src/storygen/screens/portraits.py`
- Test: `tests/unit/test_image_factory.py` or new `tests/unit/test_split_image_provider.py`
- Test: `tests/unit/test_app.py`
- Test: `tests/unit/test_pipeline.py`
- Test: `tests/unit/test_wizard_flow.py`
- Test: `tests/unit/test_portraits_screen.py`

- [ ] **Step 1: Write failing split provider test**

Create a test with fake providers. Assert `SplitImageProvider.generate_portrait()` calls the character fake and `generate_scene()` calls the art fake.

- [ ] **Step 2: Verify split provider test fails**

Run:

```bash
uv run python -m pytest tests/unit/test_split_image_provider.py -v
```

Expected: import failure because `SplitImageProvider` does not exist.

- [ ] **Step 3: Implement `SplitImageProvider`**

Create `src/storygen/images/split_provider.py` with a class accepting `character_provider: ImageProvider` and `art_provider: ImageProvider`, delegating protocol methods accordingly.

- [ ] **Step 4: Write failing integration/cost tests**

Add tests asserting:

- `_start_game()` builds the character router from `save.character_image_config` and art router from `save.image_config`.
- Wizard initial portrait cost uses character config.
- Pipeline new-character portrait cost uses character config.
- Portraits screen regeneration cost uses character config.
- Scene/cover costs still use art config.

- [ ] **Step 5: Verify integration/cost tests fail**

Run targeted tests for the new test names.

- [ ] **Step 6: Implement provider routing and cost changes**

Update app construction:

- Add helper to build art router from art config.
- Add helper to build character router from character config.
- Add helper to return `SplitImageProvider(character_router, art_router)`.
- New wizard flow receives a split provider.
- Loaded save pipeline receives a split provider pinned to the save's two configs.
- `PortraitsScreen` receives the same split provider; portrait calls route to character config.

Update cost calls:

- In `pipeline._portraits()`, use `save.character_image_config`.
- In scene rendering and cover backfill, use `save.image_config`.
- In `WizardFlow`, save both configs and use character config for portraits, art config for cover.
- In `PortraitsScreen`, use `save.character_image_config`.

- [ ] **Step 7: Verify provider/cost tests pass**

Run:

```bash
uv run python -m pytest tests/unit/test_split_image_provider.py tests/unit/test_app.py tests/unit/test_pipeline.py tests/unit/test_wizard_flow.py tests/unit/test_portraits_screen.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/storygen/images/split_provider.py src/storygen/app.py src/storygen/pipeline.py src/storygen/screens/wizard.py src/storygen/screens/portraits.py tests/unit/test_split_image_provider.py tests/unit/test_app.py tests/unit/test_pipeline.py tests/unit/test_wizard_flow.py tests/unit/test_portraits_screen.py
git commit -m "feat: route portraits through character image provider"
```

---

### Task 4: Add character image controls to Settings

**Files:**
- Modify: `src/storygen/screens/settings.py`
- Modify: `tests/unit/test_settings_screen.py`
- Modify: `tests/unit/test_app_state.py`

- [ ] **Step 1: Write failing Settings tests**

Add tests asserting:

- Settings renders a “Character portrait provider” section.
- Defaults show `openai` and `gpt-image-1.5` for character images.
- Saving persists `character_image_provider_prefs`.
- Reset restores character images to `openai / gpt-image-1.5`.

- [ ] **Step 2: Verify Settings tests fail**

Run:

```bash
uv run python -m pytest tests/unit/test_settings_screen.py tests/unit/test_app_state.py -k "character_image or character portrait" -v
```

Expected: fail because widgets/prefs are missing.

- [ ] **Step 3: Implement Settings UI and persistence**

In `SettingsScreen`:

- Add character provider Select, model Select, custom model Input, base URL Input, API key status Static, and suggestions Static.
- Add helper methods mirroring image model select sync for character widgets.
- Populate from `read_character_image_provider_prefs()`.
- Validate character model/base URL in `_save_settings()`.
- Pass `character_image_prefs` to `write_all_settings()`.
- Reset character widgets to defaults.
- Post existing `ImageProviderChanged` after save so app rebuilds both art and character providers from `load_config()`.

- [ ] **Step 4: Verify Settings tests pass**

Run:

```bash
uv run python -m pytest tests/unit/test_settings_screen.py tests/unit/test_app_state.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/storygen/screens/settings.py tests/unit/test_settings_screen.py tests/unit/test_app_state.py
git commit -m "feat: configure character image model separately"
```

---

### Task 5: Documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Optional test fixes discovered by full verification.

- [ ] **Step 1: Update docs**

Document:

- Art/scene default: OpenAI `gpt-image-2`.
- Character portrait default: OpenAI `gpt-image-1.5` for transparent-background support.
- New `STORYGEN_CHARACTER_IMAGE_*` env vars.
- Existing `STORYGEN_IMAGE_*` env vars now mean scene/cover art.
- Autoplay waits for image readiness and TTS completion.

- [ ] **Step 2: Run targeted verification**

Run:

```bash
uv run python -m pytest tests/unit/test_play_screen.py tests/unit/test_config.py tests/unit/test_app_state.py tests/unit/test_settings_screen.py tests/unit/test_split_image_provider.py -v
uv run pyright src tests
```

Expected: tests pass and pyright reports 0 errors.

- [ ] **Step 3: Run full verification**

Run:

```bash
make checkall
```

Expected: format, lint, typecheck, and tests pass.

- [ ] **Step 4: Commit docs/verification fixes**

```bash
git add README.md docs/ARCHITECTURE.md
git commit -m "docs: document split image models"
```

If code fixes were required by verification, include those files in the commit and use a `fix:` message instead.
