"""WebSocket endpoint streaming live beat generation to the web client.

Server-emitted events follow the contract in ``web/src/lib/ws-types.ts``
(mirrored as pydantic models in ``tests/unit/test_api_ws.py``); client frames
are validated against the save before ``pipeline.advance`` (ARC-007).
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any, cast

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from storygen_api.deps import build_pipeline, get_session_manager
from storygen_api.rate_limit import check_rate_limit
from storygen_api.security import ws_authorize, ws_check_origin
from storygen_api.ws import ws_manager

router = APIRouter()

_logger = logging.getLogger(__name__)

# SEC-011: cap incoming WS messages to 64 KiB. The largest legitimate message
# is an ``advance`` frame with choice_id/from_node_id (~120 bytes); 64 KiB is
# far above any plausible payload but bounds memory if a peer misbehaves.
_WS_MAX_MESSAGE_BYTES = 64 * 1024


async def _receive_json_capped(
    ws: WebSocket, *, max_bytes: int = _WS_MAX_MESSAGE_BYTES
) -> Any:
    """Receive one JSON message, rejecting frames larger than ``max_bytes``.

    Returns ``Any`` (matching Starlette's ``receive_json``) so callers keep
    the same loose-typed ``data.get("type", "")`` pattern. Starlette's
    ``receive_json`` parses whatever arrives; we read text first so an
    oversized frame is rejected before the JSON decoder allocates for it.
    Raises ``WebSocketDisconnect`` on normal close.
    """
    text = await ws.receive_text()
    if len(text.encode("utf-8")) > max_bytes:
        raise _MessageTooLarge()
    return json.loads(text)


class _MessageTooLarge(Exception):
    """Internal sentinel: incoming WS frame exceeded the size cap."""


@router.websocket("/ws/{game_id}")
async def websocket_endpoint(
    game_id: str,
    ws: WebSocket,
) -> None:
    """Persistent WebSocket for real-time pipeline events (SEC-001 auth-gated).

    Auth: bearer token via ``Sec-WebSocket-Protocol: bearer.<token>`` (the
    browser-friendly path) or the standard ``Authorization: Bearer <token>``
    header for non-browser clients. When the server has no
    ``STORYGEN_API_TOKEN`` configured, connections are refused (fail-closed).

    SEC-011: the browser-sent ``Origin`` header is checked against an
    allowlist (same hosts as CORS) at handshake time, and inbound messages
    are capped at :data:`_WS_MAX_MESSAGE_BYTES`.
    """
    # SEC-001: authenticate the handshake BEFORE accepting. Closing before
    # accept surfaces as HTTP 403 to the client (RFC 6455 handshake decline).
    if not ws_authorize(ws):
        await ws.close(code=4403)
        return
    # SEC-011: reject cross-origin browser handshakes; non-browser clients
    # omit Origin and are gated by auth alone.
    if not ws_check_origin(ws):
        await ws.close(code=4403, reason="origin not allowed")
        return

    await ws_manager.connect(game_id, ws)
    try:
        # Ensure a pipeline exists for this game. ARC-101: the manager owns the
        # single live GameSave — ``get_or_load_save`` returns the cached instance
        # so the pipeline's ``_on_usage`` closure agrees with later advances.
        mgr = get_session_manager()
        try:
            save = mgr.get_or_load_save(game_id)
        except FileNotFoundError:
            await ws.close(code=4404, reason="Game not found")
            return

        existing = mgr.get_pipeline(game_id)
        if existing is None:
            callbacks = ws_manager.make_callbacks(game_id)
            pipeline, _img = build_pipeline(save, callbacks=callbacks)
            mgr.get_or_create(game_id, save, pipeline)

        while True:
            try:
                data = await _receive_json_capped(ws)
            except _MessageTooLarge:
                # SEC-011: oversized frame — close with code 1009 (policy
                # violation / message too big) per RFC 6455 §7.4.
                await ws.close(code=1009, reason="message too large")
                break
            except json.JSONDecodeError:
                await ws.send_json(
                    {
                        "type": "error",
                        "code": "bad_request",
                        "message": "invalid JSON",
                    }
                )
                continue
            if not isinstance(data, dict):
                await ws.send_json(
                    {
                        "type": "error",
                        "code": "bad_request",
                        "message": "expected a JSON object",
                    }
                )
                continue
            # ``data`` is Any from json.loads; narrow via cast after the
            # runtime isinstance check so the dict access pattern stays typed.
            msg = cast(dict[str, Any], data)
            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await ws.send_json({"type": "pong"})
            elif msg_type == "advance":
                # SEC-103: rate-limit advance frames keyed by the direct peer
                # host. Checked per advance frame (ping frames are never
                # counted). The HTTP dependency path cannot apply to a
                # WebSocket, so we call the plain check function and translate
                # the 429 into an in-band error frame — the socket stays open
                # so the client may resume once the window slides.
                client_host = ws.client.host if ws.client else "unknown"
                try:
                    check_rate_limit(client_host)
                except HTTPException:
                    await ws.send_json(
                        {
                            "type": "error",
                            "code": "rate_limited",
                            "message": "rate limit exceeded",
                        }
                    )
                    continue

                choice_id = msg.get("choice_id", "")
                from_node_id = msg.get("from_node_id", "")
                if not choice_id or not from_node_id:
                    await ws.send_json(
                        {
                            "type": "error",
                            "code": "bad_request",
                            "message": "advance requires choice_id and from_node_id",
                        }
                    )
                    continue

                # ARC-101: the manager owns the single live GameSave.
                # ARC-102: the per-game asyncio.Lock serializes validate→
                # advance→persist so two concurrent WS advances cannot lose
                # a child node.
                try:
                    save = mgr.get_or_load_save(game_id)
                except FileNotFoundError:
                    await ws.send_json(
                        {"type": "error", "code": "not_found", "message": "Game not found"}
                    )
                    break

                async with mgr.advance_lock(game_id):
                    # ARC-007: validate choice_id / from_node_id against the
                    # actual save BEFORE invoking pipeline.advance. Pre-ARC-007
                    # arbitrary strings were passed straight through; an unknown
                    # id either tripped the pipeline's internal ValueError after
                    # LLM/image work had already started, or — for a malformed
                    # from_node_id — silently produced a bogus beat. Reject
                    # early with a clean bad_request event instead.
                    parent_node = save.nodes.get(from_node_id)
                    if parent_node is None:
                        await ws.send_json(
                            {
                                "type": "error",
                                "code": "bad_request",
                                "message": f"unknown from_node_id: {from_node_id}",
                            }
                        )
                        continue
                    if not any(c.id == choice_id for c in parent_node.choices):
                        await ws.send_json(
                            {
                                "type": "error",
                                "code": "bad_request",
                                "message": (
                                    f"choice_id {choice_id} is not on node {from_node_id}"
                                ),
                            }
                        )
                        continue

                    pipeline = mgr.get_pipeline(game_id)
                    if pipeline is None:
                        await ws.send_json(
                            {"type": "error", "code": "no_pipeline", "message": "No pipeline"}
                        )
                        break

                    callbacks = ws_manager.make_callbacks(game_id)
                    try:
                        await pipeline.advance(
                            save,
                            from_node_id=from_node_id,
                            choice_id=choice_id,
                            callbacks=callbacks,
                        )
                    except Exception:
                        # SEC-004: log server-side; emit a generic error code,
                        # never the raw exception string (which can leak the
                        # configured base_url, internal paths, or provider body).
                        _logger.exception(
                            "WS pipeline.advance failed for game %s", game_id
                        )
                        await ws.send_json(
                            {
                                "type": "error",
                                "code": "internal_error",
                                "message": "internal error",
                            }
                        )
            else:
                await ws.send_json(
                    {
                        "type": "error",
                        "code": "bad_request",
                        "message": f"Unknown message type: {msg_type}",
                    }
                )
    except WebSocketDisconnect:
        pass
    finally:
        if ws.client_state == WebSocketState.CONNECTED:
            with contextlib.suppress(RuntimeError):
                await ws_manager.disconnect(game_id, ws)
