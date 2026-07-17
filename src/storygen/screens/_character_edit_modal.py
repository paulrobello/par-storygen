"""Modal used by :class:`PortraitsScreen` to edit a character's bio fields.

Presents the four user-visible bio fields — ``name`` / ``personality`` /
``physical_description`` / ``backstory`` — for in-place editing. The modal
itself is pure UI: it returns a :class:`CharacterEditResult` on Save and the
caller (PortraitsScreen) is responsible for applying the diff against the
live :class:`~storygen.core.models.Character`, persisting the save, and
deciding whether to sync ``portrait_prompt``.

Design notes:

- Editing ``physical_description`` drifts the character away from their
  already-rendered portrait. The modal shows a dismissable warning banner
  (``[!] Physical description changed ...``) in that case but still allows
  the change — the caller syncs ``portrait_prompt`` so a subsequent
  Regenerate picks up the new description.
- Outfits have their own independent ``portrait_prompt``/``description``
  fields and are NOT retroactively updated by a bio edit; if the user wants
  outfit portraits to reflect a new physical_description they must
  regenerate each outfit individually.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static, TextArea

from storygen.core.models import Character


class CharacterEditResult(BaseModel):
    """Return value from :class:`CharacterEditModal` on Save."""

    name: str
    personality: str
    physical_description: str
    backstory: str


class CharacterEditModal(ModalScreen[CharacterEditResult | None]):
    """Edit a character's name + personality + physical_description + backstory.

    Changing physical_description drifts the character from their existing
    portrait — the modal shows a warning banner in that case, but the
    change is still allowed. After save, ``portrait_prompt`` auto-syncs to
    the new physical_description so a subsequent Regenerate uses the
    update (the sync is done by the caller, not by the modal).
    """

    DEFAULT_CSS = """
    CharacterEditModal {
        align: center middle;
    }
    CharacterEditModal #char-edit-box {
        width: 100;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    CharacterEditModal #char-edit-title {
        text-style: bold;
        margin-bottom: 1;
    }
    CharacterEditModal .char-edit-label {
        margin-top: 1;
        color: $text-muted;
    }
    CharacterEditModal #char-edit-personality {
        height: 6;
    }
    CharacterEditModal #char-edit-physical {
        height: 6;
    }
    CharacterEditModal #char-edit-backstory {
        height: 12;
    }
    CharacterEditModal #char-edit-warning {
        margin-top: 1;
        padding: 0 1;
        color: $warning;
        text-style: italic;
        display: none;
    }
    CharacterEditModal #char-edit-warning.-visible {
        display: block;
    }
    CharacterEditModal #char-edit-buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    CharacterEditModal #char-edit-save {
        margin-left: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, char: Character) -> None:
        super().__init__()
        self._char = char
        self._initial_physical = char.physical_description
        self._name_input = Input(value=char.name, id="char-edit-name")
        self._personality_area = TextArea(char.personality, id="char-edit-personality")
        self._physical_area = TextArea(char.physical_description, id="char-edit-physical")
        self._backstory_area = TextArea(char.backstory, id="char-edit-backstory")
        self._warning = Static(
            "[!] Physical description changed. Portrait no longer matches —"
            " use Regenerate afterwards to refresh it.",
            id="char-edit-warning",
            markup=False,
        )
        self._save_btn = Button("Save", id="char-edit-save", variant="primary")
        self._cancel_btn = Button("Cancel", id="char-edit-cancel")

    def compose(self) -> ComposeResult:
        with Vertical(id="char-edit-box"):
            yield Static(f"Edit {self._char.name}", id="char-edit-title")
            yield Static("Name", classes="char-edit-label")
            yield self._name_input
            yield Static("Personality", classes="char-edit-label")
            yield self._personality_area
            yield Static("Physical description", classes="char-edit-label")
            yield self._physical_area
            yield Static("Backstory", classes="char-edit-label")
            yield self._backstory_area
            yield self._warning
            with Horizontal(id="char-edit-buttons"):
                yield self._cancel_btn
                yield self._save_btn

    @on(TextArea.Changed, "#char-edit-physical")
    def _on_physical_changed(self, _event: TextArea.Changed) -> None:
        """Show/hide the drift warning as the user edits the description."""
        if self._physical_area.text != self._initial_physical:
            self._warning.add_class("-visible")
        else:
            self._warning.remove_class("-visible")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "char-edit-save":
            self._attempt_save()
            return
        if event.button.id == "char-edit-cancel":
            self.dismiss(None)

    def _attempt_save(self) -> None:
        name = self._name_input.value.strip()
        if not name:
            self.notify("Name cannot be empty.", severity="error")
            return
        result = CharacterEditResult(
            name=name,
            personality=self._personality_area.text,
            physical_description=self._physical_area.text,
            backstory=self._backstory_area.text,
        )
        self.dismiss(result)

    def action_cancel(self) -> None:
        self.dismiss(None)
