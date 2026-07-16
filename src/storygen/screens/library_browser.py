"""CharacterCatalogScreen: pick a previously exported character for import.

The catalog lists every entry in the cross-game library. For each entry the
user may:

- Import it into the wizard's in-progress cast (Keep-as-is OR adapt the
  backstory to the new story's theme via an LLM rewrite).
- Delete it from the library (requires confirmation so a misclick can't
  destroy a portrait that a user spent tokens generating).

The screen dismisses with a :class:`LibraryPick` on Import (carrying the
``mode`` literal the wizard uses to decide whether to run the backstory-adapter
LLM call) or ``None`` on Escape/Cancel. It owns no save state — the wizard is
responsible for turning the returned library character into a save-local
:class:`storygen.llm.models.Character` at append time.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import ClassVar, Literal, Protocol, cast
from uuid import uuid4

from PIL import Image
from pydantic import BaseModel
from textual import work
from textual.app import ComposeResult
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from storygen.llm.models import Character
from storygen.screens._confirm_modal import ConfirmModal
from storygen.screens._create_char_modal import CreateCharRequest
from storygen.screens._library_edit_modal import LibraryEditModal, LibraryEditResult
from storygen.screens._ref_image_modals import ReferenceImageModal, ReferenceImageResult
from storygen.screens._story_import_modal import StoryImportResult
from storygen.storage import app_state, paths
from storygen.storage.library import (
    PLACEHOLDER_PNG,
    LibraryCharacter,
    LibrarySource,
    delete_library_character,
    library_portrait_path,
    library_reference_path,
    list_library_characters,
    load_library_character,
    save_library_character,
)
from storygen.storage.save import load_game
from storygen.util import open_in_system_viewer
from storygen.widgets.image_util import render_image_thumbnail

SortMode = Literal["newest", "name"]

_logger = logging.getLogger(__name__)


def _load_portrait_bytes(library_id: str) -> bytes:
    """Read the portrait PNG for a library character (used by rm-ref to re-save without ref)."""
    path = library_portrait_path(library_id)
    if path.exists():
        return path.read_bytes()
    return PLACEHOLDER_PNG


class _CharacterAgentLike(Protocol):
    """Minimal protocol for a pydantic-ai agent that generates characters."""

    async def run(self, prompt: str) -> object: ...


class _ImageProviderLike(Protocol):
    """Minimal protocol for an image provider used by catalog character creation."""

    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        reference_image: bytes | None = None,
    ) -> bytes: ...


class LibraryPick(BaseModel):
    """Result of :class:`CharacterCatalogScreen` — a picked library character.

    ``mode="adapt"`` signals the caller should LLM-rewrite the backstory for
    the new story's theme; ``mode="keep"`` means keep-as-is.
    """

    character: LibraryCharacter
    mode: Literal["keep", "adapt"]


class _ImportModeModal(Screen[str | None]):
    """Two-option modal: Keep as-is vs Adapt backstory.

    Dismisses with ``"keep"``, ``"adapt"``, or ``None`` (cancel).
    """

    DEFAULT_CSS = """
    _ImportModeModal {
        align: center middle;
    }
    _ImportModeModal #mode-box {
        width: 70;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    _ImportModeModal #mode-title {
        text-style: bold;
        margin-bottom: 1;
    }
    _ImportModeModal .mode-option {
        margin-bottom: 1;
        width: 100%;
    }
    _ImportModeModal #mode-adapt-note {
        color: $text-muted;
        margin-bottom: 1;
        text-style: italic;
    }
    _ImportModeModal #mode-cancel {
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, character_name: str) -> None:
        super().__init__()
        self._character_name = character_name

    def compose(self) -> ComposeResult:
        with Vertical(id="mode-box"):
            yield Static(f"Import '{self._character_name}'", id="mode-title")
            yield Button(
                "Keep as-is",
                id="mode-keep",
                classes="mode-option",
                variant="primary",
            )
            yield Button(
                "Adapt backstory to new theme (LLM)",
                id="mode-adapt",
                classes="mode-option",
            )
            yield Static(
                "Rewrites backstory to fit the new story's theme, keeping"
                " name/personality/looks intact.",
                id="mode-adapt-note",
            )
            yield Button("Cancel", id="mode-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "mode-keep":
            self.dismiss("keep")
        elif event.button.id == "mode-adapt":
            self.dismiss("adapt")
        elif event.button.id == "mode-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class CharacterCatalogScreen(Screen[LibraryPick | None]):
    """Full-screen modal that lets the user browse + pick a library character.

    Dismisses with a :class:`LibraryPick` on Import (carrying whether the
    caller should adapt the backstory to the new theme via LLM), or ``None``
    on Escape/Cancel. Non-destructive: the actual character→save conversion
    is the caller's responsibility.
    """

    DEFAULT_CSS = """
    CharacterCatalogScreen #library-body {
        padding: 1 2;
    }
    CharacterCatalogScreen .library-row {
        height: 16;
        margin-bottom: 1;
        padding: 1;
        border: round $primary;
        overflow-y: hidden;
    }
    CharacterCatalogScreen .library-meta {
        width: 1fr;
        height: auto;
    }
    CharacterCatalogScreen .library-buttons {
        height: auto;
    }
    CharacterCatalogScreen .library-thumb {
        width: 28;
        height: 14;
        margin-right: 2;
    }
    CharacterCatalogScreen .library-name {
        text-style: bold;
    }
    CharacterCatalogScreen .library-source {
        color: $text-muted;
    }
    CharacterCatalogScreen #library-empty {
        width: 100%;
        height: 100%;
        content-align: center middle;
        color: $text-muted;
    }
    CharacterCatalogScreen .library-buttons Button {
        margin-right: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
        ("n", "create_character", "New Char"),
        ("s", "toggle_sort", "Sort"),
        ("t", "import_from_story", "Import Story"),
        ("j", "focus_next_row", "▼ Next"),
        ("k", "focus_prev_row", "▲ Prev"),
        ("down", "focus_next_row", "▼ Next"),
        ("up", "focus_prev_row", "▲ Prev"),
    ]

    def __init__(
        self,
        *,
        browse: bool = False,
        character_agent_factory: Callable[[], _CharacterAgentLike] | None = None,
        image_provider: _ImageProviderLike | None = None,
    ) -> None:
        super().__init__()
        self._browse = browse
        self._scroll = VerticalScroll(id="library-body")
        # Populated by `_rebuild`; keyed by LibraryCharacter.id so click
        # handlers can look up the entry without hitting disk again.
        self._entries: dict[str, LibraryCharacter] = {}
        # Ephemeral per-session sort order. Default "newest" matches the
        # on-disk order from `list_library_characters()`; toggling to "name"
        # re-sorts in memory. NOT persisted — a user who prefers one over
        # the other just taps `s` once per session.
        self._sort_mode: SortMode = "newest"
        self._creating: bool = False
        self._character_agent_factory = character_agent_factory
        self._image_provider = image_provider
        self._focused_idx: int = 0
        # Track in-flight portrait regenerations so all regen buttons are
        # disabled while any worker is running.
        self._regen_busy: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield self._scroll
        yield Footer()

    def on_mount(self) -> None:
        self._apply_title()
        self._rebuild()

    def action_cancel(self) -> None:
        if self._browse:
            self.app.pop_screen()  # pyright: ignore[reportUnknownMemberType]
        else:
            self.dismiss(None)

    def action_toggle_sort(self) -> None:
        """Cycle the sort order between newest-first and alphabetical."""
        self._sort_mode = "name" if self._sort_mode == "newest" else "newest"
        self._rebuild()

    def action_focus_next_row(self) -> None:
        if not self._entries:
            return
        entry_ids = list(self._entries.keys())
        self._focused_idx = min(self._focused_idx + 1, len(entry_ids) - 1)
        self._focus_entry_row(entry_ids[self._focused_idx])

    def action_focus_prev_row(self) -> None:
        if not self._entries:
            return
        entry_ids = list(self._entries.keys())
        self._focused_idx = max(self._focused_idx - 1, 0)
        self._focus_entry_row(entry_ids[self._focused_idx])

    def _focus_entry_row(self, entry_id: str) -> None:
        # Focus the Edit button (always present) in the target row.
        try:
            btn = self._scroll.query_one(f"#edit-{entry_id}", Button)
            btn.focus()
        except Exception:
            pass

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in ("create_character", "import_from_story"):
            return self._browse
        return True

    def action_create_character(self) -> None:
        """Open the create-character modal; on submit, kick off the gen worker."""
        if not self._browse:
            return
        from storygen.screens._create_char_modal import CreateCharacterModal

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            CreateCharacterModal(),
            self._on_create_character,
        )

    def _on_create_character(self, request: object) -> None:
        """Callback from CreateCharacterModal; validate and dispatch the worker."""
        if not isinstance(request, CreateCharRequest):
            return
        self._creating = True
        self._rebuild()
        self.notify("Generating character…", timeout=120)
        self._create_character_worker(request)

    @work(exit_on_error=False)
    async def _create_character_worker(self, request: CreateCharRequest) -> None:
        """Generate a character from a concept description via LLM + image provider."""
        try:
            if self._character_agent_factory is None:
                self.notify(
                    "Character creation unavailable — no agent configured.",
                    severity="error",
                    timeout=5,
                )
                return
            try:
                agent = self._character_agent_factory()
                prompt = request.concept
                if request.name:
                    prompt = f"Create a character named '{request.name}'. {request.concept}"
                result = await agent.run(prompt)
                raw_output = getattr(result, "output", None)
                if not isinstance(raw_output, list) or not raw_output:
                    self.notify("LLM returned no characters.", severity="error", timeout=5)
                    return
                first = raw_output[0]  # type: ignore[reportUnknownVariableType]
                if not isinstance(first, Character):
                    self.notify("LLM returned unexpected type.", severity="error", timeout=5)
                    return
                char: Character = first
                if request.name:
                    char = char.model_copy(update={"name": request.name})
            except Exception:
                _logger.debug("Character generation failed", exc_info=True)
                self.notify("Character generation failed.", severity="error", timeout=5)
                return

            portrait_bytes: bytes | None = None
            if self._image_provider is not None and app_state.art_enabled():
                try:
                    portrait_bytes = await self._image_provider.generate_portrait(
                        char.physical_description,
                        transparent=True,
                        art_style=app_state.DEFAULT_ART_STYLE,
                        reference_image=request.reference_image,
                    )
                except Exception:
                    _logger.debug("Portrait generation failed", exc_info=True)
                    self.notify("Portrait generation failed.", severity="warning", timeout=5)
            if portrait_bytes is None:
                portrait_bytes = PLACEHOLDER_PNG

            lib_char = LibraryCharacter(
                id=uuid4().hex,
                name=char.name,
                backstory=char.backstory,
                personality=char.personality,
                physical_description=char.physical_description,
                portrait_prompt=char.physical_description,
                exported_at=datetime.now(UTC),
                source="created",
            )
            save_library_character(
                lib_char, portrait_bytes, reference_bytes=request.reference_image
            )
            if app_state.auto_open_art_enabled() and portrait_bytes is not PLACEHOLDER_PNG:
                open_in_system_viewer(library_portrait_path(lib_char.id))
            self.notify(f"Created '{lib_char.name}'.", timeout=5)
        finally:
            self._creating = False
            self._rebuild()

    def action_import_from_story(self) -> None:
        """Open the story import modal to pull characters from a saved story."""
        if not self._browse:
            return
        from storygen.screens._story_import_modal import StoryImportModal

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            StoryImportModal(),
            self._on_story_import,
        )

    def _on_story_import(self, result: object) -> None:
        if not isinstance(result, list):
            return
        story_results: list[StoryImportResult] = [
            r for r in cast(list[object], result) if isinstance(r, StoryImportResult)
        ]
        if not story_results:
            return
        self._import_from_story_worker(story_results)

    @work(exit_on_error=False)
    async def _import_from_story_worker(self, results: list[StoryImportResult]) -> None:
        """Import checked characters from one or more saves into the library."""
        existing_names = {c.name for c in list_library_characters()}
        imported = 0

        for result in results:
            try:
                save = load_game(result.save_id)
            except Exception:
                self.notify("Could not load story.", severity="error", timeout=5)
                continue

            save_id = str(save.id)
            for char_id in result.character_ids:
                char = next((c for c in save.characters if c.id == char_id), None)
                if char is None:
                    continue
                if char.name in existing_names:
                    self.notify(
                        f"Skipped '{char.name}' — already in catalog.",
                        severity="warning",
                        timeout=5,
                    )
                    continue

                portrait_bytes: bytes
                if char.portrait_path:
                    try:
                        abs_path = paths.safe_join(paths.game_dir(save_id), char.portrait_path)
                        portrait_bytes = (
                            abs_path.read_bytes() if abs_path.exists() else PLACEHOLDER_PNG
                        )
                    except ValueError:
                        portrait_bytes = PLACEHOLDER_PNG
                else:
                    portrait_bytes = PLACEHOLDER_PNG

                ref_bytes: bytes | None = None
                if char.reference_image_path:
                    try:
                        ref_abs = paths.safe_join(
                            paths.game_dir(save_id), char.reference_image_path
                        )
                        if ref_abs.exists():
                            ref_bytes = ref_abs.read_bytes()
                    except ValueError:
                        pass

                lib_char = LibraryCharacter(
                    id=uuid4().hex,
                    name=char.name,
                    backstory=char.backstory,
                    personality=char.personality,
                    physical_description=char.physical_description,
                    portrait_prompt=char.portrait_prompt or char.physical_description,
                    exported_at=datetime.now(UTC),
                    exported_from=LibrarySource(
                        save_id=save_id,
                        save_title=save.theme.title,
                        character_id=char.id,
                    ),
                    source="story_import",
                )
                save_library_character(lib_char, portrait_bytes, reference_bytes=ref_bytes)
                existing_names.add(char.name)
                imported += 1

        self._rebuild()
        if imported:
            self.notify(f"Imported {imported} character(s).", timeout=5)

    def _apply_title(self) -> None:
        """Update the header title with the current count + sort mode."""
        count = len(self._entries)
        prefix = "Character Catalog" if self._browse else "Character Library"
        if count == 0:
            self.title = f"{prefix} — sorted by {self._sort_mode}"
        else:
            self.title = f"{prefix} ({count} characters, sorted by {self._sort_mode})"

    def _sort_entries(self, entries: list[LibraryCharacter]) -> list[LibraryCharacter]:
        """Apply the current sort mode to ``entries``.

        ``list_library_characters()`` already returns newest-first, so the
        "newest" case is a passthrough. "name" is case-insensitive alpha
        ascending so 'alice' and 'Alice' sort together deterministically.
        """
        if self._sort_mode == "name":
            return sorted(entries, key=lambda c: c.name.casefold())
        return entries

    def _rebuild(self) -> None:
        """Re-populate the scroll container from the current library state."""
        self._scroll.remove_children()
        self._focused_idx = 0
        entries = self._sort_entries(list_library_characters())
        # Cache entries keyed by id so click handlers can avoid a second
        # `list_library_characters()` round-trip (and the render/click race
        # that would come with it).
        self._entries = {entry.id: entry for entry in entries}
        self._apply_title()
        # Browse-mode action buttons at the top.
        if self._browse:
            btn_row = Horizontal(classes="library-buttons")
            self._scroll.mount(btn_row)
            btn_row.mount(Button("New Character", id="btn-catalog-new", variant="primary"))
            btn_row.mount(Button("Import from Story", id="btn-catalog-import-story"))
        if self._creating:
            creating_row = Horizontal(classes="library-row")
            self._scroll.mount(creating_row)
            creating_row.mount(Static("⏳ Creating new character…", classes="library-name"))
        if not entries and not self._creating:
            self._scroll.mount(
                Center(
                    Static(
                        "No characters in catalog yet.",
                        id="library-empty",
                    )
                )
            )
        for entry in entries:
            self._mount_row(entry)

    def _mount_row(self, entry: LibraryCharacter) -> None:
        row = Horizontal(classes="library-row")
        self._scroll.mount(row)
        row.mount(self._render_thumb(entry))
        meta = Vertical(classes="library-meta")
        row.mount(meta)
        meta.mount(Static(entry.name, classes="library-name"))
        first_line_personality = entry.personality.split(".", 1)[0]
        meta.mount(Static(first_line_personality))
        source_label = (
            f"from: {entry.exported_from.save_title}"
            if entry.exported_from is not None
            else "from: (unknown)"
        )
        meta.mount(Static(source_label, classes="library-source"))
        missing = not library_portrait_path(entry.id).exists()
        if missing:
            meta.mount(Static("(portrait missing)", classes="library-source"))
        photo_buttons = Horizontal(classes="library-buttons")
        meta.mount(photo_buttons)
        full_res_btn = Button("Full Res", id=f"fullres-{entry.id}")
        full_res_btn.disabled = missing
        photo_buttons.mount(full_res_btn)
        regen_btn = Button("Regenerate", id=f"regen-{entry.id}")
        regen_btn.disabled = self._image_provider is None or bool(self._regen_busy)
        photo_buttons.mount(regen_btn)
        ref_label = "Change Ref" if entry.reference_image_path else "Ref Image"
        ref_btn = Button(ref_label, id=f"ref-{entry.id}")
        ref_btn.disabled = self._image_provider is None
        photo_buttons.mount(ref_btn)
        if entry.reference_image_path is not None:
            photo_buttons.mount(Button("Rm Ref", id=f"rm-ref-{entry.id}"))
        action_buttons = Horizontal(classes="library-buttons")
        meta.mount(action_buttons)
        if not self._browse:
            import_btn = Button("Import", id=f"import-{entry.id}")
            import_btn.disabled = missing
            action_buttons.mount(import_btn)
        action_buttons.mount(Button("Edit", id=f"edit-{entry.id}"))
        action_buttons.mount(Button("Delete", id=f"delete-{entry.id}", variant="error"))

    def _render_thumb(self, entry: LibraryCharacter) -> Static:
        return render_image_thumbnail(
            library_portrait_path(entry.id),
            size=(96, 48),
            css_class="library-thumb",
            placeholder="(no portrait)",
            on_click=open_in_system_viewer,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "btn-catalog-new":
            self.action_create_character()
            return
        if button_id == "btn-catalog-import-story":
            self.action_import_from_story()
            return
        if button_id.startswith("import-"):
            library_id = button_id[len("import-") :]
            self._start_import(library_id)
            return
        if button_id.startswith("fullres-"):
            library_id = button_id[len("fullres-") :]
            self._open_full_res(library_id)
            return
        if button_id.startswith("regen-"):
            library_id = button_id[len("regen-") :]
            self._regenerate_worker(library_id, event.button)
            return
        if button_id.startswith("ref-"):
            library_id = button_id[len("ref-") :]
            self._open_ref_image_modal(library_id)
            return
        if button_id.startswith("rm-ref-"):
            library_id = button_id[len("rm-ref-") :]
            self._remove_reference_image(library_id)
            return
        if button_id.startswith("edit-"):
            library_id = button_id[len("edit-") :]
            self._start_edit(library_id)
            return
        if button_id.startswith("delete-"):
            library_id = button_id[len("delete-") :]
            self._start_delete(library_id)

    def _open_full_res(self, library_id: str) -> None:
        """Open the library character's portrait in the OS image viewer."""
        path = library_portrait_path(library_id)
        if not path.exists():
            self.notify("Portrait missing — nothing to open.", severity="warning", timeout=5)
            return
        open_in_system_viewer(path)

    @work(exit_on_error=False)
    async def _regenerate_worker(self, library_id: str, button: Button) -> None:
        """Regenerate the portrait for ``library_id`` using the current image provider.

        The triggering button is disabled + relabeled "Working…" for the
        duration; on success the list rebuilds (fresh enabled button), on
        failure we restore the original label/state if the button is still
        attached.
        """
        entry = self._entries.get(library_id)
        if entry is None:
            self.notify("Library entry no longer exists.", severity="error")
            self._rebuild()
            return
        if self._image_provider is None:
            self.notify(
                "Regeneration unavailable — no image provider configured.",
                severity="error",
                timeout=5,
            )
            return
        self._regen_busy.add(library_id)
        button.disabled = True
        button.label = "Working…"
        self.notify(f"Regenerating portrait for '{entry.name}'...", timeout=5)
        prompt = entry.portrait_prompt or entry.physical_description
        ref_bytes: bytes | None = None
        if entry.reference_image_path:
            ref_path = library_reference_path(entry.id)
            if ref_path.exists():
                ref_bytes = ref_path.read_bytes()
        try:
            portrait_bytes = await self._image_provider.generate_portrait(
                prompt,
                transparent=True,
                art_style=app_state.DEFAULT_ART_STYLE,
                reference_image=ref_bytes,
            )
        except Exception:
            _logger.debug("Portrait regeneration failed", exc_info=True)
            self.notify("Portrait regeneration failed.", severity="error", timeout=5)
        else:
            save_library_character(entry, portrait_bytes)
            if app_state.auto_open_art_enabled():
                open_in_system_viewer(library_portrait_path(entry.id))
            self._rebuild()
            self.notify(f"Regenerated portrait for '{entry.name}'.", timeout=5)
        finally:
            self._regen_busy.discard(library_id)
            if not self._regen_busy:
                self._rebuild()

    def _open_ref_image_modal(self, library_id: str) -> None:
        """Open the reference image picker for a library character."""
        entry = self._entries.get(library_id)
        if entry is None:
            return
        entry_name = entry.name

        def _after(result: object) -> None:
            if not isinstance(result, ReferenceImageResult):
                return
            self._apply_ref_image_worker(result, library_id)

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            ReferenceImageModal(entry_name, default_style=app_state.DEFAULT_ART_STYLE),
            _after,
        )

    @work(exit_on_error=False)
    async def _apply_ref_image_worker(self, result: ReferenceImageResult, library_id: str) -> None:
        """Process a reference image for a library character."""
        entry = self._entries.get(library_id)
        if entry is None:
            return
        try:
            with Image.open(result.source_path) as im:
                im = im.convert("RGBA")
                buf = io.BytesIO()
                im.save(buf, format="PNG")
                png_bytes = buf.getvalue()
        except Exception:
            _logger.debug("Failed to load reference image", exc_info=True)
            self.notify("Failed to load image.", severity="error", timeout=5)
            return

        if result.mode == "use_as_is":
            portrait_bytes = png_bytes
            entry = entry.model_copy(
                update={
                    "portrait_prompt": "(from reference image)",
                    "reference_image_path": "reference.png",
                }
            )
        else:
            if self._image_provider is None:
                self.notify("No image provider configured.", severity="error", timeout=5)
                return
            self.notify(f"Generating style-transfer portrait for {entry.name}…", timeout=120)
            try:
                portrait_bytes = await self._image_provider.generate_portrait(
                    entry.physical_description,
                    transparent=True,
                    art_style=result.style_prompt or app_state.DEFAULT_ART_STYLE,
                    reference_image=png_bytes,
                )
            except Exception:
                _logger.debug("Style-transfer failed", exc_info=True)
                self.notify("Style-transfer failed.", severity="error", timeout=5)
                return
            entry = entry.model_copy(
                update={
                    "portrait_prompt": entry.physical_description,
                    "reference_image_path": "reference.png",
                }
            )

        save_library_character(entry, portrait_bytes, reference_bytes=png_bytes)
        self._rebuild()
        if app_state.auto_open_art_enabled():
            open_in_system_viewer(library_portrait_path(entry.id))
        self.notify(f"Reference image set for {entry.name}.", timeout=5)

    def _remove_reference_image(self, library_id: str) -> None:
        """Clear the reference image from a library character."""
        entry = self._entries.get(library_id)
        if entry is None:
            return
        ref_path = library_reference_path(library_id)
        if ref_path.exists():
            ref_path.unlink()
        entry = entry.model_copy(update={"reference_image_path": None})
        save_library_character(entry, _load_portrait_bytes(library_id))
        self._rebuild()
        self.notify(f"Reference image removed from {entry.name}.", timeout=5)

    def _start_import(self, library_id: str) -> None:
        """Open the import-mode modal; on Keep as-is, dismiss with the entry."""
        entry = self._entries.get(library_id)
        if entry is None:
            self.notify("Library entry no longer exists.", severity="error")
            self._rebuild()
            return
        if not library_portrait_path(entry.id).exists():
            self.notify(
                f"Portrait for '{entry.name}' is missing — cannot import.",
                severity="error",
                timeout=5,
            )
            self._rebuild()
            return

        def _after_mode(choice: str | None) -> None:
            if choice == "keep":
                self.dismiss(LibraryPick(character=entry, mode="keep"))
            elif choice == "adapt":
                self.dismiss(LibraryPick(character=entry, mode="adapt"))

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            _ImportModeModal(entry.name),
            _after_mode,
        )

    def _start_edit(self, library_id: str) -> None:
        """Open the edit modal; on save, persist the updated LibraryCharacter."""
        entry = self._entries.get(library_id)
        if entry is None:
            self.notify("Library entry no longer exists.", severity="error")
            self._rebuild()
            return

        def _after_edit(result: LibraryEditResult | None) -> None:
            if result is None:
                return
            self._apply_edit(library_id, result)

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            LibraryEditModal(entry),
            _after_edit,
        )

    def _apply_edit(self, library_id: str, result: LibraryEditResult) -> None:
        """Persist the edited fields to disk and refresh the list."""
        try:
            char = load_library_character(library_id)
        except Exception:
            _logger.debug("Could not load character", exc_info=True)
            self.notify("Could not load character.", severity="error", timeout=5)
            self._rebuild()
            return
        physical_changed = result.physical_description != char.physical_description
        update: dict[str, object] = {
            "name": result.name,
            "personality": result.personality,
            "physical_description": result.physical_description,
            "backstory": result.backstory,
        }
        if physical_changed:
            update["portrait_prompt"] = result.physical_description
        updated = char.model_copy(update=update)
        portrait_path = library_portrait_path(library_id)
        portrait_bytes = portrait_path.read_bytes() if portrait_path.exists() else PLACEHOLDER_PNG
        save_library_character(updated, portrait_bytes)
        self._rebuild()
        self.notify(f"Updated '{result.name}'.", timeout=5)
        if physical_changed:
            self.notify(
                "Portrait no longer matches description — regenerate to refresh.",
                severity="warning",
                timeout=5,
            )

    def _start_delete(self, library_id: str) -> None:
        """Confirm + delete; rebuild the list on success."""
        entry = self._entries.get(library_id)
        if entry is None:
            self.notify("Library entry no longer exists.", severity="error")
            self._rebuild()
            return

        def _after_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                delete_library_character(library_id)
            except Exception:
                _logger.debug("Delete failed", exc_info=True)
                self.notify("Delete failed.", severity="error", timeout=5)
                return
            self.notify(f"Removed '{entry.name}' from library.", timeout=5)
            self._rebuild()

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            ConfirmModal(f"Delete '{entry.name}' from the library? This cannot be undone."),
            _after_confirm,
        )


# Re-export callable type for callers that want to type the dismiss callback.
LibraryPickCallback = Callable[[LibraryPick | None], None]
