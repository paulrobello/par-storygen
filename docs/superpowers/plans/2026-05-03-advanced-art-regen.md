# Advanced Art Regeneration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add edit-based image regeneration that uses the current image as reference and lets the user specify freeform edit instructions or edit the full prompt.

**Architecture:** A new `ArtEditModal` screen handles the dual-mode UI (edit instructions vs full prompt). A new `edit_scene` method on `BeatPipeline` accepts a modified prompt and optionally passes the current scene image as an additional reference. PortraitsScreen gets an inline worker for portrait edit-regen. Both flows push the modal, consume the result, and invoke the image provider.

**Tech Stack:** Textual (Screen, RadioSet, TextArea, Checkbox), Pydantic (BaseModel), existing pipeline/image provider infrastructure.

---

### Task 1: Create `ArtEditModal` — data model and modal screen

**Files:**
- Create: `src/storygen/screens/_art_edit_modal.py`
- Test: `tests/unit/test_art_edit_modal.py`

- [ ] **Step 1: Write failing test for modal dismiss values**

```python
# tests/unit/test_art_edit_modal.py
"""Unit tests for ArtEditModal."""

from __future__ import annotations

import pytest

from storygen.screens._art_edit_modal import ArtEditMode, ArtEditResult


def test_art_edit_result_edit_mode() -> None:
    result = ArtEditResult(mode=ArtEditMode.EDIT, text="make it darker")
    assert result.mode == ArtEditMode.EDIT
    assert result.text == "make it darker"
    assert result.use_current_as_ref is True


def test_art_edit_result_full_mode() -> None:
    result = ArtEditResult(
        mode=ArtEditMode.FULL,
        text="a sunlit meadow with wildflowers",
        use_current_as_ref=False,
    )
    assert result.mode == ArtEditMode.FULL
    assert result.text == "a sunlit meadow with wildflowers"
    assert result.use_current_as_ref is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_art_edit_modal.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write the data model and modal implementation**

```python
# src/storygen/screens/_art_edit_modal.py
"""Modal for advanced art regeneration with dual-mode editing.

Provides two modes:
- *Edit instructions*: freeform text appended to the original prompt.
- *Full prompt*: user edits the entire prompt directly.

Both modes optionally use the current image as a reference. Dismisses with
an :class:`ArtEditResult` on Generate, or ``None`` on Cancel/Escape.
"""

from __future__ import annotations

import io
from enum import StrEnum
from typing import ClassVar

from PIL import Image
from pydantic import BaseModel
from rich_pixels import Pixels
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, RadioButton, RadioSet, Static, TextArea


class ArtEditMode(StrEnum):
    EDIT = "edit"
    FULL = "full"


class ArtEditResult(BaseModel):
    mode: ArtEditMode
    text: str
    use_current_as_ref: bool = True


def _render_thumb(image_bytes: bytes) -> Pixels | None:
    """Render a small thumbnail from raw image bytes."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            im = im.convert("RGBA")
            im.thumbnail((64, 32))
            return Pixels.from_image(im)
    except Exception:
        return None


class ArtEditModal(Screen[ArtEditResult | None]):
    """Edit-regenerate modal with dual-mode prompt editing."""

    DEFAULT_CSS = """
    ArtEditModal {
        align: center middle;
    }
    ArtEditModal #art-edit-box {
        width: 72;
        height: auto;
        max-height: 36;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    ArtEditModal #art-edit-title {
        text-style: bold;
        margin-bottom: 1;
    }
    ArtEditModal #art-edit-thumb {
        height: auto;
        margin-bottom: 1;
    }
    ArtEditModal #art-edit-mode-label {
        margin-top: 1;
    }
    ArtEditModal #art-edit-original-label {
        margin-top: 1;
        color: $text-muted;
    }
    ArtEditModal #art-edit-original {
        height: auto;
        max-height: 4;
        color: $text-muted;
        margin-bottom: 1;
    }
    ArtEditModal #art-edit-input-label {
        margin-top: 1;
    }
    ArtEditModal #art-edit-input {
        height: 5;
        margin-bottom: 1;
    }
    ArtEditModal #art-edit-ref-checkbox {
        margin-bottom: 1;
    }
    ArtEditModal #art-edit-buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    ArtEditModal #art-edit-generate {
        margin-left: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        *,
        original_prompt: str,
        image_bytes: bytes | None = None,
    ) -> None:
        super().__init__()
        self._original_prompt = original_prompt
        self._image_bytes = image_bytes
        self._mode_radios = RadioSet(
            RadioButton("Edit instructions", value=True, id="art-mode-edit"),
            RadioButton("Full prompt", id="art-mode-full"),
            id="art-edit-radios",
        )
        self._input = TextArea(text="", id="art-edit-input")
        self._ref_checkbox = Checkbox(
            "Use current image as reference",
            value=True,
            id="art-edit-ref-checkbox",
        )
        self._generate_btn = Button(
            "Generate", id="art-edit-generate", variant="primary", disabled=True
        )
        self._cancel_btn = Button("Cancel", id="art-edit-cancel")
        self._input_label = Static("Edit instructions:", id="art-edit-input-label")

    def compose(self) -> ComposeResult:
        with Vertical(id="art-edit-box"):
            yield Static("Edit Art", id="art-edit-title")
            # Thumbnail preview
            if self._image_bytes:
                thumb = _render_thumb(self._image_bytes)
                if thumb:
                    yield Static(thumb, id="art-edit-thumb")
            # Mode selector
            yield Static("Mode:", id="art-edit-mode-label")
            yield self._mode_radios
            # Original prompt (read-only)
            yield Static("Original prompt:", id="art-edit-original-label")
            yield Static(self._original_prompt, id="art-edit-original", markup=False)
            # Input area
            yield self._input_label
            yield self._input
            # Ref checkbox
            yield self._ref_checkbox
            # Buttons
            with Horizontal(id="art-edit-buttons"):
                yield self._cancel_btn
                yield self._generate_btn

    def on_mount(self) -> None:
        self._refresh_generate_state()
        # Pre-fill in FULL mode
        if self._mode_radios.pressed_index == 1:
            self._input.load_text(self._original_prompt)

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "art-edit-radios":
            is_full = event.radio_set.pressed_index == 1
            if is_full:
                self._input_label.update("Edit prompt:")
                self._input.load_text(self._original_prompt)
            else:
                self._input_label.update("Edit instructions:")
                self._input.load_text("")
            self._refresh_generate_state()

    def on_text_area_changed(self, _event: TextArea.Changed) -> None:
        self._refresh_generate_state()

    def _refresh_generate_state(self) -> None:
        self._generate_btn.disabled = not self._input.text.strip()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "art-edit-generate":
            text = self._input.text.strip()
            if not text:
                return
            mode = ArtEditMode.FULL if self._mode_radios.pressed_index == 1 else ArtEditMode.EDIT
            self.dismiss(
                ArtEditResult(
                    mode=mode,
                    text=text,
                    use_current_as_ref=self._ref_checkbox.value,
                )
            )
        elif event.button.id == "art-edit-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_art_edit_modal.py -v`
Expected: PASS

- [ ] **Step 5: Run typecheck**

Run: `uv run pyright src/storygen/screens/_art_edit_modal.py tests/unit/test_art_edit_modal.py`
Expected: 0 errors

- [ ] **Step 6: Commit**

```bash
git add src/storygen/screens/_art_edit_modal.py tests/unit/test_art_edit_modal.py
git commit -m "feat: add ArtEditModal with dual-mode prompt editing"
```

---

### Task 2: Add `edit_scene` to `BeatPipeline`

**Files:**
- Modify: `src/storygen/pipeline.py`
- Test: `tests/unit/test_pipeline.py`

- [ ] **Step 1: Write failing test for `edit_scene` with prompt replacement**

Add to `tests/unit/test_pipeline.py` (after the existing `retry_scene` tests):

```python
@pytest.mark.asyncio
async def test_pipeline_edit_scene_replaces_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """edit_scene uses the new prompt and optionally passes current image as ref."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    from datetime import datetime

    failed_node = StoryNode(
        id="edit-node",
        parent_id="root",
        chosen_choice_id="c1",
        chosen_at=datetime.now(UTC),
        narration="A stormy night.",
        choices=[],
        is_major=True,
        is_ending=True,
        image_prompt="dark castle on a hill",
        image_path=None,
        image_status="done",
        illustration_reasoning="moody establishing shot",
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save.nodes["edit-node"] = failed_node
    save.nodes["root"].choices[0].child_node_id = "edit-node"
    save_game(save)

    image_provider = FakeImageProvider()
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=True,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=image_provider,
        callbacks=PipelineCallbacks(),
    )

    result = await pipeline.edit_scene(
        save,
        node_id="edit-node",
        new_prompt="dark castle on a hill with lightning",
    )

    assert len(image_provider.scenes) == 1
    assert image_provider.scenes[0][0] == "dark castle on a hill with lightning"
    assert result.image_status == "done"
    assert result.image_path is not None
    # The stored prompt should be updated.
    assert save.nodes["edit-node"].image_prompt == "dark castle on a hill with lightning"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_pipeline.py::test_pipeline_edit_scene_replaces_prompt -v`
Expected: FAIL — `edit_scene` not found

- [ ] **Step 3: Implement `edit_scene` in `BeatPipeline`**

Add this method to `BeatPipeline` in `src/storygen/pipeline.py`, right after `retry_scene` (after line 567):

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
        """Regenerate the scene image with a modified prompt.

        Like :meth:`retry_scene` but accepts a new prompt and optionally uses
        the current scene image as an additional reference for the provider.

        Args:
            new_prompt: The replacement image prompt.
            current_image_as_ref: If True, read the current image from disk and
                prepend it to the reference portraits list.
            callbacks: Per-call UI callbacks.

        Raises:
            ValueError: if the node has no stored ``image_path`` to read.
        """
        cb = callbacks if callbacks is not None else self._callbacks
        node = save.nodes[node_id]
        if not app_state.art_enabled():
            return node

        save_id = str(save.id)
        dest = paths.node_image_path(save_id, node_id)
        rel_path = str(dest.relative_to(paths.game_dir(save_id)))

        # Update the stored prompt before rendering.
        updated = node.model_copy(
            update={
                "image_prompt": new_prompt,
                "image_status": "generating",
                "image_path": rel_path,
            }
        )
        save.nodes[node_id] = updated
        save_game(save)

        return await self._render_scene(
            save,
            node_id,
            new_prompt,
            list(node.featured_character_ids),
            cb=cb,
            current_image_as_ref=current_image_as_ref,
        )
```

- [ ] **Step 4: Modify `_render_scene` to accept `current_image_as_ref`**

Change the `_render_scene` signature to accept and use the current image. In `src/storygen/pipeline.py`, update `_render_scene`:

```python
    async def _render_scene(
        self,
        save: GameSave,
        node_id: str,
        image_prompt: str,
        featured_character_ids: list[str],
        *,
        cb: PipelineCallbacks,
        current_image_as_ref: bool = False,
    ) -> StoryNode:
```

Inside `_render_scene`, after the existing `refs: list[bytes] = []` block that collects character portraits (around line 760-769), add the current image ref logic:

```python
            refs: list[bytes] = []
            # Optionally prepend the current scene image as the first reference.
            if current_image_as_ref:
                node = save.nodes[node_id]
                if node.image_path:
                    try:
                        cur_path = paths.safe_join(
                            paths.game_dir(save_id), node.image_path
                        )
                        if cur_path.exists():
                            refs.insert(0, cur_path.read_bytes())
                    except ValueError:
                        pass
            for cid in featured_character_ids:
                for c in save.characters:
                    if c.id == cid and c.portrait_path:
                        try:
                            ref_path = paths.safe_join(paths.game_dir(save_id), c.portrait_path)
                            refs.append(ref_path.read_bytes())
                        except ValueError:
                            pass
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_pipeline.py::test_pipeline_edit_scene_replaces_prompt -v`
Expected: PASS

- [ ] **Step 6: Write test for `edit_scene` with current image as ref**

Add to `tests/unit/test_pipeline.py`:

```python
@pytest.mark.asyncio
async def test_pipeline_edit_scene_includes_current_image_as_ref(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """edit_scene with current_image_as_ref=True prepends the existing image."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    from datetime import datetime

    edit_node = StoryNode(
        id="edit-node",
        parent_id="root",
        chosen_choice_id="c1",
        chosen_at=datetime.now(UTC),
        narration="A stormy night.",
        choices=[],
        is_major=True,
        is_ending=True,
        image_prompt="dark castle",
        image_path="images/nodes/edit-node.png",
        image_status="done",
        illustration_reasoning="",
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save.nodes["edit-node"] = edit_node
    save.nodes["root"].choices[0].child_node_id = "edit-node"
    # Write a dummy existing image so edit_scene can read it.
    from storygen.storage import paths as _paths

    img_dir = _paths.game_dir(str(save.id)) / "images" / "nodes"
    img_dir.mkdir(parents=True, exist_ok=True)
    (img_dir / "edit-node.png").write_bytes(b"EXISTING-PNG")
    save_game(save)

    image_provider = FakeImageProvider()
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=True,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=image_provider,
        callbacks=PipelineCallbacks(),
    )

    await pipeline.edit_scene(
        save,
        node_id="edit-node",
        new_prompt="castle with moonlight",
        current_image_as_ref=True,
    )

    assert len(image_provider.scenes) == 1
    # 1 ref = the existing scene image prepended.
    assert image_provider.scenes[0][1] == 1
```

- [ ] **Step 7: Run the new test**

Run: `uv run pytest tests/unit/test_pipeline.py::test_pipeline_edit_scene_includes_current_image_as_ref -v`
Expected: PASS

- [ ] **Step 8: Write test for `edit_scene` when art is disabled**

Add to `tests/unit/test_pipeline.py`:

```python
@pytest.mark.asyncio
async def test_pipeline_edit_scene_skips_when_art_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """edit_scene must be a no-op when art is globally disabled."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    from datetime import datetime

    from storygen.storage import app_state

    edit_node = StoryNode(
        id="edit-node",
        parent_id="root",
        chosen_choice_id="c1",
        chosen_at=datetime.now(UTC),
        narration="x",
        choices=[],
        is_major=True,
        is_ending=True,
        image_prompt="castle",
        image_path=None,
        image_status="done",
        illustration_reasoning="",
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save.nodes["edit-node"] = edit_node
    save_game(save)

    image_provider = FakeImageProvider()
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=True,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=image_provider,
        callbacks=PipelineCallbacks(),
    )

    monkeypatch.setenv("STORYGEN_ART_ENABLED", "false")
    app_state.reload()

    result = await pipeline.edit_scene(
        save,
        node_id="edit-node",
        new_prompt="castle with moonlight",
    )
    assert len(image_provider.scenes) == 0
    assert result.image_status == "done"

    # Restore
    monkeypatch.delenv("STORYGEN_ART_ENABLED", raising=False)
    app_state.reload()
```

- [ ] **Step 9: Run all pipeline tests**

Run: `uv run pytest tests/unit/test_pipeline.py -v`
Expected: All pass

- [ ] **Step 10: Run typecheck**

Run: `uv run pyright src/storygen/pipeline.py tests/unit/test_pipeline.py`
Expected: 0 errors

- [ ] **Step 11: Commit**

```bash
git add src/storygen/pipeline.py tests/unit/test_pipeline.py
git commit -m "feat: add BeatPipeline.edit_scene with current-image-as-ref support"
```

---

### Task 3: Wire `Shift+I` binding into `PlayScreen`

**Files:**
- Modify: `src/storygen/screens/play.py`

- [ ] **Step 1: Add the binding and action**

In `src/storygen/screens/play.py`:

1. Add import at top (near other screen imports):
```python
from storygen.screens._art_edit_modal import ArtEditModal, ArtEditMode
```

2. Add binding after the existing `i` line in `BINDINGS`:
```python
        ("I", "edit_regen_image", "Edit regen"),
```

3. Add guard in `check_action`, after the `retry_image` block:
```python
        if action == "edit_regen_image":
            return node.image_prompt is not None and node.image_status in (
                "failed",
                "done",
                "not_planned",
            )
```

4. Add the action method after `action_retry_image`:
```python
    async def action_edit_regen_image(self) -> None:
        """Open the edit-regen modal for the current scene image."""
        if self._pipeline is None:
            return
        node = self._save.nodes[self._save.current_node_id]
        if not node.image_prompt:
            return
        save_id = str(self._save.id)
        # Read current image bytes for reference.
        image_bytes: bytes | None = None
        if node.image_path:
            try:
                abs_path = paths.safe_join(paths.game_dir(save_id), node.image_path)
                if abs_path.exists():
                    image_bytes = abs_path.read_bytes()
            except ValueError:
                pass

        def _on_result(result: ArtEditResult | None) -> None:
            if result is None:
                return
            self.run_worker(
                self._do_edit_regen(node, result),
                exclusive=True,
                name="play-edit-regen",
            )

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            ArtEditModal(
                original_prompt=node.image_prompt,
                image_bytes=image_bytes,
            ),
            _on_result,
        )

    @work(exit_on_error=False)
    async def _do_edit_regen(self, node: StoryNode, result: ArtEditResult) -> None:
        """Execute the edit-regen after the modal returns a result."""
        if self._pipeline is None:
            return
        if result.mode == ArtEditMode.EDIT:
            new_prompt = f"{node.image_prompt}\n\nEdit instructions: {result.text}"
        else:
            new_prompt = result.text
        self._image.show_generating()
        self._choices.clear()
        cb = PipelineCallbacks(
            on_image_committed=self._on_image_committed,
            on_image_failed=self._on_image_failed,
        )
        await self._pipeline.edit_scene(
            self._save,
            node_id=node.id,
            new_prompt=new_prompt,
            current_image_as_ref=result.use_current_as_ref,
            callbacks=cb,
        )
        self._render_current()
```

5. Add the `StoryNode` import at the action method if not already imported at file top. Check for existing import — it is imported at line 29 as `from storygen.llm.models import ... StoryNode ...`. Verify and add if missing.

- [ ] **Step 2: Run typecheck**

Run: `uv run pyright src/storygen/screens/play.py`
Expected: 0 errors

- [ ] **Step 3: Commit**

```bash
git add src/storygen/screens/play.py
git commit -m "feat: add Shift+I edit-regen binding to PlayScreen"
```

---

### Task 4: Wire "Edit regen" button into `PortraitsScreen`

**Files:**
- Modify: `src/storygen/screens/portraits.py`

- [ ] **Step 1: Add import and button**

In `src/storygen/screens/portraits.py`:

1. Add import near other modal imports:
```python
from storygen.screens._art_edit_modal import ArtEditModal, ArtEditMode
```

2. In `_rebuild`, after the existing "Regenerate" button mount (around line 256), add an "Edit regen" button:
```python
            edit_regen_button = Button("Edit regen", id=f"edit-regen-{char.id}")
            edit_regen_button.disabled = art_disabled or char.portrait_path is None
            meta.mount(edit_regen_button)
```

3. Add a handler in `on_button_pressed` for the new button ID pattern. Find the existing `on_button_pressed` method and add a branch:

```python
        if button_id and button_id.startswith("edit-regen-"):
            char_id = button_id[len("edit-regen-"):]
            char = next((c for c in self._save.characters if c.id == char_id), None)
            if char is not None:
                self._open_edit_regen_modal(char)
            return
```

4. Add the modal-opening method and worker:
```python
    def _open_edit_regen_modal(self, char: Character) -> None:
        """Open the edit-regen modal for a character portrait."""
        save_id = str(self._save.id)
        image_bytes: bytes | None = None
        if char.portrait_path:
            try:
                abs_path = paths.safe_join(paths.game_dir(save_id), char.portrait_path)
                if abs_path.exists():
                    image_bytes = abs_path.read_bytes()
            except ValueError:
                pass

        original = char.portrait_prompt or char.physical_description

        def _on_result(result: ArtEditResult | None) -> None:
            if result is None:
                return
            self.run_worker(
                self._edit_regen_worker(char, result),
                exclusive=True,
                name=f"edit-regen-{char.id}",
            )

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            ArtEditModal(
                original_prompt=original,
                image_bytes=image_bytes,
            ),
            _on_result,
        )

    @work(exit_on_error=False)
    async def _edit_regen_worker(self, char: Character, result: ArtEditResult) -> None:
        """Regenerate a portrait with an edited prompt."""
        if not app_state.art_enabled():
            self.notify(
                "Art generation is disabled in Settings.",
                severity="warning",
                timeout=5,
            )
            return
        if result.mode == ArtEditMode.EDIT:
            original = char.portrait_prompt or char.physical_description
            description = f"{original}\n\nEdit instructions: {result.text}"
        else:
            description = result.text
        try:
            ref_bytes: bytes | None = None
            if result.use_current_as_ref:
                save_id = str(self._save.id)
                if char.portrait_path:
                    try:
                        abs_path = paths.safe_join(
                            paths.game_dir(save_id), char.portrait_path
                        )
                        if abs_path.exists():
                            ref_bytes = abs_path.read_bytes()
                    except ValueError:
                        pass
            png_bytes = await self._image_provider.generate_portrait(
                description,
                transparent=True,
                art_style=self._save.art_style,
                reference_image=ref_bytes,
            )
            save_id = str(self._save.id)
            paths.ensure_game_dirs(save_id)
            version = paths.next_portrait_version(save_id, char.id)
            dest = paths.character_portrait_path(save_id, char.id, version=version)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(png_bytes)
            new_rel = str(dest.relative_to(paths.game_dir(save_id)))
            updated = char.model_copy(
                update={
                    "portrait_path": new_rel,
                    "portrait_prompt": description,
                }
            )
            self._save.characters = [
                updated if c.id == char.id else c for c in self._save.characters
            ]
            self._save.total_image_cost_usd += image_cost(
                self._save.character_image_config.provider,
                model=self._save.character_image_config.model,
                size=PORTRAIT_SIZE,
                quality=PORTRAIT_QUALITY,
            )
            save_game(self._save)
            self._rebuild()
            if app_state.auto_open_art_enabled():
                open_in_system_viewer(dest)
            self.notify(
                f"Edit-regenerated portrait for {char.name} (v{version}).", timeout=5
            )
        except Exception:
            _logger.debug("Portrait edit-regen failed", exc_info=True)
            self.notify("Portrait edit-regen failed.", severity="error", timeout=5)
```

- [ ] **Step 2: Run typecheck**

Run: `uv run pyright src/storygen/screens/portraits.py`
Expected: 0 errors

- [ ] **Step 3: Commit**

```bash
git add src/storygen/screens/portraits.py
git commit -m "feat: add Edit regen button to PortraitsScreen"
```

---

### Task 5: Run full checkall and fix any issues

**Files:**
- Possibly fix issues in any files from Tasks 1-4

- [ ] **Step 1: Run `make checkall`**

Run: `make checkall`

Expected: All fmt + lint + typecheck + test pass.

- [ ] **Step 2: Fix any failures**

Fix format, lint, typecheck, or test issues found. Re-run `make checkall` until clean.

- [ ] **Step 3: Final commit if needed**

```bash
git add -A
git commit -m "fix: resolve checkall issues from advanced art regen"
```
