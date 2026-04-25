"""Unit tests for StoryPanel narration rendering."""

from __future__ import annotations

from storygen.widgets.story_panel import StoryPanel


def test_append_accumulates_text() -> None:
    panel = StoryPanel()
    panel.reset()
    panel.append_delta("Hello ")
    panel.append_delta("world.")
    assert panel.text == "Hello world."


def test_reset_clears_text() -> None:
    panel = StoryPanel()
    panel.append_delta("abc")
    panel.reset()
    assert panel.text == ""


def test_set_text_replaces() -> None:
    panel = StoryPanel()
    panel.set_text("final narration")
    assert panel.text == "final narration"
