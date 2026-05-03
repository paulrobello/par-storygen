# Templates, Recap & Style Gallery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add story presets for quick launch, on-demand "Previously on..." recaps, and a side-by-side image provider comparison gallery.

**Architecture:** Three independent features sharing only the existing app wiring. Presets add a new model + TOML loader + picker screen/modal. Recap adds a new agent + modal + per-node caching + save migration. Gallery adds a new screen that builds temporary providers for side-by-side comparison.

**Tech Stack:** Python 3.13, `tomllib` (stdlib), `importlib.resources` (stdlib), Textual, pydantic-ai, Pydantic.

---

## File Map

### New Files

| File | Responsibility |
|---|---|
| `src/storygen/core/presets.py` | `StoryPreset` model, `load_curated_presets()`, `load_custom_presets()`, `load_all_presets()`, `save_custom_preset()` |
| `src/storygen/presets/haunted_mansion.toml` | Curated preset: gothic horror |
| `src/storygen/presets/space_opera.toml` | Curated preset: sci-fi |
| `src/storygen/presets/dragons_quest.toml` | Curated preset: fantasy |
| `src/storygen/presets/noir_detective.toml` | Curated preset: crime |
| `src/storygen/presets/enchanted_forest.toml` | Curated preset: fairy tale |
| `src/storygen/presets/zombie_apocalypse.toml` | Curated preset: horror |
| `src/storygen/screens/_preset_picker_modal.py` | Modal for wizard THEME step preset loading |
| `src/storygen/screens/preset_picker.py` | Full screen for MenuScreen Quick Start |
| `src/storygen/screens/_recap_modal.py` | Modal for displaying "Previously on..." recap |
| `src/storygen/screens/style_gallery.py` | Style gallery screen with side-by-side provider comparison |
| `tests/unit/test_presets.py` | Tests for preset model, loader, writer |
| `tests/unit/test_recap.py` | Tests for recap agent, modal, caching |
| `tests/unit/test_style_gallery.py` | Tests for gallery screen |

### Modified Files

| File | Changes |
|---|---|
| `src/storygen/core/models.py` | Add `Recap` model, add `recap_text` field to `StoryNode` |
| `src/storygen/llm/agents.py` | Add `build_recap_agent()` |
| `src/storygen/llm/prompts.py` | Add `recap_system_prompt()` |
| `src/storygen/storage/save.py` | Bump version to 2, add v1→v2 migration |
| `src/storygen/storage/app_state.py` | Add `auto_recap()` / `set_auto_recap()`, `recap_interval()` / `set_recap_interval()` |
| `src/storygen/storage/paths.py` | Add `presets_dir()` helper |
| `src/storygen/screens/menu.py` | Add "Quick Start" button (conditional on presets existing) |
| `src/storygen/screens/wizard.py` | Add "Load Preset" button on THEME step, "Save as Preset" on CONFIRM step |
| `src/storygen/screens/play.py` | Add `Shift+R` binding for recap, auto-recap logic |
| `src/storygen/screens/settings.py` | Add auto-recap toggle + interval, Style Gallery button |
| `src/storygen/app.py` | Install PresetPickerScreen + StyleGalleryScreen, wire recap on resume |

---

## Feature 1: Story Templates / Presets

### Task 1: StoryPreset Model and Loader

**Files:**
- Create: `src/storygen/core/presets.py`
- Create: `tests/unit/test_presets.py`
- Modify: `src/storygen/storage/paths.py`

- [ ] **Step 1: Add `presets_dir()` to paths.py**

After `config_root()` (~line 60), add:

```python
def presets_dir() -> Path:
    """Return ``$XDG_CONFIG_HOME/storygen/presets``, creating if needed."""
    d = config_root() / "presets"
    d.mkdir(parents=True, exist_ok=True)
    return d
```

- [ ] **Step 2: Write `src/storygen/core/presets.py`**

```python
from __future__ import annotations

import tomllib
from importlib.resources import files as pkg_files
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from storygen.core.models import NarrationStyle, Pacing, ReaderLevel
from storygen.storage import paths


class StoryPreset(BaseModel):
    name: str
    description: str
    theme: str
    tone_preset: str = "serious"
    tone_descriptor: str = ""
    narration_style: NarrationStyle = "third_person"
    art_style: str = "children's story book"
    target_major_beats: int = 5
    reader_level: ReaderLevel = "ages_11_15"
    pacing: Pacing = "moderate"
    characters: str = ""


def load_curated_presets() -> list[StoryPreset]:
    """Load presets bundled with the package."""
    presets_dir = pkg_files("storygen.presets")
    results: list[StoryPreset] = []
    try:
        items = presets_dir.iterdir()
    except (TypeError, FileNotFoundError, AttributeError):
        return results
    for item in items:
        name = item.name if hasattr(item, "name") else str(item)
        if not name.endswith(".toml"):
            continue
        try:
            data = tomllib.loads(
                item.read_text(encoding="utf-8")
                if hasattr(item, "read_text")
                else Path(str(item)).read_text(encoding="utf-8")
            )
            results.append(StoryPreset(**data))
        except Exception:
            continue
    results.sort(key=lambda p: p.name)
    return results


def load_custom_presets() -> list[StoryPreset]:
    """Load user-created presets from ``$XDG_CONFIG_HOME/storygen/presets/``."""
    d = paths.presets_dir()
    results: list[StoryPreset] = []
    for f in sorted(d.glob("*.toml")):
        try:
            data = tomllib.loads(f.read_text(encoding="utf-8"))
            results.append(StoryPreset(**data))
        except Exception:
            continue
    return results


def load_all_presets() -> list[StoryPreset]:
    """Return curated + custom presets, curated first."""
    return load_curated_presets() + load_custom_presets()


def save_custom_preset(preset: StoryPreset) -> Path:
    """Write a preset as TOML to the custom presets directory."""
    d = paths.presets_dir()
    slug = preset.name.lower().replace(" ", "_")[:48]
    path = d / f"{slug}.toml"
    data: dict[str, Any] = preset.model_dump()
    lines: list[str] = []
    for key, val in data.items():
        if isinstance(val, str):
            escaped = val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            lines.append(f'{key} = "{escaped}"')
        elif isinstance(val, bool):
            lines.append(f"{key} = {'true' if val else 'false'}")
        elif isinstance(val, (int, float)):
            lines.append(f"{key} = {val}")
        elif isinstance(val, list):
            lines.append(f"{key} = {val!r}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
```

- [ ] **Step 3: Write `tests/unit/test_presets.py`**

```python
from __future__ import annotations

import pytest

from storygen.core.presets import StoryPreset


def test_preset_defaults() -> None:
    p = StoryPreset(name="Test", description="A test", theme="A theme")
    assert p.tone_preset == "serious"
    assert p.narration_style == "third_person"
    assert p.art_style == "children's story book"
    assert p.target_major_beats == 5
    assert p.reader_level == "ages_11_15"
    assert p.pacing == "moderate"
    assert p.characters == ""


def test_preset_round_trip(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from storygen.core import presets
    from storygen.storage import paths

    monkeypatch.setattr(paths, "presets_dir", lambda: tmp_path)

    p = StoryPreset(
        name="My Preset",
        description="Desc",
        theme="Spooky",
        tone_preset="dark",
        art_style="oil painting",
        target_major_beats=10,
        characters="A witch and a cat",
    )
    path = presets.save_custom_preset(p)
    assert path.exists()

    loaded = presets.load_custom_presets()
    assert len(loaded) == 1
    assert loaded[0].name == "My Preset"
    assert loaded[0].theme == "Spooky"
    assert loaded[0].characters == "A witch and a cat"


def test_load_all_includes_curated() -> None:
    from storygen.core.presets import load_all_presets

    all_presets = load_all_presets()
    names = [p.name for p in all_presets]
    assert "Haunted Mansion Mystery" in names
    assert "Space Opera Epic" in names
```

- [ ] **Step 4: Run tests to verify**

Run: `uv run pytest tests/unit/test_presets.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/storygen/core/presets.py src/storygen/storage/paths.py tests/unit/test_presets.py
git commit -m "feat: add StoryPreset model, TOML loader, and custom preset writer"
```

---

### Task 2: Curated Preset TOML Files

**Files:**
- Create: `src/storygen/presets/__init__.py` (empty)
- Create: `src/storygen/presets/haunted_mansion.toml`
- Create: `src/storygen/presets/space_opera.toml`
- Create: `src/storygen/presets/dragons_quest.toml`
- Create: `src/storygen/presets/noir_detective.toml`
- Create: `src/storygen/presets/enchanted_forest.toml`
- Create: `src/storygen/presets/zombie_apocalypse.toml`

- [ ] **Step 1: Create `__init__.py`**

Empty file to make `storygen.presets` a package.

- [ ] **Step 2: Write all 6 TOML files**

`src/storygen/presets/haunted_mansion.toml`:
```toml
name = "Haunted Mansion Mystery"
description = "A spooky gothic mystery in a Victorian mansion full of secrets"
theme = "A cursed Victorian mansion where guests disappear one by one. The walls whisper secrets and portraits watch your every move."
tone_preset = "mysterious"
tone_descriptor = "creepy, atmospheric, with moments of dark humor"
narration_style = "first_person"
art_style = "dark gothic oil painting"
target_major_beats = 8
reader_level = "ages_15_plus"
pacing = "slow"
characters = "A skeptical detective, a nervous butler who knows more than he says, a mysterious heiress, and the ghost of the previous owner"
```

`src/storygen/presets/space_opera.toml`:
```toml
name = "Space Opera Epic"
description = "A grand sci-fi adventure across the stars with alien civilizations"
theme = "An interstellar empire on the brink of war. Ancient alien technology has been discovered that could save or destroy civilization."
tone_preset = "action"
tone_descriptor = "epic, sweeping, with moments of wonder and political intrigue"
narration_style = "third_person"
art_style = "retro sci-fi poster art with vibrant colors"
target_major_beats = 10
reader_level = "ages_15_plus"
pacing = "moderate"
characters = "A rogue starship captain, an alien diplomat from a rival species, a brilliant engineer, and a mysterious AI with its own agenda"
```

`src/storygen/presets/dragons_quest.toml`:
```toml
name = "Dragon's Quest"
description = "A classic fantasy adventure with dragons, magic, and ancient prophecies"
theme = "A kingdom threatened by an ancient dragon awakened from a thousand-year slumber. Only a chosen hero can wield the legendary sword."
tone_preset = "action"
tone_descriptor = "adventurous, heroic, with moments of levity and wonder"
narration_style = "third_person"
art_style = "watercolor fantasy illustration with golden highlights"
target_major_beats = 8
reader_level = "ages_11_15"
pacing = "moderate"
characters = "A young farmhand with a hidden destiny, a wise old wizard mentor, a fierce elven archer, and a mischievous talking fox companion"
```

`src/storygen/presets/noir_detective.toml`:
```toml
name = "Noir Detective"
description = "A gritty crime story in a rain-soaked city where nothing is what it seems"
theme = "A hardboiled private investigator takes on a case that leads deep into the city's criminal underworld. Everyone has something to hide."
tone_preset = "dark"
tone_descriptor = "gritty, cynical, with sharp wit and moral ambiguity"
narration_style = "first_person"
art_style = "black and white film noir with high contrast shadows"
target_major_beats = 7
reader_level = "ages_15_plus"
pacing = "slow"
characters = "A world-weary private detective, a femme fatale with a hidden past, a corrupt police captain, and an informant who plays both sides"
```

`src/storygen/presets/enchanted_forest.toml`:
```toml
name = "Enchanted Forest"
description = "A whimsical fairy tale adventure through a magical forest"
theme = "A enchanted forest where animals talk, trees have feelings, and a young adventurer must find the Crystal of Wonders to break a spell."
tone_preset = "whimsical"
tone_descriptor = "playful, magical, with gentle humor and heartwarming moments"
narration_style = "third_person"
art_style = "storybook watercolor with soft pastel colors"
target_major_beats = 6
reader_level = "ages_6_10"
pacing = "moderate"
characters = "A brave young explorer, a wise old owl, a friendly but clumsy troll, and a mischievous fairy who speaks in riddles"
```

`src/storygen/presets/zombie_apocalypse.toml`:
```toml
name = "Zombie Apocalypse"
description = "Survive the undead hordes in a world gone mad"
theme = "Civilization has collapsed after a mysterious outbreak. A small group of survivors must find safety while confronting both the undead and the living."
tone_preset = "serious"
tone_descriptor = "intense, survival-focused, with moments of hope and humanity"
narration_style = "first_person"
art_style = "comic book gritty style with muted colors and heavy inks"
target_major_beats = 8
reader_level = "ages_15_plus"
pacing = "fast"
characters = "A former paramedic turned leader, a resourceful teenager, a cynical ex-soldier, and a scientist who might hold the key to a cure"
```

- [ ] **Step 3: Verify curated presets load**

Run: `uv run python -c "from storygen.core.presets import load_curated_presets; ps = load_curated_presets(); print(len(ps), [p.name for p in ps])"`
Expected: `6 ['Dragons Quest', 'Enchanted Forest', ...]`

- [ ] **Step 4: Run all preset tests**

Run: `uv run pytest tests/unit/test_presets.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/storygen/presets/
git commit -m "feat: add 6 curated story presets (horror, sci-fi, fantasy, noir, fairy tale, zombie)"
```

---

### Task 3: PresetPickerModal for Wizard THEME Step

**Files:**
- Create: `src/storygen/screens/_preset_picker_modal.py`
- Modify: `src/storygen/screens/wizard.py`

- [ ] **Step 1: Write `_preset_picker_modal.py`**

```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.types import NoSelection
from textual.widgets import Button, Footer, Header, Label, Static

from storygen.core.presets import StoryPreset


class PresetPickerModal(Screen[StoryPreset | None]):
    """Modal to pick a story preset. Dismisses with the selected preset or None."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, presets: list[StoryPreset]) -> None:
        super().__init__()
        self._presets = presets

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="preset-modal-box"):
            yield Label("Choose a Preset", id="preset-modal-title")
            with VerticalScroll(id="preset-list"):
                for preset in self._presets:
                    yield Static(
                        f"[bold]{preset.name}[/bold]\n{preset.description}",
                        id=f"preset-{id(preset)}",
                        classes="preset-card",
                    )
            with Vertical(id="preset-modal-buttons"):
                yield Button("Cancel", id="preset-cancel")
        yield Footer()

    def on_static_click(self, event: Static.Click) -> None:
        for preset in self._presets:
            if event.static.id == f"preset-{id(preset)}":
                self.dismiss(preset)
                return

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "preset-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
```

- [ ] **Step 2: Modify `wizard.py` — add "Load Preset" button**

In the `compose()` method, after the THEME step widgets, add a "Load Preset" button. Find the THEME step section in compose and add:

In the wizard `compose()` method, inside the THEME step container, add a button:
```python
yield Button("Load Preset", id="btn-preset", variant="primary")
```

In `__init__`, track it:
```python
self._preset_button: Button = Button("Load Preset", id="btn-preset", variant="primary")
```

In `_step_widgets()`, add `self._preset_button` to the return list.

In `_render_step()` THEME case, show `self._preset_button`.

Add handler:
```python
def on_button_pressed(self, event: Button.Pressed) -> None:
    if event.button.id == "btn-preset":
        self._open_preset_picker()
        return
    # ... existing dispatch ...

def _open_preset_picker(self) -> None:
    from storygen.core.presets import load_all_presets
    from storygen.screens._preset_picker_modal import PresetPickerModal

    presets = load_all_presets()
    if not presets:
        self.notify("No presets available", severity="warning", timeout=5)
        return

    def _on_pick(preset: StoryPreset | None) -> None:
        if preset is None:
            return
        self._apply_preset(preset)

    self.app.push_screen(PresetPickerModal(presets), _on_pick)
```

- [ ] **Step 3: Add `_apply_preset()` to wizard**

```python
def _apply_preset(self, preset: StoryPreset) -> None:
    """Populate all wizard fields from a preset and advance to CONFIRM."""
    self._theme_area.text = preset.theme
    self._tone_select.value = preset.tone_preset
    if preset.tone_descriptor:
        self._tone_descriptor.value = preset.tone_descriptor
        self._tone_descriptor.display = True
    self._style_select.value = preset.narration_style
    self._art_style_input.value = preset.art_style
    self._length_input.value = str(preset.target_major_beats)
    self._reader_level_select.value = preset.reader_level
    self._char_area.text = preset.characters

    self._art_style = preset.art_style
    self._target_major_beats = preset.target_major_beats
    self._reader_level = preset.reader_level
    self._pacing = preset.pacing

    self.notify(f"Loaded preset: {preset.name}", timeout=3)
```

- [ ] **Step 4: Add "Save as Preset" button on CONFIRM step**

Add a "Save as Preset" button instance to `__init__`:
```python
self._save_preset_button: Button = Button("Save as Preset", id="btn-save-preset")
```

In `_step_widgets()`, add `self._save_preset_button`.

In `_render_step()` CONFIRM case, show `self._save_preset_button`.

Add handler in `on_button_pressed`:
```python
if event.button.id == "btn-save-preset":
    self._save_as_preset()
    return
```

```python
def _save_as_preset(self) -> None:
    from storygen.core.presets import StoryPreset, save_custom_preset

    theme_text = self._theme_area.text.strip()
    if not theme_text:
        self.notify("Enter a theme first", severity="warning", timeout=3)
        return

    preset = StoryPreset(
        name=self._theme.title if self._theme else theme_text[:48],
        description=f"Custom preset from {datetime.now().strftime('%Y-%m-%d')}",
        theme=theme_text,
        tone_preset=self._tone_select.value,
        tone_descriptor=self._tone_descriptor.value,
        narration_style=self._style_select.value,
        art_style=self._art_style_input.value,
        target_major_beats=int(self._length_input.value or "5"),
        reader_level=self._reader_level_select.value,
        pacing=self._pacing,
        characters=self._char_area.text,
    )
    path = save_custom_preset(preset)
    self.notify(f"Preset saved to {path.name}", timeout=5)
```

- [ ] **Step 5: Commit**

```bash
git add src/storygen/screens/_preset_picker_modal.py src/storygen/screens/wizard.py
git commit -m "feat: add preset picker modal, wizard Load Preset and Save as Preset"
```

---

### Task 4: PresetPickerScreen for Menu Quick Start

**Files:**
- Create: `src/storygen/screens/preset_picker.py`
- Modify: `src/storygen/screens/menu.py`
- Modify: `src/storygen/app.py`

- [ ] **Step 1: Write `src/storygen/screens/preset_picker.py`**

```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, Static

from storygen.core.presets import StoryPreset, load_all_presets
from storygen.storage import app_state


class PresetPickerScreen(Screen[None]):
    """Full screen for Quick Start — pick a preset and launch directly."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="preset-screen-container"):
            yield Label("Quick Start — Choose a Story", id="preset-screen-title")
            with VerticalScroll(id="preset-screen-list"):
                presets = load_all_presets()
                for preset in presets:
                    yield Static(
                        f"[bold]{preset.name}[/bold]\n{preset.description}",
                        id=f"ps-{id(preset)}",
                        classes="preset-card",
                    )
            yield Button("Back", id="preset-screen-back")
        yield Footer()

    def on_static_click(self, event: Static.Click) -> None:
        presets = load_all_presets()
        for preset in presets:
            if event.static.id == f"ps-{id(preset)}":
                self._launch(preset)
                return

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "preset-screen-back":
            self.app.pop_screen()

    async def _launch(self, preset: StoryPreset) -> None:
        from storygen.llm import agents as agent_mod
        from storygen.llm.provider_factory import build_text_model
        from storygen.screens.wizard import WizardFlow

        app = self.app
        config = app._config  # type: ignore[attr-defined]

        text_model = build_text_model(config.text_config)
        flow = WizardFlow(
            text_config=config.text_config,
            image_config=config.image_config,
            character_image_config=config.character_image_config,
            theme_agent=agent_mod.build_theme_agent(text_model),
            character_agent_factory=lambda theme: agent_mod.build_character_agent(
                text_model, theme=theme
            ),
            blurb_agent_factory=lambda theme, characters, narration_style: (
                agent_mod.build_blurb_agent(
                    text_model,
                    theme=theme,
                    characters=characters,
                    narration_style=narration_style,
                )
            ),
            adapt_agent_factory=lambda theme: agent_mod.build_adapt_backstory_agent(
                text_model, theme=theme
            ),
            image_provider=app._image_provider,  # type: ignore[attr-defined]
        )

        self.notify("Generating story from preset…", timeout=120)

        try:
            theme = await flow.propose_theme(preset.theme)

            tone = app_state.Tone(
                preset=preset.tone_preset,
                custom_descriptor=preset.tone_descriptor or None,
            )
            characters = await flow.generate_characters(
                theme, user_prompt=preset.characters, imported_characters=[]
            )

            save = await flow.build_initial_save(
                theme=theme,
                tone=tone,
                narration_style=preset.narration_style,
                characters=characters,
                art_style=preset.art_style,
                target_major_beats=preset.target_major_beats,
                reader_level=preset.reader_level,
                pacing=preset.pacing,
            )
        except Exception as exc:
            self.notify(f"Failed: {exc}", severity="error", timeout=10)
            return

        await app._start_game(save)  # type: ignore[attr-defined]

    def action_back(self) -> None:
        self.app.pop_screen()
```

- [ ] **Step 2: Modify `menu.py` — add Quick Start button**

Add a new button to the compose method, after the existing 5 buttons:

```python
yield Button("Quick Start", id="btn-quick", variant="success")
```

Add to the button dispatch dict in `on_button_pressed`:
```python
"btn-quick": self.action_quick_start,
```

Add the action:
```python
def action_quick_start(self) -> None:
    from storygen.core.presets import load_all_presets

    if not load_all_presets():
        self.notify("No presets available", severity="warning", timeout=5)
        return
    self.app.push_screen("preset_picker")
```

Add a binding:
```python
# In BINDINGS list, add:
("q", "quick_start", "Quick Start"),
```

- [ ] **Step 3: Modify `app.py` — install PresetPickerScreen**

In `on_mount`, add:
```python
from storygen.screens.preset_picker import PresetPickerScreen
# ...
self.install_screen(PresetPickerScreen(), name="preset_picker")
```

- [ ] **Step 4: Commit**

```bash
git add src/storygen/screens/preset_picker.py src/storygen/screens/menu.py src/storygen/app.py
git commit -m "feat: add Quick Start preset picker screen accessible from menu"
```

---

### Task 5: Preset CSS and Integration

**Files:**
- Modify: `src/storygen/screens/_preset_picker_modal.py` (CSS)
- Modify: `src/storygen/screens/preset_picker.py` (CSS)
- Modify: `src/storygen/screens/menu.py` (CSS for new button)

- [ ] **Step 1: Add CSS to preset modal and screen**

In `_preset_picker_modal.py`, add `CSS` class variable:
```python
CSS = """
#preset-modal-box {
    width: 60;
    height: auto;
    max-height: 80vh;
    padding: 1 2;
    border: thick $accent;
    background: $surface;
}
#preset-modal-title {
    text-align: center;
    text-style: bold;
    margin-bottom: 1;
}
.preset-card {
    padding: 1;
    margin-bottom: 1;
    background: $surface-lighten-1;
}
.preset-card:hover {
    background: $accent-darken-2;
}
#preset-modal-buttons {
    height: auto;
    padding-top: 1;
}
"""
```

In `preset_picker.py`, add similar CSS:
```python
CSS = """
#preset-screen-container {
    align: center middle;
    width: 100%;
    height: 100%;
    padding: 1 4;
}
#preset-screen-title {
    text-align: center;
    text-style: bold;
    margin-bottom: 1;
}
.preset-card {
    padding: 1;
    margin-bottom: 1;
    background: $surface-lighten-1;
}
.preset-card:hover {
    background: $accent-darken-2;
}
"""
```

- [ ] **Step 2: Run checkall**

Run: `make checkall`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add -u
git commit -m "feat: add CSS styling for preset picker modal and screen"
```

---

## Feature 2: Narrative Recap / "Previously On..."

### Task 6: Recap Agent and Model

**Files:**
- Modify: `src/storygen/core/models.py` — add `Recap` model, add `recap_text` to `StoryNode`
- Modify: `src/storygen/llm/agents.py` — add `build_recap_agent()`
- Modify: `src/storygen/llm/prompts.py` — add `recap_system_prompt()`

- [ ] **Step 1: Add `Recap` model to `core/models.py`**

After the `Summary` class (~line 179), add:

```python
class Recap(BaseModel):
    text: str
```

- [ ] **Step 2: Add `recap_text` field to `StoryNode`**

In the `StoryNode` class, after `summary_to_here` (~line 212), add:

```python
    recap_text: str | None = None
```

- [ ] **Step 3: Add `recap_system_prompt()` to `prompts.py`**

After `summary_system_prompt()` (~line 276), add:

```python
def recap_system_prompt() -> str:
    """Return the system prompt for the recap agent."""
    return (
        'You write "Previously on..." recaps for an interactive story.'
        " Given a sequence of story events, produce a dramatic recap"
        " (2-4 paragraphs, max 500 tokens) that:\n"
        "- Opens with 'Previously on [story title]...'\n"
        "- Highlights key plot points, character introductions, and turning points\n"
        "- Emphasizes cliffhangers and unresolved threads\n"
        "- Uses dramatic, engaging tone (not dry summary)\n"
        "- Ends by setting up what comes next\n"
        "Return { text: str }."
    )
```

- [ ] **Step 4: Add `build_recap_agent()` to `agents.py`**

After `build_summary_agent` (~line 112), add:

```python
def build_recap_agent(model: Model) -> Agent[None, Recap]:
    """Build an agent that writes a 'Previously on...' recap."""
    return Agent(
        model=model,
        output_type=Recap,
        system_prompt=prompts.recap_system_prompt(),
    )
```

Add the import for `Recap` at the top of `agents.py`:
```python
from storygen.core.models import ..., Recap
```

- [ ] **Step 5: Commit**

```bash
git add src/storygen/core/models.py src/storygen/llm/agents.py src/storygen/llm/prompts.py
git commit -m "feat: add Recap model, recap agent, and recap system prompt"
```

---

### Task 7: Save Migration v1 → v2

**Files:**
- Modify: `src/storygen/storage/save.py`

- [ ] **Step 1: Add `SAVE_VERSION` constant**

At the top of `save.py`, after imports, add:

```python
SAVE_VERSION: int = 2
```

- [ ] **Step 2: Update `GameSave` default version**

In the `GameSave` class, change:
```python
version: int
```
to:
```python
version: int = SAVE_VERSION
```

- [ ] **Step 3: Implement v1→v2 migration**

Update `_migrate()`:

```python
def _migrate(data: dict[str, Any], *, from_version: int) -> dict[str, Any]:
    if from_version < 2:
        for node in data.get("nodes", {}).values():
            node.setdefault("recap_text", None)
    return data
```

- [ ] **Step 4: Update `save_game` to use `SAVE_VERSION`**

In `save_game()`, before writing, ensure:
```python
save.version = SAVE_VERSION
```

(Add this as a line before the write, or just rely on the model default. The simplest approach is to not touch `save_game` since new saves will already have `version=2` from the model default.)

- [ ] **Step 5: Write migration test**

In `tests/unit/test_save.py`, add:

```python
def test_migrate_v1_to_v2_adds_recap_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from storygen.storage.save import _migrate

    data = {
        "version": 1,
        "nodes": {
            "n1": {"id": "n1", "narration": "Hello"},
            "n2": {"id": "n2", "narration": "World"},
        },
    }
    result = _migrate(data, from_version=1)
    assert result["nodes"]["n1"]["recap_text"] is None
    assert result["nodes"]["n2"]["recap_text"] is None
    # v2 data passes through unchanged
    result2 = _migrate({"version": 2, "nodes": {"n1": {"id": "n1", "recap_text": "Cached"}}}, from_version=2)
    assert result2["nodes"]["n1"]["recap_text"] == "Cached"
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/unit/test_save.py -v -k "migrate"`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/storygen/storage/save.py tests/unit/test_save.py
git commit -m "feat: save migration v1→v2, adds recap_text field to StoryNode"
```

---

### Task 8: RecapModal Screen

**Files:**
- Create: `src/storygen/screens/_recap_modal.py`

- [ ] **Step 1: Write `_recap_modal.py`**

```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static


class RecapModal(Screen[None]):
    """Modal displaying a 'Previously on...' recap. Dismissed with Escape or Enter."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("enter", "close", "Close"),
    ]

    def __init__(self, recap_text: str) -> None:
        super().__init__()
        self._recap_text = recap_text

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="recap-modal-box"):
            yield Static(self._recap_text, id="recap-text", markup=False)
            yield Button("Close", id="recap-close", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "recap-close":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    CSS = """
    #recap-modal-box {
        width: 80;
        max-width: 90vw;
        height: auto;
        max-height: 80vh;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    #recap-text {
        margin-bottom: 1;
    }
    """
```

- [ ] **Step 2: Commit**

```bash
git add src/storygen/screens/_recap_modal.py
git commit -m "feat: add RecapModal screen for displaying Previously On recaps"
```

---

### Task 9: Recap App State and Settings Integration

**Files:**
- Modify: `src/storygen/storage/app_state.py`
- Modify: `src/storygen/screens/settings.py`

- [ ] **Step 1: Add auto-recap state functions to `app_state.py`**

After the existing `auto_open_art_enabled`/`set_auto_open_art_enabled` functions, add:

```python
def auto_recap_enabled() -> bool:
    """Return whether auto-recap is enabled (default: False)."""
    return read_app_state().get("auto_recap", False)


def set_auto_recap(enabled: bool) -> None:
    """Set auto-recap enabled flag."""
    _update_state({"auto_recap": enabled})


def recap_interval() -> int:
    """Return auto-recap interval in major beats (default: 3)."""
    return read_app_state().get("recap_interval", 3)


def set_recap_interval(interval: int) -> None:
    """Set auto-recap interval."""
    _update_state({"recap_interval": max(1, interval)})
```

- [ ] **Step 2: Add auto-recap controls to SettingsScreen**

In the SettingsScreen compose method, after the "Developer" section and before "Text-to-speech", add a new section:

```python
# In compose(), add:
with VerticalScroll.section(id="section-recap"):
    yield Label("Narrative Recap", classes="section-title")
    with Horizontal(classes="switch-row"):
        yield Switch(id="auto-recap-switch", value=app_state.auto_recap_enabled())
        yield Label("Auto-show recap every N major beats")
    with Horizontal(classes="setting-row"):
        yield Label("Interval (major beats):")
        yield Input(
            value=str(app_state.recap_interval()),
            id="recap-interval-input",
            classes="narrow",
        )
```

In `_populate_from_state()`, add:
```python
self.query_one("#auto-recap-switch", Switch).value = app_state.auto_recap_enabled()
self.query_one("#recap-interval-input", Input).value = str(app_state.recap_interval())
```

In `_save_settings()`, add:
```python
auto_recap = self.query_one("#auto-recap-switch", Switch).value
recap_int = max(1, int(self.query_one("#recap-interval-input", Input).value or "3"))
app_state.set_auto_recap(auto_recap)
app_state.set_recap_interval(recap_int)
```

- [ ] **Step 3: Commit**

```bash
git add src/storygen/storage/app_state.py src/storygen/screens/settings.py
git commit -m "feat: add auto-recap toggle and interval setting"
```

---

### Task 10: PlayScreen Recap Integration

**Files:**
- Modify: `src/storygen/screens/play.py`
- Modify: `src/storygen/app.py`

- [ ] **Step 1: Add Shift+R binding to PlayScreen**

In the `BINDINGS` list, add:
```python
("R", "recap", "Previously on..."),
```

- [ ] **Step 2: Add `_major_beats_since_recap` counter**

In `__init__`, add:
```python
self._major_beats_since_recap: int = 0
```

- [ ] **Step 3: Add `action_recap()` method**

```python
async def action_recap(self) -> None:
    """Show a 'Previously on...' recap for the current story."""
    if self._pipeline is None:
        return
    node = self._save.nodes[self._save.current_node_id]

    if node.recap_text:
        self.app.push_screen(RecapModal(node.recap_text))
        return

    self.notify("Generating recap…", timeout=30)
    try:
        recap = await self._generate_recap()
    except Exception as exc:
        self.notify(f"Recap failed: {exc}", severity="error", timeout=10)
        return

    node.recap_text = recap.text
    save_game(self._save)
    self.app.push_screen(RecapModal(recap.text))
```

- [ ] **Step 4: Add `_generate_recap()` helper**

```python
async def _generate_recap(self) -> Recap:
    from storygen.llm.agents import build_recap_agent
    from storygen.llm.provider_factory import build_text_model
    from storygen.storage.tree import path_from_root

    text_model = build_text_model(self._save.text_config)
    agent = build_recap_agent(text_model)

    chain = path_from_root(self._save, self._save.current_node_id)
    parts: list[str] = [f"Story title: {self._save.theme.title}"]

    for node in chain:
        if node.narration:
            parts.append(f"---\n{narration_label(node)}\n{node.narration}")
        if node.choices:
            chosen = next(
                (c for c in node.choices if c.child_node_id is not None),
                None,
            )
            if chosen:
                parts.append(f"Player chose: {chosen.text}")

    prompt = "\n\n".join(parts)
    result = await agent.run(prompt)
    return result.output
```

Add a small helper:
```python
def narration_label(node: StoryNode) -> str:
    if node.id == "root":
        return "[Opening blurb]"
    return f"[Beat]"
```

(This helper should be a module-level function near the imports, not a method.)

- [ ] **Step 5: Add auto-recap check after major beats**

In the beat completion handler (where `is_major` is processed), add after the existing summary generation:

```python
if node.is_major:
    self._major_beats_since_recap += 1
    if (
        app_state.auto_recap_enabled()
        and self._major_beats_since_recap >= app_state.recap_interval()
    ):
        self._major_beats_since_recap = 0
        self.run_worker(self.action_recap(), name="auto-recap")
```

The exact location depends on where `is_major` is handled in the pipeline callback. The implementer should find the `_on_beat` or equivalent method and add this logic there.

- [ ] **Step 6: Add recap-on-resume to `app.py`**

In `_start_game()`, after building the pipeline but before `switch_screen`, add recap-on-resume logic:

```python
# After the PlayScreen is created and switched to, show recap for loaded games
# Check if this is a loaded save (has non-root nodes) vs fresh wizard save
has_progress = len(save.nodes) > 1  # more than just the root node
if has_progress:
    # Schedule recap after screen is mounted
    async def _show_resume_recap() -> None:
        await asyncio.sleep(0.5)  # let screen mount
        play_screen = self.screen
        if isinstance(play_screen, PlayScreen):
            node = save.nodes[save.current_node_id]
            if node.recap_text:
                self.push_screen(RecapModal(node.recap_text))
            else:
                play_screen.run_worker(play_screen.action_recap(), name="resume-recap")

    asyncio.create_task(_show_resume_recap())
```

- [ ] **Step 7: Add necessary imports to play.py**

```python
from storygen.core.models import Recap
from storygen.screens._recap_modal import RecapModal
from storygen.storage.save import save_game
```

- [ ] **Step 8: Commit**

```bash
git add src/storygen/screens/play.py src/storygen/app.py
git commit -m "feat: add on-demand recap (Shift+R), auto-recap after major beats, recap on resume"
```

---

## Feature 3: Image Style Gallery

### Task 11: StyleGalleryScreen

**Files:**
- Create: `src/storygen/screens/style_gallery.py`

- [ ] **Step 1: Write the StyleGalleryScreen**

```python
from __future__ import annotations

import time
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    Static,
)

from storygen.images.pricing import image_cost
from storygen.storage import app_state

_DEFAULT_CHARACTER = (
    "A warrior princess with flowing red hair and emerald green eyes, "
    "wearing ornate silver armor, standing in a confident pose"
)

_PROVIDER_OPTIONS: list[tuple[str, str, str]] = [
    ("openai", "OpenAI", "gpt-image-2"),
    ("gemini", "Gemini", "gemini-3.1-flash-image-preview"),
    ("zai", "Z.AI", "glm-image"),
    ("ollama", "Ollama", "x/z-image-turbo"),
]


class StyleGalleryScreen(Screen[None]):
    """Compare image providers side-by-side with the same character portrait."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
    ]

    def __init__(self, config: Any, image_provider: Any) -> None:
        super().__init__()
        self._config = config
        self._image_provider = image_provider
        self._cache: dict[tuple[str, str, str], bytes] = {}
        self._results_widgets: list[Static] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="gallery-body"):
            yield Label("Image Style Gallery", id="gallery-title")
            yield Label("Compare how different providers render the same character portrait.", id="gallery-desc")

            with Vertical(id="gallery-config"):
                yield Label("Character description:")
                yield Input(value=_DEFAULT_CHARACTER, id="gallery-char-desc")

                yield Label("Providers to compare:")
                for pid, pname, default_model in _PROVIDER_OPTIONS:
                    yield Checkbox(f"{pname} ({default_model})", id=f"gallery-cb-{pid}", value=False)

                yield Button("Generate Comparison", id="gallery-gen", variant="primary")

            with Vertical(id="gallery-results"):
                pass

            yield Button("Back to Settings", id="gallery-back")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "gallery-back":
            self.app.pop_screen()
        elif event.button.id == "gallery-gen":
            self.run_worker(self._generate(), name="gallery-gen")

    def action_back(self) -> None:
        self.app.pop_screen()

    async def _generate(self) -> None:
        from storygen.images.provider_factory import build_image_provider
        from storygen.images._prompts import build_portrait_prompt
        from storygen.core.models import ImageProviderConfig

        desc = self.query_one("#gallery-char-desc", Input).value.strip()
        if not desc:
            self.notify("Enter a character description", severity="warning", timeout=3)
            return

        selected: list[tuple[str, str, str]] = []
        for pid, pname, default_model in _PROVIDER_OPTIONS:
            cb = self.query_one(f"#gallery-cb-{pid}", Checkbox)
            if cb.value:
                selected.append((pid, pname, default_model))

        if len(selected) < 1:
            self.notify("Select at least one provider", severity="warning", timeout=3)
            return

        # Clear previous results
        results = self.query_one("#gallery-results", Vertical)
        for child in list(results.children):
            await child.remove()
        self._results_widgets.clear()

        self.notify(f"Generating {len(selected)} portrait(s)…", timeout=120)

        art_style = self._config.image_config.art_style if hasattr(self._config, 'image_config') else "children's story book"

        for pid, pname, default_model in selected:
            card = Static(f"[dim]{pname}: generating…[/]", classes="gallery-card")
            await results.mount(card)
            self._results_widgets.append(card)

            start = time.monotonic()
            try:
                # Build a temporary provider for this specific provider
                api_key = self._get_api_key(pid)
                cfg = ImageProviderConfig(
                    provider=pid,  # type: ignore[arg-type]
                    model=default_model,
                    api_key=api_key,
                )
                provider = build_image_provider(cfg)
                img_bytes = await provider.generate_portrait(
                    desc,
                    transparent=False,
                    art_style=art_style,
                )
                elapsed = time.monotonic() - start
                cost = image_cost(pid, model=default_model, size="1024x1536")
                card.update(
                    f"[bold]{pname}[/bold] ({default_model})\n"
                    f"Time: {elapsed:.1f}s  |  Est. cost: ${cost:.4f}\n"
                    f"[dim]({len(img_bytes)} bytes)[/]"
                )
                self._cache[(pid, default_model, desc)] = img_bytes
            except Exception as exc:
                elapsed = time.monotonic() - start
                card.update(f"[bold]{pname}[/bold] ({default_model})\n[red]Error: {exc}[/] ({elapsed:.1f}s)")

    def _get_api_key(self, provider: str) -> str | None:
        import os

        key_map = {
            "openai": "OPENAI_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "zai": "ZAI_API_KEY",
        }
        if provider == "ollama":
            return None
        return os.environ.get(key_map.get(provider, ""), "") or None

    CSS = """
    #gallery-body {
        padding: 1 2;
    }
    #gallery-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 0;
    }
    #gallery-desc {
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
    }
    #gallery-config {
        margin-bottom: 1;
        padding: 1;
        border: solid $panel;
    }
    #gallery-results {
        margin-top: 1;
    }
    .gallery-card {
        padding: 1;
        margin-bottom: 1;
        border: solid $panel;
        background: $surface-lighten-1;
    }
    """
```

- [ ] **Step 2: Commit**

```bash
git add src/storygen/screens/style_gallery.py
git commit -m "feat: add StyleGalleryScreen for side-by-side image provider comparison"
```

---

### Task 12: Gallery Settings and App Wiring

**Files:**
- Modify: `src/storygen/screens/settings.py`
- Modify: `src/storygen/app.py`

- [ ] **Step 1: Add Style Gallery button to SettingsScreen**

In the SettingsScreen compose, after the "Art generation provider" section title and before the image provider Select, add:

```python
yield Button("Open Style Gallery", id="btn-style-gallery", variant="primary")
```

In `on_button_pressed`, add handler:
```python
if event.button.id == "btn-style-gallery":
    self.app.push_screen("style_gallery")
    return
```

- [ ] **Step 2: Install StyleGalleryScreen in `app.py`**

In `on_mount`, add:

```python
from storygen.screens.style_gallery import StyleGalleryScreen
# ...
self.install_screen(
    lambda: StyleGalleryScreen(self._config, self._image_provider),
    name="style_gallery",
)
```

- [ ] **Step 3: Run checkall**

Run: `make checkall`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add src/storygen/screens/settings.py src/storygen/app.py
git commit -m "feat: wire StyleGalleryScreen into settings and app"
```

---

### Task 13: Tests for Recap and Gallery

**Files:**
- Create: `tests/unit/test_recap.py`
- Modify: `tests/unit/test_save.py` (already done in Task 7)

- [ ] **Step 1: Write `tests/unit/test_recap.py`**

```python
from __future__ import annotations

import pytest

from storygen.core.models import Recap, StoryNode, Theme, Tone


def test_recap_model() -> None:
    r = Recap(text="Previously on Test Story...")
    assert "Previously on" in r.text


def test_story_node_has_recap_text() -> None:
    node = StoryNode(
        id="n1",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="Hello",
        choices=[],
        is_major=False,
        is_ending=False,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at="2026-01-01T00:00:00Z",
    )
    assert node.recap_text is None

    node.recap_text = "Cached recap"
    assert node.recap_text == "Cached recap"


def test_recap_system_prompt_content() -> None:
    from storygen.llm.prompts import recap_system_prompt

    prompt = recap_system_prompt()
    assert "Previously on" in prompt
    assert "500 tokens" in prompt
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/unit/test_recap.py tests/unit/test_presets.py -v`
Expected: PASS

- [ ] **Step 3: Run full checkall**

Run: `make checkall`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_recap.py
git commit -m "test: add tests for Recap model, StoryNode.recap_text, and recap prompt"
```

---

### Task 14: Update Ideas and Changelog

**Files:**
- Modify: `ideas.md` — remove completed items
- Modify: `CHANGELOG.md` — add entries

- [ ] **Step 1: Remove completed items from `ideas.md`**

Remove these sections:
- "Story Templates / Presets"
- "Narrative Recap / 'Previously On...'"
- "Image Style Gallery"

Add them to the "Completed" section with date 2026-05-03.

- [ ] **Step 2: Add CHANGELOG entries**

- [ ] **Step 3: Commit**

```bash
git add ideas.md CHANGELOG.md
git commit -m "docs: update ideas and changelog for presets, recap, and style gallery"
```

---

## Dependency Graph

```
Task 1 (preset model) → Task 2 (toml files) → Task 3 (modal) → Task 4 (screen) → Task 5 (css)
Task 6 (recap model) → Task 7 (migration) → Task 8 (modal) → Task 9 (settings) → Task 10 (play)
Task 11 (gallery screen) → Task 12 (wiring)
Task 13 (tests) — depends on Tasks 1-12
Task 14 (docs) — depends on all above
```

Tasks within each feature are sequential. Features 1, 2, and 3 are independent and can run in parallel.
