"""WizardScreen + headless WizardFlow.

`WizardFlow` (the pure state machine that owns LLM + image calls) was moved
to :mod:`storygen.runtime.wizard_flow` (ARC-005) so the FastAPI surface can
reuse it without importing a Textual-coupled module. It is re-exported below
for back-compat with existing ``from storygen.screens.wizard import WizardFlow``
imports. `WizardScreen` is the Textual wrapper that drives WizardFlow
step-by-step and remains here.
"""

from __future__ import annotations

import contextlib
import io
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import Enum, auto
from typing import ClassVar, Literal, cast
from uuid import uuid4

from PIL import Image as PILImage
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    RadioButton,
    RadioSet,
    Select,
    Static,
    TextArea,
)

from storygen.core.presets import StoryPreset
from storygen.llm.models import (
    Character,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.runtime.wizard_flow import WizardFlow  # re-exported below
from storygen.screens._ref_image_modals import ReferenceImageModal, ReferenceImageResult
from storygen.screens.library_browser import CharacterCatalogScreen, LibraryPick
from storygen.storage import app_state, paths
from storygen.storage.library import LibraryCharacter, library_portrait_path
from storygen.storage.save import (
    GameSave,
    NarrationStyle,
    Pacing,
    ReaderLevel,
)

# Re-export so ``from storygen.screens.wizard import WizardFlow`` keeps working.
__all__ = ["WizardFlow", "WizardScreen", "WizardStep"]

# Order matches the pacing SelectionList in the wizard UI; index lookup happens
# once per wizard run but keeping it module-level avoids rebuilding the tuple on
# every _advance_worker call (QA-010) and documents the contract in one place.
_PACING_OPTIONS: tuple[str, ...] = ("slow", "moderate", "fast")


class WizardStep(Enum):
    """Ordered steps in the new-game wizard."""

    THEME = auto()
    TONE = auto()
    STYLE = auto()
    ART_STYLE = auto()
    LENGTH = auto()
    READER_LEVEL = auto()
    CHARACTERS = auto()
    CONFIRM = auto()


_TonePreset = Literal[
    "silly",
    "serious",
    "dark",
    "whimsical",
    "mysterious",
    "romantic",
    "action",
    "unexpected",
    "custom",
]


TONE_PRESETS: list[tuple[str, str]] = [
    ("Silly", "silly"),
    ("Serious", "serious"),
    ("Dark", "dark"),
    ("Whimsical", "whimsical"),
    ("Mysterious", "mysterious"),
    ("Romantic", "romantic"),
    ("Action", "action"),
    ("Unexpected", "unexpected"),
    ("Custom (use descriptor below)", "custom"),
]

STYLE_OPTIONS: list[tuple[str, str]] = [
    ("First Person", "first_person"),
    ("Third Person", "third_person"),
    ("Fourth Wall (characters can address player)", "fourth_wall"),
]

READER_LEVEL_OPTIONS: list[tuple[str, str]] = [
    ("Ages 0-5", "ages_0_5"),
    ("Ages 6-10", "ages_6_10"),
    ("Ages 11-15", "ages_11_15"),
    ("Ages 15+", "ages_15_plus"),
]


def valid_reader_level_values() -> set[str]:
    return {value for _label, value in READER_LEVEL_OPTIONS}


def valid_tone_preset_values() -> set[str]:
    return {value for _label, value in TONE_PRESETS}


def valid_narration_style_values() -> set[str]:
    return {value for _label, value in STYLE_OPTIONS}


class WizardScreen(Screen[None]):
    """Textual wrapper around WizardFlow — guides the player through game setup."""

    DEFAULT_CSS = """
    WizardScreen #wizard-body {
        padding: 1 2;
    }
    WizardScreen #wizard-step {
        text-style: bold;
        color: $accent;
    }
    WizardScreen #wizard-hint {
        margin-bottom: 1;
        color: $text-muted;
    }
    WizardScreen #wizard-confirm-summary {
        margin-bottom: 1;
    }
    WizardScreen #wizard-cast-list {
        padding: 1 0;
    }
    WizardScreen #btn-next {
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "app.pop_screen", "Back"),
        ("ctrl+l", "add_from_library", "Add from Library"),
        ("ctrl+i", "import_reference_image", "Import Image"),
    ]

    current_step: reactive[WizardStep] = reactive(WizardStep.THEME)

    def __init__(
        self,
        *,
        text_config: TextProviderConfig,
        flow: WizardFlow | None = None,
        on_wizard_complete: Callable[[GameSave], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__()
        self._text_config = text_config
        self._flow = flow
        self._on_complete = on_wizard_complete

        # Pull persisted defaults so each widget can be pre-filled below.
        defaults = app_state.read_wizard_defaults()
        # Validate Select values against the option list — a stale persisted
        # preset would otherwise crash Select with "value not in options".
        tone_preset_default = (
            defaults.tone_preset
            if defaults.tone_preset in valid_tone_preset_values()
            else app_state.DEFAULT_TONE_PRESET
        )
        narration_style_default = (
            defaults.narration_style
            if defaults.narration_style in valid_narration_style_values()
            else app_state.DEFAULT_NARRATION_STYLE
        )
        self._defaults = defaults

        self._theme: Theme | None = None
        self._tone: Tone | None = None
        self._style: NarrationStyle = cast(NarrationStyle, narration_style_default)
        self._characters: list[Character] = []
        # character.id -> library_id for cast entries imported from the
        # cross-game library. Consumed by build_initial_save (it copies the
        # cached portrait instead of generating a new one). Keyed by
        # character.id so re-imports are idempotent per save.
        self._imported_from_library_ids: dict[str, str] = {}
        # Pending reference image data for characters added via Import Image.
        # Maps char_id -> (source_path, png_bytes) for the reference image.
        self._pending_ref_images: dict[str, tuple[str, bytes]] = {}
        # Maps char_id -> generated portrait bytes (style-transfer mode).
        self._pending_portrait_bytes: dict[str, bytes] = {}
        self._user_character_prompt: str = ""
        self._importing = False
        self._art_style: str = defaults.art_style or app_state.DEFAULT_ART_STYLE
        self._target_major_beats: int = defaults.target_major_beats

        self._step_label = Static("", id="wizard-step")
        self._hint = Static("", id="wizard-hint")
        self._theme_area = TextArea(text=defaults.theme, id="wizard-theme")
        self._tone_select = Select(
            TONE_PRESETS, value=tone_preset_default, allow_blank=False, id="wizard-tone"
        )
        self._tone_descriptor = Input(
            value=defaults.tone_descriptor,
            placeholder="Custom tone descriptor (e.g. melancholy comedy)",
            id="wizard-tone-custom",
        )
        self._style_select = Select(
            STYLE_OPTIONS,
            value=narration_style_default,
            allow_blank=False,
            id="wizard-style",
        )
        self._art_style_input = Input(
            value=self._art_style,
            placeholder="e.g. children's story book, watercolor, noir comic",
            id="wizard-art-style",
        )
        self._length_input = Input(
            value=str(defaults.target_major_beats),
            placeholder=(f"{app_state.MIN_TARGET_MAJOR_BEATS}-{app_state.MAX_TARGET_MAJOR_BEATS}"),
            id="wizard-length",
            restrict=r"\d*",
        )
        self._pacing_input = RadioSet(
            "Slow — long narration, fewer but weightier choices",
            RadioButton("Moderate — balanced narration and choices", value=True),
            "Fast — short narration, more frequent choices",
            id="wizard-pacing",
        )
        self._pacing: str = defaults.pacing
        reader_level_default = (
            defaults.reader_level
            if defaults.reader_level in valid_reader_level_values()
            else app_state.DEFAULT_READER_LEVEL
        )
        self._reader_level: str = reader_level_default
        self._reader_level_select = Select(
            READER_LEVEL_OPTIONS,
            value=reader_level_default,
            allow_blank=False,
            id="wizard-reader-level",
        )
        self._char_area = TextArea(text=defaults.characters, id="wizard-char")
        self._cast_list = Static("", id="wizard-cast-list")
        self._confirm_summary = Static("", id="wizard-confirm-summary")
        self._progress = Static("", id="wizard-progress")
        self._next_button = Button("Next", id="btn-next")
        self._library_button = Button("Import from Library", id="btn-library", variant="primary")
        self._preset_button: Button = Button("Load Preset", id="btn-preset", variant="primary")
        self._save_preset_button: Button = Button("Save as Preset", id="btn-save-preset")
        self._save_to_catalog_checkbox = Checkbox(
            "Save generated characters to catalog",
            value=defaults.save_to_catalog,
            id="wizard-save-catalog",
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="wizard-body"):
            yield self._step_label
            yield self._hint
            yield self._theme_area
            yield self._tone_select
            yield self._tone_descriptor
            yield self._style_select
            yield self._art_style_input
            yield self._length_input
            yield self._pacing_input
            yield self._reader_level_select
            yield self._char_area
            yield self._library_button
            yield self._save_to_catalog_checkbox
            yield self._cast_list
            yield self._confirm_summary
            yield self._next_button
        yield Footer()

    def on_mount(self) -> None:
        self._render_step()

    def watch_current_step(self) -> None:
        self._render_step()
        # Visibility of the "Add from Library" footer binding is keyed to the
        # CHARACTERS step; Textual re-reads check_action after this.
        self.refresh_bindings()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in ("add_from_library", "import_reference_image"):
            return self.current_step == WizardStep.CHARACTERS
        return True

    def action_add_from_library(self) -> None:
        """Open the library browser; on pick, append to in-progress cast."""
        if self.current_step != WizardStep.CHARACTERS:
            return
        # self.app is typed App[None] (Textual base) but is StoryGenApp at runtime
        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            CharacterCatalogScreen(),
            self._on_library_pick,
        )

    def _on_library_pick(self, picked: LibraryPick | None) -> None:
        """Handle the library browser dismissing with a picked character.

        Appends a save-local :class:`Character` built from ``picked.character``
        to the wizard's in-progress cast. When ``picked.adapt`` is True the
        backstory is first rewritten for the current theme via an async LLM
        call (see :meth:`_adapt_then_append_worker`); otherwise the keep-as-is
        path fires synchronously. The portrait file copy itself happens at
        ``build_initial_save`` time (see ``library_import_ids`` there); here
        we only commit the metadata.
        """
        if picked is None:
            return
        # Defensive: verify the portrait file still exists. A race where the
        # library was edited between list time and import time lands here.
        if not library_portrait_path(picked.character.id).exists():
            self.notify(
                f"Portrait for '{picked.character.name}' is missing — cannot import.",
                severity="error",
                timeout=5,
            )
            return
        if picked.mode == "adapt":
            if self._theme is None or self._flow is None:
                # Adapt needs a theme, which only exists after the THEME step.
                # Defensive: the Library binding is gated to the CHARACTERS
                # step (where _theme is guaranteed to be set) so we shouldn't
                # actually land here — surface an error rather than silently
                # falling back to keep-as-is.
                self.notify(
                    "Cannot adapt before a theme is chosen — try keep-as-is.",
                    severity="error",
                    timeout=5,
                )
                return
            self._adapt_then_append_worker(picked.character)
            return
        self._append_library_character(picked.character)

    def _append_library_character(self, lib: LibraryCharacter) -> None:
        """Commit ``lib`` to the in-progress cast (no backstory rewrite).

        Guards against a late-arriving adapt worker mutating the cast after
        the wizard has advanced past CHARACTERS: the adapt LLM call can take
        up to ~90 s, during which the user may hit Next. If this fires from
        a non-CHARACTERS step we discard and surface a warning instead of
        silently appending a cast entry the user can no longer edit.
        """
        if self.current_step != WizardStep.CHARACTERS:
            self.notify(
                "Discarded late library import — wizard already moved on.",
                severity="warning",
                timeout=5,
            )
            return
        new_char_id = uuid4().hex
        portrait_rel = paths.relative_character_portrait_path(new_char_id, version=1)
        new_char = Character(
            id=new_char_id,
            name=lib.name,
            backstory=lib.backstory,
            personality=lib.personality,
            physical_description=lib.physical_description,
            portrait_path=portrait_rel,
            portrait_prompt=lib.portrait_prompt,
            # Overwritten to save.root_node_id inside build_initial_save; use
            # the same "pending" convention the pipeline uses for mid-story
            # character introductions until the node id exists.
            introduced_at_node_id="pending",
        )
        self._characters.append(new_char)
        self._imported_from_library_ids[new_char_id] = lib.id
        self.notify(f"Added '{lib.name}' to cast.", timeout=5)
        self._refresh_cast_list()

    @work(exit_on_error=False)
    async def _adapt_then_append_worker(self, lib: LibraryCharacter) -> None:
        """Run ``WizardFlow.adapt_library_character`` then commit to the cast.

        On LLM failure, surface the error and leave the cast unchanged — the
        user can re-pick and choose keep-as-is explicitly.
        """
        if self._theme is None or self._flow is None:
            self.notify("Cannot adapt — wizard state incomplete.", severity="error")
            return
        self._importing = True
        self._set_busy(False)
        self.notify(f"Adapting '{lib.name}' backstory to new theme…", timeout=5)
        try:
            adapted = await self._flow.adapt_library_character(lib, self._theme)
        except Exception as exc:
            self.notify(
                f"Couldn't adapt '{lib.name}' — {type(exc).__name__}. Try keep-as-is or retry.",
                severity="error",
                timeout=5,
            )
            return
        finally:
            self._importing = False
            self._set_busy(False)
        self._append_library_character(adapted)

    # ---- Reference image import flow ------------------------------------

    def action_import_reference_image(self) -> None:
        """Open the reference image modal; on confirm, append a new character."""
        if self.current_step != WizardStep.CHARACTERS:
            return
        # self.app is typed App[None] (Textual base) but is StoryGenApp at runtime
        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            ReferenceImageModal("New Character", default_style=self._art_style),
            self._on_ref_image_pick,
        )

    def _on_ref_image_pick(self, result: ReferenceImageResult | None) -> None:
        """Handle the reference image modal dismissing with a selection."""
        if result is None:
            return
        if self.current_step != WizardStep.CHARACTERS:
            self.notify(
                "Discarded late reference import — wizard already moved on.",
                severity="warning",
                timeout=5,
            )
            return
        self._apply_ref_image_worker(result)

    @work(exit_on_error=False)
    async def _apply_ref_image_worker(self, result: ReferenceImageResult) -> None:
        """Create a new character from a reference image selection."""
        new_char_id = uuid4().hex
        ref_rel = paths.relative_character_reference_path(new_char_id)

        # Load and convert to PNG.
        try:
            with PILImage.open(result.source_path) as im:
                im = im.convert("RGBA")
                buf = io.BytesIO()
                im.save(buf, format="PNG")
                png_bytes = buf.getvalue()
        except Exception as exc:
            self.notify(f"Failed to load image: {exc}", severity="error", timeout=5)
            return

        if result.mode == "use_as_is":
            portrait_rel = paths.relative_character_portrait_path(new_char_id, version=1)
            new_char = Character(
                id=new_char_id,
                name="New Character",
                backstory="",
                personality="",
                physical_description="As shown in reference image",
                portrait_path=portrait_rel,
                portrait_prompt="(from reference image)",
                introduced_at_node_id="pending",
                reference_image_path=ref_rel,
            )
            self._characters.append(new_char)
            self._pending_ref_images[new_char_id] = (str(result.source_path), png_bytes)
        else:
            # Style-transfer: generate portrait via image provider.
            try:
                # WizardFlow.image_provider is Optional[ImageProviderLike]; pyright
                # can't narrow from the runtime guard above (_flow is initialized
                # before this branch is reachable).
                image_provider = self._flow.image_provider  # type: ignore[union-attr]
                generated = await image_provider.generate_portrait(  # type: ignore[union-attr]
                    "As shown in reference image",
                    transparent=True,
                    art_style=result.style_prompt or self._art_style,
                    reference_image=png_bytes,
                )
            except Exception as exc:
                self.notify(f"Style-transfer failed: {exc}", severity="error", timeout=5)
                return
            portrait_rel = paths.relative_character_portrait_path(new_char_id, version=1)
            new_char = Character(
                id=new_char_id,
                name="New Character",
                backstory="",
                personality="",
                physical_description="As shown in reference image",
                portrait_path=portrait_rel,
                portrait_prompt="As shown in reference image",
                introduced_at_node_id="pending",
                reference_image_path=ref_rel,
            )
            self._characters.append(new_char)
            self._pending_ref_images[new_char_id] = (str(result.source_path), png_bytes)
            self._pending_portrait_bytes[new_char_id] = generated

        self.notify("Added character from reference image.", timeout=5)
        self._refresh_cast_list()

    def _refresh_cast_list(self) -> None:
        """Re-render the cast list from ``self._characters``."""
        if not self._characters:
            self._cast_list.update("")
            self._cast_list.display = False
            return
        parts: list[str] = []
        for c in self._characters:
            if c.id in self._imported_from_library_ids:
                source = "[$text-muted]★library[/]"
            elif c.id in self._pending_ref_images:
                source = "[$text-muted]★ref-image[/]"
            else:
                source = "[$text-muted]★generated[/]"
            parts.append(f"  {c.name} {source}  [@click=screen._remove_character('{c.id}')]✕[/]")
        self._cast_list.update("Cast:\n" + "\n".join(parts))
        self._cast_list.display = True

    def _remove_character(self, char_id: str) -> None:
        """Remove a character from the in-progress cast by id."""
        name = next((c.name for c in self._characters if c.id == char_id), None)
        self._characters = [c for c in self._characters if c.id != char_id]
        self._imported_from_library_ids.pop(char_id, None)
        self._pending_ref_images.pop(char_id, None)
        self._pending_portrait_bytes.pop(char_id, None)
        self._refresh_cast_list()
        if name is not None:
            self.notify(f"Removed '{name}' from cast.", timeout=5)

    def _step_widgets(self) -> list[object]:
        return [
            self._theme_area,
            self._tone_select,
            self._tone_descriptor,
            self._style_select,
            self._art_style_input,
            self._length_input,
            self._pacing_input,
            self._reader_level_select,
            self._char_area,
            self._library_button,
            self._cast_list,
            self._preset_button,
            self._save_preset_button,
            self._save_to_catalog_checkbox,
            self._confirm_summary,
            self._progress,
        ]

    def _render_step(self) -> None:
        self._step_label.update(f"Step: {self.current_step.name}")
        # Hide every step widget; the active step re-shows what it needs.
        for widget in self._step_widgets():
            # _step_widgets returns a heterogeneous Iterable[Widget]; pyright can't
            # narrow every element to the subset that has a `display` attribute.
            widget.display = False  # pyright: ignore[reportAttributeAccessIssue]

        if self.current_step == WizardStep.THEME:
            self._hint.update("Describe your story setting, or leave blank for a surprise.")
            self._theme_area.display = True
            self._preset_button.display = True
            self._theme_area.focus()
        elif self.current_step == WizardStep.TONE:
            self._hint.update("Pick a tone preset. Choose Custom to enter your own descriptor.")
            self._tone_select.display = True
            self._tone_descriptor.display = cast(str, self._tone_select.value) == "custom"
        elif self.current_step == WizardStep.STYLE:
            self._hint.update("Choose narration style.")
            self._style_select.display = True
        elif self.current_step == WizardStep.ART_STYLE:
            self._hint.update(
                "Describe the visual style for illustrations (applied to portraits"
                " and scene images)."
            )
            self._art_style_input.display = True
            self._art_style_input.focus()
        elif self.current_step == WizardStep.LENGTH:
            self._hint.update(
                "Approximate story length in major beats — guides pacing toward"
                f" an ending. Default {app_state.DEFAULT_TARGET_MAJOR_BEATS};"
                f" clamped to {app_state.MIN_TARGET_MAJOR_BEATS}-"
                f"{app_state.MAX_TARGET_MAJOR_BEATS}."
            )
            self._length_input.display = True
            self._length_input.focus()
            self._pacing_input.display = True
        elif self.current_step == WizardStep.READER_LEVEL:
            self._hint.update(
                "Select the target reader age range. This adjusts vocabulary,"
                " sentence complexity, and thematic depth."
            )
            self._reader_level_select.display = True
        elif self.current_step == WizardStep.CHARACTERS:
            self._hint.update(
                "Describe characters you want (names, traits, count, etc.)"
                " or leave blank to let the LLM invent them.\n"
                "Press [b]Ctrl+L[/] to import from your character library"
                " or [b]Ctrl+I[/] to import a reference image."
            )
            self._char_area.display = True
            self._library_button.display = True
            self._save_to_catalog_checkbox.display = True
            self._char_area.focus()
            self._refresh_cast_list()
        elif self.current_step == WizardStep.CONFIRM:
            self._hint.update("Review your choices, then begin the story.")
            self._render_confirm_summary()
            self._confirm_summary.display = True
            self._save_preset_button.display = True
            self._progress.display = True

        if not self._next_button.disabled:
            self._next_button.label = _label_for_step(self.current_step)

    def _render_confirm_summary(self) -> None:
        tone_str = ""
        if self._tone is not None:
            if self._tone.preset == "custom":
                tone_str = f"custom: {self._tone.custom_descriptor}"
            elif self._tone.custom_descriptor:
                tone_str = f"{self._tone.preset} ({self._tone.custom_descriptor})"
            else:
                tone_str = self._tone.preset
        cast_str = (
            ", ".join(c.name for c in self._characters)
            if self._characters
            else "(no characters yet)"
        )
        reader_label = next(
            (label for label, val in READER_LEVEL_OPTIONS if val == self._reader_level),
            self._reader_level,
        )
        summary = (
            f"Theme: {self._theme.title if self._theme else ''}\n"
            f"Tone: {tone_str}\n"
            f"Style: {self._style}\n"
            f"Art: {self._art_style}\n"
            f"Length: {self._target_major_beats} beats\n"
            f"Reader level: {reader_label}\n"
            f"Cast: {cast_str}"
        )
        self._confirm_summary.update(summary)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "wizard-tone":
            self._tone_descriptor.display = event.value == "custom"

    @work(exit_on_error=False)
    async def _auto_export_to_catalog(self, save: GameSave) -> None:
        """Fire-and-forget: export newly generated characters to the catalog."""
        from storygen.storage.library import (
            PLACEHOLDER_PNG,
            LibrarySource,
            list_library_characters,
            save_library_character,
        )

        save_id = str(save.id)
        existing_names: set[str] = set[str]()
        with contextlib.suppress(Exception):
            existing_names = {c.name for c in list_library_characters()}

        for char in save.characters:
            if char.id in self._imported_from_library_ids:
                continue
            if char.name in existing_names:
                continue
            if char.portrait_path:
                abs_path = paths.game_dir(save_id) / char.portrait_path
                portrait_bytes = abs_path.read_bytes() if abs_path.exists() else PLACEHOLDER_PNG
            else:
                portrait_bytes = PLACEHOLDER_PNG

            ref_bytes: bytes | None = None
            if char.reference_image_path:
                ref_abs = paths.game_dir(save_id) / char.reference_image_path
                if ref_abs.exists():
                    ref_bytes = ref_abs.read_bytes()

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
                source="export",
            )
            with contextlib.suppress(Exception):
                save_library_character(lib_char, portrait_bytes, reference_bytes=ref_bytes)
            existing_names.add(char.name)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-preset":
            self._open_preset_picker()
            return
        if event.button.id == "btn-save-preset":
            self._save_as_preset()
            return
        if event.button.id == "btn-next" and not self._next_button.disabled:
            self._advance_worker()
        elif event.button.id == "btn-library":
            self.action_add_from_library()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not self._next_button.disabled:
            self._advance_worker()

    # ---- Preset load / save -------------------------------------------------

    def _open_preset_picker(self) -> None:
        from storygen.core.presets import load_all_presets
        from storygen.screens._preset_picker_modal import PresetPickerModal

        presets = load_all_presets()
        if not presets:
            self.notify("No presets available", severity="warning", timeout=5)
            return

        def _on_pick(preset: StoryPreset | None) -> None:
            if preset is None:
                return
            self._apply_preset(preset)

        # self.app is typed App[None] (Textual base) but is StoryGenApp at runtime
        self.app.push_screen(PresetPickerModal(presets), _on_pick)  # pyright: ignore[reportUnknownMemberType]

    def _apply_preset(self, preset: StoryPreset) -> None:
        """Populate all wizard fields from a preset."""
        self._theme_area.text = preset.theme
        self._tone_select.value = preset.tone_preset
        if preset.tone_descriptor:
            self._tone_descriptor.value = preset.tone_descriptor
            self._tone_descriptor.display = True
        self._style_select.value = preset.narration_style
        self._art_style_input.value = preset.art_style
        self._length_input.value = str(preset.target_major_beats)
        self._reader_level_select.value = preset.reader_level
        self._char_area.text = preset.characters

        self._art_style = preset.art_style
        self._target_major_beats = preset.target_major_beats
        self._reader_level = preset.reader_level
        self._pacing = preset.pacing

        self.notify(f"Loaded preset: {preset.name}", timeout=3)

    def _save_as_preset(self) -> None:
        from storygen.core.presets import save_custom_preset

        theme_text = self._theme_area.text.strip()
        if not theme_text:
            self.notify("Enter a theme first", severity="warning", timeout=3)
            return

        preset = StoryPreset(
            name=self._theme.title if self._theme else theme_text[:48],
            description=f"Custom preset from {datetime.now().strftime('%Y-%m-%d')}",
            theme=theme_text,
            tone_preset=cast(str, self._tone_select.value),
            tone_descriptor=self._tone_descriptor.value,
            narration_style=cast(NarrationStyle, self._style_select.value),
            art_style=self._art_style_input.value,
            target_major_beats=int(self._length_input.value or "5"),
            reader_level=cast(ReaderLevel, self._reader_level_select.value),
            pacing=cast(Pacing, self._pacing),
            characters=self._char_area.text,
        )
        path = save_custom_preset(preset)
        self.notify(f"Preset saved to {path.name}", timeout=5)

    def _set_busy(self, busy: bool) -> None:
        """Disable input while a worker is running so we don't double-fire."""
        self._next_button.disabled = busy or self._importing
        self._next_button.label = (
            "Working…" if (busy or self._importing) else _label_for_step(self.current_step)
        )
        self._library_button.disabled = busy or self._importing

    def _notify_progress(self, message: str) -> None:
        """Per-step progress callback for build_initial_save."""
        self._progress.update(f"[dim]⏳ {message}[/dim]")

    # ARC-012/QA-002: dispatch table replaces an 8-arm ``if self.current_step
    # == WizardStep.X`` chain (was cc=34). Each handler advances one step and
    # either sets ``self.current_step`` to the next step or returns early on a
    # validation failure (matching the original early-``return`` semantics).
    # The dispatcher below just looks up and awaits the matching handler; the
    # try/except/finally (error toast + busy re-enable) stays here so a raise
    # in any handler is caught and reported exactly as before.
    _WIZARD_STEP_HANDLERS: ClassVar[dict[WizardStep, str]] = {
        WizardStep.THEME: "_advance_step_theme",
        WizardStep.TONE: "_advance_step_tone",
        WizardStep.STYLE: "_advance_step_style",
        WizardStep.ART_STYLE: "_advance_step_art_style",
        WizardStep.LENGTH: "_advance_step_length",
        WizardStep.READER_LEVEL: "_advance_step_reader_level",
        WizardStep.CHARACTERS: "_advance_step_characters",
        WizardStep.CONFIRM: "_advance_step_confirm",
    }

    @work(exit_on_error=False)
    async def _advance_worker(self) -> None:
        if self._flow is None:
            return
        self._set_busy(True)
        try:
            handler_name = self._WIZARD_STEP_HANDLERS.get(self.current_step)
            if handler_name is not None:
                handler = cast(
                    "Callable[[], Awaitable[None]]", getattr(self, handler_name)
                )
                await handler()
        except Exception as exc:
            self._progress.update("")
            self.notify(f"Error: {exc}", severity="error", timeout=5)
        finally:
            # Re-enable button only if we're still on the wizard (CONFIRM exits).
            if self.is_attached:
                self._set_busy(False)

    async def _advance_step_theme(self) -> None:
        # Defensive guard mirrors the dispatcher's ``self._flow is None: return``
        # check; pyright does not carry self-attribute narrowing across the
        # method boundary, so each handler that touches ``self._flow`` re-narrows.
        if self._flow is None:
            return
        self._theme_area.read_only = True
        self.notify("Generating theme…", timeout=5)
        self._theme = await self._flow.propose_theme(self._theme_area.text)
        self.current_step = WizardStep.TONE

    async def _advance_step_tone(self) -> None:
        preset = cast(str, self._tone_select.value)
        descriptor = self._tone_descriptor.value.strip() or None
        if preset == "custom" and not descriptor:
            self.notify("Custom tone needs a descriptor.", severity="warning")
            return
        self._tone = Tone(preset=cast(_TonePreset, preset), custom_descriptor=descriptor)
        self.current_step = WizardStep.STYLE

    async def _advance_step_style(self) -> None:
        self._style = cast(NarrationStyle, self._style_select.value)
        self.current_step = WizardStep.ART_STYLE

    async def _advance_step_art_style(self) -> None:
        text = self._art_style_input.value.strip()
        self._art_style = text or self._defaults.art_style or app_state.DEFAULT_ART_STYLE
        self.current_step = WizardStep.LENGTH

    async def _advance_step_length(self) -> None:
        raw = self._length_input.value.strip()
        try:
            n = int(raw) if raw else self._defaults.target_major_beats
        except ValueError:
            n = self._defaults.target_major_beats
        self._target_major_beats = max(
            app_state.MIN_TARGET_MAJOR_BEATS,
            min(app_state.MAX_TARGET_MAJOR_BEATS, n),
        )
        # Capture pacing selection (module-level _PACING_OPTIONS)
        idx = self._pacing_input.pressed_index
        self._pacing = (
            _PACING_OPTIONS[idx] if 0 <= idx < len(_PACING_OPTIONS) else "moderate"
        )
        self.current_step = WizardStep.READER_LEVEL

    async def _advance_step_reader_level(self) -> None:
        self._reader_level = cast(str, self._reader_level_select.value)
        self.current_step = WizardStep.CHARACTERS

    async def _advance_step_characters(self) -> None:
        if self._flow is None:
            return
        if self._theme is None:
            self.notify("Theme not set — go back to the Theme step.", severity="warning")
            return
        self.notify("Generating characters…", timeout=5)
        self._user_character_prompt = self._char_area.text
        # Preserve any library-imported characters across a Generate
        # click; generate_characters returns only LLM-invented cast.
        imported = [c for c in self._characters if c.id in self._imported_from_library_ids]
        imported_names = {c.name.lower() for c in imported}
        generated = await self._flow.generate_characters(
            self._theme,
            user_prompt=self._user_character_prompt,
            imported_characters=imported,
        )
        # LLM may ignore the "don't duplicate" instruction — dedup by
        # full name and first name so "Paul Robello" and "Paul" collide.
        seen_full: set[str] = set(imported_names)
        seen_first: set[str] = {n.split()[0] for n in imported_names if n}
        deduped: list[Character] = []
        for c in generated:
            full = c.name.lower()
            first = full.split()[0] if full else ""
            if full in seen_full or (first and first in seen_first):
                continue
            seen_full.add(full)
            if first:
                seen_first.add(first)
            deduped.append(c)
        self._characters = imported + deduped
        self.current_step = WizardStep.CONFIRM

    async def _advance_step_confirm(self) -> None:
        if self._flow is None:
            return
        if self._theme is None:
            self.notify("Theme not set — go back to the Theme step.", severity="warning")
            return
        if self._tone is None:
            self.notify("Tone not set — go back to the Tone step.", severity="warning")
            return
        self.notify("Building your story world…", timeout=5)
        self._progress.update("[dim]⏳ Preparing…[/dim]")
        # Build pending ref-image writes: char_id -> (ref_png, portrait_png_or_none)
        pending_ref_writes = {
            cid: (data[1], self._pending_portrait_bytes.get(cid))
            for cid, data in self._pending_ref_images.items()
        }
        save = await self._flow.build_initial_save(
            theme=self._theme,
            tone=self._tone,
            narration_style=self._style,
            characters=self._characters,
            art_style=self._art_style,
            target_major_beats=self._target_major_beats,
            reader_level=self._reader_level,
            pacing=self._pacing,
            on_progress=self._notify_progress,
            theme_prompt=self._theme_area.text,
            character_prompt=self._user_character_prompt,
            library_import_ids=dict(self._imported_from_library_ids),
            pending_ref_writes=pending_ref_writes or None,
        )
        self._progress.update("[dim]⏳ Finishing up…[/dim]")
        # Auto-export generated characters to catalog if checked.
        if self._save_to_catalog_checkbox.value:
            self._auto_export_to_catalog(save)
        if self._on_complete is not None:
            # _on_complete switches the screen to PlayScreen; do NOT
            # pop_screen afterward (that would pop PlayScreen).
            await self._on_complete(save)


def _label_for_step(step: WizardStep) -> str:
    if step == WizardStep.CHARACTERS:
        return "Generate Characters"
    if step == WizardStep.CONFIRM:
        return "Begin Story"
    return "Next"
