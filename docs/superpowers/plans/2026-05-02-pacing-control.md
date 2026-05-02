# Dynamic Pacing Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a three-level pacing control (slow/moderate/fast) that adjusts narration length and choice count in the beat system prompt, with escalation threshold tuning per pacing level.

**Architecture:** A `Pacing` literal type flows from wizard → GameSave → beat agent → system prompt. A helper in `prompts.py` maps pacing to paragraph-count and choice-count ranges. `_pacing_hint_for_depth()` scales thresholds by pacing multiplier. The wizard LENGTH step adds a RadioSet for pacing selection. Settings screen adds a pacing default selector.

**Tech Stack:** Python 3.13, Pydantic, Textual (RadioSet, Select), pydantic-ai

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/storygen/core/models.py` | Add `Pacing` type alias |
| Modify | `src/storygen/storage/app_state.py` | Add `DEFAULT_PACING`, `WizardDefaults.pacing`, serialization |
| Modify | `src/storygen/storage/save.py` | Add `pacing` field to `GameSave` |
| Modify | `src/storygen/llm/prompts.py` | Add `_pacing_guidance()` helper, dynamic ranges in `beat_system_prompt()` |
| Modify | `src/storygen/llm/agents.py` | Add `pacing` param to `build_beat_agent()` |
| Modify | `src/storygen/pipeline.py` | Pass `pacing` to `_pacing_hint_for_depth()`, apply multiplier |
| Modify | `src/storygen/screens/wizard.py` | Add pacing RadioSet to LENGTH step, wire through flow |
| Modify | `src/storygen/app.py` | Pass `save.pacing` to `build_beat_agent()` |
| Modify | `src/storygen/screens/settings.py` | Add pacing Select to wizard defaults section |
| Modify | `tests/unit/test_prompts.py` | Test pacing-to-range mapping |
| Modify | `tests/unit/test_pipeline_helpers.py` | Test `_pacing_hint_for_depth()` with each pacing level |
| Modify | `tests/unit/test_save.py` | Test backward compat (old saves get default pacing) |

---

### Task 1: Add `Pacing` type and wire through data layer

**Files:**
- Modify: `src/storygen/core/models.py:25-26` (add Pacing next to ReaderLevel)
- Modify: `src/storygen/storage/app_state.py:39-43` (add DEFAULT_PACING)
- Modify: `src/storygen/storage/app_state.py:186-198` (add pacing to WizardDefaults)
- Modify: `src/storygen/storage/app_state.py:306-323` (add pacing to read_wizard_defaults)
- Modify: `src/storygen/storage/app_state.py:592-605` (add pacing to _serialize_wizard_defaults)
- Modify: `src/storygen/storage/save.py:14-24,38-66` (add pacing to GameSave)
- Modify: `tests/unit/test_save.py` (add backward-compat test)
- Modify: `tests/unit/test_app_state.py` (add pacing round-trip test)

- [ ] **Step 1: Add `Pacing` type alias to models.py**

In `src/storygen/core/models.py`, add after line 26 (`ReaderLevel = ...`):

```python
Pacing = Literal["slow", "moderate", "fast"]
```

Add `"Pacing"` to the `__all__` list (alphabetical, after `"NodeId"`).

- [ ] **Step 2: Add `DEFAULT_PACING` and `WizardDefaults.pacing` to app_state.py**

In `src/storygen/storage/app_state.py`, add after line 43 (`DEFAULT_READER_LEVEL`):

```python
DEFAULT_PACING: str = "moderate"
```

Add `ALLOWED_PACING` frozenset after line 21 (alongside `_ALLOWED_READER_LEVELS`):

```python
_ALLOWED_PACINGS: frozenset[str] = frozenset({"slow", "moderate", "fast"})
```

In `WizardDefaults` (line 186), add after `reader_level` field (line 196):

```python
    pacing: str = DEFAULT_PACING
```

- [ ] **Step 3: Wire pacing into serialization in app_state.py**

In `read_wizard_defaults()` (line 306), add after the `reader_level=coerce_reader_level(...)` line:

```python
        pacing=str(raw.get("pacing", DEFAULT_PACING)),
```

In `_serialize_wizard_defaults()` (line 592), add after the `"reader_level"` line:

```python
        "pacing": defaults.pacing,
```

- [ ] **Step 4: Add `pacing` field to `GameSave` in save.py**

In `src/storygen/storage/save.py`, add import of `Pacing` to the imports from `storygen.core.models` (line 14-24):

```python
    Pacing,
```

Add to `GameSave` class (line 38), after the `reader_level` field (line 48):

```python
    pacing: Pacing = "moderate"
```

- [ ] **Step 5: Write failing test for GameSave backward compatibility**

In `tests/unit/test_save.py`, add after the existing `test_total_image_cost_defaults_to_zero_on_old_saves` test:

```python
def test_pacing_defaults_to_moderate_on_old_saves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A save JSON without the pacing field loads with 'moderate' default."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    save_game(save)
    # Manually strip the pacing field to simulate an old save.
    import json
    path = paths.game_save_file(str(save.id))
    data = json.loads(path.read_text())
    del data["pacing"]
    path.write_text(json.dumps(data))
    restored = load_game(str(save.id))
    assert restored.pacing == "moderate"
```

- [ ] **Step 6: Write failing test for app_state pacing round-trip**

In `tests/unit/test_app_state.py`, add a new test:

```python
def test_wizard_defaults_pacing_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Pacing preference persists through wizard defaults save/load."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from storygen.storage.app_state import (
        DEFAULT_PACING,
        WizardDefaults,
        read_wizard_defaults,
        write_wizard_defaults,
    )
    write_wizard_defaults(WizardDefaults(pacing="fast"))
    loaded = read_wizard_defaults()
    assert loaded.pacing == "fast"
    # Default
    write_wizard_defaults(WizardDefaults())
    assert read_wizard_defaults().pacing == DEFAULT_PACING
```

- [ ] **Step 7: Run tests to verify**

Run: `uv run pytest tests/unit/test_save.py tests/unit/test_app_state.py -v -x`
Expected: All tests PASS (new pacing field has Pydantic default, backward compat works).

- [ ] **Step 8: Commit**

```bash
git add src/storygen/core/models.py src/storygen/storage/app_state.py src/storygen/storage/save.py tests/unit/test_save.py tests/unit/test_app_state.py
git commit -m "feat: add Pacing type and wire through data layer"
```

---

### Task 2: Add pacing guidance to beat system prompt

**Files:**
- Modify: `src/storygen/llm/prompts.py:1-159` (add helper, dynamic ranges)
- Modify: `src/storygen/llm/agents.py:41-61` (add pacing param)
- Modify: `tests/unit/test_prompts.py` (add pacing tests)

- [ ] **Step 1: Add `_pacing_guidance()` helper to prompts.py**

In `src/storygen/llm/prompts.py`, add import of `Pacing` at line 5:

```python
from storygen.core.models import Character, NarrationStyle, Pacing, ReaderLevel, Theme, Tone
```

Add the helper after `_reader_level_guidance()` (after line 84):

```python
def _pacing_guidance(pacing: Pacing) -> tuple[str, str, str]:
    """Return (paragraph_range, choice_range, extra_guidance) for pacing level."""
    if pacing == "slow":
        return (
            "4-6",
            "2",
            "\nPACING: Take time with description, atmosphere, and inner thoughts."
            " Choices should feel weighty — every decision matters.",
        )
    if pacing == "fast":
        return (
            "1-3",
            "3-5",
            "\nPACING: Keep the pace brisk — action over description. Give the"
            " player frequent choices to maintain momentum.",
        )
    # moderate — current defaults
    return "2-5", "2-4", ""
```

- [ ] **Step 2: Update `beat_system_prompt()` to use pacing**

Change the signature of `beat_system_prompt()` (line 102) to add `pacing`:

```python
def beat_system_prompt(
    *,
    theme: Theme,
    tone: Tone,
    narration_style: NarrationStyle,
    target_major_beats: int = DEFAULT_TARGET_MAJOR_BEATS,
    reader_level: ReaderLevel = "ages_11_15",
    pacing: Pacing = "moderate",
) -> str:
```

Inside the function, after line 111 (`style_reminder = ...`), add:

```python
    para_range, choice_range, pacing_extra = _pacing_guidance(pacing)
```

Replace line 120:
```python
        " - narration: 2-5 paragraphs of prose.\n"
```
with:
```python
        f" - narration: {para_range} paragraphs of prose.\n"
```

Replace lines 121-122:
```python
        " - choices: 2-4 meaningfully different options. Set to an empty"
        " list ONLY when is_ending is true.\n"
```
with:
```python
        f" - choices: {choice_range} meaningfully different options. Set to an empty"
        " list ONLY when is_ending is true.\n"
```

After the `f"{style_reminder}"` at the end of the return (line 158), add:

```python
        f"{pacing_extra}"
```

- [ ] **Step 3: Update `build_beat_agent()` in agents.py**

In `src/storygen/llm/agents.py`, add `Pacing` to the imports from `storygen.core.models` (line 8-18):

```python
    Pacing,
```

Update the `build_beat_agent()` signature (line 41):

```python
def build_beat_agent(
    model: Model,
    *,
    theme: Theme,
    tone: Tone,
    narration_style: NarrationStyle,
    target_major_beats: int = DEFAULT_TARGET_MAJOR_BEATS,
    reader_level: ReaderLevel = "ages_11_15",
    pacing: Pacing = "moderate",
) -> Agent[None, StoryBeat]:
```

Update the `system_prompt=` call inside (line 54):

```python
        system_prompt=prompts.beat_system_prompt(
            theme=theme,
            tone=tone,
            narration_style=narration_style,
            target_major_beats=target_major_beats,
            reader_level=reader_level,
            pacing=pacing,
        ),
```

- [ ] **Step 4: Write failing tests for pacing prompt mapping**

In `tests/unit/test_prompts.py`, add:

```python
def test_beat_prompt_slow_pacing_uses_longer_narration() -> None:
    theme = Theme(title="t", setting="s", premise="p", keywords=[])
    tone = Tone(preset="serious", custom_descriptor=None)
    out = beat_system_prompt(theme=theme, tone=tone, narration_style="third_person", pacing="slow")
    assert "4-6" in out
    assert "2 meaningfully" in out
    assert "atmosphere" in out.lower()


def test_beat_prompt_fast_pacing_uses_shorter_narration() -> None:
    theme = Theme(title="t", setting="s", premise="p", keywords=[])
    tone = Tone(preset="serious", custom_descriptor=None)
    out = beat_system_prompt(theme=theme, tone=tone, narration_style="third_person", pacing="fast")
    assert "1-3" in out
    assert "3-5" in out
    assert "brisk" in out.lower()


def test_beat_prompt_moderate_pacing_matches_default() -> None:
    theme = Theme(title="t", setting="s", premise="p", keywords=[])
    tone = Tone(preset="serious", custom_descriptor=None)
    out_default = beat_system_prompt(theme=theme, tone=tone, narration_style="third_person")
    out_moderate = beat_system_prompt(
        theme=theme, tone=tone, narration_style="third_person", pacing="moderate"
    )
    assert out_default == out_moderate
    assert "2-5" in out_moderate
    assert "2-4" in out_moderate
```

- [ ] **Step 5: Run tests to verify**

Run: `uv run pytest tests/unit/test_prompts.py -v -x`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/storygen/llm/prompts.py src/storygen/llm/agents.py tests/unit/test_prompts.py
git commit -m "feat: add pacing guidance to beat system prompt"
```

---

### Task 3: Add pacing-adjusted escalation thresholds in pipeline

**Files:**
- Modify: `src/storygen/pipeline.py:884-908` (add pacing param, multiplier)
- Modify: `src/storygen/pipeline.py:838-881` (pass pacing from save)
- Modify: `tests/unit/test_pipeline_helpers.py` (add pacing threshold tests)

- [ ] **Step 1: Update `_pacing_hint_for_depth()` to accept pacing**

In `src/storygen/pipeline.py`, change the signature at line 884:

```python
def _pacing_hint_for_depth(depth: int, target: int, pacing: str = "moderate") -> str:
```

Add a multiplier calculation after the docstring (line 889), before the threshold calculations:

```python
    multiplier = {"slow": 1.4, "fast": 0.7}.get(pacing, 1.0)
```

Replace lines 891-893 (the three threshold calculations):

```python
    silent_threshold = max(int(target * 0.3 * multiplier), 1)
    tension_threshold = max(int(target * 0.6 * multiplier), 1)
    climax_threshold = max(int(target * 0.9 * multiplier), 1)
```

- [ ] **Step 2: Pass pacing from `_build_beat_prompt()`**

In `_build_beat_prompt()` at line 878, change:

```python
    pacing_hint = _pacing_hint_for_depth(major_so_far, save.target_major_beats)
```
to:
```python
    pacing_hint = _pacing_hint_for_depth(major_so_far, save.target_major_beats, save.pacing)
```

- [ ] **Step 3: Write failing tests for pacing escalation**

In `tests/unit/test_pipeline_helpers.py`, add import of `_pacing_hint_for_depth`:

```python
from storygen.pipeline import (
    _build_beat_prompt,  # pyright: ignore[reportPrivateUsage]
    _one_sentence,  # pyright: ignore[reportPrivateUsage]
    _pacing_hint_for_depth,  # pyright: ignore[reportPrivateUsage]
    _resolve_chosen_text,  # pyright: ignore[reportPrivateUsage]
)
```

Add tests:

```python
# --- _pacing_hint_for_depth ---


def test_pacing_hint_moderate_silent_at_low_depth() -> None:
    # target=10, moderate → silent_threshold=3
    assert _pacing_hint_for_depth(1, 10, "moderate") == ""


def test_pacing_hint_moderate_tension_at_mid_depth() -> None:
    # target=10, moderate → tension_threshold=6
    result = _pacing_hint_for_depth(5, 10, "moderate")
    assert "tension rising" in result


def test_pacing_hint_moderate_climax_at_high_depth() -> None:
    # target=10, moderate → climax_threshold=9
    result = _pacing_hint_for_depth(8, 10, "moderate")
    assert "tightening" in result


def test_pacing_hint_slow_gives_more_room() -> None:
    # target=5, slow → multiplier=1.4 → silent=2, tension=4, climax=6
    # depth=3 should be "tension" not "climax"
    result = _pacing_hint_for_depth(3, 5, "slow")
    assert "tension rising" in result


def test_pacing_hint_fast_tightens_sooner() -> None:
    # target=5, fast → multiplier=0.7 → silent=1, tension=2, climax=3
    # depth=2 should be "tension" not "silent"
    result = _pacing_hint_for_depth(2, 5, "fast")
    assert "tension rising" in result


def test_pacing_hint_fast_climax_earlier() -> None:
    # target=5, fast → climax=3
    result = _pacing_hint_for_depth(3, 5, "fast")
    assert "tightening" in result
```

- [ ] **Step 4: Run tests to verify**

Run: `uv run pytest tests/unit/test_pipeline_helpers.py tests/unit/test_prompts.py -v -x`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/storygen/pipeline.py tests/unit/test_pipeline_helpers.py
git commit -m "feat: add pacing-adjusted escalation thresholds"
```

---

### Task 4: Wire pacing through app.py and wizard

**Files:**
- Modify: `src/storygen/app.py:532-541` (pass save.pacing)
- Modify: `src/storygen/screens/wizard.py:262-275` (add pacing param to build_initial_save)
- Modify: `src/storygen/screens/wizard.py:423-443` (pass pacing to GameSave)
- Modify: `src/storygen/screens/wizard.py:590-595` (add RadioSet widget)
- Modify: `src/storygen/screens/wizard.py:620-638` (compose RadioSet)
- Modify: `src/storygen/screens/wizard.py:923-931` (show/hide on LENGTH step)
- Modify: `src/storygen/screens/wizard.py:1095-1106` (capture pacing in advance)
- Modify: `src/storygen/screens/wizard.py:1145-1156` (pass to build_initial_save)

- [ ] **Step 1: Pass `save.pacing` to `build_beat_agent()` in app.py**

In `src/storygen/app.py`, in the `_start_game` method (around line 533), add `pacing=save.pacing` to the `build_beat_agent()` call:

```python
        beat_agent = _BeatAgentAdapter(
            agent_mod.build_beat_agent(
                text_model,
                theme=save.theme,
                tone=save.tone,
                narration_style=save.narration_style,
                target_major_beats=save.target_major_beats,
                reader_level=save.reader_level,
                pacing=save.pacing,
            ),
            on_usage=_on_usage,
        )
```

- [ ] **Step 2: Add pacing RadioSet widget to wizard.py**

In `src/storygen/screens/wizard.py`, add import at the top (near other Textual imports):

Add `RadioSet` to the Textual widget imports (find the existing `from textual.widgets import ...` line and add `RadioSet` to it).

Add the widget initialization after `self._length_input` (around line 595):

```python
        self._pacing_input = RadioSet(
            ("Slow — long narration, fewer but weightier choices", "slow"),
            ("Moderate — balanced narration and choices", "moderate"),
            ("Fast — short narration, more frequent choices", "fast"),
            id="wizard-pacing",
        )
        self._pacing: str = defaults.pacing
```

- [ ] **Step 3: Add RadioSet to compose(), _step_widgets(), and wire visibility**

In the `compose()` method (line 620), yield the RadioSet right after `self._length_input`:

```python
            yield self._length_input
            yield self._pacing_input
```

Add `self._pacing_input` to the `_step_widgets()` list (line 882), right after `self._length_input` (line 889). This is the centralized hide-all mechanism — `_render_step()` iterates `_step_widgets()` and sets `display = False` on each before showing only the current step's widgets:

```python
            self._length_input,
            self._pacing_input,
            self._reader_level_select,
```

In `_render_step()` (around line 923), in the `WizardStep.LENGTH` branch, add after `self._length_input.focus()`:

```python
            self._pacing_input.display = True
```

This is sufficient — the centralized hide-all in `_step_widgets()` handles hiding on all other steps.

- [ ] **Step 4: Capture pacing value in _advance_worker**

In the `_advance_worker` method, in the `WizardStep.LENGTH` branch (around line 1095), add after setting `self._target_major_beats`:

```python
                # Capture pacing selection
                pressed = self._pacing_input.pressed_button
                self._pacing = str(pressed.value) if pressed else "moderate"
```

- [ ] **Step 5: Add pacing to `build_initial_save()` signature and GameSave construction**

In `build_initial_save()` (line 262), add parameter:

```python
        pacing: str = app_state.DEFAULT_PACING,
```

In the `GameSave(...)` construction (line 423), add after `reader_level=...`:

```python
            pacing=cast("Pacing", pacing),
```

Add the cast import at the top of the file if not already present (it's likely already imported from `typing`).

Also add `Pacing` to the imports from `storygen.core.models` (or wherever `ReaderLevel` is imported from in this file).

- [ ] **Step 6: Pass pacing in the CONFIRM step call to build_initial_save**

In the CONFIRM step (around line 1145), add `pacing=self._pacing` to the `build_initial_save()` call:

```python
                save = await self._flow.build_initial_save(
                    theme=self._theme,
                    tone=self._tone,
                    narration_style=self._style,
                    characters=self._characters,
                    art_style=self._art_style,
                    target_major_beats=self._target_major_beats,
                    reader_level=self._reader_level,
                    pacing=self._pacing,
                    on_progress=self._notify_progress,
                    library_import_ids=dict(self._imported_from_library_ids),
                    pending_ref_writes=pending_ref_writes or None,
                )
```

- [ ] **Step 7: Run tests to verify**

Run: `uv run pytest tests/unit/test_wizard_flow.py tests/unit/test_wizard_screen.py tests/unit/test_app.py -v -x`
Expected: All tests PASS.

- [ ] **Step 8: Commit**

```bash
git add src/storygen/app.py src/storygen/screens/wizard.py
git commit -m "feat: wire pacing through app and wizard LENGTH step"
```

---

### Task 5: Add pacing selector to Settings screen

**Files:**
- Modify: `src/storygen/screens/settings.py` (add pacing Select widget, wire load/save)

- [ ] **Step 1: Add pacing Select widget**

In `src/storygen/screens/settings.py`, find where the constant options are defined (e.g., `READER_LEVEL_OPTIONS`). Add a new constant:

```python
PACING_OPTIONS: list[tuple[str, str]] = [
    ("Slow", "slow"),
    ("Moderate", "moderate"),
    ("Fast", "fast"),
]
```

In the widget initialization section (around line 325, after `self._reader_level_select`), add:

```python
        self._pacing_select = Select(
            PACING_OPTIONS,
            value=app_state.DEFAULT_PACING,
            allow_blank=False,
            id="default-pacing",
        )
```

- [ ] **Step 2: Add to compose() layout**

In the compose method (around line 420-425), add after the reader level Label and Select:

```python
            yield Label("Default pacing")
            yield self._pacing_select
```

- [ ] **Step 3: Wire load from saved defaults**

In the `_load_values()` method (around line 748, where defaults are loaded), add:

```python
            self._pacing_select.value = defaults.pacing if defaults.pacing in {"slow", "moderate", "fast"} else app_state.DEFAULT_PACING
```

Include `self._pacing_select.prevent(Select.Changed)` in the `with` context manager block alongside the other prevents.

- [ ] **Step 4: Wire save to defaults**

In the save handler (around line 1155), add `pacing=` to the `WizardDefaults(...)` construction:

```python
        defaults = app_state.WizardDefaults(
            ...
            pacing=str(self._pacing_select.value),
        )
```

- [ ] **Step 5: Run tests to verify**

Run: `uv run pytest tests/unit/test_settings_screen.py -v -x`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/storygen/screens/settings.py
git commit -m "feat: add pacing selector to Settings screen"
```

---

### Task 6: Final verification and cleanup

**Files:**
- All modified files

- [ ] **Step 1: Run full checkall**

Run: `make checkall`
Expected: All formatting, linting, type checking, and tests pass.

- [ ] **Step 2: Fix any issues found**

Address any errors from `make checkall`. Common issues:
- Missing imports
- Pyright strict mode violations
- Ruff formatting issues

- [ ] **Step 3: Update CHANGELOG.md**

Add entry under `[Unreleased]`:

```
### Added
- Dynamic pacing control (slow / moderate / fast) — adjusts narration length, choice count, and story escalation thresholds per story
```

- [ ] **Step 4: Remove pacing idea from ideas.md**

Remove the "### Dynamic Difficulty / Pacing Control" section from `ideas.md` using the `idea-done` skill.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: update changelog and ideas list for pacing control"
```
