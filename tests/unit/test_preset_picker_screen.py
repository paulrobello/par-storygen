"""Quick Start screen: clicking a preset card launches that preset."""

from __future__ import annotations

from typing import ClassVar

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from storygen.core.presets import StoryPreset, load_all_presets
from storygen.screens.preset_picker import PresetPickerScreen


class _Harness(App[None]):
    """Pushes the picker like the app does (screens yielded in App.compose
    mount as plain widgets inside a default Screen; screen-level handlers
    such as on_click never fire there)."""

    captured: ClassVar[list[StoryPreset]] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Footer()

    def on_mount(self) -> None:
        self.push_screen(PresetPickerScreen())


@pytest.mark.asyncio
async def test_click_preset_card_launches_that_preset(
    xdg_tmp: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    presets = load_all_presets()
    assert presets, "expected bundled curated presets"

    captured: list[StoryPreset] = []

    def _fake_launch(self: PresetPickerScreen, preset: StoryPreset) -> None:
        captured.append(preset)

    monkeypatch.setattr(PresetPickerScreen, "_launch", _fake_launch)

    app = _Harness()
    async with app.run_test() as pilot:
        cards = app.screen.query(".preset-card")
        assert len(cards) == len(presets)
        await pilot.click(".preset-card")

    assert captured == [presets[0]]
