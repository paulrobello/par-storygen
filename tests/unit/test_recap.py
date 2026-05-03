"""Tests for Recap model, StoryNode.recap_text field, and recap prompt/agent."""

from __future__ import annotations

from datetime import UTC, datetime

from storygen.core.models import Recap, StoryNode

_FIXTURE_DT = datetime(2026, 1, 1, tzinfo=UTC)


def test_recap_model() -> None:
    r = Recap(text="Previously on Test Story...")
    assert "Previously on" in r.text


def test_story_node_recap_text_defaults_none() -> None:
    node = StoryNode(
        id="n1",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="Hello",
        choices=[],
        is_major=False,
        is_ending=False,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=_FIXTURE_DT,
    )
    assert node.recap_text is None


def test_story_node_recap_text_settable() -> None:
    node = StoryNode(
        id="n1",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="Hello",
        choices=[],
        is_major=False,
        is_ending=False,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=_FIXTURE_DT,
    )
    node.recap_text = "Cached recap text"
    assert node.recap_text == "Cached recap text"


def test_recap_system_prompt_content() -> None:
    from storygen.llm.prompts import recap_system_prompt

    prompt = recap_system_prompt()
    assert "Previously on" in prompt
    assert "500 tokens" in prompt
    assert "dramatic" in prompt


def test_build_recap_agent_exists() -> None:
    from storygen.llm.agents import build_recap_agent

    assert callable(build_recap_agent)
