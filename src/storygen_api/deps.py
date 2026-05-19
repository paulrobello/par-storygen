from __future__ import annotations

import contextlib
from collections.abc import Callable
from functools import lru_cache
from typing import cast

from storygen.config import AppConfig, load_config
from storygen.images.provider_factory import (
    ImageProviderName,
    build_routed_image_provider,
    default_fallback_model,
)
from storygen.images.routed_provider import RoutedImageProvider
from storygen.images.split_provider import SplitImageProvider
from storygen.llm import agents as agent_mod
from storygen.llm.models import ImageProviderConfig
from storygen.llm.provider_factory import build_text_model
from storygen.llm.usage import record_usage_on_save
from storygen.pipeline import BeatPipeline, PipelineCallbacks
from storygen.storage import app_state
from storygen.storage.save import GameSave, save_game

from fastapi import Depends

from storygen_api.session import PipelineSessionManager


# ---------------------------------------------------------------------------
# Adapter classes — mirror app.py's adapters for pydantic-ai agents
# ---------------------------------------------------------------------------


class _BeatAgentAdapter:
    """Adapter: runs a pydantic-ai beat agent and emits narration as one delta.

    Implements the ``BeatAgentLike`` protocol.
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
            with contextlib.suppress(Exception):
                self._on_usage(result.usage())  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        if raw_sink is not None:
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
            with contextlib.suppress(Exception):
                self._on_usage(result.usage())  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        if raw_sink is not None:
            with contextlib.suppress(Exception):
                raw_sink(result.all_messages_json())  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        return result.output  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]


# ---------------------------------------------------------------------------
# Image provider helpers
# ---------------------------------------------------------------------------


def _resolve_fallback_cfg(
    primary: ImageProviderConfig,
) -> ImageProviderConfig | None:
    """Resolve fallback image-provider config from persisted prefs."""
    prefs = app_state.read_image_provider_prefs()
    if not prefs.fallback_provider:
        return None
    if prefs.fallback_provider == primary.provider:
        return None
    model = prefs.fallback_model or default_fallback_model(prefs.fallback_provider)
    if not model:
        return None
    return ImageProviderConfig(
        provider=cast(ImageProviderName, prefs.fallback_provider),
        model=model,
        base_url=None,
        api_key=None,
    )


def _build_routed_image_provider(
    config: ImageProviderConfig,
) -> RoutedImageProvider:
    return build_routed_image_provider(
        config,
        fallback_cfg=_resolve_fallback_cfg(config),
    )


def _build_split_image_provider(
    save: GameSave,
    config: AppConfig,
) -> SplitImageProvider:
    """Build a save-pinned split image provider."""
    art_router = _build_routed_image_provider(save.image_config)
    character_router = _build_routed_image_provider(save.character_image_config)
    return SplitImageProvider(character_provider=character_router, art_provider=art_router)


# ---------------------------------------------------------------------------
# Pipeline construction
# ---------------------------------------------------------------------------


def build_pipeline(
    save: GameSave,
    config: AppConfig,
    *,
    callbacks: PipelineCallbacks | None = None,
) -> tuple[BeatPipeline, SplitImageProvider]:
    """Build a BeatPipeline + image provider for a given save.

    Mirrors ``StoryGenApp._start_game`` wiring.
    """
    model_name = save.text_config.model
    text_model = build_text_model(save.text_config)

    def _on_usage(usage: object) -> None:
        record_usage_on_save(save, model=model_name, usage=usage)
        save_game(save)

    beat_agent = _BeatAgentAdapter(
        agent_mod.build_beat_agent(
            text_model,
            theme=save.theme,
            tone=save.tone,
            narration_style=save.narration_style,
            target_major_beats=save.target_major_beats,
            reader_level=save.reader_level,
            pacing=save.pacing,
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

    image_provider = _build_split_image_provider(save, config)

    pipeline = BeatPipeline(
        beat_agent=beat_agent,
        illustration_agent=illustration_agent,
        summary_agent=summary_agent,
        image_provider=image_provider,
        callbacks=callbacks or PipelineCallbacks(),
    )
    return pipeline, image_provider


# ---------------------------------------------------------------------------
# Wizard helpers
# ---------------------------------------------------------------------------


def build_split_image_provider_for_wizard(config: AppConfig) -> SplitImageProvider:
    """Build a split image provider from app config (for wizard, before a save exists)."""
    art_router = _build_routed_image_provider(config.image_config)
    character_router = _build_routed_image_provider(config.character_image_config)
    return SplitImageProvider(character_provider=character_router, art_provider=art_router)


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_app_config() -> AppConfig:
    """Cached AppConfig — loaded once per process."""
    return load_config()


_session_manager: PipelineSessionManager | None = None


def get_session_manager() -> PipelineSessionManager:
    """Return the singleton PipelineSessionManager."""
    global _session_manager
    if _session_manager is None:
        _session_manager = PipelineSessionManager()
    return _session_manager


def get_wizard_image_provider(
    config: AppConfig = Depends(get_app_config),
) -> SplitImageProvider:
    """FastAPI dependency: build a split image provider from app config."""
    return build_split_image_provider_for_wizard(config)
