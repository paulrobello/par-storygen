"""Modal for creating a new character in the catalog via LLM."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Static, TextArea


class CreateCharRequest(BaseModel):
    """Result of CreateCharacterModal — name + concept to generate."""

    name: str
    concept: str


class CreateCharacterModal(Screen[CreateCharRequest | None]):
    """Collect a character concept (and optional name) for LLM generation.

    Dismisses with a CreateCharRequest or None on cancel.
    """

    DEFAULT_CSS = """
    CreateCharacterModal {
        align: center middle;
    }
    CreateCharacterModal #create-char-box {
        width: 70;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    CreateCharacterModal #create-char-title {
        text-style: bold;
        margin-bottom: 1;
    }
    CreateCharacterModal #create-char-concept-label {
        margin-top: 1;
    }
    CreateCharacterModal #create-char-concept {
        height: 5;
        margin-bottom: 1;
    }
    CreateCharacterModal #create-char-buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    CreateCharacterModal #create-char-generate {
        margin-left: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
    ]

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
        self._generate_btn = Button(
            "Create",
            id="create-char-generate",
            variant="primary",
        )
        self._cancel_btn = Button("Cancel", id="create-char-cancel")

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
            with Horizontal(id="create-char-buttons"):
                yield self._cancel_btn
                yield self._generate_btn

    def on_mount(self) -> None:
        self._refresh_generate_state()

    def on_input_changed(self, _event: Input.Changed) -> None:
        self._refresh_generate_state()

    def on_text_area_changed(self, _event: TextArea.Changed) -> None:
        self._refresh_generate_state()

    def _refresh_generate_state(self) -> None:
        concept = self._concept_area.text.strip()
        self._generate_btn.disabled = not concept

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-char-generate":
            concept = self._concept_area.text.strip()
            if not concept:
                return
            name = self._name_input.value.strip()
            self.dismiss(CreateCharRequest(name=name, concept=concept))
            return
        if event.button.id == "create-char-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
