"""Modal for creating a new character in the catalog via LLM."""

from __future__ import annotations

import io
from pathlib import Path
from typing import ClassVar

from PIL import Image
from pydantic import BaseModel
from rich_pixels import Pixels
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Static, TextArea


class CreateCharRequest(BaseModel):
    """Result of CreateCharacterModal — name + concept to generate."""

    name: str
    concept: str
    reference_image: bytes | None = None


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
    CreateCharacterModal #create-char-ref-label {
        margin-top: 1;
    }
    CreateCharacterModal #create-char-ref-preview {
        margin-top: 0;
        height: auto;
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

    def on_mount(self) -> None:
        self._refresh_generate_state()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "create-char-ref-path":
            self._try_ref_preview()
        else:
            self._refresh_generate_state()

    def on_text_area_changed(self, _event: TextArea.Changed) -> None:
        self._refresh_generate_state()

    def _refresh_generate_state(self) -> None:
        concept = self._concept_area.text.strip()
        self._generate_btn.disabled = not concept

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-char-ref-browse":
            self._browse_ref()
            return
        if event.button.id == "create-char-generate":
            concept = self._concept_area.text.strip()
            if not concept:
                return
            name = self._name_input.value.strip()
            self.dismiss(
                CreateCharRequest(
                    name=name,
                    concept=concept,
                    reference_image=self._loaded_ref_bytes,
                )
            )
            return
        if event.button.id == "create-char-cancel":
            self.dismiss(None)

    _ACCEPTED_SUFFIXES: ClassVar[frozenset[str]] = frozenset({".png", ".jpg", ".jpeg", ".webp"})

    def _try_ref_preview(self) -> None:
        path_str = self._ref_path_input.value.strip()
        preview = self.query_one("#create-char-ref-preview", Static)
        if not path_str:
            self._loaded_ref_bytes = None
            preview.update("")
            return
        path = Path(path_str)
        if not path.is_file() or path.suffix.lower() not in self._ACCEPTED_SUFFIXES:
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
        from storygen.screens._ref_image_modals import (
            _try_native_file_picker,  # pyright: ignore[reportPrivateUsage]
        )

        selected = _try_native_file_picker()
        if selected:
            self._ref_path_input.value = selected
            self._try_ref_preview()

    def action_cancel(self) -> None:
        self.dismiss(None)
