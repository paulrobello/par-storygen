"""Tests for tree.children_index."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from storygen.core.models import (
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.storage.save import GameSave
from storygen.storage.tree import children_index


def _node(node_id: str, parent: str | None) -> StoryNode:
    return StoryNode(
        id=node_id,
        parent_id=parent,
        chosen_choice_id=None,
        chosen_at=None,
        narration=f"beat-{node_id}",
        choices=[StoredChoice(id="c1", text="next")],
        is_major=False,
        is_ending=False,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )


def _empty_save(nodes: dict[str, StoryNode]) -> GameSave:
    return GameSave(
        version=1,
        id=uuid4(),
        theme=Theme(title="t", setting="s", premise="p", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        characters=[],
        nodes=nodes,
        root_node_id="root",
        current_node_id=list(nodes.keys())[-1],
        endings_reached=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_children_index_builds_parent_map() -> None:
    save = _empty_save(
        {
            "root": _node("root", None),
            "a": _node("a", "root"),
            "b": _node("b", "root"),
            "c": _node("c", "a"),
        }
    )
    idx = children_index(save)
    assert sorted(idx["root"]) == ["a", "b"]
    assert idx["a"] == ["c"]
    assert "b" not in idx  # no children


def test_children_index_empty_for_leaf_only() -> None:
    save = _empty_save({"root": _node("root", None)})
    idx = children_index(save)
    assert idx == {}


def test_children_index_root_absent_when_no_children() -> None:
    save = _empty_save(
        {
            "root": _node("root", None),
            "leaf": _node("leaf", "root"),
        }
    )
    idx = children_index(save)
    assert "leaf" not in idx  # leaf has no children
    assert "root" in idx
