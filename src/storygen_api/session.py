from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from storygen.storage.save import GameSave

if TYPE_CHECKING:
    from storygen.pipeline import BeatPipeline


class PipelineSessionManager:
    """Thread-safe registry of per-game BeatPipeline instances."""

    def __init__(self) -> None:
        self._pipelines: dict[str, BeatPipeline] = {}
        self._saves: dict[str, GameSave] = {}
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
            return self._pipelines[game_id]

    def get_pipeline(self, game_id: str) -> BeatPipeline | None:
        with self._lock:
            return self._pipelines.get(game_id)

    def get_save(self, game_id: str) -> GameSave | None:
        with self._lock:
            return self._saves.get(game_id)

    def update_save(self, game_id: str, save: GameSave) -> None:
        with self._lock:
            self._saves[game_id] = save

    async def cleanup(self, game_id: str) -> None:
        """Cancel prefetches and remove the pipeline for *game_id*."""
        with self._lock:
            pipeline = self._pipelines.pop(game_id, None)
            self._saves.pop(game_id, None)
        if pipeline is not None:
            await pipeline.cancel_all_prefetches()

    async def cleanup_all(self) -> None:
        """Cleanup all active sessions."""
        with self._lock:
            game_ids = list(self._pipelines.keys())
        for gid in game_ids:
            await self.cleanup(gid)
