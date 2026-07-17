"""The "Previously on..." recap modal.

A read-only Textual ``Screen`` shown on demand (PlayScreen's ``R`` / Shift+R
binding), on auto-recap, and on resume when a recap is available. Renders the
cached ``node.recap_text`` and offers a ``t`` binding to read the recap aloud
via the active TTS player.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from storygen.storage import app_state

if TYPE_CHECKING:
    from storygen.tts.player import TTSPlayer


class RecapModal(Screen[None]):
    """Modal displaying a 'Previously on...' recap. Dismissed with Escape or Enter."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close", "Close"),
        Binding("enter", "close", "Close"),
        Binding("t", "read_aloud", "Read aloud"),
    ]

    def __init__(
        self, recap_text: str, *, tts_player: TTSPlayer | None = None, tts_cache_path: str = ""
    ) -> None:
        super().__init__()
        self._recap_text = recap_text
        self._tts_player = tts_player
        self._tts_cache_path = tts_cache_path

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

    def action_read_aloud(self) -> None:
        if self._tts_player is None or not self._recap_text:
            return
        tts_prefs = app_state.read_tts_prefs()
        self._tts_player.configure(
            tts_prefs.provider,
            api_key=tts_prefs.api_key,
            voice=tts_prefs.voice,
        )
        from pathlib import Path

        cache = Path(self._tts_cache_path) if self._tts_cache_path else None
        if cache and not cache.exists():
            self.notify("Generating speech…", timeout=15)  # pyright: ignore[reportUnknownMemberType]
        self.run_worker(  # pyright: ignore[reportUnknownMemberType]
            self._tts_player.speak(self._recap_text, cache_path=cache),
            exclusive=True,
            name="recap-tts",
        )

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
