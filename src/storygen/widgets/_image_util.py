"""Shared image-thumbnail rendering utility for TUI screens.

All screens that need to render a half-block image thumbnail (portraits,
library browser, endings) go through :func:`render_image_thumbnail` so the
exception handling and sizing logic live in one place.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from rich.console import RenderableType
from rich_pixels import Pixels
from textual.widgets import Static


class _ClickableThumbnail(Static):
    """Static thumbnail that invokes a callback with its image path on click."""

    def __init__(
        self,
        content: RenderableType,
        *,
        path: Path,
        on_click_cb: Callable[[Path], None],
        **kwargs: object,
    ) -> None:
        super().__init__(content, **kwargs)  # type: ignore[arg-type]
        self._path = path
        self._on_click_cb = on_click_cb

    def on_click(self) -> None:
        self._on_click_cb(self._path)


def render_image_thumbnail(
    path: Path,
    size: tuple[int, int],
    css_class: str,
    placeholder: str = "(unavailable)",
    *,
    on_click: Callable[[Path], None] | None = None,
) -> Static:
    """Open ``path`` as a half-block thumbnail, or return a placeholder Static.

    Args:
        path: Absolute path to the image file.
        size: ``(width, height)`` in pixels for :meth:`PIL.Image.thumbnail`.
        css_class: CSS class applied to the returned :class:`Static` widget.
        placeholder: Text shown when the image cannot be loaded.
        on_click: Optional callback invoked with ``path`` when the thumbnail
            is clicked.  When provided and the image loads, the returned
            widget is a clickable subclass; otherwise a plain Static.

    Returns:
        A :class:`Static` widget containing either the rendered pixels or the
        placeholder text.  The caller is responsible for mounting it.
    """
    if not path.exists():
        return Static(placeholder, classes=css_class, markup=False)
    try:
        with Image.open(path) as im:
            im = im.convert("RGBA")
            im.thumbnail(size)
            pixels = Pixels.from_image(im)
    except (OSError, ValueError, UnidentifiedImageError):
        return Static(placeholder, classes=css_class, markup=False)
    if on_click is not None:
        return _ClickableThumbnail(pixels, path=path, on_click_cb=on_click, classes=css_class)
    return Static(pixels, classes=css_class)
