"""ImagePanel: full-color renderer with animated throbber / image states.

Uses par-textual-image's TerminalImage widget with auto-detected protocol
(Kitty TGP, Sixel, iTerm2, or halfblock fallback).
"""

from __future__ import annotations

import contextlib
from enum import Enum, auto
from pathlib import Path

from par_textual_image import TerminalImage
from par_textual_image.protocols._detect import ProtocolName
from textual.app import ComposeResult
from textual.containers import Grid
from textual.reactive import reactive
from textual.widgets import Static

from storygen.util import open_in_system_viewer
from storygen.widgets.throbber import Throbber


class ImagePanelState(Enum):
    EMPTY = auto()
    GENERATING = auto()
    DONE = auto()
    FAILED = auto()


class _Overlay(Grid):
    """Grid overlay for status text + throbber, positioned on top of the image."""

    DEFAULT_CSS = """
    _Overlay {
        grid-size: 1;
        height: auto;
    }
    _Overlay Throbber {
        height: 1;
        visibility: hidden;
    }
    _Overlay Throbber.-active {
        visibility: visible;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="img-status")
        yield Throbber()


class ImagePanel(Grid):
    """Renders an image using the best available terminal protocol."""

    DEFAULT_CSS = """
    ImagePanel {
        grid-size: 1;
        overflow: hidden;
    }
    ImagePanel > TerminalImage {
        width: 100%;
        height: 100%;
    }
    ImagePanel > _Overlay {
        width: 100%;
        height: auto;
    }
    """

    panel_state: reactive[ImagePanelState] = reactive(ImagePanelState.EMPTY, init=False)

    def __init__(self) -> None:
        super().__init__()
        self._image_path: Path | None = None
        self._protocol: ProtocolName | None = None

    def set_protocol(self, mode: str) -> None:
        """Force a specific graphics protocol. Call before or after mount."""
        if mode != "auto":
            self._protocol = mode  # type: ignore[assignment]

    def compose(self) -> ComposeResult:
        yield TerminalImage(id="img-term")
        yield _Overlay()

    def on_mount(self) -> None:
        if self._protocol:
            term = self._try_term()
            if term:
                term.force_protocol(self._protocol)

    def _try_term(self) -> TerminalImage | None:
        with contextlib.suppress(Exception):
            return self.query_one(TerminalImage)
        return None

    def _try_overlay(self) -> _Overlay | None:
        with contextlib.suppress(Exception):
            return self.query_one(_Overlay)
        return None

    def _try_status(self) -> Static | None:
        with contextlib.suppress(Exception):
            return self.query_one("#img-status", Static)
        return None

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
        if overlay := self._try_overlay():
            overlay.display = True
        if status := self._try_status():
            status.update("generating illustration...")
            status.display = True
        if term := self._try_term():
            term.display = False
        self._start_throbber()

    def show_failed(self) -> None:
        self._image_path = None
        self.panel_state = ImagePanelState.FAILED
        self.display = True
        if overlay := self._try_overlay():
            overlay.display = True
        if status := self._try_status():
            status.update("image failed -- press i to retry")
            status.display = True
        if term := self._try_term():
            term.display = False
        self._stop_throbber()

    def show_image(self, path: Path) -> None:
        self._image_path = path
        self.panel_state = ImagePanelState.DONE
        self.display = True
        if overlay := self._try_overlay():
            overlay.display = False
        term = self._try_term()
        if term:
            term.image = path
            term.display = True
        self._stop_throbber()

    def clear(self) -> None:
        self._image_path = None
        self.panel_state = ImagePanelState.EMPTY
        self.display = False
        if overlay := self._try_overlay():
            overlay.display = False
        if status := self._try_status():
            status.update("")
        term = self._try_term()
        if term:
            term.image = None
            term.display = False
        self._stop_throbber()

    def on_click(self) -> None:
        """Open the displayed image in the OS default viewer."""
        if self._image_path is not None:
            open_in_system_viewer(self._image_path)
