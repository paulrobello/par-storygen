"""Smoke tests for ReplayScreen — cursor navigation, jump callback, boundary behavior."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from storygen.core.models import (
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.screens.replay import ReplayScreen
from storygen.storage.save import GameSave


def _make_root() -> StoryNode:
    return StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="Root beat narration. You wake in a dim room.",
        choices=[
            StoredChoice(id="c1", text="open the door", child_node_id="n1"),
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


def _make_child(
    node_id: str,
    *,
    parent_id: str,
    chosen_choice_id: str,
    narration: str,
    choices: list[StoredChoice] | None = None,
    image_path: str | None = None,
    is_ending: bool = False,
) -> StoryNode:
    return StoryNode(
        id=node_id,
        parent_id=parent_id,
        chosen_choice_id=chosen_choice_id,
        chosen_at=datetime.now(UTC),
        narration=narration,
        choices=choices or [],
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


def _three_beat_save() -> GameSave:
    """Build a save with root -> n1 -> n2 (3 beats deep)."""
    root = _make_root()
    n1 = _make_child(
        "n1",
        parent_id="root",
        chosen_choice_id="c1",
        narration="Second beat: a humming corridor stretches ahead.",
        choices=[StoredChoice(id="c3", text="press onward", child_node_id="n2")],
    )
    n2 = _make_child(
        "n2",
        parent_id="n1",
        chosen_choice_id="c3",
        narration="Third beat: you reach a quiet courtyard.",
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
        nodes={"root": root, "n1": n1, "n2": n2},
        root_node_id="root",
        current_node_id="n2",
        endings_reached=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class _Harness(App[None]):
    def __init__(
        self,
        save: GameSave,
        target_node_id: str,
        on_jump: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self._save = save
        self._target = target_node_id
        self._jumped: list[str] = []
        self._cb: Callable[[str], None] | None = on_jump
        if self._cb is None:
            self._cb = self._jumped.append

    def on_mount(self) -> None:
        self.push_screen(ReplayScreen(self._save, self._target, on_jump_to_live=self._cb))

    def compose(self) -> ComposeResult:
        yield from []


def _text_of(screen: ReplayScreen, widget_id: str) -> str:
    """Return the rendered text of a Static on `screen` by id.

    Uses Static.content (the underlying string passed to ``update()``); this
    is more reliable than ``render()`` which sometimes returns an empty
    Content depending on Textual version.
    """
    static = screen.query_one(f"#{widget_id}", Static)
    content = cast(object, getattr(static, "content", ""))
    if isinstance(content, str):
        return content
    try:
        return str(cast(object, static.render()))  # pyright: ignore[reportUnknownMemberType]
    except Exception:
        return ""


@pytest.mark.asyncio
async def test_replay_initial_state() -> None:
    """At cursor=0 the root narration + [Beginning] choice marker render."""
    save = _three_beat_save()
    app = _Harness(save, "n2")
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ReplayScreen)
        assert screen._cursor == 0  # pyright: ignore[reportPrivateUsage]
        assert "Root beat narration" in _text_of(screen, "replay-narration")
        assert _text_of(screen, "replay-choice") == "[Beginning]"


@pytest.mark.asyncio
async def test_action_next_advances_cursor_and_rerenders() -> None:
    save = _three_beat_save()
    app = _Harness(save, "n2")
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ReplayScreen)
        screen.action_next()
        await pilot.pause()
        assert screen._cursor == 1  # pyright: ignore[reportPrivateUsage]
        assert "Second beat" in _text_of(screen, "replay-narration")
        # Choice line for non-root beats shows the choice text the user took.
        assert "open the door" in _text_of(screen, "replay-choice")


@pytest.mark.asyncio
async def test_action_next_at_end_does_nothing() -> None:
    save = _three_beat_save()
    app = _Harness(save, "n2")
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ReplayScreen)
        screen.action_next()
        screen.action_next()
        await pilot.pause()
        assert screen._cursor == 2  # pyright: ignore[reportPrivateUsage]
        # Past-end should be a no-op, not raise / advance further.
        screen.action_next()
        screen.action_next()
        await pilot.pause()
        assert screen._cursor == 2  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_action_prev_at_start_does_nothing() -> None:
    save = _three_beat_save()
    app = _Harness(save, "n2")
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ReplayScreen)
        screen.action_prev()
        screen.action_prev()
        await pilot.pause()
        assert screen._cursor == 0  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_jump_to_live_invokes_callback_with_current_path_node() -> None:
    save = _three_beat_save()
    received: list[str] = []
    app = _Harness(save, "n2", on_jump=received.append)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ReplayScreen)
        screen.action_next()
        screen.action_next()
        await pilot.pause()
        assert screen._cursor == 2  # pyright: ignore[reportPrivateUsage]
        screen.action_jump_to_live()
        await pilot.pause()
        assert received == ["n2"]
        # After dismiss, ReplayScreen is no longer the active screen.
        assert not isinstance(app.screen, ReplayScreen)


@pytest.mark.asyncio
async def test_jump_to_live_uses_cursor_node_not_target() -> None:
    """Stepping back then jumping should jump to the cursor's node, not the original target."""
    save = _three_beat_save()
    received: list[str] = []
    app = _Harness(save, "n2", on_jump=received.append)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ReplayScreen)
        screen.action_next()  # cursor=1 -> n1
        await pilot.pause()
        screen.action_jump_to_live()
        await pilot.pause()
        assert received == ["n1"]


@pytest.mark.asyncio
async def test_no_image_renders_placeholder() -> None:
    save = _three_beat_save()
    # Root has image_path=None, so the initial render should hide the image widget.
    app = _Harness(save, "n2")
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ReplayScreen)
        assert _text_of(screen, "replay-image") == ""


@pytest.mark.asyncio
async def test_end_of_branch_hint_visible_at_last_step() -> None:
    save = _three_beat_save()
    app = _Harness(save, "n2")
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ReplayScreen)
        # Pre-end: hint is empty.
        assert _text_of(screen, "replay-end-hint") == ""
        screen.action_next()
        screen.action_next()
        await pilot.pause()
        assert _text_of(screen, "replay-end-hint") == "[End of branch]"


@pytest.mark.asyncio
async def test_choice_line_for_root_is_beginning_marker() -> None:
    save = _three_beat_save()
    app = _Harness(save, "n2")
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ReplayScreen)
        assert _text_of(screen, "replay-choice") == "[Beginning]"


@pytest.mark.asyncio
async def test_jump_callback_none_just_dismisses() -> None:
    """If on_jump_to_live is None, action_jump_to_live silently dismisses."""
    save = _three_beat_save()

    class _NoCbHarness(App[None]):
        def __init__(self) -> None:
            super().__init__()
            self._save = save

        def on_mount(self) -> None:
            self.push_screen(ReplayScreen(self._save, "n2", on_jump_to_live=None))

        def compose(self) -> ComposeResult:
            yield from []

    app = _NoCbHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ReplayScreen)
        screen.action_jump_to_live()
        await pilot.pause()
        assert not isinstance(app.screen, ReplayScreen)
