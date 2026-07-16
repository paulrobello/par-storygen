"""WizardScreen + headless WizardFlow.

`WizardFlow` is the pure state machine that owns LLM + image calls.
`WizardScreen` is the Textual wrapper that drives WizardFlow step-by-step.
"""

from __future__ import annotations

import contextlib
import io
import shutil
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import Enum, auto
from typing import ClassVar, Literal, Protocol, cast
from uuid import UUID, uuid4

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
from storygen.images._prompts import build_cover_prompt
from storygen.images.constants import (
    PORTRAIT_QUALITY,
    PORTRAIT_SIZE,
    SCENE_QUALITY,
    SCENE_SIZE,
)
from storygen.images.pricing import image_cost
from storygen.llm.models import (
    Character,
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.llm.usage import UsageTotals
from storygen.screens._ref_image_modals import ReferenceImageModal, ReferenceImageResult
from storygen.screens.library_browser import CharacterCatalogScreen, LibraryPick
from storygen.storage import app_state, paths
from storygen.storage.library import LibraryCharacter, library_portrait_path, load_library_character
from storygen.storage.llm_cache import dump_llm_exchange
from storygen.storage.save import (
    GameSave,
    NarrationStyle,
    Pacing,
    ReaderLevel,
    StoryCreationPrompts,
    list_existing_story_titles,
    save_game,
)


def _load_lib_char_if_exists(library_id: str) -> LibraryCharacter | None:
    """Best-effort load of a library character; returns None on any failure."""
    try:
        return load_library_character(library_id)
    except Exception:
        return None


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


class _AgentLike(Protocol):
    async def run(self, prompt: str) -> object: ...


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


class WizardFlow:
    """Headless wizard state machine — coordinates LLM + image calls."""

    def __init__(
        self,
        *,
        text_config: TextProviderConfig,
        image_config: ImageProviderConfig,
        character_image_config: ImageProviderConfig | None = None,
        theme_agent: _AgentLike,
        character_agent_factory: Callable[[Theme], _AgentLike],
        blurb_agent_factory: Callable[[Theme, list[Character], NarrationStyle], _AgentLike],
        image_provider: object,
        adapt_agent_factory: Callable[[Theme], _AgentLike] | None = None,
    ) -> None:
        self._text_config = text_config
        self._image_config = image_config
        self._character_image_config = character_image_config or ImageProviderConfig(
            provider="openai", model="gpt-image-2"
        )
        self._theme_agent = theme_agent
        self._character_agent_factory = character_agent_factory
        self._blurb_agent_factory = blurb_agent_factory
        # Optional so legacy test wiring (pre-Phase-4) still works without
        # constructing an adapter; callers that invoke adapt_library_character
        # MUST provide one or the call raises RuntimeError.
        self._adapt_agent_factory = adapt_agent_factory
        self._image_provider = image_provider
        self._usage_totals = UsageTotals()
        # Pre-generate the game ID so wizard-stage LLM exchanges can be
        # cached to the same llm/ directory that build_initial_save uses.
        self._game_id: str = str(uuid4())

    def _dump_llm(self, agent_name: str, result: object) -> None:
        """Best-effort dump of an LLM exchange to the debug cache."""
        if not app_state.llm_cache_enabled():
            return
        with contextlib.suppress(Exception):
            dump_llm_exchange(
                self._game_id,
                "wizard",
                agent_name,
                result.all_messages_json(),  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType,reportAttributeAccessIssue]
            )

    @property
    def image_provider(self) -> object:
        """Return the image provider instance (typed as object for protocol flexibility)."""
        return self._image_provider

    def _record_result_usage(self, result: object) -> None:
        """Best-effort: pull a RunUsage off ``result`` and tally it."""
        usage = getattr(result, "usage", None)
        # pydantic-ai 2.x exposes ``usage`` as a RunUsage attribute; 1.x exposed a callable.
        if callable(usage):
            try:
                usage = usage()
            except Exception:
                return
        if usage is None:
            return
        self._usage_totals.record(
            model=self._text_config.model,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            requests=getattr(usage, "requests", None) or 1,
        )

    async def propose_theme(self, user_prompt: str) -> Theme:
        """Run the theme agent and return a Theme."""
        prompt = user_prompt.strip() or "Propose a theme."
        existing_titles = list_existing_story_titles()
        if existing_titles:
            titles = "\n".join(f"- {title}" for title in existing_titles)
            prompt = (
                f"{prompt}\n\n"
                "Existing story titles to avoid:\n"
                f"{titles}\n\n"
                "Do not reuse or closely imitate any existing title. Pick a distinct title "
                "and premise that will not be confused with these saved stories."
            )
        result = await self._theme_agent.run(prompt)
        self._record_result_usage(result)
        self._dump_llm("theme", result)
        return result.output  # type: ignore[union-attr]

    async def generate_characters(
        self,
        theme: Theme,
        *,
        user_prompt: str = "",
        imported_characters: list[Character] | None = None,
    ) -> list[Character]:
        """Generate the initial cast for the given theme.

        Args:
            theme: The story theme.
            user_prompt: Optional user description of desired characters.
            imported_characters: Characters already in the cast (from library
                or reference image). When non-empty, the prompt instructs the
                LLM to give them prominent starring roles.

        Returns:
            List of generated Character models.
        """
        agent = self._character_agent_factory(theme)
        request = f"Generate cast for theme: {theme.title}"
        cleaned = user_prompt.strip()
        if cleaned:
            request = f"{request}\n\nUser-specified character requirements:\n{cleaned}"
        if imported_characters:
            lines = "\n".join(
                f"- {c.name}: {c.personality or c.backstory or 'no description'}"
                for c in imported_characters
            )
            request += (
                "\n\nThe following characters are already part of the cast and MUST"
                " have prominent, starring roles. Generate additional characters"
                " only if the story needs them:\n" + lines
            )
        result = await agent.run(request)
        self._record_result_usage(result)
        self._dump_llm("characters", result)
        return list(result.output)  # type: ignore[union-attr]

    async def adapt_library_character(
        self, lib: LibraryCharacter, theme: Theme
    ) -> LibraryCharacter:
        """Rewrite a library character's backstory to fit ``theme``.

        Returns a new :class:`LibraryCharacter` with the rewritten backstory
        and everything else preserved. The caller is still responsible for
        turning it into a save-local :class:`Character` (the existing
        keep-as-is append flow works as-is with the adapted instance).

        Raises:
            RuntimeError: If no ``adapt_agent_factory`` was supplied at
                :class:`WizardFlow` construction time.
        """
        if self._adapt_agent_factory is None:
            raise RuntimeError(
                "adapt_library_character requires adapt_agent_factory at WizardFlow init"
            )
        agent = self._adapt_agent_factory(theme)
        user_prompt = (
            f"Character name: {lib.name}\n"
            f"Personality: {lib.personality}\n"
            f"Physical description: {lib.physical_description}\n\n"
            f"Current backstory (from a prior story):\n{lib.backstory}\n\n"
            f"Rewrite the backstory to fit the new theme."
        )
        result = await agent.run(user_prompt)
        self._record_result_usage(result)
        self._dump_llm("adapt", result)
        adapted = getattr(result, "output", None)
        new_backstory = str(getattr(adapted, "backstory", "")).strip()
        if not new_backstory:
            # Don't let an empty-string adaptation silently erase the
            # character's backstory; surface as a clear error the worker
            # will turn into a friendlier toast.
            raise ValueError("adapt agent returned empty backstory")
        return lib.model_copy(update={"backstory": new_backstory})

    async def build_initial_save(
        self,
        *,
        theme: Theme,
        tone: Tone,
        narration_style: NarrationStyle,
        characters: list[Character],
        art_style: str = app_state.DEFAULT_ART_STYLE,
        target_major_beats: int = app_state.DEFAULT_TARGET_MAJOR_BEATS,
        reader_level: str = app_state.DEFAULT_READER_LEVEL,
        pacing: str = app_state.DEFAULT_PACING,
        on_progress: Callable[[str], None] | None = None,
        theme_prompt: str = "",
        character_prompt: str = "",
        library_import_ids: dict[str, str] | None = None,
        pending_ref_writes: dict[str, tuple[bytes, bytes | None]] | None = None,
    ) -> GameSave:
        """Generate portraits, build the root node, persist and return the save.

        Args:
            theme: Story theme.
            tone: Tone of voice for the story.
            narration_style: Narration POV.
            characters: Initial cast.
            art_style: Visual style guidance applied to portrait + scene prompts.
            on_progress: Optional callback fired before each portrait generation,
                useful for surfacing per-character progress in the UI.
            theme_prompt: Original user prompt entered on the theme step.
            character_prompt: Original user prompt entered on the characters step.
            library_import_ids: Optional mapping ``{character_id: library_id}``
                flagging characters imported from the cross-game library. For
                those characters the portrait is COPIED from the library
                instead of generated, and ``portrait_prompt`` is preserved
                so later regenerations stay visually consistent.
            pending_ref_writes: Optional mapping ``{character_id:
                (reference_png_bytes, generated_portrait_bytes_or_None)}``
                for characters added via reference image import. The reference
                image and portrait bytes are written to disk instead of
                generated.
        """
        game_id = UUID(self._game_id)
        paths.ensure_game_dirs(str(game_id))

        art_on = app_state.art_enabled()
        import_map = library_import_ids or {}
        ref_writes = pending_ref_writes or {}
        enriched: list[Character] = []
        total = len(characters)
        total_image_cost_usd = 0.0
        for index, char in enumerate(characters, start=1):
            library_id = import_map.get(char.id)
            if library_id is not None:
                # Imported library character: copy the cached portrait PNG
                # rather than re-generating. Preserve the library's
                # portrait_prompt so regenerations use the same visual intent.
                if on_progress is not None:
                    on_progress(f"Copying portrait from library: {char.name}…")
                src = library_portrait_path(library_id)
                dest = paths.character_portrait_path(str(game_id), char.id, version=1)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src, dest)
                rel_import: str = str(dest.relative_to(paths.game_dir(str(game_id))))
                # Copy reference image if the library entry has one.
                lib_char_meta = _load_lib_char_if_exists(library_id)
                if lib_char_meta is not None and lib_char_meta.reference_image_path:
                    from storygen.storage.library import library_reference_path

                    lib_ref = library_reference_path(library_id)
                    if lib_ref.exists():
                        save_ref = paths.character_reference_path(str(game_id), char.id)
                        save_ref.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy(str(lib_ref), str(save_ref))
                enriched.append(
                    char.model_copy(
                        update={
                            "portrait_path": rel_import,
                            # char.portrait_prompt was set at wizard-append time
                            # from the library's portrait_prompt; preserve it.
                            "introduced_at_node_id": "root",
                        }
                    )
                )
                continue
            if char.id in ref_writes:
                # Character added via reference image import.
                ref_png, portrait_png = ref_writes[char.id]
                if on_progress is not None:
                    on_progress(f"Storing reference image for {char.name}…")
                ref_path = paths.character_reference_path(str(game_id), char.id)
                ref_path.parent.mkdir(parents=True, exist_ok=True)
                ref_path.write_bytes(ref_png)
                portrait_dest = paths.character_portrait_path(str(game_id), char.id, version=1)
                if portrait_png is not None:
                    portrait_dest.write_bytes(portrait_png)
                    total_image_cost_usd += image_cost(
                        self._character_image_config.provider,
                        model=self._character_image_config.model,
                        size=PORTRAIT_SIZE,
                        quality=PORTRAIT_QUALITY,
                    )
                else:
                    # Use-as-is: reference and portrait are the same bytes.
                    portrait_dest.write_bytes(ref_png)
                enriched.append(
                    char.model_copy(
                        update={
                            "introduced_at_node_id": "root",
                        }
                    )
                )
                continue
            if art_on:
                if on_progress is not None:
                    on_progress(f"Generating portrait {index} of {total}: {char.name}…")
                raw = await self._image_provider.generate_portrait(  # type: ignore[union-attr]
                    char.physical_description,
                    transparent=True,
                    art_style=art_style,
                )
                total_image_cost_usd += image_cost(
                    self._character_image_config.provider,
                    model=self._character_image_config.model,
                    size=PORTRAIT_SIZE,
                    quality=PORTRAIT_QUALITY,
                )
                png_bytes = cast(bytes, raw)
                dest = paths.character_portrait_path(str(game_id), char.id, version=1)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(png_bytes)
                rel: str | None = str(dest.relative_to(paths.game_dir(str(game_id))))
            else:
                rel = None
            enriched.append(
                char.model_copy(
                    update={
                        "portrait_path": rel,
                        "portrait_prompt": char.physical_description,
                        "introduced_at_node_id": "root",
                    }
                )
            )

        if on_progress is not None:
            on_progress("Writing back-cover blurb…")
        blurb_agent = self._blurb_agent_factory(theme, enriched, narration_style)
        blurb_result = await blurb_agent.run("Write the back-cover blurb.")
        self._record_result_usage(blurb_result)
        self._dump_llm("blurb", blurb_result)
        blurb = str(blurb_result.output)  # type: ignore[union-attr]

        root = StoryNode(
            id="root",
            parent_id=None,
            chosen_choice_id=None,
            chosen_at=None,
            narration=blurb,
            choices=[StoredChoice(id="start", text="Begin")],
            is_major=True,
            is_ending=False,
            image_prompt=None,
            image_path=None,
            image_status="not_planned",
            illustration_reasoning=None,
            featured_character_ids=[c.id for c in enriched],
            summary_to_here=None,
            created_at=datetime.now(UTC),
        )
        save = GameSave(
            version=1,
            id=game_id,
            theme=theme,
            tone=tone,
            narration_style=narration_style,
            art_style=art_style,
            target_major_beats=target_major_beats,
            reader_level=cast("ReaderLevel", reader_level),
            pacing=cast("Pacing", pacing),
            text_config=self._text_config,
            image_config=self._image_config,
            character_image_config=self._character_image_config,
            creation_prompts=StoryCreationPrompts(
                theme_prompt=theme_prompt,
                character_prompt=character_prompt,
            ),
            characters=enriched,
            nodes={"root": root},
            root_node_id="root",
            current_node_id="root",
            endings_reached=[],
            total_image_cost_usd=total_image_cost_usd,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        # Generate cover art for the root node.
        if art_on:
            if on_progress is not None:
                on_progress("Generating cover art…")
            cover_prompt = build_cover_prompt(
                theme_title=theme.title,
                theme_description=f"{theme.setting} {theme.premise}",
                art_style=art_style,
            )
            cover_bytes = await self._image_provider.generate_scene(  # type: ignore[union-attr]
                cover_prompt,
                reference_portraits=[],
                art_style=art_style,
            )
            cover_path = paths.node_image_path(str(game_id), "root")
            cover_path.parent.mkdir(parents=True, exist_ok=True)
            cover_path.write_bytes(cast(bytes, cover_bytes))
            cover_rel = str(cover_path.relative_to(paths.game_dir(str(game_id))))
            if app_state.auto_open_art_enabled():
                from storygen.util import open_in_system_viewer

                open_in_system_viewer(cover_path)
            total_image_cost_usd += image_cost(
                self._image_config.provider,
                model=self._image_config.model,
                size=SCENE_SIZE,
                quality=SCENE_QUALITY,
            )
            root = root.model_copy(
                update={
                    "image_prompt": cover_prompt,
                    "image_path": cover_rel,
                    "image_status": "done",
                }
            )
            save.nodes["root"] = root
            save.total_image_cost_usd = total_image_cost_usd
        # Merge the wizard's accumulated token usage onto the freshly built save.
        self._usage_totals.apply_to_save(save)
        save_game(save)
        return save


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

    @work(exit_on_error=False)
    async def _advance_worker(self) -> None:
        if self._flow is None:
            return
        self._set_busy(True)
        try:
            if self.current_step == WizardStep.THEME:
                self._theme_area.read_only = True
                self.notify("Generating theme…", timeout=5)
                self._theme = await self._flow.propose_theme(self._theme_area.text)
                self.current_step = WizardStep.TONE
                return
            if self.current_step == WizardStep.TONE:
                preset = cast(str, self._tone_select.value)
                descriptor = self._tone_descriptor.value.strip() or None
                if preset == "custom" and not descriptor:
                    self.notify("Custom tone needs a descriptor.", severity="warning")
                    return
                self._tone = Tone(preset=cast(_TonePreset, preset), custom_descriptor=descriptor)
                self.current_step = WizardStep.STYLE
                return
            if self.current_step == WizardStep.STYLE:
                self._style = cast(NarrationStyle, self._style_select.value)
                self.current_step = WizardStep.ART_STYLE
                return
            if self.current_step == WizardStep.ART_STYLE:
                text = self._art_style_input.value.strip()
                self._art_style = text or self._defaults.art_style or app_state.DEFAULT_ART_STYLE
                self.current_step = WizardStep.LENGTH
                return
            if self.current_step == WizardStep.LENGTH:
                raw = self._length_input.value.strip()
                try:
                    n = int(raw) if raw else self._defaults.target_major_beats
                except ValueError:
                    n = self._defaults.target_major_beats
                self._target_major_beats = max(
                    app_state.MIN_TARGET_MAJOR_BEATS,
                    min(app_state.MAX_TARGET_MAJOR_BEATS, n),
                )
                # Capture pacing selection
                _PACING_OPTIONS = ("slow", "moderate", "fast")
                idx = self._pacing_input.pressed_index
                self._pacing = (
                    _PACING_OPTIONS[idx] if 0 <= idx < len(_PACING_OPTIONS) else "moderate"
                )
                self.current_step = WizardStep.READER_LEVEL
                return
            if self.current_step == WizardStep.READER_LEVEL:
                self._reader_level = cast(str, self._reader_level_select.value)
                self.current_step = WizardStep.CHARACTERS
                return
            if self.current_step == WizardStep.CHARACTERS:
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
                return
            if self.current_step == WizardStep.CONFIRM:
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
                return
        except Exception as exc:
            self._progress.update("")
            self.notify(f"Error: {exc}", severity="error", timeout=5)
        finally:
            # Re-enable button only if we're still on the wizard (CONFIRM exits).
            if self.is_attached:
                self._set_busy(False)


def _label_for_step(step: WizardStep) -> str:
    if step == WizardStep.CHARACTERS:
        return "Generate Characters"
    if step == WizardStep.CONFIRM:
        return "Begin Story"
    return "Next"
