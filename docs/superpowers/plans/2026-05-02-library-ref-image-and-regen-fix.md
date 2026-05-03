# Library Reference Image + Regenerate Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reference image support to the library browser and fix all regenerate flows to use stored reference images.

**Architecture:** Extend existing patterns — the `ReferenceImageModal`, `save_library_character(reference_bytes=...)`, and the `reference_image` param on `generate_portrait` already exist. We add the missing UI buttons in the library browser and thread ref bytes through all regenerate call sites.

**Tech Stack:** Python 3.13, Textual TUI, pytest, PIL/Pillow

---

## File Structure

| File | Responsibility |
|---|---|
| `src/storygen/screens/portraits.py:465-510` | Fix `_regenerate_worker` to pass ref image |
| `src/storygen/screens/portraits.py:695-740` | Fix `_create_outfit_worker` to pass ref image |
| `src/storygen/screens/library_browser.py` | Add ref buttons, workers; fix regen worker |
| `src/storygen/screens/_create_char_modal.py` | Add optional ref image input + preview |
| `tests/unit/test_portraits_screen.py` | Tests for regen-with-ref and outfit-with-ref |
| `tests/unit/test_library_browser_screen.py` | Tests for ref buttons, regen-with-ref |

---

### Task 1: Fix PortraitsScreen `_regenerate_worker` to use stored reference image

**Files:**
- Modify: `src/storygen/screens/portraits.py:465-510`
- Test: `tests/unit/test_portraits_screen.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_portraits_screen.py` after the existing `test_regenerate_writes_versioned_file_and_updates_save` (around line 186):

```python
@pytest.mark.asyncio
async def test_regenerate_uses_reference_image_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regenerate passes stored reference_image bytes to generate_portrait."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_portrait_on_disk()
    save.character_image_config = ImageProviderConfig(
        provider="gemini", model="gemini-3.1-flash-image-preview"
    )
    char = save.characters[0]
    ref_rel = f"images/characters/{char.id}-ref.png"
    save.characters = [
        char.model_copy(update={"reference_image_path": ref_rel})
    ]
    save_game(save)
    # Write the ref image to disk so the worker can load it.
    ref_abs = paths.game_dir(str(save.id)) / ref_rel
    ref_abs.parent.mkdir(parents=True, exist_ok=True)
    ref_abs.write_bytes(_PNG_BYTES)

    provider = FakeImageProvider()
    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click(f"#regen-{char.id}")
        for _ in range(30):
            await pilot.pause()
            expected = paths.game_dir(str(save.id)) / "images" / "characters" / f"{char.id}-v2.png"
            if expected.exists():
                break

    # generate_portrait was called with reference_image=<bytes>
    assert provider.ref_calls == [_PNG_BYTES]
```

Update `FakeImageProvider` (around line 44) to track ref image calls:

```python
class FakeImageProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.ref_calls: list[bytes | None] = []

    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
        reference_image: bytes | None = None,
    ) -> bytes:
        del on_partial
        self.calls.append(description)
        self.ref_calls.append(reference_image)
        return b"NEWPNG"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_portraits_screen.py::test_regenerate_uses_reference_image_when_present -v`
Expected: FAIL — `assert provider.ref_calls == [_PNG_BYTES]` because the worker doesn't pass `reference_image`.

- [ ] **Step 3: Write minimal implementation**

In `src/storygen/screens/portraits.py`, modify `_regenerate_worker` (around line 477). Replace the `generate_portrait` call block:

Before:
```python
        try:
            png_bytes = await self._image_provider.generate_portrait(
                char.physical_description,
                transparent=True,
                art_style=self._save.art_style,
            )
```

After:
```python
        try:
            ref_bytes: bytes | None = None
            if char.reference_image_path:
                ref_abs = paths.safe_join(
                    paths.game_dir(save_id), char.reference_image_path
                )
                if ref_abs.exists():
                    ref_bytes = ref_abs.read_bytes()
            png_bytes = await self._image_provider.generate_portrait(
                char.physical_description,
                transparent=True,
                art_style=self._save.art_style,
                reference_image=ref_bytes,
            )
```

Note: `save_id` is already computed inside the `try` block on the line immediately after the `generate_portrait` call — move it before the ref-image load:

The full restructured block should be:
```python
        original_label = button.label
        button.disabled = True
        button.label = "Working…"
        try:
            save_id = str(self._save.id)
            ref_bytes: bytes | None = None
            if char.reference_image_path:
                ref_abs = paths.safe_join(
                    paths.game_dir(save_id), char.reference_image_path
                )
                if ref_abs.exists():
                    ref_bytes = ref_abs.read_bytes()
            png_bytes = await self._image_provider.generate_portrait(
                char.physical_description,
                transparent=True,
                art_style=self._save.art_style,
                reference_image=ref_bytes,
            )
            paths.ensure_game_dirs(save_id)
            version = paths.next_portrait_version(save_id, char.id)
            dest = paths.character_portrait_path(save_id, char.id, version=version)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(png_bytes)
            new_rel = str(dest.relative_to(paths.game_dir(save_id)))
            updated = char.model_copy(update={"portrait_path": new_rel})
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
            self.notify(f"Regenerated portrait for {char.name} (v{version}).", timeout=5)
        except Exception:
            _logger.debug("Portrait regeneration failed", exc_info=True)
            self.notify("Portrait regeneration failed.", severity="error", timeout=5)
            if button.is_attached:
                button.disabled = False
                button.label = cast(str, original_label)
```

- [ ] **Step 4: Run all portraits tests to verify nothing broke**

Run: `uv run pytest tests/unit/test_portraits_screen.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/storygen/screens/portraits.py tests/unit/test_portraits_screen.py
git commit -m "feat: pass stored reference image in portrait regeneration"
```

---

### Task 2: Fix PortraitsScreen `_create_outfit_worker` to use stored reference image

**Files:**
- Modify: `src/storygen/screens/portraits.py:695-740`
- Test: `tests/unit/test_portraits_screen.py`

- [ ] **Step 1: Write the failing test**

Add after the outfit tests in `tests/unit/test_portraits_screen.py`:

```python
@pytest.mark.asyncio
async def test_outfit_uses_reference_image_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Creating an outfit passes stored reference_image to generate_portrait."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_portrait_on_disk()
    save.character_image_config = ImageProviderConfig(
        provider="gemini", model="gemini-3.1-flash-image-preview"
    )
    char = save.characters[0]
    ref_rel = f"images/characters/{char.id}-ref.png"
    save.characters = [
        char.model_copy(update={"reference_image_path": ref_rel})
    ]
    save_game(save)
    ref_abs = paths.game_dir(str(save.id)) / ref_rel
    ref_abs.parent.mkdir(parents=True, exist_ok=True)
    ref_abs.write_bytes(_PNG_BYTES)

    provider = FakeImageProvider()
    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(PortraitsScreen, app.screen)
        screen._create_outfit_worker(  # pyright: ignore[reportPrivateUsage]
            char,
            OutfitCreateRequest(name="Armor", description="shiny plate armor"),
        )
        for _ in range(40):
            await pilot.pause()
            reloaded = load_game(str(save.id))
            if any(o.name == "Armor" for o in reloaded.characters[0].outfits):
                break

    assert provider.ref_calls == [_PNG_BYTES]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_portraits_screen.py::test_outfit_uses_reference_image_when_present -v`
Expected: FAIL — `ref_calls` is empty or `None` because worker doesn't pass `reference_image`.

- [ ] **Step 3: Write minimal implementation**

In `src/storygen/screens/portraits.py`, modify `_create_outfit_worker` (around line 703). Replace the `generate_portrait` call:

Before:
```python
            png_bytes = await self._image_provider.generate_portrait(
                combined,
                transparent=True,
                art_style=self._save.art_style,
            )
```

After:
```python
            save_id = str(self._save.id)
            ref_bytes: bytes | None = None
            if char.reference_image_path:
                ref_abs = paths.safe_join(
                    paths.game_dir(save_id), char.reference_image_path
                )
                if ref_abs.exists():
                    ref_bytes = ref_abs.read_bytes()
            png_bytes = await self._image_provider.generate_portrait(
                combined,
                transparent=True,
                art_style=self._save.art_style,
                reference_image=ref_bytes,
            )
```

Remove the duplicate `save_id = str(self._save.id)` line that was previously 2 lines below (now moved up).

- [ ] **Step 4: Run all portraits tests**

Run: `uv run pytest tests/unit/test_portraits_screen.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/storygen/screens/portraits.py tests/unit/test_portraits_screen.py
git commit -m "feat: pass stored reference image in outfit generation"
```

---

### Task 3: Fix CharacterCatalogScreen `_regenerate_worker` to use stored reference image

**Files:**
- Modify: `src/storygen/screens/library_browser.py:576-619`
- Test: `tests/unit/test_library_browser_screen.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_library_browser_screen.py`. First, add a `FakeImageProvider` class and a `_BrowseHarnessWithProvider` after the existing `_BrowseHarness` (around line 394):

```python
from collections.abc import Awaitable, Callable
from storygen.storage.library import library_reference_path


class _FakeImageProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.ref_calls: list[bytes | None] = []

    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
        reference_image: bytes | None = None,
    ) -> bytes:
        del on_partial
        self.calls.append(description)
        self.ref_calls.append(reference_image)
        return b"NEWPNG"


class _BrowseHarnessWithProvider(App[None]):
    """Pushes CharacterCatalogScreen in browse mode with a fake image provider."""

    def __init__(self, provider: _FakeImageProvider) -> None:
        super().__init__()
        self._provider = provider

    def on_mount(self) -> None:
        self.push_screen(CharacterCatalogScreen(browse=True, image_provider=self._provider))

    def compose(self) -> ComposeResult:
        yield from []
```

Then add the test:

```python
@pytest.mark.asyncio
async def test_regenerate_uses_reference_image_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regenerate in library browser passes stored reference bytes."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_lib_char()
    save_library_character(char, _PNG_BYTES, reference_bytes=_PNG_BYTES)
    assert char.reference_image_path == "reference.png"

    provider = _FakeImageProvider()
    app = _BrowseHarnessWithProvider(provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click(f"#regen-{char.id}")
        for _ in range(30):
            await pilot.pause()
            on_disk = library_reference_path(char.id)
            if on_disk.exists() and on_disk.read_bytes() == b"NEWPNG":
                break

    assert provider.ref_calls == [_PNG_BYTES]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_library_browser_screen.py::test_regenerate_uses_reference_image_when_present -v`
Expected: FAIL — `ref_calls` is `[None]` because regen doesn't pass `reference_image`.

- [ ] **Step 3: Write minimal implementation**

In `src/storygen/screens/library_browser.py`, modify `_regenerate_worker`. Before the `generate_portrait` call (around line 601), add ref-image loading. Replace:

```python
        prompt = entry.portrait_prompt or entry.physical_description
        try:
            portrait_bytes = await self._image_provider.generate_portrait(
                prompt,
                transparent=True,
                art_style=app_state.DEFAULT_ART_STYLE,
            )
```

With:

```python
        prompt = entry.portrait_prompt or entry.physical_description
        ref_bytes: bytes | None = None
        if entry.reference_image_path:
            ref_path = library_reference_path(entry.id)
            if ref_path.exists():
                ref_bytes = ref_path.read_bytes()
        try:
            portrait_bytes = await self._image_provider.generate_portrait(
                prompt,
                transparent=True,
                art_style=app_state.DEFAULT_ART_STYLE,
                reference_image=ref_bytes,
            )
```

Also add `library_reference_path` to the import block at the top of the file (around line 44):

```python
from storygen.storage.library import (
    PLACEHOLDER_PNG,
    LibraryCharacter,
    LibrarySource,
    delete_library_character,
    library_portrait_path,
    library_reference_path,
    list_library_characters,
    load_library_character,
    save_library_character,
)
```

- [ ] **Step 4: Run all library browser tests**

Run: `uv run pytest tests/unit/test_library_browser_screen.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/storygen/screens/library_browser.py tests/unit/test_library_browser_screen.py
git commit -m "feat: pass stored reference image in library browser regeneration"
```

---

### Task 4: Add reference image buttons + flow to CharacterCatalogScreen

**Files:**
- Modify: `src/storygen/screens/library_browser.py`
- Test: `tests/unit/test_library_browser_screen.py`

- [ ] **Step 1: Write failing tests for button rendering**

Add to `tests/unit/test_library_browser_screen.py`:

```python
@pytest.mark.asyncio
async def test_ref_image_button_renders_without_ref(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Character without ref shows 'Ref Image' button."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_lib_char()
    save_library_character(char, _PNG_BYTES)

    app = _BrowseHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        ref_btn = app.screen.query_one(f"#ref-{char.id}", Button)
        assert "Ref Image" in str(ref_btn.label)
        # No rm-ref button when no ref is set.
        rm_btns = app.screen.query(f"#rm-ref-{char.id}")
        assert len(rm_btns) == 0


@pytest.mark.asyncio
async def test_ref_image_button_changes_label_with_ref(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Character with ref shows 'Change Ref' and 'Rm Ref' buttons."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_lib_char()
    save_library_character(char, _PNG_BYTES, reference_bytes=_PNG_BYTES)

    app = _BrowseHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        ref_btn = app.screen.query_one(f"#ref-{char.id}", Button)
        assert "Change Ref" in str(ref_btn.label)
        rm_btn = app.screen.query_one(f"#rm-ref-{char.id}", Button)
        assert rm_btn is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_library_browser_screen.py::test_ref_image_button_renders_without_ref tests/unit/test_library_browser_screen.py::test_ref_image_button_changes_label_with_ref -v`
Expected: FAIL — buttons don't exist yet.

- [ ] **Step 3: Add ref image buttons to `_mount_row`**

In `src/storygen/screens/library_browser.py`, in `_mount_row` (around line 521), after mounting the "Regenerate" button and before the `action_buttons` horizontal, add ref buttons:

```python
        ref_label = "Change Ref" if entry.reference_image_path else "Ref Image"
        ref_btn = Button(ref_label, id=f"ref-{entry.id}")
        ref_btn.disabled = self._image_provider is None
        photo_buttons.mount(ref_btn)
        if entry.reference_image_path is not None:
            photo_buttons.mount(Button("Rm Ref", id=f"rm-ref-{entry.id}"))
```

- [ ] **Step 4: Run button rendering tests**

Run: `uv run pytest tests/unit/test_library_browser_screen.py::test_ref_image_button_renders_without_ref tests/unit/test_library_browser_screen.py::test_ref_image_button_changes_label_with_ref -v`
Expected: PASS

- [ ] **Step 5: Add button dispatch to `on_button_pressed`**

In `on_button_pressed` (around line 556), add handlers after the `"regen-"` case:

```python
        if button_id.startswith("ref-"):
            library_id = button_id[len("ref-"):]
            self._open_ref_image_modal(library_id)
            return
        if button_id.startswith("rm-ref-"):
            library_id = button_id[len("rm-ref-"):]
            self._remove_reference_image(library_id)
            return
```

- [ ] **Step 6: Add `_open_ref_image_modal`, `_apply_ref_image_worker`, and `_remove_reference_image`**

Add these methods after `_regenerate_worker`. Also add the necessary imports at the top of the file.

Import `ReferenceImageModal` and `ReferenceImageResult` — add to the import block (after the existing `_create_char_modal` import on line 35):

```python
from storygen.screens._ref_image_modals import ReferenceImageModal, ReferenceImageResult
```

Add the three methods after `_regenerate_worker`:

```python
    def _open_ref_image_modal(self, library_id: str) -> None:
        """Open the reference image picker for a library character."""
        entry = self._entries.get(library_id)
        if entry is None:
            return
        entry_name = entry.name

        def _after(result: object) -> None:
            if not isinstance(result, ReferenceImageResult):
                return
            self._apply_ref_image_worker(result, library_id)

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            ReferenceImageModal(entry_name),
            _after,
        )

    @work(exit_on_error=False)
    async def _apply_ref_image_worker(
        self, result: ReferenceImageResult, library_id: str
    ) -> None:
        """Process a reference image for a library character."""
        entry = self._entries.get(library_id)
        if entry is None:
            return
        try:
            with Image.open(result.source_path) as im:
                im = im.convert("RGBA")
                buf = io.BytesIO()
                im.save(buf, format="PNG")
                png_bytes = buf.getvalue()
        except Exception:
            _logger.debug("Failed to load reference image", exc_info=True)
            self.notify("Failed to load image.", severity="error", timeout=5)
            return

        if result.mode == "use_as_is":
            portrait_bytes = png_bytes
            entry = entry.model_copy(
                update={
                    "portrait_prompt": "(from reference image)",
                    "reference_image_path": "reference.png",
                }
            )
        else:
            if self._image_provider is None:
                self.notify("No image provider configured.", severity="error", timeout=5)
                return
            try:
                portrait_bytes = await self._image_provider.generate_portrait(
                    entry.physical_description,
                    transparent=True,
                    art_style=app_state.DEFAULT_ART_STYLE,
                    reference_image=png_bytes,
                )
            except Exception:
                _logger.debug("Style-transfer failed", exc_info=True)
                self.notify("Style-transfer failed.", severity="error", timeout=5)
                return
            entry = entry.model_copy(
                update={
                    "portrait_prompt": entry.physical_description,
                    "reference_image_path": "reference.png",
                }
            )

        save_library_character(entry, portrait_bytes, reference_bytes=png_bytes)
        self._rebuild()
        if app_state.auto_open_art_enabled():
            open_in_system_viewer(library_portrait_path(entry.id))
        self.notify(f"Reference image set for {entry.name}.", timeout=5)

    def _remove_reference_image(self, library_id: str) -> None:
        """Clear the reference image from a library character."""
        entry = self._entries.get(library_id)
        if entry is None:
            return
        ref_path = library_reference_path(entry.id)
        if ref_path.exists():
            ref_path.unlink()
        entry = entry.model_copy(update={"reference_image_path": None})
        save_library_character(entry, _load_portrait_bytes(entry.id))
        self._rebuild()
        self.notify(f"Reference image removed from {entry.name}.", timeout=5)
```

Add the helper `_load_portrait_bytes` and the new imports. Add `io` and `Image` imports at the top:

```python
import io
```

```python
from PIL import Image
```

Add helper at module level (before the class):

```python
def _load_portrait_bytes(library_id: str) -> bytes:
    """Read the portrait PNG for a library character (used by rm-ref to re-save without ref)."""
    path = library_portrait_path(library_id)
    if path.exists():
        return path.read_bytes()
    return PLACEHOLDER_PNG
```

- [ ] **Step 7: Write tests for ref image flow and removal**

Add to `tests/unit/test_library_browser_screen.py`:

```python
@pytest.mark.asyncio
async def test_remove_ref_clears_reference_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Rm Ref button clears reference_image_path and deletes reference.png."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_lib_char()
    save_library_character(char, _PNG_BYTES, reference_bytes=_PNG_BYTES)

    app = _BrowseHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click(f"#rm-ref-{char.id}")
        for _ in range(10):
            await pilot.pause()

    from storygen.storage.library import load_library_character
    reloaded = load_library_character(char.id)
    assert reloaded.reference_image_path is None
    assert not library_reference_path(char.id).exists()
```

- [ ] **Step 8: Run all library browser tests**

Run: `uv run pytest tests/unit/test_library_browser_screen.py -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add src/storygen/screens/library_browser.py tests/unit/test_library_browser_screen.py
git commit -m "feat: add reference image support to library browser"
```

---

### Task 5: Add optional reference image to CreateCharacterModal

**Files:**
- Modify: `src/storygen/screens/_create_char_modal.py`
- Modify: `src/storygen/screens/library_browser.py`
- Test: `tests/unit/test_library_browser_screen.py`

- [ ] **Step 1: Update `CreateCharRequest` model**

In `src/storygen/screens/_create_char_modal.py`, add `reference_image` field to `CreateCharRequest`:

```python
class CreateCharRequest(BaseModel):
    """Result of CreateCharacterModal — name + concept to generate."""

    name: str
    concept: str
    reference_image: bytes | None = None
```

- [ ] **Step 2: Add reference image UI to `CreateCharacterModal`**

Add imports at the top:

```python
import io

from PIL import Image
from rich_pixels import Pixels
```

Add `__init__` state for ref image:

```python
    def __init__(self) -> None:
        super().__init__()
        self._name_input = Input(
            placeholder="(optional — leave blank to let the LLM name the character)",
            id="create-char-name",
        )
        self._concept_area = TextArea(
            text="",
            id="create-char-concept",
        )
        self._ref_path_input = Input(
            placeholder="(optional) /path/to/reference.png",
            id="create-char-ref-path",
        )
        self._ref_browse_btn = Button("Browse", id="create-char-ref-browse")
        self._loaded_ref_bytes: bytes | None = None
        self._generate_btn = Button(
            "Create",
            id="create-char-generate",
            variant="primary",
        )
        self._cancel_btn = Button("Cancel", id="create-char-cancel")
```

Add CSS for the ref section in `DEFAULT_CSS`:

```css
    CreateCharacterModal #create-char-ref-label {
        margin-top: 1;
    }
    CreateCharacterModal #create-char-ref-preview {
        margin-top: 0;
        height: auto;
    }
```

Update `compose` to include the ref input:

```python
    def compose(self) -> ComposeResult:
        with Vertical(id="create-char-box"):
            yield Static("Create New Character", id="create-char-title")
            yield Static("Name", id="create-char-name-label")
            yield self._name_input
            yield Static(
                "Describe the character (personality, role, appearance — "
                "the LLM will fill in the rest)",
                id="create-char-concept-label",
            )
            yield self._concept_area
            yield Static("Reference image (optional)", id="create-char-ref-label")
            with Horizontal():
                yield self._ref_path_input
                yield self._ref_browse_btn
            yield Static(id="create-char-ref-preview")
            with Horizontal(id="create-char-buttons"):
                yield self._cancel_btn
                yield self._generate_btn
```

Update `_refresh_generate_state` to also handle ref path input changes — it already fires on `Input.Changed` and `TextArea.Changed`. Add ref path preview logic by updating `on_input_changed`:

```python
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "create-char-ref-path":
            self._try_ref_preview()
        else:
            self._refresh_generate_state()
```

Add the browse and preview helpers:

```python
    def _try_ref_preview(self) -> None:
        path_str = self._ref_path_input.value.strip()
        preview = self.query_one("#create-char-ref-preview", Static)
        if not path_str:
            self._loaded_ref_bytes = None
            preview.update("")
            return
        path = Path(path_str)
        _ACCEPTED = {".png", ".jpg", ".jpeg", ".webp"}
        if not path.is_file() or path.suffix.lower() not in _ACCEPTED:
            self._loaded_ref_bytes = None
            preview.update("(invalid path)")
            return
        try:
            with Image.open(path) as im:
                im = im.convert("RGBA")
                buf = io.BytesIO()
                im.save(buf, format="PNG")
                self._loaded_ref_bytes = buf.getvalue()
                thumb = im.copy()
                thumb.thumbnail((96, 48))
                preview.update(Pixels.from_image(thumb))
        except Exception:
            self._loaded_ref_bytes = None
            preview.update("(failed to load)")

    def _browse_ref(self) -> None:
        from storygen.screens._ref_image_modals import _try_native_file_picker

        selected = _try_native_file_picker()
        if selected:
            self._ref_path_input.value = selected
            self._try_ref_preview()
```

Update `on_button_pressed` to handle the browse button and pass ref bytes:

```python
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-char-ref-browse":
            self._browse_ref()
            return
        if event.button.id == "create-char-generate":
            concept = self._concept_area.text.strip()
            if not concept:
                return
            name = self._name_input.value.strip()
            self.dismiss(CreateCharRequest(
                name=name, concept=concept, reference_image=self._loaded_ref_bytes,
            ))
            return
        if event.button.id == "create-char-cancel":
            self.dismiss(None)
```

- [ ] **Step 3: Wire `reference_image` through `_create_character_worker` in library_browser.py**

In `src/storygen/screens/library_browser.py`, modify `_create_character_worker`. When calling `generate_portrait` (around line 322 in the current file), pass the ref image:

Before:
```python
            portrait_bytes = await self._image_provider.generate_portrait(
                char.physical_description,
                transparent=True,
                art_style=app_state.DEFAULT_ART_STYLE,
            )
```

After:
```python
            portrait_bytes = await self._image_provider.generate_portrait(
                char.physical_description,
                transparent=True,
                art_style=app_state.DEFAULT_ART_STYLE,
                reference_image=request.reference_image,
            )
```

Also update `save_library_character` to persist the ref image (around line 348):

Before:
```python
        save_library_character(lib_char, portrait_bytes)
```

After:
```python
        save_library_character(lib_char, portrait_bytes, reference_bytes=request.reference_image)
```

- [ ] **Step 4: Write test for character creation with reference image**

Add to `tests/unit/test_library_browser_screen.py`:

```python
@pytest.mark.asyncio
async def test_create_character_with_ref_image_passes_to_portrait_gen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Creating a character with a ref image passes bytes to generate_portrait."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    provider = _FakeImageProvider()

    class _FakeAgent:
        async def run(self, prompt: str) -> object:
            from storygen.llm.models import Character as Char
            return type("_R", (), {"output": [Char(
                id="c1", name="Test", backstory="b", personality="p",
                physical_description="desc", introduced_at_node_id="root",
            )]})()

    app = _BrowseHarnessWithProviderAndAgent(provider, _FakeAgent)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, CharacterCatalogScreen)
        ref_bytes = b"\x89PNG\r\n\x1a\n"  # minimal PNG header
        request = CreateCharRequest(
            name="Test", concept="a test character", reference_image=ref_bytes,
        )
        screen._create_character_worker(request)  # pyright: ignore[reportPrivateUsage]
        for _ in range(40):
            await pilot.pause()
            if provider.ref_calls:
                break

    assert provider.ref_calls == [ref_bytes]
```

This needs the `_BrowseHarnessWithProviderAndAgent` harness:

```python
class _BrowseHarnessWithProviderAndAgent(App[None]):
    """Browse mode with both a fake image provider and a fake character agent."""

    def __init__(
        self,
        provider: _FakeImageProvider,
        agent_cls: type,
    ) -> None:
        super().__init__()
        self._provider = provider
        self._agent_cls = agent_cls

    def on_mount(self) -> None:
        self.push_screen(CharacterCatalogScreen(
            browse=True,
            image_provider=self._provider,
            character_agent_factory=self._agent_cls,
        ))

    def compose(self) -> ComposeResult:
        yield from []
```

Also add the import for `CreateCharRequest`:

```python
from storygen.screens._create_char_modal import CreateCharRequest
```

- [ ] **Step 5: Run all library browser tests**

Run: `uv run pytest tests/unit/test_library_browser_screen.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full test suite**

Run: `make checkall`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/storygen/screens/_create_char_modal.py src/storygen/screens/library_browser.py tests/unit/test_library_browser_screen.py
git commit -m "feat: add optional reference image to character creation modal"
```
