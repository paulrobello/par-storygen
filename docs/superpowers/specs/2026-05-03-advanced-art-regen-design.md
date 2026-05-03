# Advanced Art Regeneration

**Date:** 2026-05-03
**Status:** Implemented

## Problem

Scene and portrait regeneration (`i` key, "Regenerate" button) reuses the
original prompt verbatim. Users cannot steer the result — they must accept
whatever the LLM generates or re-roll and hope for something different.

## Goal

Allow the user to edit-regenerate any existing image by:

1. Using the current image as a reference (where the provider supports it).
2. Specifying freeform edit instructions *or* editing the full prompt.

## Scope

- **Scenes** (PlayScreen): new `Shift+I` binding.
- **Portraits** (PortraitsScreen): new "Edit regen" button per character row.
- Existing `i` key and "Regenerate" button remain unchanged.

## Design

### 1. Data model

```python
# src/storygen/screens/_art_edit_modal.py

class ArtEditMode(StrEnum):
    EDIT = "edit"        # freeform edit instructions appended to original prompt
    FULL  = "full"       # user edits the entire prompt

class ArtEditResult(BaseModel):
    mode: ArtEditMode
    text: str             # edit instructions (EDIT) or full replacement prompt (FULL)
    use_current_as_ref: bool = True
```

### 2. Modal — `ArtEditModal`

`Screen[ArtEditResult | None]`, following the existing modal pattern
(see `CharacterEditModal`, `OutfitCreateModal`).

**Layout:**

```
┌─ Edit Art ──────────────────────────────┐
│                                          │
│  [Thumbnail of current image]            │
│                                          │
│  Mode: (•) Edit instructions  ( ) Full   │
│                                          │
│  Original prompt:                        │
│  ┌─ read-only Static ─────────────────┐  │
│  │ A dark forest clearing with...      │  │
│  └─────────────────────────────────────┘  │
│                                          │
│  [TextArea: edit instructions / prompt]  │
│                                          │
│  (✓) Use current image as reference      │
│                                          │
│  [Generate]                    [Cancel]  │
└──────────────────────────────────────────┘
```

- `RadioSet` toggles between `EDIT` and `FULL`.
- In `EDIT` mode, the TextArea label says "Edit instructions".
- In `FULL` mode, the TextArea is pre-filled with the original prompt and
  the label says "Edit prompt".
- A `Checkbox` controls `use_current_as_ref` (default: checked).
- `Escape` or Cancel dismisses with `None`.
- Generate dismisses with `ArtEditResult`.

### 3. Scene edit-regen flow (PlayScreen)

**Binding:** `("I", "edit_regen_image", "Edit regen")`

**Guard:** same as `retry_image` — node must have an `image_prompt` and
`image_status` in `("failed", "done", "not_planned")`.

**Flow:**

1. `action_edit_regen_image` reads the current node's image file from disk
   (for the reference bytes) and the stored `image_prompt`.
2. Pushes `ArtEditModal(image_bytes=current_image, original_prompt=prompt)`.
3. Callback receives `ArtEditResult`:
   - **EDIT mode:** builds new prompt =
     `"{original_prompt}\n\nEdit instructions: {edit_text}"`.
   - **FULL mode:** uses `result.text` as the prompt directly.
4. Calls `self._pipeline.edit_scene(save, node_id, new_prompt,
   current_image_as_ref=result.use_current_as_ref, callbacks=cb)`.
5. The pipeline writes the new prompt to the node's `image_prompt` field
   (so future simple regens also use the updated prompt), generates, and
   fires callbacks as usual.

### 4. Pipeline — `BeatPipeline.edit_scene`

New method alongside `retry_scene`:

```python
async def edit_scene(
    self,
    save: GameSave,
    *,
    node_id: str,
    new_prompt: str,
    current_image_as_ref: bool = True,
    callbacks: PipelineCallbacks | None = None,
) -> StoryNode:
```

Implementation mirrors `retry_scene` but:

- Uses `new_prompt` instead of `node.image_prompt`.
- Updates the node's `image_prompt` to `new_prompt` before rendering.
- When `current_image_as_ref` is true, reads the current image file and
  *prepends* it to the `refs` list passed to `generate_scene`. The character
  portrait refs follow after it. This works because OpenAI's `images.edit`
  accepts multiple images — the first (the existing scene) provides structural
  guidance, the character refs preserve faces.

### 5. Portrait edit-regen flow (PortraitsScreen)

**Trigger:** new "Edit regen" button per character row, next to existing
"Regenerate".

**Flow:**

1. Reads the current portrait file bytes and `physical_description`/`portrait_prompt`.
2. Pushes `ArtEditModal(image_bytes=current_portrait, original_prompt=desc)`.
3. Callback builds the prompt (EDIT or FULL mode, same logic as scenes).
4. Runs a worker identical to `_regenerate_worker` but:
   - Uses the modified prompt as `description`.
   - If `use_current_as_ref`, passes the current portrait bytes as
     `reference_image` to `generate_portrait` (in addition to any existing
     `char.reference_image_path` ref). When both exist, the current portrait
     is used as the reference (it's closer to the desired result than the
     original user-uploaded ref).

### 6. Provider compatibility

| Provider  | Scene (ref) | Portrait (ref) | Behavior without ref support |
|-----------|-------------|----------------|------------------------------|
| OpenAI    | Yes         | Yes            | Full support via `images.edit` |
| Gemini    | Yes (inline bytes) | No (ignored) | Scene ref works; portrait ref dropped |
| ZAI       | No          | No             | Prompt-only edit, `on_ref_loss` fires |
| Ollama    | No          | No             | Prompt-only edit, `on_ref_loss` fires |

When the provider drops the reference, the user gets a notification:
"Provider does not support image references — using prompt only."

### 7. Files to create/modify

| File | Action | Purpose |
|------|--------|---------|
| `src/storygen/screens/_art_edit_modal.py` | **Create** | Modal with dual-mode editing |
| `src/storygen/screens/play.py` | Modify | Add `Shift+I` binding, `action_edit_regen_image` |
| `src/storygen/screens/portraits.py` | Modify | Add "Edit regen" button, worker method |
| `src/storygen/pipeline.py` | Modify | Add `edit_scene` method |
| `src/storygen/core/models.py` | No change | `ArtEditResult` lives in modal module |
| `tests/unit/test_pipeline.py` | Modify | Test `edit_scene` |
| `tests/unit/test_art_edit_modal.py` | **Create** | Modal unit tests |

### 8. Edge cases

- **No current image on disk** (deleted manually): the modal still opens but
  the thumbnail shows a placeholder. `use_current_as_ref` is silently set to
  `False` — the edit proceeds with prompt only.
- **Empty edit text**: Generate button is disabled until text is non-empty.
- **Provider doesn't support image editing** (all providers except OpenAI for
  portrait ref): the checkbox is still shown (the prompt edit is still
  valuable), but if checked and the provider drops the ref, a warning
  notification fires.
- **Streaming**: `edit_scene` inherits the same streaming behavior as
  `retry_scene` — `on_partial` callbacks fire during generation for OpenAI.
