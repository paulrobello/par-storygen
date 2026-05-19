from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

from storygen.core.models import Character, StoryNode
from storygen.pipeline import PipelineCallbacks

_logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections per game and bridges PipelineCallbacks."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, game_id: str, ws: WebSocket) -> None:
        await ws.accept()
        if game_id not in self._connections:
            self._connections[game_id] = []
        self._connections[game_id].append(ws)

    def disconnect(self, game_id: str, ws: WebSocket) -> None:
        conns = self._connections.get(game_id)
        if conns is not None:
            with contextlib.suppress(ValueError):
                conns.remove(ws)
            if not conns:
                del self._connections[game_id]

    async def _broadcast(self, game_id: str, data: dict[str, Any]) -> None:
        conns = self._connections.get(game_id, [])
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(game_id, ws)

    def make_callbacks(self, game_id: str) -> PipelineCallbacks:
        """Create PipelineCallbacks that broadcast events to WebSocket clients."""

        async def on_narration_delta(delta: str) -> None:
            await self._broadcast(
                game_id,
                {
                    "type": "narration_delta",
                    "delta": delta,
                    "ts": datetime.now(UTC).isoformat(),
                },
            )

        async def on_beat_committed(node: StoryNode) -> None:
            await self._broadcast(
                game_id,
                {
                    "type": "beat_committed",
                    "node_id": node.id,
                    "is_ending": node.is_ending,
                    "ts": datetime.now(UTC).isoformat(),
                },
            )

        async def on_image_committed(node: StoryNode) -> None:
            await self._broadcast(
                game_id,
                {
                    "type": "image_status",
                    "node_id": node.id,
                    "status": node.image_status,
                    "ts": datetime.now(UTC).isoformat(),
                },
            )

        async def on_image_failed(node: StoryNode) -> None:
            await self._broadcast(
                game_id,
                {
                    "type": "image_failed",
                    "node_id": node.id,
                    "status": node.image_status,
                    "ts": datetime.now(UTC).isoformat(),
                },
            )

        async def on_new_characters(characters: list[Character]) -> None:
            await self._broadcast(
                game_id,
                {
                    "type": "new_characters",
                    "characters": [{"id": c.id, "name": c.name} for c in characters],
                    "ts": datetime.now(UTC).isoformat(),
                },
            )

        return PipelineCallbacks(
            on_narration_delta=on_narration_delta,
            on_beat_committed=on_beat_committed,
            on_image_committed=on_image_committed,
            on_image_failed=on_image_failed,
            on_new_characters=on_new_characters,
        )


# Singleton
ws_manager = WebSocketManager()
