from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from storygen.config import AppConfig, load_config
from storygen.images.split_provider import SplitImageProvider
from storygen.llm import agents as agent_mod
from storygen.llm.provider_factory import build_text_model
from storygen.llm.usage import record_usage_on_save
from storygen.pipeline import BeatPipeline, PipelineCallbacks
from storygen.runtime.adapters import (
    BeatAgentAdapter,
    IllustrationAdapter,
    SummaryAdapter,
    build_split_provider,
    build_split_provider_for_save,
)
from storygen.storage.save import GameSave, save_game
from storygen_api.session import PipelineSessionManager

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

    Mirrors ``StoryGenApp._start_game`` wiring. Adapters and image-provider
    helpers come from the shared :mod:`storygen.runtime.adapters` module
    (ARC-003) so the TUI and API surfaces can't diverge again.
    """
    _ = config  # kept for back-compat with existing call sites; not used here
    model_name = save.text_config.model
    text_model = build_text_model(save.text_config)

    def _on_usage(usage: object) -> None:
        record_usage_on_save(save, model=model_name, usage=usage)
        save_game(save)

    beat_agent = BeatAgentAdapter(
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
    illustration_agent = IllustrationAdapter(
        agent_mod.build_illustration_agent(text_model),
        on_usage=_on_usage,
    )
    summary_agent = SummaryAdapter(
        agent_mod.build_summary_agent(text_model),
        on_usage=_on_usage,
    )

    image_provider = build_split_provider_for_save(save)

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
    return build_split_provider(
        art_config=config.image_config,
        character_config=config.character_image_config,
    )


# Public alias so existing router imports keep resolving (back-compat).
# ``routers/images.py`` imports ``build_split_image_provider`` for save-pinned
# provider construction; the signature mirrors the historical one
# ``(save, config)`` even though ``config`` is no longer needed.
def build_split_image_provider(
    save: GameSave,
    config: AppConfig,  # kept for back-compat with router call sites (was unused pre-ARC-003 too)
) -> SplitImageProvider:
    """Build a save-pinned split image provider."""
    return build_split_provider_for_save(save)


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
