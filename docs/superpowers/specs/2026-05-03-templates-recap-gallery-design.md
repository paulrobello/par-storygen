# Story Templates, Narrative Recap, and Image Style Gallery

**Date:** 2026-05-03
**Status:** Design

Three independent features for par-storygen: pre-built story presets for quick launch, on-demand "Previously on..." recaps, and a side-by-side image provider comparison gallery.

---

## 1. Story Templates / Presets

### Data Format

Presets are TOML files mapping all wizard fields:

```toml
name = "Haunted Mansion Mystery"
description = "A spooky gothic mystery in a Victorian mansion"
theme = "A cursed Victorian mansion where guests disappear one by one"
tone_preset = "suspenseful"
tone_descriptor = "creepy, atmospheric, with moments of dark humor"
narration_style = "first_person"
art_style = "dark gothic oil painting"
target_major_beats = 8
reader_level = "ages_15_plus"
pacing = "slow"
characters = "A skeptical detective, a nervous butler, a mysterious heiress, and the ghost of the previous owner"
```

### Storage

- **Curated**: `src/storygen/presets/*.toml` — bundled with the package, loaded via `importlib.resources`.
- **Custom**: `$XDG_CONFIG_HOME/storygen/presets/*.toml` — user-created, auto-discovered on launch.

### Preset Model

```python
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
```

New file: `src/storygen/core/presets.py` — model, loader (`load_curated_presets()`, `load_custom_presets()`, `load_all_presets()`), and writer (`save_custom_preset()`).

### UI Integration

**MenuScreen**: Add "Quick Start" button (shown only when presets exist). Opens `PresetPickerScreen` (new installed screen) showing curated + custom presets as selectable cards grouped by source. On pick: creates a `WizardFlow` with all fields pre-filled from the preset, runs the LLM steps (theme validation, character generation, portraits, cover), and goes straight to play. Shows a progress notification during generation.

**WizardScreen THEME step**: Add "Load Preset" button below the text area. Opens a compact `PresetPickerModal`. On pick: populates all wizard fields (theme text area, tone select/input, style select, art style input, length input/radio, reader level select, characters text area) and auto-advances to CONFIRM so the user can review and tweak before committing.

### Saving Custom Presets

On the CONFIRM step, add a "Save as Preset" button. Prompts for name + description via a small modal, writes TOML to `$XDG_CONFIG_HOME/storygen/presets/<slugified-name>.toml`. Uses `app_state.xdg_config_home()` for the directory, creating `presets/` if absent.

### Curated Presets (6)

| Name | Genre | Tone | Style | Art Style |
|---|---|---|---|---|
| Haunted Mansion Mystery | Gothic horror | Suspenseful | First person | Dark gothic oil painting |
| Space Opera Epic | Sci-fi | Epic | Third person | Retro sci-fi poster art |
| Dragon's Quest | Fantasy | Adventurous | Third person | Watercolor fantasy illustration |
| Noir Detective | Crime | Gritty | First person | Black and white film noir |
| Enchanted Forest | Fairy tale | Whimsical | Third person | Storybook watercolor |
| Zombie Apocalypse | Horror | Intense | First person | Comic book gritty |

### Files Changed

- **New**: `src/storygen/core/presets.py`, `src/storygen/presets/*.toml` (6 files), `src/storygen/screens/preset_picker.py`
- **Modified**: `src/storygen/screens/menu.py` (Quick Start button), `src/storygen/screens/wizard.py` (Load Preset button + Save as Preset on CONFIRM), `src/storygen/app.py` (install PresetPickerScreen, wire preset loading)

---

## 2. Narrative Recap / "Previously On..."

### Agent Design

New `build_recap_agent(model)` in `agents.py`. Dedicated system prompt:

```
You write "Previously on..." recaps for an interactive story. Given a sequence of story beats, produce a dramatic recap (2-4 paragraphs, max 500 tokens) that:
- Opens with "Previously on [story title]..."
- Highlights key plot points, character introductions, and turning points
- Emphasizes cliffhangers and unresolved threads
- Uses dramatic, engaging tone (not dry summary)
- Ends by setting up what comes next
Return { text: str }.
```

Output type: `Recap(text: str)` in `core/models.py`.

### Input Construction

Reuse the pattern from `_build_beat_prompt()` in `pipeline.py`:

1. Walk `path_from_root(save, node_id)` to get the full path.
2. Find the latest `summary_to_here` on an ancestor node.
3. Append full narration of beats since that summary.
4. Pass to the recap agent as the user message.

### Trigger Points

1. **On-demand (Shift+R)**: PlayScreen keybinding. Shows a modal (`RecapModal`) with the recap text in a scrollable area. Dismissible with Escape/Enter. Generation shows a loading indicator (throbber + "Generating recap..."). The recap text is cached on the current node.

2. **On resume**: When `_start_game(save)` is called for a loaded save (not a fresh wizard save), auto-trigger recap generation. Show as a dismissible notification overlay, not blocking the game view. Uses the current node's cached recap if available.

3. **Auto-recap**: Optional setting (default: off). When enabled, show recap every N major beats. Tracked via a counter on PlayScreen — after each major beat, check if `(major_beats_since_last_recap >= recap_interval)`. If so, trigger recap.

### Settings Integration

Add to app state:
- `auto_recap: bool = False`
- `recap_interval: int = 3`

Add a toggle switch + integer input to SettingsScreen. Both hidden when `auto_recap` is False.

### Per-Node Caching

Add `recap_text: str | None = None` to `StoryNode`. On-demand recap checks current node first. Only calls LLM if `recap_text` is None. After generation, sets `recap_text` and persists the save.

### Save Migration

Bump `GameSave.version` from 1 to 2. Migration adds `recap_text: null` to all nodes in the save. Additive only — no data loss risk.

### Files Changed

- **New**: `src/storygen/screens/_recap_modal.py`
- **Modified**: `src/storygen/llm/agents.py` (build_recap_agent), `src/storygen/llm/prompts.py` (recap_system_prompt), `src/storygen/core/models.py` (Recap model, StoryNode.recap_text), `src/storygen/storage/save.py` (version bump, migration v1→v2), `src/storygen/screens/play.py` (Shift+R binding, auto-recap logic), `src/storygen/screens/settings.py` (auto_recap toggle + interval), `src/storygen/storage/app_state.py` (auto_recap, recap_interval), `src/storygen/app.py` (recap on resume)

---

## 3. Image Style Gallery

### Screen Design

New `StyleGalleryScreen` installed in `app.py`. Accessible via a "Style Gallery" button on SettingsScreen (next to image provider configuration).

### Flow

1. **Pick character**: Scrollable list of library characters. If library is empty, offer a built-in default description: "A warrior princess with flowing red hair and emerald green eyes, wearing ornate silver armor, standing in a confident pose."

2. **Pick providers**: Multi-select `CheckboxSet` of all 4 providers (OpenAI, Gemini, Z.AI, Ollama). Providers without a configured API key are shown grayed out with "(no API key)" label. User picks 2-4 to compare.

3. **Generate**: "Generate Comparison" button. Fires all selected providers concurrently via `@work`. Each builds a temporary `ImageProvider` from that provider's config and calls `generate_portrait(description, art_style=current_art_style)`.

4. **Results**: Horizontal grid of rendered portraits. Each card shows:
   - The rendered image (using the app's existing image rendering — half-block or protocol-detected)
   - Provider name + model name
   - Generation time (seconds)
   - Estimated cost (from `pricing.py`)
   - "Use This Provider" button that writes the provider choice to app state and posts `ImageProviderChanged`

### Caching

Session-scoped `dict[tuple[str, str, str], bytes]` keyed by `(provider, model, character_id)`. No disk persistence — gallery is ephemeral. Re-generating clears the cache for that provider/model/character combo.

### Layout

```
┌─ Style Gallery ──────────────────────────────────────────┐
│                                                           │
│  Character: [A warrior princess with flowing...] ▼        │
│                                                           │
│  Providers:                                               │
│  [x] OpenAI (gpt-image-2)                                │
│  [x] Gemini (gemini-3.1-flash)                           │
│  [ ] Z.AI (glm-image) — no API key                       │
│  [ ] Ollama (x/z-image-turbo)                            │
│                                                           │
│  [Generate Comparison]                                    │
│                                                           │
│  ┌──────────┐  ┌──────────┐                              │
│  │  IMAGE   │  │  IMAGE   │                              │
│  │          │  │          │                              │
│  │ OpenAI   │  │ Gemini   │                              │
│  │ $0.011   │  │ $0.045   │                              │
│  │ 3.2s     │  │ 5.1s     │                              │
│  │[Use This]│  │[Use This]│                              │
│  └──────────┘  └──────────┘                              │
│                                                           │
│  [Back to Settings]                                       │
└───────────────────────────────────────────────────────────┘
```

### Cost & Time Tracking

Each generation wrapped with `time.monotonic()` for timing. Cost computed via existing functions in `images/pricing.py`. Both displayed alongside each result card.

### Art Style

Uses the currently configured `art_style` from app settings so the comparison reflects what the user would actually see in-game.

### Files Changed

- **New**: `src/storygen/screens/style_gallery.py`
- **Modified**: `src/storygen/screens/settings.py` (Style Gallery button), `src/storygen/app.py` (install StyleGalleryScreen, wire dependencies)

---

## Dependency Order

These three features are independent and can be implemented in any order. Recommended sequence for minimal conflict:

1. **Presets** (new files + wizard/menu changes)
2. **Recap** (agent + models + save migration + play screen)
3. **Style Gallery** (new screen + settings)
