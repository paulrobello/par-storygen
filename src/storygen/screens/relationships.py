"""RelationshipsScreen: modal displaying character relationships."""

from __future__ import annotations

from collections import defaultdict
from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Static

from storygen.core.models import Character, CharacterId, Relationship, RelationshipType

_REL_TYPE_ICONS: dict[RelationshipType, str] = {
    RelationshipType.ALLY: "↔",
    RelationshipType.RIVAL: "⚔",
    RelationshipType.NEUTRAL: "○",
    RelationshipType.ROMANTIC: "♥",
    RelationshipType.MENTOR: "↑",
    RelationshipType.STUDENT: "↓",
    RelationshipType.FAMILY: "⌂",
    RelationshipType.STRANGER: "✗",
}


def _strength_bar(strength: int) -> str:
    filled = "█" * strength
    empty = "░" * (5 - strength)
    return f"{filled}{empty}"


class RelationshipsScreen(ModalScreen[None]):
    """Modal screen showing character relationships grouped by character."""

    DEFAULT_CSS = """
    RelationshipsScreen {
        align: center middle;
    }
    RelationshipsScreen #rel-container {
        width: 72;
        max-width: 90vw;
        height: auto;
        max-height: 80vh;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    RelationshipsScreen #rel-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    RelationshipsScreen #rel-content {
        margin-bottom: 1;
    }
    RelationshipsScreen #rel-footer {
        text-align: center;
        color: $text-muted;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    ]

    def __init__(
        self,
        characters: list[Character] | None = None,
        relationships: list[Relationship] | None = None,
    ) -> None:
        super().__init__()
        self._characters: list[Character] = characters or []
        self._relationships: list[Relationship] = relationships or []

    def set_data(
        self,
        characters: list[Character],
        relationships: list[Relationship],
    ) -> None:
        """Update the screen data (safe to call after mount)."""
        self._characters = characters
        self._relationships = relationships
        content = self.query_one("#rel-content", Static)
        content.update(self._build_renderable())

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="rel-container"):
            yield Static("Relationships", id="rel-title")
            yield Static(self._build_renderable(), id="rel-content")
            yield Static("Press Esc or q to close", id="rel-footer")
        yield Footer()

    def on_mount(self) -> None:
        self._apply_header()

    def _apply_header(self) -> None:
        self.title = "Relationships"
        self.sub_title = f"{len(self._relationships)} relationship(s)"

    def action_close(self) -> None:
        self.dismiss(None)

    def _build_renderable(self) -> str:
        if not self._relationships:
            return "No known relationships."

        char_map: dict[CharacterId, str] = {c.id: c.name for c in self._characters}

        # Group relationships by character ID.
        by_char: dict[CharacterId, list[Relationship]] = defaultdict(list)
        for rel in self._relationships:
            by_char[rel.char_a_id].append(rel)
            by_char[rel.char_b_id].append(rel)

        lines: list[str] = []
        seen_chars: set[CharacterId] = set()
        # Render sections ordered by the characters list for stable ordering.
        for char in self._characters:
            if char.id not in by_char or char.id in seen_chars:
                continue
            seen_chars.add(char.id)
            lines.append(f"[bold]{char.name}[/bold]")
            for rel in by_char[char.id]:
                other_id = rel.char_b_id if rel.char_a_id == char.id else rel.char_a_id
                other_name = char_map.get(other_id, other_id)
                icon = _REL_TYPE_ICONS.get(rel.type, "?")
                bar = _strength_bar(rel.strength)
                rel_type = rel.type.value
                lines.append(f"  {icon} {other_name}  {rel_type}  {bar} ({rel.strength}/5)")
                if rel.context:
                    lines.append(f"    [dim]{rel.context}[/dim]")
            lines.append("")

        return "\n".join(lines).rstrip()
