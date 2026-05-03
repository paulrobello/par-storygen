from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static


class RecapModal(Screen[None]):
    """Modal displaying a 'Previously on...' recap. Dismissed with Escape or Enter."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close", "Close"),
        Binding("enter", "close", "Close"),
    ]

    def __init__(self, recap_text: str) -> None:
        super().__init__()
        self._recap_text = recap_text

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="recap-modal-box"):
            yield Static(self._recap_text, id="recap-text", markup=False)
            yield Button("Close", id="recap-close", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "recap-close":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    CSS = """
    #recap-modal-box {
        width: 80;
        max-width: 90vw;
        height: auto;
        max-height: 80vh;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    #recap-text {
        margin-bottom: 1;
    }
    """
