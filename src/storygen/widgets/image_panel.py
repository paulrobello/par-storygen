"""ImagePanel: half-block renderer with spinner / warning / image states."""

from __future__ import annotations

from enum import Enum, auto
from pathlib import Path

from PIL import Image
from rich_pixels import Pixels
from textual.reactive import reactive
from textual.widgets import Static

from storygen.util import open_in_system_viewer


class ImagePanelState(Enum):
    EMPTY = auto()
    GENERATING = auto()
    DONE = auto()
    FAILED = auto()


class ImagePanel(Static):
    """Renders a PNG as half-block pixels, or a status glyph."""

    panel_state: reactive[ImagePanelState] = reactive(ImagePanelState.EMPTY, init=False)

    def __init__(self) -> None:
        super().__init__("")
        self._image_path: Path | None = None

    def show_generating(self) -> None:
        self._image_path = None
        self.panel_state = ImagePanelState.GENERATING
        self.display = True
        self.update("generating illustration...")

    def show_failed(self) -> None:
        self._image_path = None
        self.panel_state = ImagePanelState.FAILED
        self.display = True
        self.update("image failed -- press i to retry")

    def show_image(self, path: Path) -> None:
        self._image_path = path
        self.panel_state = ImagePanelState.DONE
        self.display = True
        # Hover styling (defined in PlayScreen CSS) is the click affordance;
        # no tooltip — it was distracting on every mouseover.
        with Image.open(path) as im:
            im = im.convert("RGBA")
            # Sized for the ~33% side column. 96 image cols x 48 rows of
            # half-blocks renders to 96 cell-cols x 24 cell-rows. The widget
            # itself is constrained by CSS so a narrow column will shrink the
            # rendered output proportionally.
            im.thumbnail((96, 48))
            self.update(Pixels.from_image(im))

    def clear(self) -> None:
        self._image_path = None
        self.panel_state = ImagePanelState.EMPTY
        self.display = False
        self.update("")

    def on_click(self) -> None:
        """Open the displayed image in the OS default viewer."""
        if self._image_path is not None:
            open_in_system_viewer(self._image_path)
