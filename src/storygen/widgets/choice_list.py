"""ChoiceList: renders numbered choices with optional highlight cursor."""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import RenderableType
from rich.text import Text
from textual.widgets import Static

from storygen.llm.models import Choice


def format_choice_line(n: int, choice: Choice, *, highlighted: bool = False) -> Text:
    selected_marker = " [selected]" if getattr(choice, "child_node_id", None) else ""
    label = f"{n}. {choice.text}{selected_marker}"
    text = Text(label)
    if highlighted:
        text.stylize("bold reverse")
    return text


class ChoiceList(Static):
    def __init__(self) -> None:
        super().__init__("", markup=False)
        self._choices: list[Choice] = []
        self._highlighted: int | None = None

    @property
    def renderable(self) -> RenderableType:
        """Current content as a Rich renderable (for testing and inspection)."""
        return self.content  # type: ignore[return-value]

    def set_choices(self, choices: Sequence[Choice]) -> None:
        # Sequence (read-only, covariant) so callers can pass list[StoredChoice]
        # — StoredChoice is a Choice subclass with a child_node_id field this
        # widget doesn't care about.
        self._choices = list(choices)
        self._highlighted = None
        self._refresh_display()

    def clear(self) -> None:
        self._choices = []
        self._highlighted = None
        self.update("")

    def choice_for_key(self, key: str) -> Choice | None:
        if not key.isdigit():
            return None
        idx = int(key) - 1
        if 0 <= idx < len(self._choices):
            return self._choices[idx]
        return None

    @property
    def highlighted(self) -> int | None:
        """1-based index of the highlighted choice, or None."""
        if self._highlighted is None:
            return None
        return self._highlighted + 1

    def highlight_next(self) -> Choice | None:
        """Move highlight down. Returns the newly highlighted choice or None."""
        if not self._choices:
            return None
        if self._highlighted is None:
            self._highlighted = 0
        else:
            self._highlighted = min(self._highlighted + 1, len(self._choices) - 1)
        self._refresh_display()
        return self._choices[self._highlighted]

    def highlight_prev(self) -> Choice | None:
        """Move highlight up. Returns the newly highlighted choice or None."""
        if not self._choices:
            return None
        if self._highlighted is None:
            self._highlighted = len(self._choices) - 1
        else:
            self._highlighted = max(self._highlighted - 1, 0)
        self._refresh_display()
        return self._choices[self._highlighted]

    def highlighted_choice(self) -> Choice | None:
        """Return the currently highlighted choice, or None."""
        if self._highlighted is None or self._highlighted >= len(self._choices):
            return None
        return self._choices[self._highlighted]

    def _refresh_display(self) -> None:
        lines: list[Text] = []
        for i, c in enumerate(self._choices):
            lines.append(format_choice_line(i + 1, c, highlighted=(i == self._highlighted)))
        content = Text("\n", justify="left").join(lines) if lines else ""
        if self.is_mounted:
            self.update(content)
