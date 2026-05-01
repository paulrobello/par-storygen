"""Intro screen: figlet splash shown briefly at app launch."""

from __future__ import annotations

from pyfiglet import Figlet
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

_SPLASH_DURATION = 2.5
_GRADIENT_COLORS = ["#e06cff", "#b44dff", "#7c3aed", "#3b82f6", "#06b6d4", "#22d3ee"]


def gradient_text(ascii_art: str) -> Text:
    """Apply a vertical gradient of colors to figlet block characters."""
    lines = ascii_art.splitlines()
    text = Text()
    for i, line in enumerate(lines):
        color = _GRADIENT_COLORS[i % len(_GRADIENT_COLORS)]
        text.append(line, style=color)
        if i < len(lines) - 1:
            text.append("\n")
    return text


class IntroScreen(Screen[None]):
    """Splash screen with figlet title, auto-dismisses after a short delay."""

    DEFAULT_CSS = """
    IntroScreen {
        align: center middle;
        background: $surface;
    }
    IntroScreen #splash-container {
        align: center middle;
        width: 100%;
        height: 100%;
    }
    IntroScreen #splash-title {
        text-align: center;
        margin-bottom: 1;
    }
    IntroScreen #splash-subtitle {
        text-align: center;
        color: $text-muted;
    }
    """

    def compose(self) -> ComposeResult:
        fig = Figlet(font="blocky")
        title_art = fig.renderText("PAR") + "\n" + fig.renderText("STORYGEN")
        with Vertical(id="splash-container"):
            yield Static(gradient_text(title_art), id="splash-title")
            yield Static("AI-driven choose-your-own-adventure", id="splash-subtitle")

    def on_mount(self) -> None:
        self.set_timer(_SPLASH_DURATION, self._dismiss)

    def _dismiss(self) -> None:
        self.app.pop_screen()  # pyright: ignore[reportUnknownMemberType]

    def on_key(self, event: object) -> None:
        self._dismiss()
