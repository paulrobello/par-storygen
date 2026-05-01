"""Unit tests for LLM system prompt templates."""

from __future__ import annotations

from storygen.llm.models import Character, Theme, Tone
from storygen.llm.prompts import (
    adapt_backstory_system_prompt,
    beat_system_prompt,
    blurb_system_prompt,
    character_system_prompt,
    theme_system_prompt,
)


def test_theme_prompt_asks_for_three_options() -> None:
    out = theme_system_prompt()
    assert "three" in out.lower()


def test_character_prompt_mentions_physical_description() -> None:
    theme = Theme(title="t", setting="s", premise="p", keywords=[])
    out = character_system_prompt(theme)
    assert "physical description" in out.lower()


def test_beat_prompt_injects_tone_and_style() -> None:
    theme = Theme(title="Neon", setting="City", premise="Heist", keywords=["cyberpunk"])
    tone = Tone(preset="serious", custom_descriptor="with dark humor")
    out = beat_system_prompt(theme=theme, tone=tone, narration_style="fourth_wall")
    assert "serious" in out.lower()
    assert "dark humor" in out.lower()
    assert "fourth" in out.lower()


def test_beat_prompt_custom_tone_descriptor_required_present() -> None:
    theme = Theme(title="t", setting="s", premise="p", keywords=[])
    tone = Tone(preset="custom", custom_descriptor="whimsically ominous")
    out = beat_system_prompt(theme=theme, tone=tone, narration_style="first_person")
    assert "whimsically ominous" in out.lower()


def test_beat_prompt_uses_target_major_beats() -> None:
    """The pacing wording reflects the per-save target, not a hardcoded range."""
    theme = Theme(title="t", setting="s", premise="p", keywords=[])
    tone = Tone(preset="serious", custom_descriptor=None)
    out = beat_system_prompt(
        theme=theme, tone=tone, narration_style="third_person", target_major_beats=15
    )
    assert "15" in out
    # Stale hardcoded wording must be gone.
    assert "6-12" not in out
    assert "beat 8+" not in out
    # New tightening threshold should be max(target - 2, 4) = 13 here.
    assert "beat 13+" in out


def test_beat_prompt_default_target_is_five() -> None:
    theme = Theme(title="t", setting="s", premise="p", keywords=[])
    tone = Tone(preset="serious", custom_descriptor=None)
    out = beat_system_prompt(theme=theme, tone=tone, narration_style="third_person")
    assert "5" in out
    assert "6-12" not in out


def test_beat_prompt_includes_reader_level_guidance() -> None:
    theme = Theme(title="t", setting="s", premise="p", keywords=[])
    tone = Tone(preset="serious", custom_descriptor=None)
    out = beat_system_prompt(
        theme=theme, tone=tone, narration_style="third_person", reader_level="ages_0_5"
    )
    assert "simple vocabulary" in out.lower()
    assert "max 8 words" in out.lower()


def test_beat_prompt_reader_level_ages_15_plus_no_restrictions() -> None:
    theme = Theme(title="t", setting="s", premise="p", keywords=[])
    tone = Tone(preset="serious", custom_descriptor=None)
    out = beat_system_prompt(
        theme=theme, tone=tone, narration_style="third_person", reader_level="ages_15_plus"
    )
    assert "no reading-level restrictions" in out.lower()


def test_beat_system_prompt_contains_continuation_rules() -> None:
    """Static continuation directives should live in the system prompt."""
    theme = Theme(title="t", setting="s", premise="p", keywords=[])
    tone = Tone(preset="serious", custom_descriptor=None)
    out = beat_system_prompt(theme=theme, tone=tone, narration_style="third_person")
    assert "stay consistent with the cast" in out.lower()


def test_beat_system_prompt_contains_style_reminder() -> None:
    """Style reminder should be baked into the system prompt for fourth_wall."""
    theme = Theme(title="t", setting="s", premise="p", keywords=[])
    tone = Tone(preset="serious", custom_descriptor=None)
    out = beat_system_prompt(theme=theme, tone=tone, narration_style="fourth_wall")
    assert "fourth-wall voice" in out.lower()


def test_blurb_prompt_includes_theme_and_characters() -> None:
    theme = Theme(
        title="The Hollow Crown",
        setting="A crumbling kingdom.",
        premise="An heir vanishes on coronation eve.",
        keywords=["intrigue"],
    )
    char1 = Character(
        id="c1",
        name="Aurelia",
        backstory="b",
        personality="Sharp-witted and patient. Slow to trust.",
        physical_description="d",
        introduced_at_node_id="root",
    )
    char2 = Character(
        id="c2",
        name="Borin",
        backstory="b",
        personality="Loyal to a fault. Wields a notched axe.",
        physical_description="d",
        introduced_at_node_id="root",
    )
    out = blurb_system_prompt(theme, [char1, char2])
    assert "Aurelia" in out
    assert "Borin" in out
    assert "The Hollow Crown" in out


def test_adapt_backstory_prompt_forbids_identity_changes() -> None:
    """Hard constraints on name/personality/physical description are present."""
    theme = Theme(
        title="Neon Tokyo",
        setting="A sprawling cyberpunk metropolis.",
        premise="Megacorps hunt a rogue AI.",
        keywords=["cyberpunk"],
    )
    out = adapt_backstory_system_prompt(theme)
    lower = out.lower()
    assert "must not change" in lower
    assert "name" in lower
    assert "personality" in lower
    assert "physical description" in lower
    # The theme is threaded into the prompt so the LLM can rewrite to fit.
    assert "Neon Tokyo" in out
    assert "cyberpunk metropolis" in out
    assert "Megacorps hunt a rogue AI." in out
    # Output-shape guidance — rewrites only the backstory, not a full
    # re-character-sheet.
    assert "backstory" in lower
