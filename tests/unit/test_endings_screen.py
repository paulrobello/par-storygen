"""Smoke tests for EndingsScreen — empty/populated state, jump callback, breadcrumb."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from storygen.llm.models import (
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.screens.endings import EndingsScreen
from storygen.storage.save import GameSave


def _static_texts(screen: object) -> list[str]:
    """Return the rendered text of every Static widget on ``screen``.

    Uses ``Static.render()`` which works across Textual versions where the
    deprecated ``renderable`` attribute is not exposed. Wraps each call in
    try/except so a Pixels-rendered thumbnail (which renders to something
    non-stringifiable) doesn't break the test.
    """
    out: list[str] = []
    for s in screen.query(Static):  # type: ignore[attr-defined]
        try:
            rendered = cast(object, s.render())  # pyright: ignore[reportUnknownMemberType]
            out.append(str(rendered))
        except Exception:
            continue
    return out


def _root_save() -> GameSave:
    """Build a minimal GameSave with only a root node and no endings."""
    root = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="You wake in a dim room.",
        choices=[
            StoredChoice(id="c1", text="open the door"),
            StoredChoice(id="c2", text="check the window"),
        ],
        is_major=True,
        is_ending=False,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    return GameSave(
        version=1,
        id=uuid4(),
        theme=Theme(title="t", setting="s", premise="p", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        characters=[],
        nodes={"root": root},
        root_node_id="root",
        current_node_id="root",
        endings_reached=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_child(
    node_id: str,
    *,
    parent_id: str,
    chosen_choice_id: str,
    narration: str = "Beat narration.",
    is_ending: bool = False,
    image_path: str | None = None,
) -> StoryNode:
    return StoryNode(
        id=node_id,
        parent_id=parent_id,
        chosen_choice_id=chosen_choice_id,
        chosen_at=datetime.now(UTC),
        narration=narration,
        choices=[],
        is_major=False,
        is_ending=is_ending,
        image_prompt=None,
        image_path=image_path,
        image_status="done" if image_path else "not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )


def _save_with_endings(n: int) -> GameSave:
    """Build a save with `n` ending nodes hanging off the root via choices."""
    save = _root_save()
    # Ensure root has enough choices to wire up to each ending.
    extra: list[StoredChoice] = [StoredChoice(id=f"ec{i}", text=f"path {i}") for i in range(n)]
    save.nodes["root"].choices.extend(extra)
    for i in range(n):
        ending_id = f"end{i}"
        save.nodes["root"].choices[2 + i].child_node_id = ending_id
        save.nodes[ending_id] = _make_child(
            ending_id,
            parent_id="root",
            chosen_choice_id=f"ec{i}",
            narration=f"And so it ended in scenario {i}.",
            is_ending=True,
        )
        save.endings_reached.append(ending_id)
    return save


class _Harness(App[None]):
    def __init__(
        self,
        save: GameSave,
        on_jump: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self._save = save
        self._jumped: list[str] = []
        self._cb: Callable[[str], None] = on_jump or (lambda nid: self._jumped.append(nid))

    def on_mount(self) -> None:
        self.push_screen(EndingsScreen(self._save, on_jump=self._cb))

    def compose(self) -> ComposeResult:
        yield from []


@pytest.mark.asyncio
async def test_empty_state_renders_when_no_endings() -> None:
    save = _root_save()
    app = _Harness(save)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, EndingsScreen)
        texts = _static_texts(screen)
        assert any("No endings reached yet" in t for t in texts)


@pytest.mark.asyncio
async def test_populated_state_renders_one_card_per_ending() -> None:
    save = _save_with_endings(3)
    app = _Harness(save)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, EndingsScreen)
        jump_buttons = [b for b in screen.query(Button) if (b.id or "").startswith("jump-")]
        assert len(jump_buttons) == 3


@pytest.mark.asyncio
async def test_jump_button_invokes_callback_and_dismisses() -> None:
    save = _save_with_endings(2)
    received: list[str] = []
    app = _Harness(save, on_jump=received.append)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, EndingsScreen)
        target_id = save.endings_reached[0]
        button = next(b for b in screen.query(Button) if b.id == f"jump-{target_id}")
        await pilot.click(button)
        await pilot.pause()
        assert received == [target_id]
        # Screen should be dismissed — no longer the active screen.
        assert not isinstance(app.screen, EndingsScreen)


@pytest.mark.asyncio
async def test_breadcrumb_uses_path_from_root() -> None:
    save = _save_with_endings(1)
    app = _Harness(save)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, EndingsScreen)
        breadcrumb_texts = _static_texts(screen)
        # The choice text used to wire ending 0 was "path 0".
        assert any("path 0" in t for t in breadcrumb_texts)


@pytest.mark.asyncio
async def test_image_missing_renders_no_image_placeholder() -> None:
    save = _save_with_endings(1)
    # The single ending has image_path=None by default; assert thumbnail is hidden.
    app = _Harness(save)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, EndingsScreen)
        texts = _static_texts(screen)
        assert not any("[no image]" in t for t in texts)


@pytest.mark.asyncio
async def test_jump_callback_receives_correct_node_id_for_later_ending() -> None:
    save = _save_with_endings(3)
    received: list[str] = []
    app = _Harness(save, on_jump=received.append)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, EndingsScreen)
        target_id = save.endings_reached[2]
        button = next(b for b in screen.query(Button) if b.id == f"jump-{target_id}")
        # Off-screen buttons can't be reached via pilot.click(); invoke the
        # screen handler directly with a synthesized Pressed event instead.
        screen.on_button_pressed(Button.Pressed(button))
        await pilot.pause()
        assert received == [target_id]
