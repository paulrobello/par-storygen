"""par-storygen: top-level Textual App wiring screens, config, and providers."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Protocol, cast, runtime_checkable

from textual import work
from textual.app import App

# Apply Textual library workarounds before any Header is constructed.
import storygen._textual_patches  # noqa: F401  # pyright: ignore[reportUnusedImport]
from storygen.config import AppConfig, load_config
from storygen.images._prompts import build_cover_prompt
from storygen.images.base import ImageProvider
from storygen.images.constants import SCENE_QUALITY, SCENE_SIZE
from storygen.images.provider_factory import (
    ImageProviderName,
    build_routed_image_provider,
    default_fallback_model,
)
from storygen.images.routed_provider import RoutedImageProvider
from storygen.llm import agents as agent_mod
from storygen.llm.models import ImageProviderConfig
from storygen.llm.provider_factory import build_text_model
from storygen.llm.usage import record_usage_on_save
from storygen.pipeline import BeatPipeline, PipelineCallbacks
from storygen.pipeline import background_tasks as _background_tasks
from storygen.screens.intro import IntroScreen
from storygen.screens.library_browser import CharacterCatalogScreen
from storygen.screens.load import LoadGameScreen
from storygen.screens.menu import MenuScreen
from storygen.screens.play import PlayScreen
from storygen.screens.settings import ImageProviderChanged, SettingsScreen, TextProviderChanged
from storygen.screens.wizard import WizardFlow, WizardScreen
from storygen.storage import app_state, paths
from storygen.storage.llm_cache import dump_llm_exchange
from storygen.storage.save import GameSave, load_game, save_game


@runtime_checkable
class _HeaderUpdatable(Protocol):
    """Protocol for screens that expose _apply_header."""

    def _apply_header(self) -> None: ...


@runtime_checkable
class _RenderCurrentable(Protocol):
    """Protocol for screens that expose _render_current."""

    def _render_current(self) -> None: ...


class _BeatAgentAdapter:
    """Adapter: runs a pydantic-ai beat agent and emits the narration as one delta.

    Implements :class:`storygen.pipeline.BeatAgentLike` (the ``run`` method).
    Despite the original class name suggesting streaming, this uses
    ``agent.run()`` rather than ``agent.run_stream()``: pydantic-ai's stream
    API does NOT retry on output-validation failure (raises
    ``UnexpectedModelBehavior`` immediately), and the StoryBeat schema's
    ending-vs-choices validator triggers that path occasionally.  ``agent.run()``
    retries validation failures up to the agent's budget, and beat generation
    is fast enough (~5-10 s) that the player doesn't need character-by-character
    streaming. The whole narration is delivered in a single ``on_narration_delta``
    call after ``run()`` resolves.
    """

    def __init__(
        self,
        agent,  # type: ignore[no-untyped-def]
        *,
        on_usage: Callable[[object], None] | None = None,
    ) -> None:
        self._agent = agent  # pyright: ignore[reportUnknownMemberType]
        self._on_usage = on_usage

    async def run(self, prompt, on_narration_delta, raw_sink=None):  # type: ignore[no-untyped-def]
        result = await self._agent.run(prompt)  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        if self._on_usage is not None:
            # Never let usage tracking crash a beat.
            with contextlib.suppress(Exception):
                self._on_usage(result.usage())  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        if raw_sink is not None:
            # Debug-only raw cache; must never crash the pipeline.
            with contextlib.suppress(Exception):
                raw_sink(result.all_messages_json())  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        beat = result.output  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        narration = getattr(beat, "narration", "") or ""  # pyright: ignore[reportUnknownArgumentType]
        if narration:
            await on_narration_delta(narration)  # pyright: ignore[reportUnknownArgumentType]
        return beat  # pyright: ignore[reportUnknownVariableType]


class _SummaryAdapter:
    """Adapter: turns a pydantic-ai summary agent into the pipeline protocol."""

    def __init__(
        self,
        agent,  # type: ignore[no-untyped-def]
        *,
        on_usage: Callable[[object], None] | None = None,
    ) -> None:
        self._agent = agent  # pyright: ignore[reportUnknownMemberType]
        self._on_usage = on_usage

    async def run(self, path_summary_prompt, raw_sink=None):  # type: ignore[no-untyped-def]
        result = await self._agent.run(path_summary_prompt)  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        if self._on_usage is not None:
            with contextlib.suppress(Exception):
                self._on_usage(result.usage())  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        if raw_sink is not None:
            with contextlib.suppress(Exception):
                raw_sink(result.all_messages_json())  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        return result.output  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]


class _IllustrationAdapter:
    """Adapter: turns a pydantic-ai illustration agent into the pipeline protocol."""

    def __init__(
        self,
        agent,  # type: ignore[no-untyped-def]
        *,
        on_usage: Callable[[object], None] | None = None,
    ) -> None:
        self._agent = agent  # pyright: ignore[reportUnknownMemberType]
        self._on_usage = on_usage

    async def run(self, beat, characters, raw_sink=None):  # type: ignore[no-untyped-def]
        summary = f"BEAT:\n{beat.narration}\n\nCHARACTERS:\n" + "\n".join(  # pyright: ignore[reportUnknownMemberType]
            f"- {c.id}: {c.name} — {c.physical_description}"  # pyright: ignore[reportUnknownMemberType]
            for c in characters  # pyright: ignore[reportUnknownVariableType]
        )
        result = await self._agent.run(summary)  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        if self._on_usage is not None:
            # Never let usage tracking crash a beat.
            with contextlib.suppress(Exception):
                self._on_usage(result.usage())  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        if raw_sink is not None:
            with contextlib.suppress(Exception):
                raw_sink(result.all_messages_json())  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        return result.output  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]


class StoryGenApp(App[None]):
    TITLE = "par-storygen"
    SUB_TITLE = "AI-driven choose-your-own-adventure"

    def __init__(self, *, resume_last: bool = False) -> None:
        super().__init__()
        self._config: AppConfig = load_config()
        self._text_model = build_text_model(self._config.text_config)
        # Provider labels we've already surfaced a ref-loss toast for this
        # session. One-per-(app, label) de-dup so players don't get spammed
        # on every scene generation with a non-ref provider.
        self._ref_loss_warned: set[str] = set()
        self._image_provider: RoutedImageProvider = self._build_app_image_provider()
        self._resume_last = resume_last

    def on_mount(self) -> None:
        self.install_screen(MenuScreen(), name="menu")  # pyright: ignore[reportUnknownMemberType]
        self.install_screen(self._make_wizard, name="wizard")  # pyright: ignore[reportUnknownMemberType,reportArgumentType]
        self.install_screen(self._make_load, name="load")  # pyright: ignore[reportUnknownMemberType,reportArgumentType]
        self.install_screen(lambda: SettingsScreen(self._config), name="settings")  # pyright: ignore[reportUnknownMemberType,reportArgumentType]
        self.install_screen(self._make_catalog, name="catalog")  # pyright: ignore[reportUnknownMemberType,reportArgumentType]
        self.push_screen("menu")  # pyright: ignore[reportUnknownMemberType]
        if self._resume_last:
            self._auto_resume()
        else:
            self.push_screen(IntroScreen())  # pyright: ignore[reportUnknownMemberType]

    def on_text_provider_changed(self, event: TextProviderChanged) -> None:
        """Re-read config and rebuild provider clients so new stories pick them up.

        Runs on the app thread after the SettingsScreen persists new prefs.
        Existing in-flight games keep their already-bound agents; only games
        started after this handler sees the fresh ``_text_model`` /
        ``_image_provider``.
        """
        self._config = load_config()
        self._text_model = build_text_model(self._config.text_config)
        self._rebuild_image_provider()
        self.notify(
            "Provider saved — new stories will use "
            f"{self._config.text_config.provider}/{self._config.text_config.model}.",
            timeout=5,
        )

    def on_image_provider_changed(self, event: ImageProviderChanged) -> None:
        """Reload config + rebuild the routed image provider on Settings save.

        Unlike :meth:`on_text_provider_changed`, this clears
        ``_ref_loss_warned`` — the user has explicitly chosen a new image
        provider, so any prior session-scoped ref-loss toast is no longer
        relevant and we should re-surface the warning if the new provider
        still doesn't support refs.
        """
        self._config = load_config()
        self._ref_loss_warned.clear()
        self._rebuild_image_provider()
        prefs = event.prefs
        self.notify(
            f"Image provider saved — new stories will use {prefs.provider}/{prefs.model}.",
            timeout=5,
        )

    def _build_app_image_provider(self) -> RoutedImageProvider:
        """Build the app-level routed image provider from current config + prefs."""
        return build_routed_image_provider(
            self._config.image_config,
            fallback_cfg=self._resolve_fallback_cfg(self._config.image_config),
            on_ref_loss=self._handle_ref_loss,
            on_fallback=self._handle_fallback,
        )

    def _rebuild_image_provider(self) -> None:
        """Rebuild :attr:`_image_provider` from current config + prefs.

        Called at ``__init__`` and whenever Settings persists a change
        affecting image routing. Does NOT reset :attr:`_ref_loss_warned` —
        the user has already seen those warnings this session and showing
        them again after an unrelated Settings change would be noise.
        """
        self._image_provider = self._build_app_image_provider()

    def _resolve_fallback_cfg(self, primary: ImageProviderConfig) -> ImageProviderConfig | None:
        """Resolve the fallback image-provider config from persisted prefs.

        Returns ``None`` when:
        - no fallback provider is configured (``fallback_provider == ""``),
        - or the fallback provider matches the primary (degenerate — no
          real fallback).

        Otherwise returns an :class:`ImageProviderConfig` with
        ``base_url=None`` and ``api_key=None`` so the fallback provider
        resolves its credentials from the env. Per-save api_key pinning is
        a primary-only feature.
        """
        prefs = app_state.read_image_provider_prefs()
        if not prefs.fallback_provider:
            return None
        if prefs.fallback_provider == primary.provider:
            return None
        model = prefs.fallback_model or default_fallback_model(prefs.fallback_provider)
        if not model:
            return None
        return ImageProviderConfig(
            # prefs.fallback_provider is validated at read time against the
            # allow-list (see app_state.read_image_provider_prefs), so we
            # narrow from ``str`` to ``ImageProviderName`` via cast rather
            # than a type: ignore.
            provider=cast(ImageProviderName, prefs.fallback_provider),
            model=model,
            base_url=None,
            api_key=None,
        )

    def _handle_ref_loss(self, provider_label: str) -> None:
        """Surface a one-per-session toast when a non-ref provider drops refs."""
        if provider_label in self._ref_loss_warned:
            return
        self._ref_loss_warned.add(provider_label)
        self.notify(
            f"{provider_label} doesn't support reference images — "
            "character visual consistency will degrade.",
            severity="warning",
            timeout=10,
        )

    def _handle_fallback(self, fallback_label: str, exc: Exception) -> None:
        """Surface a toast each time the primary fails and fallback takes over."""
        self.notify(
            f"Primary image provider failed; switched to {fallback_label}. "
            f"({type(exc).__name__}: {exc})",
            severity="warning",
            timeout=8,
        )

    @work(exit_on_error=False)
    async def _auto_resume(self) -> None:
        """If a last-played story id is recorded, jump straight into it."""
        game_id = app_state.last_story_id()
        if game_id is None:
            self.notify(
                "No previous story to resume — pick one from Load Story.",
                severity="warning",
                timeout=5,
            )
            return
        try:
            save = load_game(game_id)
        except FileNotFoundError:
            self.notify(f"Last story {game_id} no longer exists.", severity="warning", timeout=5)
            return
        await self._start_game(save)

    def _make_load(self) -> LoadGameScreen:
        return LoadGameScreen(
            on_save_selected=self._start_game,
            image_provider_factory=self._build_save_image_provider,
        )

    def _build_save_image_provider(self, save: GameSave) -> RoutedImageProvider:
        """Build a save-pinned image provider for cover backfill + regeneration.

        Mirrors the per-save provider construction in ``_start_game`` so
        cover art for a loaded save uses the save's own ``image_config``
        (not whatever the app default is right now).
        """
        return build_routed_image_provider(
            save.image_config,
            fallback_cfg=self._resolve_fallback_cfg(save.image_config),
            on_ref_loss=self._handle_ref_loss,
            on_fallback=self._handle_fallback,
        )

    def _make_catalog(self) -> CharacterCatalogScreen:
        return CharacterCatalogScreen(
            browse=True,
            character_agent_factory=lambda: agent_mod.build_catalog_character_agent(
                self._text_model
            ),  # type: ignore[no-untyped-def]
            image_provider=self._image_provider,
        )

    def _make_wizard(self) -> WizardScreen:
        return WizardScreen(
            text_config=self._config.text_config,
            flow=WizardFlow(
                text_config=self._config.text_config,
                image_config=self._config.image_config,
                theme_agent=agent_mod.build_theme_agent(self._text_model),  # pyright: ignore[reportArgumentType]
                character_agent_factory=lambda theme: agent_mod.build_character_agent(  # pyright: ignore[reportArgumentType]
                    self._text_model, theme=theme
                ),
                blurb_agent_factory=lambda theme, characters, narration_style: (
                    agent_mod.build_blurb_agent(  # pyright: ignore[reportArgumentType]
                        self._text_model,
                        theme=theme,
                        characters=characters,
                        narration_style=narration_style,
                    )
                ),
                adapt_agent_factory=lambda theme: agent_mod.build_adapt_backstory_agent(  # pyright: ignore[reportArgumentType]
                    self._text_model, theme=theme
                ),
                image_provider=self._image_provider,
            ),
            on_wizard_complete=self._start_game,
        )

    async def _backfill_blurb_if_missing(self, save: GameSave) -> None:
        """Generate the back-cover blurb for legacy saves that lack one.

        Saves created before the blurb feature have ``root.narration == ""``.
        On first load we generate the blurb, write it back to the root node,
        and persist the save so subsequent loads are instant.
        """
        root = save.nodes.get(save.root_node_id)
        if root is None or root.narration.strip():
            return
        # Honor the save's pinned text_config rather than the app-level model,
        # which may have been rebuilt by a later Settings change.
        text_model = build_text_model(save.text_config)
        try:
            agent = agent_mod.build_blurb_agent(
                text_model,
                theme=save.theme,
                characters=save.characters,
                narration_style=save.narration_style,
            )
            result = await agent.run("Write the back-cover blurb.")
        except Exception as exc:
            self.notify(f"Blurb generation failed: {exc}", severity="error", timeout=10)
            return
        # Usage capture is best-effort; don't break the backfill on failure.
        with contextlib.suppress(Exception):
            record_usage_on_save(save, model=save.text_config.model, usage=result.usage())
        # Debug-only raw-exchange cache. Keyed to the root node id because
        # the blurb lives on the root. Suppress broadly; never crash load.
        if app_state.llm_cache_enabled():
            with contextlib.suppress(Exception):
                dump_llm_exchange(
                    str(save.id),
                    save.root_node_id,
                    "blurb",
                    result.all_messages_json(),
                )
        blurb = str(result.output).strip()
        if not blurb:
            return
        save.nodes[save.root_node_id] = root.model_copy(update={"narration": blurb})
        save_game(save)

    def _mark_cover_generating_if_needed(self, save: GameSave) -> bool:
        """Set root node to ``image_status="generating"`` if a backfill is needed.

        Returns True when a backfill was queued (caller should fire the async
        task). Returns False when no backfill is needed (art off, already done,
        or root missing).
        """
        if not app_state.art_enabled():
            return False
        root = save.nodes.get(save.root_node_id)
        if root is None or root.image_status == "done":
            return False
        save.nodes[save.root_node_id] = root.model_copy(update={"image_status": "generating"})
        return True

    async def _backfill_cover_if_missing(
        self,
        save: GameSave,
        *,
        image_provider: ImageProvider,
    ) -> None:
        """Generate cover art for legacy saves whose root node lacks one.

        Fire-and-forget: the root node is already set to ``image_status=
        "generating"`` by ``_mark_cover_generating_if_needed`` so PlayScreen
        shows a spinner. On completion the image fields are updated, the save
        is persisted, and the play-screen image panel is refreshed.
        """
        root = save.nodes.get(save.root_node_id)
        if root is None or root.image_status == "done":
            return
        from storygen.images.pricing import image_cost as _image_cost

        cover_prompt = build_cover_prompt(
            theme_title=save.theme.title,
            theme_description=f"{save.theme.setting} {save.theme.premise}",
            art_style=save.art_style,
        )
        try:
            cover_bytes = await image_provider.generate_scene(
                cover_prompt,
                reference_portraits=[],
                art_style=save.art_style,
            )
        except Exception as exc:
            save.nodes[save.root_node_id] = root.model_copy(update={"image_status": "failed"})
            save_game(save)
            self.notify(f"Cover art generation failed: {exc}", severity="error", timeout=10)
            return
        cover_path = paths.node_image_path(str(save.id), save.root_node_id)
        cover_path.parent.mkdir(parents=True, exist_ok=True)
        cover_path.write_bytes(cover_bytes)
        cover_rel = str(cover_path.relative_to(paths.game_dir(str(save.id))))
        cost = _image_cost(
            save.image_config.provider,
            model=save.image_config.model,
            size=SCENE_SIZE,
            quality=SCENE_QUALITY,
        )
        save.nodes[save.root_node_id] = root.model_copy(
            update={
                "image_prompt": cover_prompt,
                "image_path": cover_rel,
                "image_status": "done",
            }
        )
        save.total_image_cost_usd += cost
        save_game(save)
        # Refresh the play-screen image panel so the cover appears.
        with contextlib.suppress(Exception):
            screen = self.screen
            if isinstance(screen, _RenderCurrentable):
                screen._render_current()  # pyright: ignore[reportPrivateUsage]

    async def _start_game(self, save: GameSave) -> None:
        await self._backfill_blurb_if_missing(save)
        # Persist this story id as the last-played so `--resume` can find it.
        with contextlib.suppress(OSError):
            app_state.remember_last_story(str(save.id))
        model_name = save.text_config.model
        # Each save pins its own text_config — build a per-save model so a
        # later Settings change doesn't silently reroute this save's traffic
        # to a different provider. self._text_model is only for NEW wizards.
        text_model = build_text_model(save.text_config)

        def _on_usage(usage: object) -> None:
            record_usage_on_save(save, model=model_name, usage=usage)
            save_game(save)
            # If the play screen is mounted, refresh its header so totals update.
            with contextlib.suppress(Exception):
                screen = self.screen
                if isinstance(screen, _HeaderUpdatable):
                    screen._apply_header()  # pyright: ignore[reportPrivateUsage]

        beat_agent = _BeatAgentAdapter(
            agent_mod.build_beat_agent(
                text_model,
                theme=save.theme,
                tone=save.tone,
                narration_style=save.narration_style,
                target_major_beats=save.target_major_beats,
                reader_level=save.reader_level,
            ),
            on_usage=_on_usage,
        )
        illustration_agent = _IllustrationAdapter(
            agent_mod.build_illustration_agent(text_model),
            on_usage=_on_usage,
        )
        summary_agent = _SummaryAdapter(
            agent_mod.build_summary_agent(text_model),
            on_usage=_on_usage,
        )
        # Each save pins its own image_config — build a per-save router so
        # that a later Settings change to the primary image provider doesn't
        # silently reroute this save's generation traffic. The fallback is
        # still resolved from app-level prefs (not pinned per-save).
        save_image_provider = build_routed_image_provider(
            save.image_config,
            fallback_cfg=self._resolve_fallback_cfg(save.image_config),
            on_ref_loss=self._handle_ref_loss,
            on_fallback=self._handle_fallback,
        )
        pipeline = BeatPipeline(
            beat_agent=beat_agent,
            illustration_agent=illustration_agent,
            summary_agent=summary_agent,
            image_provider=save_image_provider,
            callbacks=PipelineCallbacks(),
        )
        # Backfill cover art for legacy saves. Fire-and-forget so the player
        # sees the spinner immediately instead of a blank pause.
        if self._mark_cover_generating_if_needed(save):
            _cover_task: asyncio.Task[None] = asyncio.create_task(
                self._backfill_cover_if_missing(save, image_provider=save_image_provider)
            )
            _background_tasks.add(_cover_task)
            _cover_task.add_done_callback(_background_tasks.discard)
        # switch_screen replaces the caller (wizard or load) with the play screen,
        # so ESC from play returns to the menu rather than back to the source screen.
        self.switch_screen(  # pyright: ignore[reportUnknownMemberType]
            PlayScreen(save, pipeline=pipeline, image_provider=save_image_provider)
        )
