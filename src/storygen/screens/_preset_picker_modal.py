"""PresetPickerModal: select a story preset to populate wizard fields.

Dismisses with the chosen :class:`StoryPreset` or ``None`` (cancel / Escape).
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.events import Click
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, Static

from storygen.core.presets import StoryPreset


class PresetPickerModal(Screen[StoryPreset | None]):
    """Modal to pick a story preset. Dismisses with the selected preset or None."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, presets: list[StoryPreset]) -> None:
        super().__init__()
        self._presets = presets

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="preset-modal-box"):
            yield Label("Choose a Preset", id="preset-modal-title")
            with VerticalScroll(id="preset-list"):
                for preset in self._presets:
                    yield Static(
                        f"[bold]{preset.name}[/bold]\n{preset.description}",
                        id=f"preset-{id(preset)}",
                        classes="preset-card",
                    )
            with Vertical(id="preset-modal-buttons"):
                yield Button("Cancel", id="preset-cancel")
        yield Footer()

    def on_click(self, event: Click) -> None:
        widget, _region = self.get_widget_at(event.screen_x, event.screen_y)
        if not isinstance(widget, Static) or not widget.has_class("preset-card"):
            return
        for preset in self._presets:
            if widget.id == f"preset-{id(preset)}":
                self.dismiss(preset)
                return

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "preset-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    DEFAULT_CSS = """
    PresetPickerModal {
        align: center middle;
    }
    #preset-modal-box {
        width: 60;
        height: auto;
        max-height: 80vh;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    #preset-modal-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    .preset-card {
        padding: 1;
        margin-bottom: 1;
        background: $surface-lighten-1;
    }
    .preset-card:hover {
        background: $accent-darken-2;
    }
    #preset-modal-buttons {
        height: auto;
        padding-top: 1;
    }
    """
