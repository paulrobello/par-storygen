"""In-memory per-game pipeline registry for the FastAPI surface.

``PipelineSessionManager`` is the single owner of the live ``GameSave`` for
each active ``game_id``. Routers must obtain the save via
:meth:`PipelineSessionManager.get_or_load_save` so the pipeline's ``_on_usage``
closure (captured at construction time in :func:`storygen_api.deps.build_pipeline`)
records usage on the same object that subsequent advances mutate and persist
(ARC-101). Per-game :class:`asyncio.Lock` instances
(:meth:`PipelineSessionManager.advance_lock`) serialize the
load→advance→persist critical section so concurrent advances on the same game
cannot lose a child node (ARC-102). Idle sessions are evicted by
:meth:`PipelineSessionManager.evict_idle` (ARC-106).

State is process-local — the API must run with ``--workers 1`` or this registry
silently desyncs (ARC-004).
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING

from storygen.storage.save import GameSave, load_game

if TYPE_CHECKING:
    from storygen.pipeline import BeatPipeline


class PipelineSessionManager:
    """Thread-safe registry owning the single in-memory ``GameSave`` per active game.

    Routers must use :meth:`get_or_load_save` to obtain a save for a
    session-active game. The pipeline's ``_on_usage`` closure captures the save
    at construction time; because ``get_or_load_save`` returns the same cached
    object across calls, usage recording and subsequent node mutations land on
    the same instance (ARC-101).
    """

    def __init__(self) -> None:
        self._pipelines: dict[str, BeatPipeline] = {}
        self._saves: dict[str, GameSave] = {}
        self._advance_locks: dict[str, asyncio.Lock] = {}
        self._last_used: dict[str, float] = {}
        self._lock = threading.Lock()

    def get_or_create(
        self,
        game_id: str,
        save: GameSave,
        pipeline: BeatPipeline,
    ) -> BeatPipeline:
        """Return existing pipeline for *game_id*, or register *pipeline*."""
        with self._lock:
            if game_id not in self._pipelines:
                self._pipelines[game_id] = pipeline
                self._saves[game_id] = save
            self._last_used[game_id] = time.monotonic()
            return self._pipelines[game_id]

    def get_pipeline(self, game_id: str) -> BeatPipeline | None:
        """Return the registered pipeline for *game_id*, or ``None``.

        Stamps ``_last_used`` only when a pipeline is registered (a query for
        an unknown game does not count as activity).
        """
        with self._lock:
            pipeline = self._pipelines.get(game_id)
            if pipeline is not None:
                self._last_used[game_id] = time.monotonic()
            return pipeline

    def get_or_load_save(self, game_id: str) -> GameSave:
        """Return the owned ``GameSave`` for *game_id*, loading from disk once.

        This is the only sanctioned way routers obtain a save for a
        session-active game (ARC-101). The first call loads the save from disk
        and caches it in ``_saves``; subsequent calls return the same object so
        the pipeline's construction-time ``_on_usage`` closure and every
        ``advance(save)`` agree on the instance.

        Raises:
            FileNotFoundError: propagated from :func:`load_game` when no save
                exists for *game_id* (routers map this to HTTP 404).
        """
        with self._lock:
            save = self._saves.get(game_id)
            if save is None:
                save = load_game(game_id)
                self._saves[game_id] = save
            self._last_used[game_id] = time.monotonic()
            return save

    def advance_lock(self, game_id: str) -> asyncio.Lock:
        """Return the per-game asyncio.Lock serializing load→advance→persist.

        The lock is created lazily under the thread lock so two concurrent
        requests cannot create separate locks for the same game (ARC-102).
        Callers wrap the critical section in ``async with mgr.advance_lock(gid)``.
        """
        with self._lock:
            return self._advance_locks.setdefault(game_id, asyncio.Lock())

    def update_save(self, game_id: str, save: GameSave) -> None:
        """Re-register the owned save.

        Vestigial post-ARC-101 (``get_or_load_save`` registers on first access
        and the pipeline persists via ``save_game`` internally), but kept as a
        no-op-safe re-registration point for any call site that still uses it.
        """
        with self._lock:
            self._saves[game_id] = save
            self._last_used[game_id] = time.monotonic()

    async def evict_idle(self, max_idle_seconds: float = 1800.0) -> list[str]:
        """Evict idle sessions (ARC-106).

        Collects game_ids whose ``_last_used`` stamp is older than
        *max_idle_seconds*, skipping any whose advance lock is currently held
        (a mid-advance game must not be evicted), then awaits :meth:`cleanup`
        for each. Returns the list of evicted game_ids. An evicted game
        transparently re-opens via :meth:`get_or_load_save` on the next request.

        ``cleanup`` cancels in-flight prefetch tasks; saves need no separate
        persistence here because the pipeline is write-through (``save_game``
        is called inside ``advance`` via the ``_on_usage`` closure and at the
        end of beat generation).
        """
        now = time.monotonic()
        with self._lock:
            idle: list[str] = []
            for gid, last in self._last_used.items():
                if now - last <= max_idle_seconds:
                    continue
                lock = self._advance_locks.get(gid)
                if lock is not None and lock.locked():
                    # Do not evict a game mid-advance.
                    continue
                idle.append(gid)
        for gid in idle:
            await self.cleanup(gid)
        return idle

    async def cleanup(self, game_id: str) -> None:
        """Cancel prefetches and remove the pipeline + save + lock for *game_id*."""
        with self._lock:
            pipeline = self._pipelines.pop(game_id, None)
            self._saves.pop(game_id, None)
            self._advance_locks.pop(game_id, None)
            self._last_used.pop(game_id, None)
        if pipeline is not None:
            await pipeline.cancel_all_prefetches()

    async def cleanup_all(self) -> None:
        """Cleanup all active sessions."""
        with self._lock:
            game_ids = list(self._pipelines.keys())
        for gid in game_ids:
            await self.cleanup(gid)
