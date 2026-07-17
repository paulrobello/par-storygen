"""Unit tests for story-tree traversal helpers."""

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
from storygen.storage.tree import (
    ancestors,
    children,
    descendants,
    latest_summary,
    path_from_root,
)


def _node(
    node_id: str,
    parent: str | None,
    *,
    chose: str | None = None,
    is_major: bool = False,
    summary: str | None = None,
) -> StoryNode:
    return StoryNode(
        id=node_id,
        parent_id=parent,
        chosen_choice_id=chose,
        chosen_at=datetime.now(UTC) if chose else None,
        narration=f"beat-{node_id}",
        choices=[StoredChoice(id="c1", text="next")],
        is_major=is_major,
        is_ending=False,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=summary,
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


def test_path_from_root_linear() -> None:
    save = _empty_save(
        {
            "root": _node("root", None),
            "a": _node("a", "root", chose="c1"),
            "b": _node("b", "a", chose="c1"),
        }
    )
    path = path_from_root(save, "b")
    assert [n.id for n in path] == ["root", "a", "b"]


def test_ancestors_excludes_self() -> None:
    save = _empty_save(
        {
            "root": _node("root", None),
            "a": _node("a", "root", chose="c1"),
            "b": _node("b", "a", chose="c1"),
        }
    )
    assert [n.id for n in ancestors(save, "b")] == ["a", "root"]


def test_children_returns_only_direct() -> None:
    save = _empty_save(
        {
            "root": _node("root", None),
            "a": _node("a", "root", chose="c1"),
            "b": _node("b", "a", chose="c1"),
            "c": _node("c", "root", chose="c2"),
        }
    )
    assert sorted(n.id for n in children(save, "root")) == ["a", "c"]


def test_latest_summary_walks_ancestors() -> None:
    save = _empty_save(
        {
            "root": _node("root", None, is_major=True, summary="summary-at-root"),
            "a": _node("a", "root", chose="c1"),
            "b": _node("b", "a", chose="c1", is_major=True, summary="summary-at-b"),
            "c": _node("c", "b", chose="c1"),
        }
    )
    assert latest_summary(save, "c") == "summary-at-b"


def test_latest_summary_none_if_no_major_ancestors() -> None:
    save = _empty_save(
        {
            "root": _node("root", None),
            "a": _node("a", "root", chose="c1"),
        }
    )
    assert latest_summary(save, "a") is None


def test_descendants_returns_bfs_order() -> None:
    save = _empty_save(
        {
            "root": _node("root", None),
            "a": _node("a", "root", chose="c1"),
            "b": _node("b", "root", chose="c2"),
            "a1": _node("a1", "a", chose="c1"),
            "a2": _node("a2", "a", chose="c2"),
            "a1x": _node("a1x", "a1", chose="c1"),
        }
    )
    result = descendants(save, "a")
    assert set(result) == {"a", "a1", "a2", "a1x"}
    assert result.index("a") < result.index("a1")


def test_descendants_leaf_returns_self_only() -> None:
    save = _empty_save(
        {
            "root": _node("root", None),
            "a": _node("a", "root", chose="c1"),
        }
    )
    assert descendants(save, "a") == ["a"]


def test_descendants_root_returns_everything() -> None:
    save = _empty_save(
        {
            "root": _node("root", None),
            "a": _node("a", "root", chose="c1"),
            "b": _node("b", "root", chose="c2"),
        }
    )
    assert set(descendants(save, "root")) == {"root", "a", "b"}
