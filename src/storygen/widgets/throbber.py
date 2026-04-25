"""Animated rainbow gradient progress bar for loading states."""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from time import monotonic

from rich.color import Color as RichColor
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual.color import Color, Gradient
from textual.css.styles import RulesMap
from textual.strip import Strip
from textual.style import Style
from textual.visual import RenderOptions, Visual
from textual.widget import Widget

COLORS = [
    "#881177",
    "#aa3355",
    "#cc6666",
    "#ee9944",
    "#eedd00",
    "#99dd55",
    "#44dd88",
    "#22ccbb",
    "#00bbcc",
    "#0099cc",
    "#3366bb",
    "#663399",
    "#881177",
]

_GRADIENT = Gradient.from_colors(*[Color.parse(color) for color in COLORS])


@lru_cache(maxsize=8)
def _make_segments(
    character: str,
    bg_color: RichColor | None,
    width: int,
) -> list[Segment]:
    return [
        Segment(
            character,
            RichStyle.from_color(
                _GRADIENT.get_rich_color((offset / width) % 1),
                bg_color,
            ),
        )
        for offset in range(width * 2)
    ]


class ThrobberVisual(Visual):
    """Animated rainbow gradient bar that scrolls horizontally."""

    def __init__(
        self,
        character: str = "━",
        get_time: Callable[[], float] = monotonic,
    ) -> None:
        self.character = character
        self.get_time = get_time

    def render_strips(
        self,
        width: int,
        height: int | None,
        style: Style,
        options: RenderOptions,
    ) -> list[Strip]:
        time = self.get_time()
        segments = _make_segments(
            self.character,
            style.rich_style.bgcolor,  # type: ignore[arg-type]
            width,
        )
        offset = width - int((time % 1.0) * width)
        segments = segments[offset : offset + width]
        return [Strip(segments, cell_length=width)]

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        return container_width

    def get_height(self, rules: RulesMap, width: int) -> int:
        return 1


class Throbber(Widget):
    """Full-width animated rainbow bar — show/hide via CSS class toggling."""

    DEFAULT_CSS = """
    Throbber {
        width: 100%;
        height: 1;
        visibility: hidden;
    }
    Throbber.-active {
        visibility: visible;
    }
    """

    def on_mount(self) -> None:
        self.auto_refresh = 1 / 15

    def render(self) -> ThrobberVisual:
        return ThrobberVisual()

    def start(self) -> None:
        self.set_class(True, "-active")

    def stop(self) -> None:
        self.set_class(False, "-active")
