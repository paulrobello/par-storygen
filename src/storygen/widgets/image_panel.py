"""ImagePanel: half-block renderer with animated spinner / image states."""

from __future__ import annotations

from enum import Enum, auto
from pathlib import Path

from PIL import Image
from rich.text import Text
from rich_pixels import Pixels
from textual.reactive import reactive
from textual.widgets import Static

from storygen.util import open_in_system_viewer

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class ImagePanelState(Enum):
    EMPTY = auto()
    GENERATING = auto()
    DONE = auto()
    FAILED = auto()


class ImagePanel(Static):
    """Renders a PNG as half-block pixels, or a spinner / status glyph."""

    panel_state: reactive[ImagePanelState] = reactive(ImagePanelState.EMPTY, init=False)

    def on_mount(self) -> None:
        if self.panel_state == ImagePanelState.GENERATING:
            self._tick_spinner()

    def __init__(self) -> None:
        super().__init__("")
        self._image_path: Path | None = None
        self._frame: int = 0
        self._spinner_timer: object | None = None

    def _tick_spinner(self) -> None:
        """Timer callback: advance spinner frame and update content."""
        if self.panel_state != ImagePanelState.GENERATING:
            return
        ch = _SPINNER_FRAMES[self._frame % len(_SPINNER_FRAMES)]
        self.update(Text(f"  {ch} generating illustration...", style="bold"))
        self._frame += 1
        self._spinner_timer = self.set_timer(0.25, self._tick_spinner)

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer = None

    def show_generating(self) -> None:
        self._image_path = None
        self.panel_state = ImagePanelState.GENERATING
        self.display = True
        self._frame = 0
        if self._is_mounted:
            self._tick_spinner()
        else:
            self.update("generating illustration...")

    def show_failed(self) -> None:
        self._image_path = None
        self._stop_spinner()
        self.panel_state = ImagePanelState.FAILED
        self.display = True
        self.update("image failed -- press i to retry")

    def show_image(self, path: Path) -> None:
        self._image_path = path
        self._stop_spinner()
        self.panel_state = ImagePanelState.DONE
        self.display = True
        with Image.open(path) as im:
            im = im.convert("RGBA")
            im.thumbnail((96, 48))
            self.update(Pixels.from_image(im))

    def clear(self) -> None:
        self._image_path = None
        self._stop_spinner()
        self.panel_state = ImagePanelState.EMPTY
        self.display = False
        self.update("")

    def on_click(self) -> None:
        """Open the displayed image in the OS default viewer."""
        if self._image_path is not None:
            open_in_system_viewer(self._image_path)
