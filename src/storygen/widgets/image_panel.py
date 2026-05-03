"""ImagePanel: half-block renderer with animated throbber / image states."""

from __future__ import annotations

import contextlib
from enum import Enum, auto
from pathlib import Path

from PIL import Image
from rich_pixels import Pixels
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widgets import Static

from storygen.util import open_in_system_viewer
from storygen.widgets.throbber import Throbber


class ImagePanelState(Enum):
    EMPTY = auto()
    GENERATING = auto()
    DONE = auto()
    FAILED = auto()


class ImagePanel(Static):
    """Renders a PNG as half-block pixels, or a throbber / status glyph."""

    DEFAULT_CSS = """
    ImagePanel {
        layout: vertical;
    }
    ImagePanel Throbber {
        height: 1;
        display: none;
    }
    ImagePanel Throbber.-active {
        display: block;
    }
    """

    panel_state: reactive[ImagePanelState] = reactive(ImagePanelState.EMPTY, init=False)

    def __init__(self) -> None:
        super().__init__("")
        self._image_path: Path | None = None

    def compose(self) -> ComposeResult:
        yield Throbber()

    def _start_throbber(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one(Throbber).start()

    def _stop_throbber(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one(Throbber).stop()

    def show_generating(self) -> None:
        self._image_path = None
        self.panel_state = ImagePanelState.GENERATING
        self.display = True
        self.update("generating illustration...")
        self._start_throbber()

    def show_failed(self) -> None:
        self._image_path = None
        self.panel_state = ImagePanelState.FAILED
        self.display = True
        self.update("image failed -- press i to retry")
        self._stop_throbber()

    def show_image(self, path: Path) -> None:
        self._image_path = path
        self.panel_state = ImagePanelState.DONE
        self.display = True
        self._stop_throbber()
        with Image.open(path) as im:
            im = im.convert("RGBA")
            im.thumbnail((96, 48))
            self.update(Pixels.from_image(im))

    def clear(self) -> None:
        self._image_path = None
        self.panel_state = ImagePanelState.EMPTY
        self.display = False
        self.update("")
        self._stop_throbber()

    def on_click(self) -> None:
        """Open the displayed image in the OS default viewer."""
        if self._image_path is not None:
            open_in_system_viewer(self._image_path)
