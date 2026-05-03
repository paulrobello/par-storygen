"""Unit tests for ChoiceList widget rendering."""

from __future__ import annotations

from storygen.llm.models import Choice, StoredChoice
from storygen.widgets.choice_list import ChoiceList, format_choice_line


def test_format_choice_line() -> None:
    choice = Choice(id="c1", text="Take the left path")
    assert str(format_choice_line(1, choice)) == "1. Take the left path"


def test_format_choice_line_marks_previously_selected_choice() -> None:
    choice = StoredChoice(id="c1", text="open the door", child_node_id="child-1")

    assert str(format_choice_line(1, choice)) == "1. open the door [selected]"


def test_format_choice_line_leaves_unselected_choice_plain() -> None:
    choice = StoredChoice(id="c1", text="open the door", child_node_id=None)

    assert str(format_choice_line(1, choice)) == "1. open the door"


def test_format_choice_line_highlighted_applies_style() -> None:
    choice = Choice(id="c1", text="Go north")
    result = format_choice_line(1, choice, highlighted=True)
    assert str(result) == "1. Go north"
    assert len(result.spans) > 0


def test_format_choice_line_unhighlighted_has_no_spans() -> None:
    choice = Choice(id="c1", text="Go north")
    result = format_choice_line(1, choice, highlighted=False)
    assert len(result.spans) == 0


def test_choice_for_key() -> None:
    panel = ChoiceList()
    # Set choices list directly to avoid Textual app context requirement.
    choices = [Choice(id="c1", text="a"), Choice(id="c2", text="b")]
    panel._choices = choices  # pyright: ignore[reportPrivateUsage]
    assert panel.choice_for_key("1") is choices[0]
    assert panel.choice_for_key("2") is choices[1]
    assert panel.choice_for_key("3") is None
    assert panel.choice_for_key("x") is None


def test_highlight_next_prev() -> None:
    panel = ChoiceList()
    choices = [Choice(id="c1", text="a"), Choice(id="c2", text="b"), Choice(id="c3", text="c")]
    panel._choices = choices  # pyright: ignore[reportPrivateUsage]
    assert panel.highlighted is None
    panel.highlight_next()
    assert panel.highlighted == 1
    panel.highlight_next()
    assert panel.highlighted == 2
    panel.highlight_next()
    assert panel.highlighted == 3  # clamped at last
    panel.highlight_prev()
    assert panel.highlighted == 2
    panel.highlight_prev()
    assert panel.highlighted == 1
    panel.highlight_prev()
    assert panel.highlighted == 1  # clamped at first


def test_highlighted_choice() -> None:
    panel = ChoiceList()
    choices = [Choice(id="c1", text="a"), Choice(id="c2", text="b")]
    panel._choices = choices  # pyright: ignore[reportPrivateUsage]
    assert panel.highlighted_choice() is None
    panel.highlight_next()
    assert panel.highlighted_choice() is choices[0]
    panel.highlight_next()
    assert panel.highlighted_choice() is choices[1]


def test_highlight_empty_choices() -> None:
    panel = ChoiceList()
    assert panel.highlight_next() is None
    assert panel.highlight_prev() is None
    assert panel.highlighted_choice() is None
