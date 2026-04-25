"""Tests for CreateCharacterModal."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button

from storygen.screens._create_char_modal import CreateCharacterModal, CreateCharRequest


class _ModalHarness(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.result: object = "<unset>"

    def on_mount(self) -> None:
        def _cap(r: object) -> None:
            self.result = r

        self.push_screen(CreateCharacterModal(), _cap)

    def compose(self) -> ComposeResult:
        yield from []


@pytest.mark.asyncio
async def test_create_button_disabled_when_empty() -> None:
    app = _ModalHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        btn = app.screen.query_one("#create-char-generate", Button)
        assert btn.disabled is True


@pytest.mark.asyncio
async def test_cancel_dismisses_with_none() -> None:
    app = _ModalHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#create-char-cancel")
        await pilot.pause()
    assert app.result is None


@pytest.mark.asyncio
async def test_escape_dismisses_with_none() -> None:
    app = _ModalHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None


def test_create_char_request_model() -> None:
    req = CreateCharRequest(name="Merlin", concept="an old wizard")
    assert req.name == "Merlin"
    assert req.concept == "an old wizard"


def test_create_char_request_name_optional() -> None:
    req = CreateCharRequest(name="", concept="a brave knight")
    assert req.name == ""
