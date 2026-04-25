"""Smoke test: MenuScreen composes the expected buttons."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button

from storygen.screens.menu import MenuScreen


class _Harness(App[None]):
    def compose(self) -> ComposeResult:
        yield MenuScreen()


@pytest.mark.asyncio
async def test_menu_shows_core_options() -> None:
    app = _Harness()
    async with app.run_test() as pilot:
        labels = [str(b.label) for b in app.screen.query(Button)]
        assert "New Story" in labels
        assert "Existing Stories" in labels
        assert "Settings" in labels
        assert "Quit" in labels
        await pilot.pause()
