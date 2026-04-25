"""Modal for editing a library character's fields from the catalog browser.

Presents name / personality / physical_description / backstory for in-place
editing. Returns a :class:`LibraryEditResult` on Save; the caller persists
the updated ``LibraryCharacter`` to disk. If ``physical_description`` changed,
``portrait_prompt`` is synced so a future regenerate uses the new description.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static, TextArea

from storygen.storage.library import LibraryCharacter


class LibraryEditResult(BaseModel):
    """Return value from :class:`LibraryEditModal` on Save."""

    name: str
    personality: str
    physical_description: str
    backstory: str


class LibraryEditModal(ModalScreen[LibraryEditResult | None]):
    """Edit a library character's name + personality + physical_description + backstory.

    Changing physical_description drifts the character from their existing
    portrait — a warning banner appears in that case. After save,
    ``portrait_prompt`` auto-syncs so a future regenerate uses the updated
    description.
    """

    DEFAULT_CSS = """
    LibraryEditModal {
        align: center middle;
    }
    LibraryEditModal #lib-edit-box {
        width: 100;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    LibraryEditModal #lib-edit-title {
        text-style: bold;
        margin-bottom: 1;
    }
    LibraryEditModal .lib-edit-label {
        margin-top: 1;
        color: $text-muted;
    }
    LibraryEditModal #lib-edit-personality {
        height: 6;
    }
    LibraryEditModal #lib-edit-physical {
        height: 6;
    }
    LibraryEditModal #lib-edit-backstory {
        height: 12;
    }
    LibraryEditModal #lib-edit-warning {
        margin-top: 1;
        padding: 0 1;
        color: $warning;
        text-style: italic;
        display: none;
    }
    LibraryEditModal #lib-edit-warning.-visible {
        display: block;
    }
    LibraryEditModal #lib-edit-buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    LibraryEditModal #lib-edit-save {
        margin-left: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, char: LibraryCharacter) -> None:
        super().__init__()
        self._char = char
        self._initial_physical = char.physical_description
        self._name_input = Input(value=char.name, id="lib-edit-name")
        self._personality_area = TextArea(char.personality, id="lib-edit-personality")
        self._physical_area = TextArea(char.physical_description, id="lib-edit-physical")
        self._backstory_area = TextArea(char.backstory, id="lib-edit-backstory")
        self._warning = Static(
            "[!] Physical description changed. Portrait no longer matches.",
            id="lib-edit-warning",
            markup=False,
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="lib-edit-box"):
            yield Static(f"Edit {self._char.name}", id="lib-edit-title")
            yield Static("Name", classes="lib-edit-label")
            yield self._name_input
            yield Static("Personality", classes="lib-edit-label")
            yield self._personality_area
            yield Static("Physical description", classes="lib-edit-label")
            yield self._physical_area
            yield Static("Backstory", classes="lib-edit-label")
            yield self._backstory_area
            yield self._warning
            with Horizontal(id="lib-edit-buttons"):
                yield Button("Cancel", id="lib-edit-cancel")
                yield Button("Save", id="lib-edit-save", variant="primary")

    @on(TextArea.Changed, "#lib-edit-physical")
    def _on_physical_changed(self, _event: TextArea.Changed) -> None:
        if self._physical_area.text != self._initial_physical:
            self._warning.add_class("-visible")
        else:
            self._warning.remove_class("-visible")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "lib-edit-save":
            self._attempt_save()
            return
        if event.button.id == "lib-edit-cancel":
            self.dismiss(None)

    def _attempt_save(self) -> None:
        name = self._name_input.value.strip()
        if not name:
            self.notify("Name cannot be empty.", severity="error")
            return
        result = LibraryEditResult(
            name=name,
            personality=self._personality_area.text,
            physical_description=self._physical_area.text,
            backstory=self._backstory_area.text,
        )
        self.dismiss(result)

    def action_cancel(self) -> None:
        self.dismiss(None)
