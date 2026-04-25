"""Tests for LibraryEditModal."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button

from storygen.screens._library_edit_modal import LibraryEditModal, LibraryEditResult
from storygen.storage.library import LibraryCharacter


def _make_lib_char(**kwargs: object) -> LibraryCharacter:
    defaults: dict[str, object] = {
        "id": uuid4().hex,
        "name": "Aria",
        "personality": "Brave and curious.",
        "physical_description": "Tall with silver hair.",
        "backstory": "A wandering mage from the eastern hills.",
        "portrait_prompt": "Tall silver-haired mage, neutral pose.",
        "exported_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    return LibraryCharacter(**defaults)  # type: ignore[arg-type]


class _ModalHarness(App[None]):
    def __init__(self, char: LibraryCharacter) -> None:
        super().__init__()
        self._char = char
        self.result: object = "<unset>"

    def on_mount(self) -> None:
        def _cap(r: object) -> None:
            self.result = r

        self.push_screen(LibraryEditModal(self._char), _cap)

    def compose(self) -> ComposeResult:
        yield from []


@pytest.mark.asyncio
async def test_save_with_all_fields_valid_dismisses_with_result() -> None:
    """Pressing Save with a non-empty name dismisses with a LibraryEditResult."""
    char = _make_lib_char()
    app = _ModalHarness(char)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen.query_one("#lib-edit-save", Button).press()
        await pilot.pause()
    assert isinstance(app.result, LibraryEditResult)
    assert app.result.name == "Aria"
    assert app.result.personality == "Brave and curious."
    assert app.result.physical_description == "Tall with silver hair."
    assert app.result.backstory == "A wandering mage from the eastern hills."


@pytest.mark.asyncio
async def test_save_with_empty_name_notifies_and_does_not_dismiss() -> None:
    """Pressing Save with an empty name shows an error and does NOT dismiss."""
    char = _make_lib_char()
    app = _ModalHarness(char)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Clear the name field
        from textual.widgets import Input

        name_input = app.screen.query_one("#lib-edit-name", Input)
        name_input.value = ""
        await pilot.pause()
        app.screen.query_one("#lib-edit-save", Button).press()
        await pilot.pause()
    # Modal should NOT have dismissed — result still at sentinel
    assert app.result == "<unset>"


@pytest.mark.asyncio
async def test_physical_description_change_shows_warning() -> None:
    """Editing physical_description reveals the portrait-drift warning banner."""
    char = _make_lib_char(physical_description="Original description.")
    app = _ModalHarness(char)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Warning banner should start hidden
        warning = app.screen.query_one("#lib-edit-warning")
        assert "-visible" not in warning.classes
        # Change the physical description text area
        from textual.widgets import TextArea

        physical_area = app.screen.query_one("#lib-edit-physical", TextArea)
        physical_area.text = "A completely different appearance."
        await pilot.pause()
        # Warning should now be visible
        assert "-visible" in warning.classes


@pytest.mark.asyncio
async def test_cancel_button_dismisses_with_none() -> None:
    """Pressing Cancel dismisses with None."""
    char = _make_lib_char()
    app = _ModalHarness(char)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen.query_one("#lib-edit-cancel", Button).press()
        await pilot.pause()
    assert app.result is None


@pytest.mark.asyncio
async def test_escape_key_dismisses_with_none() -> None:
    """Pressing Escape dismisses with None."""
    char = _make_lib_char()
    app = _ModalHarness(char)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None


def test_library_edit_result_model() -> None:
    """LibraryEditResult is a plain Pydantic model with the expected fields."""
    result = LibraryEditResult(
        name="Hero",
        personality="Bold.",
        physical_description="Tall.",
        backstory="A great hero.",
    )
    assert result.name == "Hero"
    assert result.personality == "Bold."
    assert result.physical_description == "Tall."
    assert result.backstory == "A great hero."
