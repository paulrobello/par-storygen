"""Smoke tests for GraphScreen — tree composition, markers, and selection."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from storygen.llm.models import (
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.screens.graph import GraphScreen
from storygen.screens.replay import ReplayScreen
from storygen.storage.save import GameSave


def _root_save(*, choices: list[StoredChoice] | None = None) -> GameSave:
    """Build a GameSave with only a root node (and the given choice list)."""
    if choices is None:
        choices = [
            StoredChoice(id="c1", text="open the door"),
            StoredChoice(id="c2", text="check the window"),
        ]
    root = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="You wake in a dim room. Dust motes drift through pale light.",
        choices=choices,
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
    choices: list[StoredChoice] | None = None,
    is_major: bool = False,
    is_ending: bool = False,
) -> StoryNode:
    return StoryNode(
        id=node_id,
        parent_id=parent_id,
        chosen_choice_id=chosen_choice_id,
        chosen_at=datetime.now(UTC),
        narration=narration,
        choices=choices or [],
        is_major=is_major,
        is_ending=is_ending,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )


class _Harness(App[None]):
    def __init__(
        self,
        save: GameSave,
        on_select: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self._save = save
        self._selected: list[str] = []
        self._cb: Callable[[str], None] = on_select or (lambda nid: self._selected.append(nid))

    def on_mount(self) -> None:
        self.push_screen(GraphScreen(self._save, on_node_selected=self._cb))

    def compose(self) -> ComposeResult:
        yield from []


def _walk(node: TreeNode[dict[str, object]]) -> list[TreeNode[dict[str, object]]]:
    """Return the node and all descendants in DFS order."""
    out: list[TreeNode[dict[str, object]]] = [node]
    for child in node.children:
        out.extend(_walk(child))
    return out


@pytest.mark.asyncio
async def test_graph_screen_shows_root_only() -> None:
    save = _root_save()
    app = _Harness(save)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GraphScreen)
        tree = cast(Tree[dict[str, object]], screen.query_one(Tree))
        all_nodes = _walk(tree.root)
        # Root is the single visited node; the other 2 entries are unexplored.
        visited = [n for n in all_nodes if (n.data or {}).get("node_id")]
        unexplored = [n for n in all_nodes if (n.data or {}).get("unexplored")]
        assert len(visited) == 1
        assert len(unexplored) == len(save.nodes["root"].choices)


@pytest.mark.asyncio
async def test_graph_screen_lists_visited_descendants() -> None:
    save = _root_save()
    # Wire choice c1 → child node; leave c2 unexplored.
    save.nodes["root"].choices[0].child_node_id = "child"
    save.nodes["child"] = _make_child(
        "child",
        parent_id="root",
        chosen_choice_id="c1",
        narration="You step into a humming corridor.",
    )

    app = _Harness(save)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GraphScreen)
        tree = cast(Tree[dict[str, object]], screen.query_one(Tree))
        all_nodes = _walk(tree.root)
        visited = [n for n in all_nodes if (n.data or {}).get("node_id")]
        unexplored = [n for n in all_nodes if (n.data or {}).get("unexplored")]
        # Root + 1 visited child; one unexplored sibling choice.
        assert len(visited) == 2
        assert len(unexplored) == 1
        # Root is current, so its label has the → marker.
        root_label = str(tree.root.label)
        assert root_label.startswith("→")


@pytest.mark.asyncio
async def test_graph_screen_callback_fires_with_node_id() -> None:
    save = _root_save()
    save.nodes["root"].choices[0].child_node_id = "child"
    save.nodes["child"] = _make_child(
        "child",
        parent_id="root",
        chosen_choice_id="c1",
        narration="A second beat.",
    )

    received: list[str] = []
    app = _Harness(save, on_select=lambda nid: received.append(nid))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GraphScreen)
        tree = cast(Tree[dict[str, object]], screen.query_one(Tree))
        # Find the visited child TreeNode by node_id and simulate selecting it.
        target = next(n for n in _walk(tree.root) if (n.data or {}).get("node_id") == "child")
        screen.on_tree_node_selected(Tree.NodeSelected(target))
        assert received == ["child"]


@pytest.mark.asyncio
async def test_replay_binding_present() -> None:
    """`r` is registered in GraphScreen BINDINGS so the footer + key route work."""
    keys = [b[0] for b in GraphScreen.BINDINGS]
    assert "r" in keys


@pytest.mark.asyncio
async def test_action_replay_pushes_replay_screen() -> None:
    """With a node highlighted, action_replay pushes ReplayScreen with target=node_id."""
    save = _root_save()
    save.nodes["root"].choices[0].child_node_id = "child"
    save.nodes["child"] = _make_child(
        "child",
        parent_id="root",
        chosen_choice_id="c1",
        narration="A second beat.",
    )

    app = _Harness(save)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GraphScreen)
        tree = cast(Tree[dict[str, object]], screen.query_one(Tree))
        target = next(n for n in _walk(tree.root) if (n.data or {}).get("node_id") == "child")
        tree.move_cursor(target)
        await pilot.pause()
        screen.action_replay()
        await pilot.pause()
        replay = app.screen
        assert isinstance(replay, ReplayScreen)
        assert replay._target_node_id == "child"  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_action_replay_with_unexplored_cursor_notifies_warning() -> None:
    """Cursor on an unexplored leaf triggers a warning notification, no push."""
    save = _root_save()
    app = _Harness(save)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GraphScreen)
        tree = cast(Tree[dict[str, object]], screen.query_one(Tree))
        # Move cursor to first unexplored child of root.
        unexplored = next(n for n in _walk(tree.root) if (n.data or {}).get("unexplored"))
        tree.move_cursor(unexplored)
        await pilot.pause()
        screen.action_replay()
        await pilot.pause()
        # Still on GraphScreen (no push happened).
        assert isinstance(app.screen, GraphScreen)


@pytest.mark.asyncio
async def test_replay_jump_callback_invokes_node_selected() -> None:
    """ReplayScreen's on_jump_to_live should route through GraphScreen._jump_to."""
    save = _root_save()
    save.nodes["root"].choices[0].child_node_id = "child"
    save.nodes["child"] = _make_child(
        "child",
        parent_id="root",
        chosen_choice_id="c1",
        narration="A second beat.",
    )
    received: list[str] = []
    app = _Harness(save, on_select=received.append)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GraphScreen)
        tree = cast(Tree[dict[str, object]], screen.query_one(Tree))
        target = next(n for n in _walk(tree.root) if (n.data or {}).get("node_id") == "child")
        tree.move_cursor(target)
        await pilot.pause()
        screen.action_replay()
        await pilot.pause()
        replay = app.screen
        assert isinstance(replay, ReplayScreen)
        # Advance to the branch terminus before jumping; jump-to-live uses the
        # cursor node, not the original target.
        replay.action_next()
        await pilot.pause()
        replay.action_jump_to_live()
        await pilot.pause()
        assert received == ["child"]


@pytest.mark.asyncio
async def test_prune_binding_present() -> None:
    """`p` is registered in GraphScreen BINDINGS."""
    keys = [b[0] for b in GraphScreen.BINDINGS]
    assert "p" in keys


@pytest.mark.asyncio
async def test_action_prune_root_shows_warning() -> None:
    """Pruning root shows a warning and does nothing."""
    save = _root_save()
    app = _Harness(save)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GraphScreen)
        screen.action_prune()
        await pilot.pause()
        assert isinstance(app.screen, GraphScreen)
        assert "root" in save.nodes


@pytest.mark.asyncio
async def test_action_prune_unexplored_shows_warning() -> None:
    """Pruning an unexplored leaf shows a warning."""
    save = _root_save()
    app = _Harness(save)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GraphScreen)
        tree = cast(Tree[dict[str, object]], screen.query_one(Tree))
        unexplored = next(n for n in _walk(tree.root) if (n.data or {}).get("unexplored"))
        tree.move_cursor(unexplored)
        await pilot.pause()
        screen.action_prune()
        await pilot.pause()
        assert isinstance(app.screen, GraphScreen)


@pytest.mark.asyncio
async def test_action_prune_with_visited_node_pushes_confirm() -> None:
    """Pruning a visited node pushes a Confirm dialog."""
    save = _root_save()
    save.nodes["root"].choices[0].child_node_id = "child"
    save.nodes["child"] = _make_child(
        "child",
        parent_id="root",
        chosen_choice_id="c1",
        narration="A second beat.",
    )
    app = _Harness(save)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GraphScreen)
        tree = cast(Tree[dict[str, object]], screen.query_one(Tree))
        target = next(n for n in _walk(tree.root) if (n.data or {}).get("node_id") == "child")
        tree.move_cursor(target)
        await pilot.pause()
        screen.action_prune()
        await pilot.pause()
        # ConfirmModal is pushed as a screen on top of GraphScreen.
        from storygen.screens._confirm_modal import ConfirmModal

        current = app.screen
        assert isinstance(current, ConfirmModal)
