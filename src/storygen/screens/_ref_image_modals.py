"""Modals for selecting a reference image for character portrait generation.

Provides:
- :class:`ImageFilePickerModal` — a Textual-native directory tree browser
  filtered to image files.
- :class:`ReferenceImageModal` — path input with Browse button, thumbnail
  preview, and a use-as-is / style-transfer toggle.

Dismisses with a :class:`ReferenceImageResult` on confirm, or ``None`` on cancel.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import ClassVar, Literal

from PIL import Image
from pydantic import BaseModel
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DirectoryTree, Input, RadioButton, RadioSet, Static

from storygen.widgets._image_util import pixels_from_image

_logger = logging.getLogger(__name__)

_ACCEPTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class ReferenceImageResult(BaseModel):
    """Result of :class:`ReferenceImageModal` — selected file and processing mode."""

    source_path: Path
    mode: Literal["use_as_is", "style_transfer"]
    style_prompt: str = ""


class _ImageDirectoryTree(DirectoryTree):
    """DirectoryTree that only shows image files and directories."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [p for p in paths if p.is_dir() or p.suffix.lower() in _ACCEPTED_SUFFIXES]


class ImageFilePickerModal(Screen[Path | None]):
    """A Textual-native file picker filtered to image files.

    Dismisses with the selected file path, or ``None`` on cancel.
    """

    DEFAULT_CSS = """
    ImageFilePickerModal {
        align: center middle;
    }
    ImageFilePickerModal #file-picker-box {
        width: 80;
        height: 30;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    ImageFilePickerModal #file-picker-title {
        text-style: bold;
        margin-bottom: 1;
    }
    ImageFilePickerModal #file-picker-tree {
        height: 1fr;
    }
    ImageFilePickerModal #file-picker-path-row {
        height: auto;
        margin-top: 1;
    }
    ImageFilePickerModal #file-picker-path-display {
        width: 1fr;
    }
    ImageFilePickerModal #file-picker-buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    ImageFilePickerModal #file-picker-ok {
        margin-left: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, start_path: str | Path = ".") -> None:
        super().__init__()
        self._start_path = Path(start_path).expanduser().resolve()
        if not self._start_path.is_dir():
            self._start_path = Path.home()
        self._selected: Path | None = None
        self._ok_btn = Button("OK", id="file-picker-ok", variant="primary", disabled=True)
        self._cancel_btn = Button("Cancel", id="file-picker-cancel")

    def compose(self) -> ComposeResult:
        with Vertical(id="file-picker-box"):
            yield Static("Select Image File", id="file-picker-title")
            with VerticalScroll(id="file-picker-tree"):
                yield _ImageDirectoryTree(self._start_path)
            with Horizontal(id="file-picker-path-row"):
                yield Static(id="file-picker-path-display")
            with Horizontal(id="file-picker-buttons"):
                yield self._cancel_btn
                yield self._ok_btn

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        event.stop()
        path = event.path
        if path.suffix.lower() in _ACCEPTED_SUFFIXES:
            self._selected = path
            self.query_one("#file-picker-path-display", Static).update(str(path))
            self._ok_btn.disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "file-picker-ok" and self._selected is not None:
            self.dismiss(self._selected)
        elif event.button.id == "file-picker-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


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
    ReferenceImageModal #ref-image-path {
        width: 1fr;
    }
    ReferenceImageModal #ref-image-browse {
        width: auto;
    }
    ReferenceImageModal #ref-style-row {
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

    def __init__(self, character_name: str, *, default_style: str = "") -> None:
        super().__init__()
        self._character_name = character_name
        self._path_input = Input(
            placeholder="/path/to/image.png",
            id="ref-image-path",
        )
        self._browse_btn = Button("Browse", id="ref-image-browse")
        self._style_input = Input(
            value=default_style,
            placeholder="e.g. anime, oil painting, watercolor…",
            id="ref-style-input",
        )
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
            with Vertical(id="ref-style-row"):
                yield Static("Art style:", id="ref-style-label")
                yield self._style_input
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

    def on_mount(self) -> None:
        self._sync_style_row_visibility()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "ref-image-radios":
            self._sync_style_row_visibility()

    def _sync_style_row_visibility(self) -> None:
        radios = self.query_one("#ref-image-radios", RadioSet)
        is_transfer = radios.pressed_index == 1
        style_row = self.query_one("#ref-style-row", Vertical)
        style_row.display = is_transfer

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_changed(self, _event: Input.Changed) -> None:
        self._try_preview()

    def _browse(self) -> None:
        current = self._path_input.value.strip()
        start = Path(current).parent if current else Path.home()
        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            ImageFilePickerModal(start),
            self._on_file_picked,
        )

    def _on_file_picked(self, result: Path | None) -> None:
        if result is not None:
            self._path_input.value = str(result)
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
            with Image.open(path) as im:
                im = im.convert("RGBA")
                buf = io.BytesIO()
                im.save(buf, format="PNG")
                self._loaded_png_bytes = buf.getvalue()
        except Exception:
            _logger.debug("Failed to load reference image for validation", exc_info=True)
            self._ok_btn.disabled = True
            return
        self._ok_btn.disabled = False
        try:
            thumb = Image.open(path)
            thumb = thumb.convert("RGBA")
            thumb.thumbnail((96, 48))
            pixels = pixels_from_image(thumb)
            preview = self.query_one("#ref-image-preview", Static)
            preview.update(pixels)
        except Exception:
            _logger.debug("Thumbnail preview failed (non-fatal)", exc_info=True)

    def _confirm(self) -> None:
        path_str = self._path_input.value.strip()
        if not path_str or self._loaded_png_bytes is None:
            return
        radios = self.query_one("#ref-image-radios", RadioSet)
        mode: Literal["use_as_is", "style_transfer"] = (
            "style_transfer" if radios.pressed_index == 1 else "use_as_is"
        )
        style_prompt = ""
        if mode == "style_transfer":
            style_prompt = self._style_input.value.strip()
        self.dismiss(
            ReferenceImageResult(source_path=Path(path_str), mode=mode, style_prompt=style_prompt)
        )
