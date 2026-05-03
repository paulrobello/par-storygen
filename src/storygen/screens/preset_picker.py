"""PresetPickerScreen: full-screen Quick Start — pick a preset and launch directly."""

from __future__ import annotations

from typing import ClassVar

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.events import Click
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, Static

from storygen.core.presets import StoryPreset, load_all_presets


class PresetPickerScreen(Screen[None]):
    """Full screen for Quick Start -- pick a preset and launch directly."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="preset-screen-container"):
            yield Label("Quick Start — Choose a Story", id="preset-screen-title")
            with VerticalScroll(id="preset-screen-list"):
                for preset in load_all_presets():
                    yield Static(
                        f"[bold]{preset.name}[/bold]\n{preset.description}",
                        id=f"ps-{id(preset)}",
                        classes="preset-card",
                    )
            yield Button("Back", id="preset-screen-back")
        yield Footer()

    def on_click(self, event: Click) -> None:
        widget, _region = self.get_widget_at(event.screen_x, event.screen_y)
        if not isinstance(widget, Static) or not widget.has_class("preset-card"):
            return
        for preset in load_all_presets():
            if widget.id == f"ps-{id(preset)}":
                self._launch(preset)
                return

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "preset-screen-back":
            self.app.pop_screen()  # pyright: ignore[reportUnknownMemberType]

    @work(exit_on_error=False)
    async def _launch(self, preset: StoryPreset) -> None:
        from storygen.core.models import Tone
        from storygen.llm import agents as agent_mod
        from storygen.llm.provider_factory import build_text_model
        from storygen.screens.wizard import WizardFlow

        app = self.app  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        config = app._config  # type: ignore[attr-defined]  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]

        text_model = build_text_model(config.text_config)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        flow = WizardFlow(
            text_config=config.text_config,  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            image_config=config.image_config,  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            character_image_config=config.character_image_config,  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            theme_agent=agent_mod.build_theme_agent(text_model),  # pyright: ignore[reportArgumentType]
            character_agent_factory=lambda theme: agent_mod.build_character_agent(  # pyright: ignore[reportArgumentType]
                text_model, theme=theme
            ),
            blurb_agent_factory=lambda theme, characters, narration_style: (
                agent_mod.build_blurb_agent(  # pyright: ignore[reportArgumentType]
                    text_model,
                    theme=theme,
                    characters=characters,
                    narration_style=narration_style,
                )
            ),
            adapt_agent_factory=lambda theme: agent_mod.build_adapt_backstory_agent(  # pyright: ignore[reportArgumentType]
                text_model, theme=theme
            ),
            image_provider=app._image_provider,  # type: ignore[attr-defined]
        )

        self.notify("Generating story from preset…", timeout=120)

        try:
            theme = await flow.propose_theme(preset.theme)

            tone = Tone(
                preset=preset.tone_preset,  # pyright: ignore[reportArgumentType]
                custom_descriptor=preset.tone_descriptor or None,
            )
            characters = await flow.generate_characters(
                theme, user_prompt=preset.characters, imported_characters=[]
            )

            save = await flow.build_initial_save(
                theme=theme,
                tone=tone,
                narration_style=preset.narration_style,
                characters=characters,
                art_style=preset.art_style,
                target_major_beats=preset.target_major_beats,
                reader_level=preset.reader_level,
                pacing=preset.pacing,
            )
        except Exception as exc:
            self.notify(f"Failed: {exc}", severity="error", timeout=10)
            return

        await app._start_game(save)  # type: ignore[attr-defined]

    def action_back(self) -> None:
        self.app.pop_screen()  # pyright: ignore[reportUnknownMemberType]

    DEFAULT_CSS = """
    PresetPickerScreen #preset-screen-container {
        align: center middle;
        width: 100%;
        height: 100%;
        padding: 1 4;
    }
    PresetPickerScreen #preset-screen-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    PresetPickerScreen .preset-card {
        padding: 1;
        margin-bottom: 1;
        background: $surface-lighten-1;
    }
    PresetPickerScreen .preset-card:hover {
        background: $accent-darken-2;
    }
    """
