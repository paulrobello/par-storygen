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
    """Manages WebSocket connections per game and bridges PipelineCallbacks.

    The broadcast payloads emitted here are the source-of-truth server side of
    the WebSocket event contract — they must match the TypeScript
    ``ServerEvent`` union in ``web/src/lib/ws-types.ts``. The contract tests in
    ``tests/unit/test_api_ws.py`` pin every payload's shape against a pydantic
    mirror of that TS file (ARC-001).
    """

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

    async def broadcast_error(
        self, game_id: str, *, message: str, code: str = "internal_error"
    ) -> None:
        """Emit an ``error`` event per the ws-types.ts contract.

        Field is ``message`` (not ``error``) to match ``ServerError`` in
        ``web/src/lib/ws-types.ts`` and what ``useWebSocket.ts`` reads.
        """
        await self._broadcast(
            game_id,
            {"type": "error", "code": code, "message": message},
        )

    def make_callbacks(self, game_id: str) -> PipelineCallbacks:
        """Create PipelineCallbacks that broadcast contract-correct events.

        Each handler emits the exact fields declared in
        ``web/src/lib/ws-types.ts`` so the React hook (``useWebSocket.ts``)
        reads what the server sends. Pre-ARC-001 these were three-way
        divergent (server sent ``delta`` but hook read ``text``; server omitted
        ``choices[]`` from beat_committed; image_committed was emitted as
        ``image_status``; image_failed sent ``status`` instead of ``error``;
        new_characters omitted the per-character card fields).
        """

        async def on_narration_delta(delta: str) -> None:
            # Contract: ServerNarrationDelta {type, node_id, text}.
            # The pipeline fires this before the beat is committed, so we
            # don't yet know the child node id; the hook appends to a running
            # narration buffer keyed by the eventual beat_committed.node_id.
            # Emit node_id="" (the hook treats it as a delta on the current
            # node) and ``text=delta`` so the existing reader path works.
            await self._broadcast(
                game_id,
                {
                    "type": "narration_delta",
                    "node_id": "",
                    "text": delta,
                    "ts": datetime.now(UTC).isoformat(),
                },
            )

        async def on_beat_committed(node: StoryNode) -> None:
            # Contract: ServerBeatCommitted {type, node_id, is_ending, choices[]}.
            # choices[] must be non-empty so the player can pick the next step.
            await self._broadcast(
                game_id,
                {
                    "type": "beat_committed",
                    "node_id": node.id,
                    "is_ending": node.is_ending,
                    "choices": [
                        {
                            "id": c.id,
                            "text": c.text,
                            "child_node_id": c.child_node_id,
                        }
                        for c in node.choices
                    ],
                    "ts": datetime.now(UTC).isoformat(),
                },
            )

        async def on_image_committed(node: StoryNode) -> None:
            # Contract: ServerImageCommitted {type, node_id, image_path}.
            # Fires when the scene illustration lands. Pre-ARC-001 this hook
            # emitted type="image_status" which the React useWebSocket
            # image_committed case never matched — scene art never rendered.
            await self._broadcast(
                game_id,
                {
                    "type": "image_committed",
                    "node_id": node.id,
                    "image_path": node.image_path or "",
                    "ts": datetime.now(UTC).isoformat(),
                },
            )

        async def on_image_failed(node: StoryNode) -> None:
            # Contract: ServerImageFailed {type, node_id, error}.
            # Pre-ARC-001 sent ``status`` which the hook read as ``msg.error``
            # (undefined) — image failures surfaced no message to the player.
            await self._broadcast(
                game_id,
                {
                    "type": "image_failed",
                    "node_id": node.id,
                    "error": f"image generation failed (status={node.image_status})",
                    "ts": datetime.now(UTC).isoformat(),
                },
            )

        async def on_new_characters(characters: list[Character]) -> None:
            # Contract: ServerNewCharacters {type, characters[{id, name,
            # backstory, personality, physical_description, portrait_path}]}.
            # Pre-ARC-101 sent only {id, name} — the hook's addCharacters call
            # expected the full Character card.
            await self._broadcast(
                game_id,
                {
                    "type": "new_characters",
                    "characters": [
                        {
                            "id": c.id,
                            "name": c.name,
                            "backstory": c.backstory,
                            "personality": c.personality,
                            "physical_description": c.physical_description,
                            "portrait_path": c.portrait_path,
                        }
                        for c in characters
                    ],
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
