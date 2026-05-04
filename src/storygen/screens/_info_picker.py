"""InfoPickerModal: quick-pick modal for story info screens (portraits, graph, endings, relationships)."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Static


class InfoPickerModal(Screen[str | None]):
    """Modal picker for story info screens.

    Dismisses with one of ``"portraits"``, ``"graph"``, ``"endings"``,
    ``"relationships"``, or ``None`` (cancelled).
    """

    DEFAULT_CSS = """
    InfoPickerModal {
        align: center middle;
    }
    InfoPickerModal #info-box {
        width: 50;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    InfoPickerModal #info-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    InfoPickerModal #info-options {
        margin-bottom: 1;
    }
    InfoPickerModal #info-options > Button {
        width: 100%;
        margin-bottom: 1;
    }
    InfoPickerModal #info-cancel {
        align-horizontal: right;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
        ("p", "pick_portraits", "Portraits"),
        ("g", "pick_graph", "Graph"),
        ("e", "pick_endings", "Endings"),
        ("r", "pick_relationships", "Relationships"),
    ]

    def __init__(
        self,
        *,
        can_portraits: bool = True,
        can_graph: bool = True,
        can_endings: bool = True,
        can_relationships: bool = True,
    ) -> None:
        super().__init__()
        self._can_portraits = can_portraits
        self._can_graph = can_graph
        self._can_endings = can_endings
        self._can_relationships = can_relationships

    def compose(self) -> ComposeResult:
        with Vertical(id="info-box"):
            yield Static("Info", id="info-title")
            with Vertical(id="info-options"):
                yield Button(
                    "Portraits       [p]", id="btn-portraits", disabled=not self._can_portraits
                )
                yield Button("Graph           [g]", id="btn-graph", disabled=not self._can_graph)
                yield Button(
                    "Endings         [e]", id="btn-endings", disabled=not self._can_endings
                )
                yield Button(
                    "Relationships   [r]",
                    id="btn-relationships",
                    disabled=not self._can_relationships,
                )
            with Vertical(id="info-cancel"):
                yield Button("Cancel", id="btn-cancel")
        yield Footer()

    def _pick(self, action: str) -> None:
        self.dismiss(action)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_pick_portraits(self) -> None:
        if self._can_portraits:
            self._pick("portraits")

    def action_pick_graph(self) -> None:
        if self._can_graph:
            self._pick("graph")

    def action_pick_endings(self) -> None:
        if self._can_endings:
            self._pick("endings")

    def action_pick_relationships(self) -> None:
        if self._can_relationships:
            self._pick("relationships")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        mapping = {
            "btn-portraits": "portraits",
            "btn-graph": "graph",
            "btn-endings": "endings",
            "btn-relationships": "relationships",
            "btn-cancel": None,
        }
        result = mapping.get(event.button.id or "")
        if result is not None or event.button.id == "btn-cancel":
            self.dismiss(result)
