"""Modal for selecting a reference image for character portrait generation.

Provides a file path input, optional native file picker (via tkinter on
macOS/Windows), a thumbnail preview, and a use-as-is / style-transfer toggle.

Dismisses with a :class:`ReferenceImageResult` on confirm, or ``None`` on cancel.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import ClassVar, Literal

from PIL import Image
from pydantic import BaseModel
from rich_pixels import Pixels
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, RadioButton, RadioSet, Static

_logger = logging.getLogger(__name__)

_ACCEPTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class ReferenceImageResult(BaseModel):
    """Result of :class:`ReferenceImageModal` — selected file and processing mode."""

    source_path: Path
    mode: Literal["use_as_is", "style_transfer"]


def _try_native_file_picker() -> str | None:
    """Attempt to open a native file dialog via tkinter.

    Returns the selected file path, or None if tkinter is unavailable or
    the user cancelled.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)  # type: ignore[arg-type]
        path = filedialog.askopenfilename(
            title="Select Reference Image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp"),
                ("All files", "*.*"),
            ],
        )
        root.destroy()
        return path if path else None
    except Exception:
        _logger.debug("tkinter file dialog unavailable", exc_info=True)
        return None


def _load_and_convert(path: Path) -> tuple[bytes, Pixels]:
    """Load an image file, convert to PNG, and create a thumbnail Pixels.

    Returns (png_bytes, thumbnail_pixels).
    """
    with Image.open(path) as im:
        im = im.convert("RGBA")
        png_bytes_io = io.BytesIO()
        im.save(png_bytes_io, format="PNG")
        png_bytes = png_bytes_io.getvalue()
        thumb = im.copy()
        thumb.thumbnail((96, 48))
        pixels = Pixels.from_image(thumb)
    return png_bytes, pixels


class ReferenceImageModal(Screen[ReferenceImageResult | None]):
    """Select a reference image and choose processing mode.

    Dismisses with a :class:`ReferenceImageResult` on confirm, or ``None``
    on cancel/escape.
    """

    DEFAULT_CSS = """
    ReferenceImageModal {
        align: center middle;
    }
    ReferenceImageModal #ref-image-box {
        width: 72;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    ReferenceImageModal #ref-image-title {
        text-style: bold;
        margin-bottom: 1;
    }
    ReferenceImageModal #ref-image-path-label,
    ReferenceImageModal #ref-image-mode-label {
        margin-top: 1;
    }
    ReferenceImageModal #ref-image-preview {
        margin-top: 1;
        height: auto;
    }
    ReferenceImageModal #ref-image-buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    ReferenceImageModal #ref-image-ok {
        margin-left: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, character_name: str) -> None:
        super().__init__()
        self._character_name = character_name
        self._path_input = Input(
            placeholder="/path/to/image.png",
            id="ref-image-path",
        )
        self._browse_btn = Button("Browse", id="ref-image-browse")
        self._ok_btn = Button("OK", id="ref-image-ok", variant="primary", disabled=True)
        self._cancel_btn = Button("Cancel", id="ref-image-cancel")
        self._preview: Static | None = None
        self._loaded_png_bytes: bytes | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="ref-image-box"):
            yield Static(
                f"Reference image for {self._character_name}",
                id="ref-image-title",
            )
            yield Static("Image path:", id="ref-image-path-label")
            with Horizontal():
                yield self._path_input
                yield self._browse_btn
            yield Static(id="ref-image-preview")
            yield Static("Mode:", id="ref-image-mode-label")
            with RadioSet(id="ref-image-radios"):
                yield RadioButton("Use as-is", value=True, id="ref-mode-as-is")
                yield RadioButton(
                    "Style-transfer (regenerate in art style)", id="ref-mode-transfer"
                )
            with Horizontal(id="ref-image-buttons"):
                yield self._cancel_btn
                yield self._ok_btn

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ref-image-browse":
            self._browse()
            return
        if event.button.id == "ref-image-ok":
            self._confirm()
            return
        if event.button.id == "ref-image-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_changed(self, _event: Input.Changed) -> None:
        self._try_preview()

    def _browse(self) -> None:
        selected = _try_native_file_picker()
        if selected:
            self._path_input.value = selected
            self._try_preview()

    def _try_preview(self) -> None:
        path_str = self._path_input.value.strip()
        if not path_str:
            self._ok_btn.disabled = True
            return
        path = Path(path_str)
        if not path.is_file() or path.suffix.lower() not in _ACCEPTED_SUFFIXES:
            self._ok_btn.disabled = True
            return
        try:
            png_bytes, pixels = _load_and_convert(path)
        except Exception:
            self._ok_btn.disabled = True
            return
        self._loaded_png_bytes = png_bytes
        preview = self.query_one("#ref-image-preview", Static)
        preview.update(pixels)
        self._ok_btn.disabled = False

    def _confirm(self) -> None:
        path_str = self._path_input.value.strip()
        if not path_str or self._loaded_png_bytes is None:
            return
        radios = self.query_one("#ref-image-radios", RadioSet)
        mode: Literal["use_as_is", "style_transfer"] = (
            "style_transfer" if radios.pressed_index == 1 else "use_as_is"
        )
        self.dismiss(ReferenceImageResult(source_path=Path(path_str), mode=mode))
