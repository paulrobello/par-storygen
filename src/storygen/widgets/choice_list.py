"""ChoiceList: renders numbered choices and maps number keys back to choices."""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import RenderableType
from textual.widgets import Static

from storygen.llm.models import Choice


def format_choice_line(n: int, choice: Choice) -> str:
    selected_marker = " [selected]" if getattr(choice, "child_node_id", None) else ""
    return f"{n}. {choice.text}{selected_marker}"


class ChoiceList(Static):
    def __init__(self) -> None:
        super().__init__("", markup=False)
        self._choices: list[Choice] = []

    @property
    def renderable(self) -> RenderableType:
        """Current content as a Rich renderable (for testing and inspection)."""
        return self.content  # type: ignore[return-value]

    def set_choices(self, choices: Sequence[Choice]) -> None:
        # Sequence (read-only, covariant) so callers can pass list[StoredChoice]
        # — StoredChoice is a Choice subclass with a child_node_id field this
        # widget doesn't care about.
        self._choices = list(choices)
        body = "\n".join(format_choice_line(i + 1, c) for i, c in enumerate(self._choices))
        self.update(body)

    def clear(self) -> None:
        self._choices = []
        self.update("")

    def choice_for_key(self, key: str) -> Choice | None:
        if not key.isdigit():
            return None
        idx = int(key) - 1
        if 0 <= idx < len(self._choices):
            return self._choices[idx]
        return None
