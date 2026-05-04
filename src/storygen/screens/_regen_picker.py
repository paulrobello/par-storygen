"""RegenPickerModal: quick-pick modal for regen actions (image, edit, beat, audio)."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Static


class RegenPickerModal(Screen[str | None]):
    """Modal picker for regen actions.

    Dismisses with one of ``"retry_image"``, ``"edit_regen_image"``,
    ``"regenerate_node"``, ``"regen_audio"``, or ``None`` (cancelled).
    """

    DEFAULT_CSS = """
    RegenPickerModal {
        align: center middle;
    }
    RegenPickerModal #regen-box {
        width: 50;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    RegenPickerModal #regen-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    RegenPickerModal #regen-options {
        margin-bottom: 1;
    }
    RegenPickerModal #regen-options > Button {
        width: 100%;
        margin-bottom: 1;
    }
    RegenPickerModal #regen-cancel {
        align-horizontal: right;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
        ("i", "pick_retry", "Regen image"),
        ("e", "pick_edit", "Edit regen"),
        ("b", "pick_beat", "Regen beat"),
        ("a", "pick_audio", "Regen audio"),
    ]

    def __init__(
        self,
        *,
        can_retry_image: bool = True,
        can_edit_regen: bool = True,
        can_regen_beat: bool = True,
        can_regen_audio: bool = True,
    ) -> None:
        super().__init__()
        self._can_retry = can_retry_image
        self._can_edit = can_edit_regen
        self._can_beat = can_regen_beat
        self._can_audio = can_regen_audio

    def compose(self) -> ComposeResult:
        with Vertical(id="regen-box"):
            yield Static("Regen", id="regen-title")
            with Vertical(id="regen-options"):
                yield Button("Regen image  [i]", id="btn-retry", disabled=not self._can_retry)
                yield Button("Edit regen   [e]", id="btn-edit", disabled=not self._can_edit)
                yield Button("Regen beat   [b]", id="btn-beat", disabled=not self._can_beat)
                yield Button("Regen audio  [a]", id="btn-audio", disabled=not self._can_audio)
            with Vertical(id="regen-cancel"):
                yield Button("Cancel", id="btn-cancel")
        yield Footer()

    def _pick(self, action: str) -> None:
        self.dismiss(action)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_pick_retry(self) -> None:
        if self._can_retry:
            self._pick("retry_image")

    def action_pick_edit(self) -> None:
        if self._can_edit:
            self._pick("edit_regen_image")

    def action_pick_beat(self) -> None:
        if self._can_beat:
            self._pick("regenerate_node")

    def action_pick_audio(self) -> None:
        if self._can_audio:
            self._pick("regen_audio")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        mapping = {
            "btn-retry": "retry_image",
            "btn-edit": "edit_regen_image",
            "btn-beat": "regenerate_node",
            "btn-audio": "regen_audio",
            "btn-cancel": None,
        }
        result = mapping.get(event.button.id or "")
        if result is not None or event.button.id == "btn-cancel":
            self.dismiss(result)
