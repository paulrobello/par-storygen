"""pydantic-ai → pipeline Protocol adapters + shared image-provider helpers.

This module is the single source of truth (ARC-003) for the three adapter
classes that bridge pydantic-ai agents to the pipeline's
``BeatAgentLike``/``IllustrationAgentLike``/``SummaryAgentLike`` Protocols,
and for the three image-provider helpers used by both composition roots
(``storygen.app.StoryGenApp`` and the FastAPI ``storygen_api.deps`` module).

Previously these were copy-pasted between ``app.py`` and ``deps.py`` and had
**silently diverged**: ``app.py`` accessed ``result.usage`` (the correct
property form for pydantic-ai ≥ 0.x — confirmed against 2.11.0 via
``inspect.getattr_static(AgentRunResult, "usage")`` → ``property``), while
``deps.py`` called ``result.usage()`` — a ``TypeError: 'RunUsage' object is
not callable`` swallowed by the surrounding ``contextlib.suppress(Exception)``,
silently dropping usage tracking on the entire API surface.

The shared module uses the correct property form; both ``app.py`` and
``deps.py`` import from here.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import cast

from storygen.core.models import ImageProviderConfig
from storygen.images.provider_factory import (
    ImageProviderName,
    build_routed_image_provider,
    default_fallback_model,
)
from storygen.images.routed_provider import RoutedImageProvider
from storygen.images.split_provider import SplitImageProvider
from storygen.storage import app_state
from storygen.storage.save import GameSave


class BeatAgentAdapter:
    """Adapter: runs a pydantic-ai beat agent and emits narration as one delta.

    Implements :class:`storygen.pipeline.BeatAgentLike` (the ``run`` method).
    Despite the original class name suggesting streaming, this uses
    ``agent.run()`` rather than ``agent.run_stream()``: pydantic-ai's stream
    API does NOT retry on output-validation failure (raises
    ``UnexpectedModelBehavior`` immediately), and the StoryBeat schema's
    ending-vs-choices validator triggers that path occasionally. ``agent.run()``
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
            # ``result.usage`` is a property on pydantic-ai's AgentRunResult
            # (verified against 2.11.0). Calling ``result.usage()`` raises
            # TypeError and gets swallowed by this suppress — silently dropping
            # usage tracking. Never let usage tracking crash a beat regardless.
            with contextlib.suppress(Exception):
                self._on_usage(result.usage)  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        if raw_sink is not None:
            # Debug-only raw cache; must never crash the pipeline.
            with contextlib.suppress(Exception):
                raw_sink(result.all_messages_json())  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        beat = result.output  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        narration = getattr(beat, "narration", "") or ""  # pyright: ignore[reportUnknownArgumentType]
        if narration:
            await on_narration_delta(narration)  # pyright: ignore[reportUnknownArgumentType]
        return beat  # pyright: ignore[reportUnknownVariableType]


class SummaryAdapter:
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
                self._on_usage(result.usage)  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        if raw_sink is not None:
            with contextlib.suppress(Exception):
                raw_sink(result.all_messages_json())  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        return result.output  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]


class IllustrationAdapter:
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
                self._on_usage(result.usage)  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        if raw_sink is not None:
            with contextlib.suppress(Exception):
                raw_sink(result.all_messages_json())  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        return result.output  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]


# ---------------------------------------------------------------------------
# Image provider helpers
# ---------------------------------------------------------------------------


def resolve_fallback_cfg(
    primary: ImageProviderConfig,
) -> ImageProviderConfig | None:
    """Resolve fallback image-provider config from persisted prefs.

    Returns ``None`` when:
    - no fallback provider is configured (``fallback_provider == ""``),
    - or the fallback provider matches the primary (degenerate — no real fallback).

    Otherwise returns an :class:`ImageProviderConfig` with ``base_url=None`` and
    ``api_key=None`` so the fallback provider resolves its credentials from the
    env. Per-save api_key pinning is a primary-only feature.
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
        # allow-list (see app_state.read_image_provider_prefs), so we narrow
        # from ``str`` to ``ImageProviderName`` via cast rather than a type: ignore.
        provider=cast(ImageProviderName, prefs.fallback_provider),
        model=model,
        base_url=None,
        api_key=None,
    )


def build_routed_provider(
    config: ImageProviderConfig,
    *,
    on_ref_loss: Callable[[str], None] | None = None,
    on_fallback: Callable[[str, Exception], None] | None = None,
) -> RoutedImageProvider:
    """Build a routed image provider with the app-level fallback prefs applied.

    ``on_ref_loss``/``on_fallback`` are optional callbacks the TUI app uses to
    surface toasts; the API surface passes ``None`` (server has no UI).
    """
    return build_routed_image_provider(
        config,
        fallback_cfg=resolve_fallback_cfg(config),
        on_ref_loss=on_ref_loss,
        on_fallback=on_fallback,
    )


def build_split_provider(
    *,
    art_config: ImageProviderConfig,
    character_config: ImageProviderConfig,
    on_ref_loss: Callable[[str], None] | None = None,
    on_fallback: Callable[[str, Exception], None] | None = None,
) -> SplitImageProvider:
    """Build a split provider with fallback routing applied to both halves."""
    art_router = build_routed_provider(
        art_config, on_ref_loss=on_ref_loss, on_fallback=on_fallback
    )
    character_router = build_routed_provider(
        character_config, on_ref_loss=on_ref_loss, on_fallback=on_fallback
    )
    return SplitImageProvider(character_provider=character_router, art_provider=art_router)


def build_split_provider_for_save(
    save: GameSave,
    *,
    on_ref_loss: Callable[[str], None] | None = None,
    on_fallback: Callable[[str, Exception], None] | None = None,
) -> SplitImageProvider:
    """Build a save-pinned split provider for art and portraits.

    Each save pins its own image configs so a later Settings change to the
    primary image provider doesn't silently reroute this save's generation
    traffic. The fallback is still resolved from app-level prefs (not pinned
    per-save).
    """
    return build_split_provider(
        art_config=save.image_config,
        character_config=save.character_image_config,
        on_ref_loss=on_ref_loss,
        on_fallback=on_fallback,
    )
