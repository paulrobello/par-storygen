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
