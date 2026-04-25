"""ConfirmModal: reusable yes/no confirmation screen.

Dismisses with ``True`` on confirm, ``False`` on cancel or Escape. Used by
any caller that needs a destructive-action confirmation prompt.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Static


class ConfirmModal(Screen[bool]):
    """Small yes/no confirmation modal.

    Args:
        message: Body text shown to the user (plain string; Rich markup is
            NOT interpreted, so LLM-authored text cannot inject styling).
        confirm_label: Text on the destructive-action button.
        cancel_label: Text on the non-destructive button.
    """

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    ConfirmModal #confirm-box {
        width: 60;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    ConfirmModal #confirm-message {
        margin-bottom: 1;
    }
    ConfirmModal #confirm-buttons {
        height: auto;
        align-horizontal: right;
    }
    ConfirmModal #confirm-yes {
        margin-left: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        message: str,
        *,
        confirm_label: str = "Delete",
        cancel_label: str = "Cancel",
    ) -> None:
        super().__init__()
        self._message = message
        self._confirm_label = confirm_label
        self._cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self._message, id="confirm-message", markup=False)
            with Horizontal(id="confirm-buttons"):
                yield Button(self._cancel_label, id="confirm-no")
                yield Button(self._confirm_label, id="confirm-yes", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")

    def action_cancel(self) -> None:
        self.dismiss(False)
