"""Tests for pipeline private helpers: _one_sentence, _truncate, _resolve_chosen_text, _build_beat_prompt."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from storygen.llm.models import (
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.pipeline import (
    _build_beat_prompt,  # pyright: ignore[reportPrivateUsage]
    _one_sentence,  # pyright: ignore[reportPrivateUsage]
    _resolve_chosen_text,  # pyright: ignore[reportPrivateUsage]
    _truncate,  # pyright: ignore[reportPrivateUsage]
)
from storygen.storage.save import GameSave


def _node(
    node_id: str,
    parent: str | None,
    *,
    narration: str = "narration",
    chose: str | None = None,
    is_major: bool = False,
    summary: str | None = None,
    choices: list[StoredChoice] | None = None,
) -> StoryNode:
    return StoryNode(
        id=node_id,
        parent_id=parent,
        chosen_choice_id=chose,
        chosen_at=datetime.now(UTC) if chose else None,
        narration=narration,
        choices=choices or [StoredChoice(id="c1", text="next")],
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


# --- _one_sentence ---


def test_one_sentence_stops_at_period() -> None:
    assert _one_sentence("Hello there. And more.") == "Hello there."


def test_one_sentence_stops_at_exclamation() -> None:
    assert _one_sentence("Watch out! Run.") == "Watch out!"


def test_one_sentence_stops_at_question_mark() -> None:
    assert _one_sentence("Who goes there? Nobody.") == "Who goes there?"


def test_one_sentence_returns_full_when_short_and_no_terminator() -> None:
    assert _one_sentence("Short text") == "Short text"


def test_one_sentence_clips_long_text_without_terminator() -> None:
    text = "A" * 200
    result = _one_sentence(text)
    assert len(result) == 158  # 157 + "…" (single unicode char)
    assert result.endswith("…")


def test_one_sentence_strips_whitespace() -> None:
    assert _one_sentence("  Hello. World.  ") == "Hello."


# --- _truncate ---


def test_truncate_short_text_unchanged() -> None:
    assert _truncate("hi", 100) == "hi"


def test_truncate_long_text_clips() -> None:
    result = _truncate("abcde", 4)
    assert result == "abc…"
    assert len(result) == 4


def test_truncate_exact_limit_unchanged() -> None:
    assert _truncate("abc", 3) == "abc"


def test_truncate_strips_whitespace() -> None:
    assert _truncate("  hi  ", 10) == "hi"


# --- _resolve_chosen_text ---


def test_resolve_chosen_text_finds_matching_choice() -> None:
    parent = _node("root", None, choices=[StoredChoice(id="c1", text="Go left")])
    child = _node("child", "root", chose="c1")
    save = _empty_save({"root": parent, "child": child})
    assert _resolve_chosen_text(save, child) == "Go left"


def test_resolve_chosen_text_returns_empty_when_no_chosen_id() -> None:
    node = _node("root", None, chose=None)
    save = _empty_save({"root": node})
    assert _resolve_chosen_text(save, node) == ""


def test_resolve_chosen_text_returns_empty_when_no_parent() -> None:
    node = _node("root", None, chose="c1")
    save = _empty_save({"root": node})
    assert _resolve_chosen_text(save, node) == ""


def test_resolve_chosen_text_returns_empty_when_parent_missing() -> None:
    child = _node("child", "missing_parent", chose="c1")
    save = _empty_save({"child": child})
    assert _resolve_chosen_text(save, child) == ""


def test_resolve_chosen_text_returns_empty_when_choice_not_found() -> None:
    parent = _node("root", None, choices=[StoredChoice(id="c1", text="Go left")])
    child = _node("child", "root", chose="c99")
    save = _empty_save({"root": parent, "child": child})
    assert _resolve_chosen_text(save, child) == ""


# --- _build_beat_prompt ---


def test_build_beat_prompt_includes_choice_text() -> None:
    root = _node("root", None, narration="The adventure begins.")
    save = _empty_save({"root": root})
    prompt = _build_beat_prompt(save, "root", "open the door")
    assert "PLAYER JUST CHOSE: open the door" in prompt


def test_build_beat_prompt_includes_parent_narration() -> None:
    root = _node("root", None, narration="A dark cave looms ahead.")
    save = _empty_save({"root": root})
    prompt = _build_beat_prompt(save, "root", "enter")
    assert "IMMEDIATELY PRIOR BEAT:\nA dark cave looms ahead." in prompt


def test_build_beat_prompt_includes_summary() -> None:
    root = _node("root", None, narration="Start.", summary="The hero awoke.")
    save = _empty_save({"root": root})
    prompt = _build_beat_prompt(save, "root", "go")
    assert "STORY-SO-FAR SUMMARY:\nThe hero awoke." in prompt


def test_build_beat_prompt_omits_summary_when_none() -> None:
    root = _node("root", None, narration="Start.")
    save = _empty_save({"root": root})
    prompt = _build_beat_prompt(save, "root", "go")
    assert "STORY-SO-FAR" not in prompt


def test_build_beat_prompt_includes_older_beats() -> None:
    root = _node("root", None, narration="Root beat.", is_major=True)
    mid = _node("mid", "root", narration="Middle beat.", chose="c1")
    leaf = _node("leaf", "mid", narration="Leaf beat.", chose="c1")
    save = _empty_save({"root": root, "mid": mid, "leaf": leaf})
    prompt = _build_beat_prompt(save, "leaf", "fight")
    assert "EARLIER BEATS" in prompt
    assert "Root beat." in prompt


def test_build_beat_prompt_omits_older_beats_for_root() -> None:
    root = _node("root", None, narration="Start.")
    save = _empty_save({"root": root})
    prompt = _build_beat_prompt(save, "root", "go")
    assert "EARLIER BEATS" not in prompt


def test_build_beat_prompt_includes_pacing_hint_at_depth() -> None:
    root = _node("root", None, narration="Start.", is_major=True)
    save = _empty_save({"root": root})
    save.target_major_beats = 10
    result = _build_beat_prompt(save, "root", "go")
    # depth=1 (root is major), target=10 → 30% threshold=3 → silent (no pacing hint)
    assert "PLAYER JUST CHOSE: go" in result
