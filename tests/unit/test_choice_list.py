"""Unit tests for ChoiceList widget rendering."""

from __future__ import annotations

from storygen.llm.models import Choice
from storygen.widgets.choice_list import ChoiceList, format_choice_line


def test_format_choice_line() -> None:
    choice = Choice(id="c1", text="Take the left path")
    assert format_choice_line(1, choice) == "1. Take the left path"


def test_set_choices_renders() -> None:
    panel = ChoiceList()
    panel.set_choices([Choice(id="c1", text="a"), Choice(id="c2", text="b")])
    rendered = panel.renderable
    assert "1. a" in str(rendered)
    assert "2. b" in str(rendered)


def test_clear_empties() -> None:
    panel = ChoiceList()
    panel.set_choices([Choice(id="c1", text="a")])
    panel.clear()
    assert "1. a" not in str(panel.renderable)


def test_choice_for_index_returns_choice() -> None:
    panel = ChoiceList()
    choices = [Choice(id="c1", text="a"), Choice(id="c2", text="b")]
    panel.set_choices(choices)
    assert panel.choice_for_key("1") == choices[0]
    assert panel.choice_for_key("2") == choices[1]
    assert panel.choice_for_key("3") is None
