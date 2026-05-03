"""Unit tests for ArtEditModal."""

from __future__ import annotations

import pytest
from textual.app import App
from textual.screen import Screen
from textual.widgets import Button, Checkbox, RadioButton, RadioSet, TextArea

from storygen.screens._art_edit_modal import ArtEditModal, ArtEditMode, ArtEditResult

_UNSET: ArtEditResult | None = None


class _Harness(App[None]):
    """Harness that pushes an ArtEditModal on mount and captures its result."""

    def __init__(self, modal: ArtEditModal) -> None:
        super().__init__()
        self._modal = modal
        self.result: ArtEditResult | None = _UNSET

    def on_mount(self) -> None:
        def _cb(r: ArtEditResult | None) -> None:
            self.result = r
            self.exit()

        self.push_screen(self._modal, _cb)


def _select_radio(radios: RadioSet, index: int) -> None:
    """Programmatically select a radio button by index and fire Changed."""
    rb_id = "art-mode-full" if index == 1 else "art-mode-edit"
    rb = radios.query_one(f"#{rb_id}", RadioButton)
    rb.value = True


def _click_button(screen: Screen[object], button: Button) -> None:
    """Synthesize a button press (avoids OutOfBounds for off-screen widgets)."""
    assert isinstance(screen, ArtEditModal)
    screen.on_button_pressed(Button.Pressed(button))


# --- Pydantic model tests ---


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


# --- Async harness tests ---


@pytest.mark.asyncio
async def test_generate_disabled_on_mount() -> None:
    """Generate button is disabled when the TextArea is empty on mount."""
    modal = ArtEditModal(original_prompt="test prompt", image_bytes=None)
    app = _Harness(modal)
    async with app.run_test() as pilot:
        await pilot.pause()
        btn = app.screen.query_one("#art-edit-generate", Button)
        assert btn.disabled is True


@pytest.mark.asyncio
async def test_generate_enables_when_text_entered() -> None:
    """Generate button becomes enabled once text is typed into the TextArea."""
    modal = ArtEditModal(original_prompt="test prompt", image_bytes=None)
    app = _Harness(modal)
    async with app.run_test() as pilot:
        await pilot.pause()
        ta = app.screen.query_one("#art-edit-input", TextArea)
        ta.load_text("make it darker")
        await pilot.pause()
        btn = app.screen.query_one("#art-edit-generate", Button)
        assert btn.disabled is False


@pytest.mark.asyncio
async def test_cancel_dismisses_with_none() -> None:
    """Clicking Cancel dismisses the modal with None."""
    modal = ArtEditModal(original_prompt="test prompt", image_bytes=None)
    app = _Harness(modal)
    async with app.run_test() as pilot:
        await pilot.pause()
        cancel_btn = app.screen.query_one("#art-edit-cancel", Button)
        _click_button(app.screen, cancel_btn)
        await pilot.pause()
    assert app.result is None


@pytest.mark.asyncio
async def test_escape_dismisses_with_none() -> None:
    """Pressing Escape dismisses the modal with None."""
    modal = ArtEditModal(original_prompt="test prompt", image_bytes=None)
    app = _Harness(modal)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None


@pytest.mark.asyncio
async def test_full_mode_prefills_textarea() -> None:
    """Switching to FULL mode pre-fills the TextArea with the original prompt."""
    modal = ArtEditModal(original_prompt="a dark forest", image_bytes=None)
    app = _Harness(modal)
    async with app.run_test() as pilot:
        await pilot.pause()
        radios = app.screen.query_one("#art-edit-radios", RadioSet)
        _select_radio(radios, 1)  # index 1 = "Full prompt"
        await pilot.pause()
        ta = app.screen.query_one("#art-edit-input", TextArea)
        assert ta.text == "a dark forest"


@pytest.mark.asyncio
async def test_edit_mode_clears_textarea() -> None:
    """Switching back to EDIT mode clears the TextArea."""
    modal = ArtEditModal(original_prompt="a dark forest", image_bytes=None)
    app = _Harness(modal)
    async with app.run_test() as pilot:
        await pilot.pause()
        radios = app.screen.query_one("#art-edit-radios", RadioSet)
        # Switch to FULL first
        _select_radio(radios, 1)
        await pilot.pause()
        ta = app.screen.query_one("#art-edit-input", TextArea)
        assert ta.text == "a dark forest"
        # Switch back to EDIT
        _select_radio(radios, 0)
        await pilot.pause()
        assert ta.text == ""


@pytest.mark.asyncio
async def test_generate_dismisses_with_result() -> None:
    """Generate dismisses with the correct ArtEditResult."""
    modal = ArtEditModal(original_prompt="original scene", image_bytes=None)
    app = _Harness(modal)
    async with app.run_test() as pilot:
        await pilot.pause()
        ta = app.screen.query_one("#art-edit-input", TextArea)
        ta.load_text("add a dragon")
        await pilot.pause()
        gen_btn = app.screen.query_one("#art-edit-generate", Button)
        _click_button(app.screen, gen_btn)
        await pilot.pause()
    assert isinstance(app.result, ArtEditResult)
    assert app.result.mode == ArtEditMode.EDIT
    assert app.result.text == "add a dragon"
    assert app.result.use_current_as_ref is True


@pytest.mark.asyncio
async def test_generate_full_mode_with_ref_unchecked() -> None:
    """Generate in FULL mode with ref unchecked returns correct result."""
    modal = ArtEditModal(original_prompt="a castle on a hill", image_bytes=None)
    app = _Harness(modal)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Switch to FULL mode
        radios = app.screen.query_one("#art-edit-radios", RadioSet)
        _select_radio(radios, 1)
        await pilot.pause()
        # Uncheck ref checkbox
        cb = app.screen.query_one("#art-edit-ref-checkbox", Checkbox)
        cb.toggle()
        await pilot.pause()
        # Generate
        gen_btn = app.screen.query_one("#art-edit-generate", Button)
        _click_button(app.screen, gen_btn)
        await pilot.pause()
    assert isinstance(app.result, ArtEditResult)
    assert app.result.mode == ArtEditMode.FULL
    assert app.result.text == "a castle on a hill"
    assert app.result.use_current_as_ref is False
