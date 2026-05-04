"""Main-menu screen: New / Load / Settings / Quit."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header

from storygen.storage.app_state import last_story_id


class MenuScreen(Screen[None]):
    """Top-level menu shown at app start."""

    DEFAULT_CSS = """
    MenuScreen #menu {
        align: center middle;
        width: 100%;
        height: 1fr;
    }
    MenuScreen #menu > Button {
        width: 28;
        margin-bottom: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("r", "resume_story", "Resume Last"),
        ("n", "new_story", "New Story"),
        ("k", "quick_start", "Quick Start"),
        ("l", "load_story", "Existing Stories"),
        ("c", "characters", "Characters"),
        ("s", "settings", "Settings"),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="menu"):
            yield Button("Resume Last Story", id="btn-resume", variant="primary")
            yield Button("New Story", id="btn-new")
            yield Button("Quick Start", id="btn-quick", variant="success")
            yield Button("Existing Stories", id="btn-load")
            yield Button("Characters", id="btn-characters")
            yield Button("Settings", id="btn-settings")
            yield Button("Quit", id="btn-quit")
        yield Footer()

    def on_mount(self) -> None:
        if last_story_id() is None:
            self.query_one("#btn-resume", Button).disabled = True

    async def action_resume_story(self) -> None:
        from storygen.app import StoryGenApp

        app = self.app  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        if isinstance(app, StoryGenApp):
            await app._auto_resume()  # pyright: ignore[reportPrivateUsage]

    def action_new_story(self) -> None:
        from storygen.app import StoryGenApp

        app = self.app  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        if isinstance(app, StoryGenApp):
            app.push_screen(app._make_wizard())  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType]
        else:
            app.push_screen("wizard")  # pyright: ignore[reportUnknownMemberType]

    def action_quick_start(self) -> None:
        from storygen.core.presets import load_all_presets

        if not load_all_presets():
            self.notify("No presets available", severity="warning", timeout=5)
            return
        self.app.push_screen("preset_picker")  # pyright: ignore[reportUnknownMemberType]

    def action_load_story(self) -> None:
        self.app.push_screen("load")  # pyright: ignore[reportUnknownMemberType]

    def action_characters(self) -> None:
        self.app.push_screen("catalog")  # pyright: ignore[reportUnknownMemberType]

    def action_settings(self) -> None:
        self.app.push_screen("settings")  # pyright: ignore[reportUnknownMemberType]

    def action_quit(self) -> None:
        self.app.exit()  # pyright: ignore[reportUnknownMemberType]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "btn-resume": self.action_resume_story,
            "btn-new": self.action_new_story,
            "btn-quick": self.action_quick_start,
            "btn-load": self.action_load_story,
            "btn-characters": self.action_characters,
            "btn-settings": self.action_settings,
            "btn-quit": self.action_quit,
        }
        action = actions.get(event.button.id or "")
        if action:
            action()
