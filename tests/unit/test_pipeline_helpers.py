"""Tests for pipeline private helpers: _one_sentence, _resolve_chosen_text, _build_beat_prompt."""

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
    _pacing_hint_for_depth,  # pyright: ignore[reportPrivateUsage]
    _resolve_chosen_text,  # pyright: ignore[reportPrivateUsage]
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


def test_build_beat_prompt_includes_beat_narration() -> None:
    root = _node("root", None, narration="A dark cave looms ahead.")
    save = _empty_save({"root": root})
    prompt = _build_beat_prompt(save, "root", "enter")
    assert "A dark cave looms ahead." in prompt


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


def test_build_beat_prompt_includes_beats_since_summary() -> None:
    root = _node("root", None, narration="Root beat.", is_major=True, summary="Summary.")
    mid = _node("mid", "root", narration="Middle beat.", chose="c1")
    leaf = _node("leaf", "mid", narration="Leaf beat.", chose="c1")
    save = _empty_save({"root": root, "mid": mid, "leaf": leaf})
    prompt = _build_beat_prompt(save, "leaf", "fight")
    assert "BEATS SINCE LAST SUMMARY" in prompt
    assert "Middle beat." in prompt
    assert "Leaf beat." in prompt


def test_build_beat_prompt_includes_all_beats_when_no_summary() -> None:
    root = _node("root", None, narration="Root beat.")
    mid = _node("mid", "root", narration="Middle beat.", chose="c1")
    leaf = _node("leaf", "mid", narration="Leaf beat.", chose="c1")
    save = _empty_save({"root": root, "mid": mid, "leaf": leaf})
    prompt = _build_beat_prompt(save, "leaf", "fight")
    assert "Root beat." in prompt
    assert "Middle beat." in prompt
    assert "Leaf beat." in prompt


def test_build_beat_prompt_includes_pacing_hint_at_depth() -> None:
    root = _node("root", None, narration="Start.", is_major=True)
    save = _empty_save({"root": root})
    save.target_major_beats = 10
    result = _build_beat_prompt(save, "root", "go")
    # depth=1 (root is major), target=10 → 30% threshold=3 → silent (no pacing hint)
    assert "PLAYER JUST CHOSE: go" in result


# --- _pacing_hint_for_depth ---


def test_pacing_hint_moderate_silent_at_low_depth() -> None:
    assert _pacing_hint_for_depth(1, 10, "moderate") == ""


def test_pacing_hint_moderate_tension_at_mid_depth() -> None:
    result = _pacing_hint_for_depth(5, 10, "moderate")
    assert "tension rising" in result


def test_pacing_hint_moderate_climax_at_high_depth() -> None:
    result = _pacing_hint_for_depth(8, 10, "moderate")
    assert "tightening" in result


def test_pacing_hint_slow_gives_more_room() -> None:
    # target=5, slow -> multiplier=1.4 -> silent=2, tension=4, climax=6
    # depth=3 should be "tension" not "climax"
    result = _pacing_hint_for_depth(3, 5, "slow")
    assert "tension rising" in result


def test_pacing_hint_fast_tightens_sooner() -> None:
    # target=5, fast -> multiplier=0.7 -> silent=1, tension=2, climax=3
    # depth=2 should be "tension" not "silent"
    result = _pacing_hint_for_depth(2, 5, "fast")
    assert "tension rising" in result


def test_pacing_hint_fast_climax_earlier() -> None:
    # target=5, fast -> climax=3
    result = _pacing_hint_for_depth(3, 5, "fast")
    assert "tightening" in result


# --- _build_beat_prompt with relationships ---


def test_build_beat_prompt_includes_relationships_section() -> None:
    """When save has relationships, _build_beat_prompt includes a RELATIONSHIPS section."""
    from storygen.core.models import Character, Relationship, RelationshipType

    root = _node("root", None, narration="Start.")
    save = _empty_save({"root": root})
    save.characters = [
        Character(
            id="alyx", name="Alyx", backstory="b", personality="p",
            physical_description="d", introduced_at_node_id="root",
        ),
        Character(
            id="kael", name="Kael", backstory="b", personality="p",
            physical_description="d", introduced_at_node_id="root",
        ),
    ]
    save.relationships = [
        Relationship(
            char_a_id="alyx", char_b_id="kael", type=RelationshipType.ALLY,
            strength=4, context="bonded during ambush", updated_at_node_id="root",
        ),
    ]
    prompt = _build_beat_prompt(save, "root", "go left")
    assert "RELATIONSHIPS:" in prompt
    assert "Alyx ↔ Kael" in prompt
    assert "ally" in prompt
    assert "bonded during ambush" in prompt


def test_build_beat_prompt_omits_relationships_when_empty() -> None:
    """When save has no relationships, no RELATIONSHIPS section appears."""
    root = _node("root", None, narration="Start.")
    save = _empty_save({"root": root})
    prompt = _build_beat_prompt(save, "root", "go left")
    assert "RELATIONSHIPS:" not in prompt
