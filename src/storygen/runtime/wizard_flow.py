"""Headless ``WizardFlow`` — the LLM + image-facing wizard state machine.

Moved out of :mod:`storygen.screens.wizard` (ARC-005) so the FastAPI
surface can use it without importing a Textual-coupled module. The Textual
``WizardScreen`` remains in :mod:`storygen.screens.wizard` and depends on
this module (screen → runtime is the correct layering direction).
"""

from __future__ import annotations

import contextlib
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID, uuid4

from storygen.core.models import (
    Character,
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.images.constants import (
    PORTRAIT_QUALITY,
    PORTRAIT_SIZE,
    SCENE_QUALITY,
    SCENE_SIZE,
)
from storygen.images.pricing import image_cost
from storygen.images.prompts import build_cover_prompt
from storygen.images.provider_factory import ImageProviderName
from storygen.llm.usage import UsageTotals
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


class _AgentLike(Protocol):
    async def run(self, prompt: str) -> object: ...


class WizardFlow:
    """Headless wizard state machine — coordinates LLM + image calls.

    Owns no UI; both the Textual ``WizardScreen`` and the FastAPI wizard
    router drive this same state machine so wizard logic can't diverge
    between the two surfaces.
    """

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
            # app_state constant is str-typed but always one of the allow-listed
            # provider ids (it derives from IMAGE_PROVIDERS); narrow via cast
            # rather than a type: ignore. Mirrors config.py:135.
            provider=cast(ImageProviderName, app_state.DEFAULT_CHARACTER_IMAGE_PROVIDER),
            model=app_state.DEFAULT_CHARACTER_IMAGE_MODEL,
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
