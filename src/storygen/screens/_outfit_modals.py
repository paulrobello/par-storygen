"""Modals used by :class:`PortraitsScreen` for outfit add / action flows.

Two modals live here:

- :class:`OutfitCreateModal` — collect outfit name + description and dismiss
  with an :class:`OutfitCreateRequest` describing what the caller should
  generate. The modal itself does NOT touch the image provider — that keeps
  the modal pure-UI and lets the caller (PortraitsScreen) own worker
  lifecycle, button gating, and save persistence.
- :class:`OutfitActionModal` — click on an outfit thumb and pick
  ``"set"`` / ``"delete"`` / ``None`` (cancel).

Extracted from :mod:`storygen.screens.portraits` so PortraitsScreen stays
under the ~600-LOC threshold; both modals are otherwise PortraitsScreen-only
and could be folded back in if the screen shrinks.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Static, TextArea


class OutfitCreateRequest(BaseModel):
    """Result of :class:`OutfitCreateModal` — name + description to generate."""

    name: str
    description: str


class OutfitCreateModal(Screen[OutfitCreateRequest | None]):
    """Collect outfit name + description.

    Dismisses with an :class:`OutfitCreateRequest` once both fields are
    non-empty and the user clicks Generate, or ``None`` on Cancel/Escape.
    The caller is responsible for actually invoking the image provider and
    persisting the resulting outfit.
    """

    DEFAULT_CSS = """
    OutfitCreateModal {
        align: center middle;
    }
    OutfitCreateModal #outfit-create-box {
        width: 70;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    OutfitCreateModal #outfit-create-title {
        text-style: bold;
        margin-bottom: 1;
    }
    OutfitCreateModal #outfit-create-name-label,
    OutfitCreateModal #outfit-create-desc-label {
        margin-top: 1;
    }
    OutfitCreateModal #outfit-create-desc {
        height: 5;
        margin-bottom: 1;
    }
    OutfitCreateModal #outfit-create-buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    OutfitCreateModal #outfit-create-generate {
        margin-left: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, character_name: str) -> None:
        super().__init__()
        self._character_name = character_name
        self._name_input = Input(
            placeholder="e.g. ballroom gown",
            id="outfit-create-name",
        )
        self._desc_area = TextArea(
            text="",
            id="outfit-create-desc",
        )
        self._generate_btn = Button(
            "Generate",
            id="outfit-create-generate",
            variant="primary",
        )
        self._cancel_btn = Button("Cancel", id="outfit-create-cancel")

    def compose(self) -> ComposeResult:
        with Vertical(id="outfit-create-box"):
            yield Static(
                f"New outfit for {self._character_name}",
                id="outfit-create-title",
            )
            yield Static("Name", id="outfit-create-name-label")
            yield self._name_input
            yield Static(
                "Description (e.g. 'wearing a flowing red gown with gold trim')",
                id="outfit-create-desc-label",
            )
            yield self._desc_area
            with Horizontal(id="outfit-create-buttons"):
                yield self._cancel_btn
                yield self._generate_btn

    def on_mount(self) -> None:
        self._refresh_generate_state()

    def on_input_changed(self, _event: Input.Changed) -> None:
        self._refresh_generate_state()

    def on_text_area_changed(self, _event: TextArea.Changed) -> None:
        self._refresh_generate_state()

    def _refresh_generate_state(self) -> None:
        name = self._name_input.value.strip()
        desc = self._desc_area.text.strip()
        self._generate_btn.disabled = not (name and desc)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "outfit-create-generate":
            name = self._name_input.value.strip()
            desc = self._desc_area.text.strip()
            if not (name and desc):
                return
            self.dismiss(OutfitCreateRequest(name=name, description=desc))
            return
        if event.button.id == "outfit-create-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


OutfitActionResult = Literal["set", "delete"]


class OutfitActionModal(Screen[OutfitActionResult | None]):
    """Pick what to do with an existing outfit.

    Dismisses with ``"set"`` / ``"delete"`` / ``None`` (cancel). The
    "Set as current" button is disabled when the outfit is already current.
    """

    DEFAULT_CSS = """
    OutfitActionModal {
        align: center middle;
    }
    OutfitActionModal #outfit-action-box {
        width: 70;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    OutfitActionModal #outfit-action-title {
        text-style: bold;
        margin-bottom: 1;
    }
    OutfitActionModal #outfit-action-desc {
        margin-bottom: 1;
        color: $text-muted;
    }
    OutfitActionModal .outfit-action-button {
        margin-bottom: 1;
        width: 100%;
    }
    OutfitActionModal #outfit-action-cancel {
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        outfit_name: str,
        outfit_description: str,
        *,
        is_current: bool,
    ) -> None:
        super().__init__()
        self._outfit_name = outfit_name
        self._outfit_description = outfit_description
        self._is_current = is_current

    def compose(self) -> ComposeResult:
        with Vertical(id="outfit-action-box"):
            yield Static(
                f"Outfit: {self._outfit_name}",
                id="outfit-action-title",
            )
            display_desc = self._outfit_description
            if len(display_desc) > 240:
                display_desc = display_desc[:237] + "..."
            yield Static(display_desc, id="outfit-action-desc", markup=False)
            set_btn = Button(
                "Set as current",
                id="outfit-action-set",
                classes="outfit-action-button",
                variant="primary",
            )
            set_btn.disabled = self._is_current
            yield set_btn
            yield Button(
                "Delete",
                id="outfit-action-delete",
                classes="outfit-action-button",
                variant="error",
            )
            yield Button("Cancel", id="outfit-action-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "outfit-action-set":
            self.dismiss("set")
        elif event.button.id == "outfit-action-delete":
            self.dismiss("delete")
        elif event.button.id == "outfit-action-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
