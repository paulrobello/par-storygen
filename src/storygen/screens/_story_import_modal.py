"""Modal for importing characters from an existing story save into the catalog."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Header, Static

from storygen.storage import paths
from storygen.storage.save import GameSave, load_game


class StoryImportResult(BaseModel):
    """Result of StoryImportModal — which characters to import from which save."""

    save_id: str
    character_ids: list[str]


class StoryImportModal(Screen[list[StoryImportResult] | None]):
    """Lists saves with checkboxes per character, plus a single Import button.

    Each save section has a "Select All" checkbox and per-character checkboxes.
    The Import button collects all checked characters across all saves and
    dismisses with a list of :class:`StoryImportResult` (one per save that has
    selections). Dismisses with None on cancel.
    """

    DEFAULT_CSS = """
    StoryImportModal #story-import-body {
        padding: 1 2;
    }
    StoryImportModal .save-section {
        margin-bottom: 1;
        padding: 1;
        border: round $primary;
    }
    StoryImportModal .save-header {
        text-style: bold;
        margin-bottom: 1;
    }
    StoryImportModal .save-meta {
        color: $text-muted;
        margin-bottom: 1;
    }
    StoryImportModal .char-row {
        height: auto;
        margin-bottom: 0;
    }
    StoryImportModal #story-import-empty {
        color: $text-muted;
    }
    StoryImportModal #story-import-footer {
        dock: bottom;
        height: auto;
        padding: 1 2;
        background: $surface;
    }
    StoryImportModal #story-import-footer Button {
        margin-right: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._scroll = VerticalScroll(id="story-import-body")
        self._saves: dict[str, GameSave] = {}
        # Track save_id -> set of char_ids for checked characters.
        self._checked: dict[str, set[str]] = {}
        # Guard against reentrant on_checkbox_changed calls when select-all
        # programmatically sets per-character checkboxes.
        self._updating_checkboxes: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield self._scroll
        with Horizontal(id="story-import-footer"):
            yield Button("Import Selected", id="btn-do-import", variant="primary")
            yield Button("Cancel", id="btn-cancel-import")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Import from Story"
        self._rebuild()

    def _rebuild(self) -> None:
        self._scroll.remove_children()
        self._saves.clear()
        self._checked.clear()
        saves = self._scan_saves()
        if not saves:
            self._scroll.mount(Static("No saved stories found.", id="story-import-empty"))
            return
        for save in saves:
            self._mount_save_section(save)

    def _mount_save_section(self, save: GameSave) -> None:
        save_id = str(save.id)
        self._saves[save_id] = save
        self._checked[save_id] = set()

        section = Vertical(classes="save-section")
        self._scroll.mount(section)
        section.mount(Static(save.theme.title, classes="save-header"))
        updated = save.updated_at.strftime("%Y-%m-%d %H:%M")
        section.mount(
            Static(
                f"Updated: {updated}  ·  {len(save.characters)} character(s)", classes="save-meta"
            )
        )

        # Select All checkbox for this save.
        select_all = Checkbox(
            "Select All",
            value=False,
            id=f"selall-{save_id}",
        )
        section.mount(select_all)

        # Per-character checkboxes.
        for char in save.characters:
            cb = Checkbox(
                char.name,
                value=False,
                id=f"charcb-{save_id}__{char.id}",
            )
            section.mount(cb)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        # Guard against reentrant calls triggered when select-all programmatically
        # updates per-character checkboxes (each .value set fires this handler).
        if self._updating_checkboxes:
            return
        cb_id = event.checkbox.id or ""
        if cb_id.startswith("selall-"):
            save_id = cb_id[len("selall-") :]
            save = self._saves.get(save_id)
            if save is None:
                return
            checked = event.value
            self._updating_checkboxes = True
            try:
                self._checked.setdefault(save_id, set())
                for char in save.characters:
                    if checked:
                        self._checked[save_id].add(char.id)
                    else:
                        self._checked[save_id].discard(char.id)
                    # Update the per-character checkbox widget to match.
                    cb = self.query_one(f"#charcb-{save_id}__{char.id}", Checkbox)
                    cb.value = checked
            finally:
                self._updating_checkboxes = False
        elif cb_id.startswith("charcb-"):
            remainder = cb_id[len("charcb-") :]
            parts = remainder.split("__", 1)
            if len(parts) != 2:
                return
            save_id, char_id = parts
            self._checked.setdefault(save_id, set())
            if event.value:
                self._checked[save_id].add(char_id)
            else:
                self._checked[save_id].discard(char_id)
            # Sync the "Select All" checkbox.
            save = self._saves.get(save_id)
            if save is not None:
                all_ids = {c.id for c in save.characters}
                sel_all = self.query_one(f"#selall-{save_id}", Checkbox)
                sel_all.value = all_ids == self._checked.get(save_id, set())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "btn-do-import":
            self._do_import()
        elif button_id == "btn-cancel-import":
            self.dismiss(None)

    def _do_import(self) -> None:
        """Collect all checked characters across all saves and dismiss with results."""
        results = [
            StoryImportResult(save_id=save_id, character_ids=list(char_ids))
            for save_id, char_ids in self._checked.items()
            if char_ids
        ]
        if not results:
            self.notify("No characters selected.", severity="warning", timeout=3)
            return
        self.dismiss(results)

    def action_cancel(self) -> None:
        self.dismiss(None)

    @staticmethod
    def _scan_saves() -> list[GameSave]:
        root = paths.games_root()
        if not root.exists():
            return []
        results: list[GameSave] = []
        for d in root.iterdir():
            if not d.is_dir():
                continue
            if not (d / "game.json").exists():
                continue
            try:
                results.append(load_game(d.name))
            except Exception:
                continue
        return sorted(results, key=lambda s: s.updated_at, reverse=True)
