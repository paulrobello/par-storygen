"""Unit tests for the extracted wizard confirm-summary builder (ARC-012/QA-006).

Exercises the pure summary string construction — especially the branched
tone formatting — without a Textual Screen. The screen-side widget update
is covered by ``test_wizard_screen.py``.
"""

from __future__ import annotations

from storygen.core.models import Character, Theme, Tone
from storygen.screens.controllers.wizard_summary import build_confirm_summary


def _char(name: str) -> Character:
    return Character(
        id=name.lower(),
        name=name,
        backstory="...",
        personality="bold",
        physical_description="tall",
        introduced_at_node_id="root",
    )


def test_summary_renders_all_fields() -> None:
    summary = build_confirm_summary(
        theme=Theme(title="The Cavern", setting="s", premise="p", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        style="third_person",
        art_style="watercolor",
        target_major_beats=8,
        reader_label="Ages 6-10",
        characters=[_char("Mira"), _char("Jorn")],
    )
    assert "Theme: The Cavern" in summary
    assert "Tone: serious" in summary
    assert "Style: third_person" in summary
    assert "Art: watercolor" in summary
    assert "Length: 8 beats" in summary
    assert "Reader level: Ages 6-10" in summary
    assert "Cast: Mira, Jorn" in summary


def test_summary_no_theme_and_no_characters() -> None:
    summary = build_confirm_summary(
        theme=None,
        tone=None,
        style="first_person",
        art_style="",
        target_major_beats=5,
        reader_label="Ages 11-15",
        characters=[],
    )
    assert "Theme: \n" in summary
    assert "Tone: \n" in summary
    assert "Cast: (no characters yet)" in summary


def test_tone_custom_format() -> None:
    summary = build_confirm_summary(
        theme=None,
        tone=Tone(preset="custom", custom_descriptor="spooky and warm"),
        style="third_person",
        art_style="",
        target_major_beats=5,
        reader_label="Adults",
        characters=[],
    )
    assert "Tone: custom: spooky and warm" in summary


def test_tone_preset_with_descriptor_format() -> None:
    summary = build_confirm_summary(
        theme=None,
        tone=Tone(preset="serious", custom_descriptor="dark"),
        style="third_person",
        art_style="",
        target_major_beats=5,
        reader_label="Adults",
        characters=[],
    )
    assert "Tone: serious (dark)" in summary
