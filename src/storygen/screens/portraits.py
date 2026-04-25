"""PortraitsScreen: review and regenerate character portraits."""

from __future__ import annotations

import io
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, cast
from uuid import uuid4

from PIL import Image
from rich.console import RenderableType
from rich_pixels import Pixels
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Click
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from storygen.images.base import ImageProvider
from storygen.images.constants import (
    PORTRAIT_QUALITY,
    PORTRAIT_SIZE,
)
from storygen.images.pricing import image_cost
from storygen.llm.models import Character, CharacterOutfit
from storygen.screens._character_edit_modal import (
    CharacterEditModal,
    CharacterEditResult,
)
from storygen.screens._outfit_modals import (
    OutfitActionModal,
    OutfitActionResult,
    OutfitCreateModal,
    OutfitCreateRequest,
)
from storygen.screens._ref_image_modals import ReferenceImageModal, ReferenceImageResult
from storygen.storage import app_state, paths
from storygen.storage.library import (
    LibraryCharacter,
    LibrarySource,
    save_library_character,
)
from storygen.storage.save import GameSave, save_game
from storygen.util import open_in_system_viewer
from storygen.widgets._header_util import format_cost_subtitle
from storygen.widgets._image_util import render_image_thumbnail

_logger = logging.getLogger(__name__)


class _OutfitThumb(Static):
    """Clickable mini-thumbnail for a single outfit; emits an action modal.

    The screen finds the click target via the widget's ``char_id`` /
    ``outfit_id`` attributes — see :meth:`PortraitsScreen.on_click`.
    """

    DEFAULT_CSS = """
    _OutfitThumb {
        border: round $primary 50%;
        margin-right: 1;
    }
    _OutfitThumb:hover {
        border: round $accent;
    }
    _OutfitThumb.-current {
        border: round $accent;
    }
    """

    def __init__(
        self,
        content: RenderableType,
        *,
        char_id: str,
        outfit_id: str,
        is_current: bool,
        **kwargs: object,
    ) -> None:
        super().__init__(content, **kwargs)  # type: ignore[arg-type]
        self.char_id = char_id
        self.outfit_id = outfit_id
        if is_current:
            self.add_class("-current")


def _atomic_write_png(dest: Path, png_bytes: bytes) -> None:
    """Write ``png_bytes`` to ``dest`` via ``.png.tmp`` + ``os.replace``.

    Mirrors :func:`storygen.pipeline._atomic_write_png`. Duplicated rather
    than imported because ``pipeline`` sits above ``screens`` in the layered
    architecture (see CLAUDE.md), and the body is trivial.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".png.tmp")
    tmp.write_bytes(png_bytes)
    os.replace(tmp, dest)


def _base_portrait_relpath(save_id: str, char_id: str) -> str:
    """Best available relative path for a character's base portrait.

    Uses :func:`paths.latest_portrait_version` to pick the most recent
    base portrait (v2, v3, ...) so reverting from an outfit doesn't lose
    a manually-regenerated base. Falls back to ``-v1.png`` when no base
    portrait has ever been written (art was disabled at wizard time);
    the path may not exist on disk, but downstream renderers handle
    missing files gracefully.
    """
    version = paths.latest_portrait_version(save_id, char_id) or 1
    return paths.relative_character_portrait_path(char_id, version=version)


class PortraitsScreen(Screen[None]):
    """Modal screen listing each character with a Regenerate button."""

    DEFAULT_CSS = """
    PortraitsScreen #portraits-body {
        padding: 1 2;
    }
    PortraitsScreen .portrait-row {
        height: 16;
        margin-bottom: 1;
        padding: 1;
        border: round $primary;
        overflow-y: hidden;
    }
    PortraitsScreen .portrait-main {
        height: auto;
    }
    PortraitsScreen .portrait-thumb {
        width: 28;
        height: 14;
        margin-right: 2;
        border: round $primary 50%;
    }
    PortraitsScreen .portrait-thumb:hover {
        border: round $accent;
    }
    PortraitsScreen .portrait-meta {
        width: 1fr;
    }
    PortraitsScreen .portrait-name {
        text-style: bold;
    }
    PortraitsScreen .portrait-meta Button {
        margin-right: 1;
    }
    PortraitsScreen .outfits-header {
        margin-top: 1;
        text-style: bold;
        color: $text-muted;
    }
    PortraitsScreen .outfits-row {
        height: auto;
        overflow-x: auto;
        margin-top: 1;
    }
    PortraitsScreen .outfit-cell {
        width: 24;
        height: auto;
        margin-right: 1;
    }
    PortraitsScreen .outfit-thumb-mini {
        width: 22;
        height: 12;
    }
    PortraitsScreen .outfit-name {
        width: 22;
    }
    PortraitsScreen .outfit-name.-current {
        color: $accent;
        text-style: bold;
    }
    PortraitsScreen .outfit-buttons {
        height: auto;
        margin-top: 1;
    }
    PortraitsScreen .outfit-buttons Button {
        margin-right: 1;
    }
    PortraitsScreen .portrait-art-disabled {
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "app.pop_screen", "Back"),
        ("f", "open_full_res", "Full Res"),
    ]

    def __init__(self, save: GameSave, image_provider: ImageProvider) -> None:
        super().__init__()
        self._save = save
        self._image_provider = image_provider
        self._scroll = VerticalScroll(id="portraits-body")
        # Track which characters currently have an outfit-create worker in
        # flight so the per-row Add button stays disabled until it lands.
        self._outfit_create_busy: set[str] = set()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "open_full_res":
            return app_state.art_enabled()
        return True

    def action_open_full_res(self) -> None:
        """Open the first available character portrait in the system viewer."""
        for char in self._save.characters:
            if char.portrait_path:
                try:
                    abs_path = paths.safe_join(
                        paths.game_dir(str(self._save.id)), char.portrait_path
                    )
                except ValueError:
                    continue
                open_in_system_viewer(abs_path)
                return

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield self._scroll
        yield Footer()

    def on_mount(self) -> None:
        self._apply_header()
        self._rebuild()

    def _apply_header(self) -> None:
        """Set the screen title to the story theme + cumulative image cost + tokens."""
        self.title = self._save.theme.title
        self.sub_title = format_cost_subtitle(self._save)

    def _rebuild(self) -> None:
        """Clear the scroll container and re-mount one row per character."""
        self._apply_header()
        self._scroll.remove_children()
        art_disabled = not app_state.art_enabled()
        for char in self._save.characters:
            row = Vertical(classes="portrait-row")
            self._scroll.mount(row)
            main = Horizontal(classes="portrait-main")
            row.mount(main)
            main.mount(self._render_thumb(char))
            meta = Vertical(classes="portrait-meta")
            main.mount(meta)
            meta.mount(Static(char.name, classes="portrait-name"))
            first_line_personality = char.personality.split(".", 1)[0]
            meta.mount(Static(first_line_personality))
            regen_button = Button("Regenerate", id=f"regen-{char.id}")
            regen_button.disabled = art_disabled
            meta.mount(regen_button)
            export_button = Button("Export", id=f"export-{char.id}")
            # Export is a file copy — keep it enabled even when art is off.
            # It can only run when there's something to copy.
            export_button.disabled = char.portrait_path is None
            meta.mount(export_button)
            # Edit bio (name / personality / physical / backstory) — always
            # enabled; text-only, no image generation.
            meta.mount(Button("Edit", id=f"edit-bio-{char.id}"))
            # Reference image button — label changes if ref already set.
            ref_label = "Change Ref" if char.reference_image_path else "Ref Image"
            meta.mount(Button(ref_label, id=f"ref-image-{char.id}"))
            if char.reference_image_path is not None:
                meta.mount(Button("Rm Ref", id=f"rm-ref-{char.id}"))
            self._render_outfits_row(row, char, art_disabled=art_disabled)
        if art_disabled:
            self._scroll.mount(
                Static(
                    "(Art generation disabled in Settings)",
                    classes="portrait-art-disabled",
                )
            )

    def _render_thumb(self, char: Character) -> Static:
        if not char.portrait_path:
            thumb = Static("", classes="portrait-thumb")
            thumb.display = False
            return thumb
        try:
            abs_path = paths.safe_join(paths.game_dir(str(self._save.id)), char.portrait_path)
        except ValueError:
            thumb = Static("", classes="portrait-thumb")
            thumb.display = False
            return thumb
        return render_image_thumbnail(
            abs_path,
            size=(96, 48),
            css_class="portrait-thumb",
            placeholder="(no portrait)",
            on_click=open_in_system_viewer,
        )

    def _render_outfit_thumb(
        self,
        char: Character,
        outfit: CharacterOutfit,
    ) -> Static:
        """Render a single outfit's mini-thumbnail (or placeholder)."""
        is_current = outfit.id == char.current_outfit_id
        try:
            abs_path = paths.safe_join(paths.game_dir(str(self._save.id)), outfit.portrait_path)
        except ValueError:
            return Static("[no image]", classes="outfit-thumb-mini", markup=False)
        if not abs_path.exists():
            placeholder = Static(
                "[no image]",
                classes="outfit-thumb-mini",
                markup=False,
            )
            return placeholder
        try:
            with Image.open(abs_path) as im:
                im = im.convert("RGBA")
                im.thumbnail((44, 22))
                return _OutfitThumb(
                    Pixels.from_image(im),
                    char_id=char.id,
                    outfit_id=outfit.id,
                    is_current=is_current,
                    classes="outfit-thumb-mini",
                )
        except Exception:
            return Static("[unavailable]", classes="outfit-thumb-mini", markup=False)

    def _render_outfits_row(
        self,
        row: Vertical,
        char: Character,
        *,
        art_disabled: bool,
    ) -> None:
        """Mount the outfits sub-row (label + thumbs + Add/Revert buttons)."""
        row.mount(Static("Outfits", classes="outfits-header"))
        outfits_container = Horizontal(classes="outfits-row")
        row.mount(outfits_container)
        for outfit in char.outfits:
            cell = Vertical(classes="outfit-cell")
            outfits_container.mount(cell)
            cell.mount(self._render_outfit_thumb(char, outfit))
            is_current = outfit.id == char.current_outfit_id
            label = f"{outfit.name} [active]" if is_current else outfit.name
            name_classes = "outfit-name -current" if is_current else "outfit-name"
            cell.mount(Static(label, classes=name_classes, markup=False))
        # Action buttons row beneath the outfits.
        button_row = Horizontal(classes="outfit-buttons")
        row.mount(button_row)
        add_btn = Button("Add outfit", id=f"add-outfit-{char.id}")
        add_btn.disabled = art_disabled or char.id in self._outfit_create_busy
        button_row.mount(add_btn)
        if char.current_outfit_id is not None:
            button_row.mount(Button("Revert to base", id=f"revert-outfit-{char.id}"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("regen-"):
            char_id = button_id[len("regen-") :]
            char = next((c for c in self._save.characters if c.id == char_id), None)
            if char is None:
                return
            self._regenerate_worker(char, event.button)
            return
        if button_id.startswith("export-"):
            char_id = button_id[len("export-") :]
            char = next((c for c in self._save.characters if c.id == char_id), None)
            if char is None:
                self.notify("Character not found", severity="error")
                return
            self._export_to_library(char)
            return
        if button_id.startswith("edit-bio-"):
            char_id = button_id[len("edit-bio-") :]
            char = next((c for c in self._save.characters if c.id == char_id), None)
            if char is None:
                return
            self._open_edit_bio_modal(char)
            return
        if button_id.startswith("ref-image-"):
            char_id = button_id[len("ref-image-") :]
            char = next((c for c in self._save.characters if c.id == char_id), None)
            if char:
                self._open_ref_image_modal(char)
            return
        if button_id.startswith("rm-ref-"):
            char_id = button_id[len("rm-ref-") :]
            self._remove_reference_image(char_id)
            return
        if button_id.startswith("add-outfit-"):
            char_id = button_id[len("add-outfit-") :]
            char = next((c for c in self._save.characters if c.id == char_id), None)
            if char is None:
                return
            self._open_create_outfit_modal(char)
            return
        if button_id.startswith("revert-outfit-"):
            char_id = button_id[len("revert-outfit-") :]
            char = next((c for c in self._save.characters if c.id == char_id), None)
            if char is None:
                return
            self._revert_to_base(char)
            return

    def on_click(self, event: Click) -> None:
        """Outfit-thumb click → action modal.

        Attached at the screen level so a single dispatcher handles every
        row. The main portrait thumbnail (rendered by
        :func:`render_image_thumbnail` with ``on_click``) handles its own
        click locally and stops here naturally — the screen-level handler
        ignores anything that isn't an :class:`_OutfitThumb`.
        """
        widget = event.widget
        if isinstance(widget, _OutfitThumb):
            self._open_outfit_action_modal(widget.char_id, widget.outfit_id)

    def _export_to_library(self, char: Character) -> None:
        """Copy ``char`` (with its current portrait) into the cross-game library.

        No dedup: re-exporting the same character creates another library entry
        with a fresh ``uuid4`` id. Any filesystem error is surfaced via
        ``notify`` and never crashes the screen.
        """
        if char.portrait_path is None:
            self.notify(
                "This character has no portrait yet — cannot export.",
                severity="error",
                timeout=5,
            )
            return
        try:
            portrait_abs = paths.safe_join(paths.game_dir(str(self._save.id)), char.portrait_path)
            portrait_bytes = portrait_abs.read_bytes()
            lib_char = LibraryCharacter(
                id=uuid4().hex,
                name=char.name,
                backstory=char.backstory,
                personality=char.personality,
                physical_description=char.physical_description,
                portrait_prompt=char.portrait_prompt or char.physical_description,
                exported_at=datetime.now(UTC),
                exported_from=LibrarySource(
                    save_id=str(self._save.id),
                    save_title=self._save.theme.title,
                ),
            )
            # Include reference image if present.
            ref_bytes: bytes | None = None
            if char.reference_image_path:
                ref_abs = paths.safe_join(
                    paths.game_dir(str(self._save.id)), char.reference_image_path
                )
                if ref_abs.exists():
                    ref_bytes = ref_abs.read_bytes()

            save_library_character(lib_char, portrait_bytes, reference_bytes=ref_bytes)
            self.notify(f"Exported '{char.name}' to library.", timeout=5)
        except Exception:
            _logger.debug("Export failed", exc_info=True)
            self.notify("Export failed — check logs for details.", severity="error", timeout=5)

    @work(exit_on_error=False)
    async def _regenerate_worker(self, char: Character, button: Button) -> None:
        if not app_state.art_enabled():
            self.notify(
                "Art generation is disabled in Settings.",
                severity="warning",
                timeout=5,
            )
            return
        original_label = button.label
        button.disabled = True
        button.label = "Working…"
        try:
            png_bytes = await self._image_provider.generate_portrait(
                char.physical_description,
                transparent=True,
                art_style=self._save.art_style,
            )
            save_id = str(self._save.id)
            paths.ensure_game_dirs(save_id)
            version = paths.next_portrait_version(save_id, char.id)
            dest = paths.character_portrait_path(save_id, char.id, version=version)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(png_bytes)
            new_rel = str(dest.relative_to(paths.game_dir(save_id)))
            updated = char.model_copy(update={"portrait_path": new_rel})
            self._save.characters = [
                updated if c.id == char.id else c for c in self._save.characters
            ]
            self._save.total_image_cost_usd += image_cost(
                self._save.image_config.provider,
                model=self._save.image_config.model,
                size=PORTRAIT_SIZE,
                quality=PORTRAIT_QUALITY,
            )
            save_game(self._save)
            self._rebuild()
            self.notify(f"Regenerated portrait for {char.name} (v{version}).", timeout=5)
        except Exception:
            _logger.debug("Portrait regeneration failed", exc_info=True)
            self.notify("Portrait regeneration failed.", severity="error", timeout=5)
            if button.is_attached:
                button.disabled = False
                button.label = cast(str, original_label)

    # ---- Bio edit flow ---------------------------------------------------

    def _open_edit_bio_modal(self, char: Character) -> None:
        """Push the bio-edit modal; apply its result on save."""

        def _after(result: CharacterEditResult | None) -> None:
            if result is None:
                return
            self._apply_bio_edit(char.id, result)

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            CharacterEditModal(char),
            _after,
        )

    def _apply_bio_edit(self, char_id: str, result: CharacterEditResult) -> None:
        """Merge the modal's result into the save and persist.

        If ``physical_description`` changed, ``portrait_prompt`` is synced
        to the new value so a subsequent Regenerate uses the updated
        description. The on-disk portrait file is NOT modified — the user
        must press Regenerate to actually refresh the image.

        Outfits (which carry their own independent ``portrait_prompt`` /
        ``description``) are NOT touched by bio edits; regenerating outfits
        individually is the only way to sync them to a new
        ``physical_description``.
        """
        idx = next(
            (i for i, c in enumerate(self._save.characters) if c.id == char_id),
            None,
        )
        if idx is None:
            return
        c = self._save.characters[idx]
        update: dict[str, object] = {
            "name": result.name,
            "personality": result.personality,
            "physical_description": result.physical_description,
            "backstory": result.backstory,
        }
        physical_changed = result.physical_description != c.physical_description
        if physical_changed:
            update["portrait_prompt"] = result.physical_description
        self._save.characters[idx] = c.model_copy(update=update)
        save_game(self._save)
        self._rebuild()
        self.notify(f"Updated {result.name}.", timeout=5)
        if physical_changed:
            self.notify(
                "Portrait no longer matches — press Regenerate to refresh.",
                severity="warning",
                timeout=5,
            )

    # ---- Reference image flows -------------------------------------------

    def _open_ref_image_modal(self, char: Character) -> None:
        """Open the reference image picker modal for a character."""

        def _after(result: ReferenceImageResult | None) -> None:
            if result is None:
                return
            self._apply_ref_image_worker(result, char)

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            ReferenceImageModal(char.name),
            _after,
        )

    @work(exit_on_error=False)
    async def _apply_ref_image_worker(self, result: ReferenceImageResult, char: Character) -> None:
        """Process a reference image selection — store file and optionally generate."""
        save_id = str(self._save.id)

        # Load and convert to PNG bytes.
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

        # Write reference image atomically.
        ref_path = paths.character_reference_path(save_id, char.id)
        _atomic_write_png(ref_path, png_bytes)
        ref_rel = paths.relative_character_reference_path(char.id)

        if result.mode == "use_as_is":
            # Copy reference as the next portrait version.
            version = paths.next_portrait_version(save_id, char.id)
            portrait_path = paths.character_portrait_path(save_id, char.id, version=version)
            _atomic_write_png(portrait_path, png_bytes)
            new_rel = paths.relative_character_portrait_path(char.id, version=version)
            updated = char.model_copy(
                update={
                    "portrait_path": new_rel,
                    "portrait_prompt": "(from reference image)",
                    "reference_image_path": ref_rel,
                }
            )
        else:
            # Style-transfer: generate portrait using reference image.
            try:
                generated = await self._image_provider.generate_portrait(
                    char.physical_description,
                    transparent=True,
                    art_style=self._save.art_style,
                    reference_image=png_bytes,
                )
            except Exception:
                _logger.debug("Style-transfer failed", exc_info=True)
                self.notify("Style-transfer failed.", severity="error", timeout=5)
                return
            version = paths.next_portrait_version(save_id, char.id)
            portrait_path = paths.character_portrait_path(save_id, char.id, version=version)
            _atomic_write_png(portrait_path, generated)
            new_rel = paths.relative_character_portrait_path(char.id, version=version)
            updated = char.model_copy(
                update={
                    "portrait_path": new_rel,
                    "portrait_prompt": char.physical_description,
                    "reference_image_path": ref_rel,
                }
            )
            # Track cost.
            cost = image_cost(
                self._save.image_config.provider,
                model=self._save.image_config.model,
                size=PORTRAIT_SIZE,
                quality=PORTRAIT_QUALITY,
            )
            self._save.total_image_cost_usd += cost

        self._save.characters = [updated if c.id == char.id else c for c in self._save.characters]
        save_game(self._save)
        self._rebuild()
        self.notify(f"Reference image set for {char.name}", timeout=5)

    def _remove_reference_image(self, char_id: str) -> None:
        """Clear reference_image_path from a character; portrait stays as-is."""
        char = next((c for c in self._save.characters if c.id == char_id), None)
        if char is None:
            return
        updated = char.model_copy(update={"reference_image_path": None})
        self._save.characters = [updated if c.id == char_id else c for c in self._save.characters]
        save_game(self._save)
        self._rebuild()
        self.notify(f"Reference image removed for {char.name}", timeout=5)

    # ---- Outfit flows ----------------------------------------------------

    def _open_create_outfit_modal(self, char: Character) -> None:
        """Push the create modal; on success kick off the gen worker."""
        if not app_state.art_enabled():
            self.notify(
                "Art generation is disabled in Settings.",
                severity="warning",
                timeout=5,
            )
            return
        if char.id in self._outfit_create_busy:
            return

        def _after(request: OutfitCreateRequest | None) -> None:
            if request is None:
                return
            self._outfit_create_busy.add(char.id)
            self._rebuild()
            self._create_outfit_worker(char, request)

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            OutfitCreateModal(char.name),
            _after,
        )

    @work(exit_on_error=False)
    async def _create_outfit_worker(self, char: Character, request: OutfitCreateRequest) -> None:
        try:
            # Strip a trailing period so we don't double-up when joining with
            # ". Outfit: ..." — the physical_description usually already ends
            # in a sentence, the suffix should look like one continuous prose.
            base = char.physical_description.rstrip().rstrip(".")
            combined = f"{base}. Outfit: {request.description}."
            png_bytes = await self._image_provider.generate_portrait(
                combined,
                transparent=True,
                art_style=self._save.art_style,
            )
            save_id = str(self._save.id)
            paths.ensure_game_dirs(save_id)
            outfit_id = uuid4().hex
            dest = paths.character_outfit_path(save_id, char.id, outfit_id)
            _atomic_write_png(dest, png_bytes)
            outfit = CharacterOutfit(
                id=outfit_id,
                name=request.name,
                description=request.description,
                portrait_path=paths.relative_character_outfit_path(char.id, outfit_id),
                portrait_prompt=combined,
                created_at=datetime.now(UTC),
            )
            self._append_outfit(char.id, outfit)
            self._save.total_image_cost_usd += image_cost(
                self._save.image_config.provider,
                model=self._save.image_config.model,
                size=PORTRAIT_SIZE,
                quality=PORTRAIT_QUALITY,
            )
            save_game(self._save)
            self.notify(
                f"Added outfit '{request.name}' for {char.name}.",
                timeout=5,
            )
        except Exception:
            _logger.debug("Outfit generation failed", exc_info=True)
            self.notify("Outfit generation failed.", severity="error", timeout=5)
        finally:
            self._outfit_create_busy.discard(char.id)
            self._rebuild()

    def _append_outfit(self, char_id: str, outfit: CharacterOutfit) -> None:
        """Append ``outfit`` to the named character (in-place on the save)."""
        for idx, c in enumerate(self._save.characters):
            if c.id == char_id:
                self._save.characters[idx] = c.model_copy(update={"outfits": [*c.outfits, outfit]})
                return

    def _open_outfit_action_modal(self, char_id: str, outfit_id: str) -> None:
        char = next((c for c in self._save.characters if c.id == char_id), None)
        if char is None:
            return
        outfit = next((o for o in char.outfits if o.id == outfit_id), None)
        if outfit is None:
            return
        is_current = outfit.id == char.current_outfit_id

        def _after(result: OutfitActionResult | None) -> None:
            self._handle_outfit_action(char_id, outfit_id, result)

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            OutfitActionModal(
                outfit.name,
                outfit.description,
                is_current=is_current,
            ),
            _after,
        )

    def _handle_outfit_action(
        self,
        char_id: str,
        outfit_id: str,
        result: OutfitActionResult | None,
    ) -> None:
        """Apply the action modal's result against the live save."""
        if result is None:
            return
        char = next((c for c in self._save.characters if c.id == char_id), None)
        if char is None:
            return
        outfit = next((o for o in char.outfits if o.id == outfit_id), None)
        if outfit is None:
            return
        if result == "set":
            self._set_outfit_as_current(char, outfit)
        elif result == "delete":
            self._delete_outfit(char, outfit)

    def _set_outfit_as_current(self, char: Character, outfit: CharacterOutfit) -> None:
        for idx, c in enumerate(self._save.characters):
            if c.id == char.id:
                self._save.characters[idx] = c.model_copy(
                    update={
                        "current_outfit_id": outfit.id,
                        "portrait_path": outfit.portrait_path,
                        "portrait_prompt": outfit.portrait_prompt,
                    }
                )
                break
        save_game(self._save)
        self._rebuild()
        self.notify(
            f"'{outfit.name}' is now {char.name}'s active outfit.",
            timeout=5,
        )

    def _delete_outfit(self, char: Character, outfit: CharacterOutfit) -> None:
        was_current = outfit.id == char.current_outfit_id
        save_id = str(self._save.id)
        # Build the post-delete character: drop the outfit, optionally
        # revert active fields back to the latest existing base portrait.
        update: dict[str, object] = {
            "outfits": [o for o in char.outfits if o.id != outfit.id],
        }
        if was_current:
            update["current_outfit_id"] = None
            update["portrait_path"] = _base_portrait_relpath(save_id, char.id)
            update["portrait_prompt"] = char.physical_description
        for idx, c in enumerate(self._save.characters):
            if c.id == char.id:
                self._save.characters[idx] = c.model_copy(update=update)
                break
        # Best-effort delete of the on-disk PNG; missing file is fine.
        try:
            paths.character_outfit_path(save_id, char.id, outfit.id).unlink(missing_ok=True)
        except OSError:
            _logger.debug("Could not remove outfit file", exc_info=True)
            self.notify(
                "Could not remove outfit image file.",
                severity="warning",
                timeout=5,
            )
        save_game(self._save)
        self._rebuild()
        self.notify(f"Deleted outfit '{outfit.name}'.", timeout=5)

    def _revert_to_base(self, char: Character) -> None:
        if char.current_outfit_id is None:
            return
        save_id = str(self._save.id)
        for idx, c in enumerate(self._save.characters):
            if c.id == char.id:
                self._save.characters[idx] = c.model_copy(
                    update={
                        "current_outfit_id": None,
                        "portrait_path": _base_portrait_relpath(save_id, char.id),
                        "portrait_prompt": char.physical_description,
                    }
                )
                break
        save_game(self._save)
        self._rebuild()
        self.notify(f"Reverted {char.name} to base portrait.", timeout=5)
