"""Unit tests for CharacterSheet rendering."""

from __future__ import annotations

import io

from rich.console import Console

from storygen.llm.models import Character
from storygen.widgets.character_sheet import CharacterSheet, format_character_entry


def _render(sheet: CharacterSheet) -> str:
    buf = io.StringIO()
    Console(file=buf, force_terminal=False, width=80).print(sheet.renderable)
    return buf.getvalue()


def test_format_character_entry() -> None:
    c = Character(
        id="alyx",
        name="Alyx",
        backstory="b",
        personality="p",
        physical_description="d",
        portrait_path=None,
        portrait_prompt=None,
        introduced_at_node_id="root",
    )
    assert "Alyx" in format_character_entry(c)


def test_set_characters_renders_all() -> None:
    sheet = CharacterSheet()
    sheet.set_characters(
        [
            Character(
                id=f"c{i}",
                name=f"Name{i}",
                backstory="b",
                personality="p",
                physical_description="d",
                portrait_path=None,
                portrait_prompt=None,
                introduced_at_node_id="root",
            )
            for i in range(2)
        ]
    )
    rendered = _render(sheet)
    assert "Name0" in rendered
    assert "Name1" in rendered
