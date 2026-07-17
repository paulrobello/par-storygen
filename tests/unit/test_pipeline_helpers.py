"""Tests for pipeline private helpers: _one_sentence, _resolve_chosen_text, _build_beat_prompt."""

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
from storygen.core.models import one_sentence as _one_sentence
from storygen.pipeline_prompts import (
    build_beat_prompt as _build_beat_prompt,
)
from storygen.pipeline_prompts import (
    pacing_hint_for_depth as _pacing_hint_for_depth,
)
from storygen.pipeline_prompts import (
    resolve_chosen_text as _resolve_chosen_text,
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
    # root's is_major=True is excluded from the count, so depth=0,
    # target=10 → 30% threshold=3 → silent (no pacing hint)
    assert "PLAYER JUST CHOSE: go" in result


def test_build_beat_prompt_root_blurb_excluded_from_major_count() -> None:
    """Root's is_major=True (marketing blurb) must not inflate major_so_far.

    A naive ``sum(1 for n in full_chain if n.is_major)`` count would include
    the root, reaching depth=2 at this small target and crossing into the
    tension tier. The corrected (root-excluded) count stops at depth=1 and
    stays silent.
    """
    root = _node("root", None, narration="Blurb.", is_major=True)
    beat = _node("beat", "root", narration="First real beat.", chose="c1", is_major=True)
    save = _empty_save({"root": root, "beat": beat})
    save.target_major_beats = 4  # moderate: silent<=1, tension<=2
    prompt = _build_beat_prompt(save, "beat", "go")
    assert "Keep tension rising" not in prompt
    assert "Progress:" not in prompt
    # sanity: the naive root-inclusive depth of 2 would have been tension tier
    assert "tension rising" in _pacing_hint_for_depth(2, 4, "moderate")


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


def test_pacing_hint_climax_mentions_central_conflict_choice() -> None:
    result = _pacing_hint_for_depth(9, 10, "moderate")
    assert "drive directly at the central conflict" in result


def test_pacing_hint_resolve_mentions_resolution_choice() -> None:
    result = _pacing_hint_for_depth(11, 10, "moderate")
    assert "leads directly to resolution" in result


def test_pacing_hint_runaway_guard_forces_resolve_tier() -> None:
    # target=5, moderate -> guard_climax=15, guard_resolve=20; total_beats=21
    # exceeds guard_resolve, so the resolve tier fires regardless of depth.
    result = _pacing_hint_for_depth(1, 5, "moderate", total_beats=21)
    assert "leads directly to resolution" in result


def test_pacing_hint_runaway_guard_forces_at_least_climax_tier() -> None:
    # total_beats=16 exceeds guard_climax (15) but not guard_resolve (20), so
    # the tier is forced up to at least climax even though depth alone (1)
    # would be silent.
    result = _pacing_hint_for_depth(1, 5, "moderate", total_beats=16)
    assert "drive directly at the central conflict" in result


# --- _build_beat_prompt with relationships ---


def test_build_beat_prompt_includes_relationships_section() -> None:
    """When save has relationships, _build_beat_prompt includes a RELATIONSHIPS section."""
    from storygen.core.models import Character, Relationship, RelationshipType

    root = _node("root", None, narration="Start.")
    save = _empty_save({"root": root})
    save.characters = [
        Character(
            id="alyx",
            name="Alyx",
            backstory="b",
            personality="p",
            physical_description="d",
            introduced_at_node_id="root",
        ),
        Character(
            id="kael",
            name="Kael",
            backstory="b",
            personality="p",
            physical_description="d",
            introduced_at_node_id="root",
        ),
    ]
    save.relationships = [
        Relationship(
            char_a_id="alyx",
            char_b_id="kael",
            type=RelationshipType.ALLY,
            strength=4,
            context="bonded during ambush",
            updated_at_node_id="root",
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


# --- _build_beat_prompt CAST dedup ---


def test_build_beat_prompt_cast_backstory_not_duplicated() -> None:
    """The first sentence of a full backstory must not also appear in the one-liner."""
    from storygen.core.models import Character

    root = _node("root", None, narration="Start.")
    save = _empty_save({"root": root})
    save.characters = [
        Character(
            id="alyx",
            name="Alyx",
            backstory="Alyx grew up in the wastes. She learned to fight early.",
            personality="p",
            physical_description="d",
            introduced_at_node_id="root",
        ),
    ]
    prompt = _build_beat_prompt(save, "root", "go")
    assert prompt.count("Alyx grew up in the wastes.") == 1
    assert "Backstory: Alyx grew up in the wastes. She learned to fight early." in prompt


def test_build_beat_prompt_cast_uses_summary_fragment_when_backstory_empty() -> None:
    """A character with no full backstory still gets its backstory_summary fragment."""
    from storygen.core.models import Character

    root = _node("root", None, narration="Start.")
    save = _empty_save({"root": root})
    save.characters = [
        Character(
            id="alyx",
            name="Alyx",
            backstory="",
            backstory_summary="A wanderer with no home.",
            personality="p",
            physical_description="d",
            introduced_at_node_id="root",
        ),
    ]
    prompt = _build_beat_prompt(save, "root", "go")
    assert "A wanderer with no home." in prompt
    assert "Backstory:" not in prompt


# --- _build_beat_prompt opening blurb label ---


def test_build_beat_prompt_labels_opening_blurb_not_other_beats() -> None:
    """Root's narration is marked as marketing copy; other beats are unlabeled."""
    root = _node("root", None, narration="Buy this book now!", is_major=True)
    mid = _node("mid", "root", narration="A real beat.", chose="c1")
    save = _empty_save({"root": root, "mid": mid})
    prompt = _build_beat_prompt(save, "mid", "go")
    assert "- [Opening blurb — marketing copy, not in-story narration] Buy this book now!" in prompt
    assert "- A real beat." in prompt
    assert prompt.count("[Opening blurb") == 1
