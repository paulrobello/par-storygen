from __future__ import annotations

from fastapi import APIRouter, WebSocket
from fastapi.websockets import WebSocketDisconnect

from storygen.storage.save import load_game
from storygen_api.deps import build_pipeline, get_app_config, get_session_manager
from storygen_api.ws import ws_manager

router = APIRouter()


@router.websocket("/ws/{game_id}")
async def websocket_endpoint(
    game_id: str,
    ws: WebSocket,
) -> None:
    """Persistent WebSocket for real-time pipeline events."""
    await ws_manager.connect(game_id, ws)
    try:
        # Ensure a pipeline exists for this game
        try:
            save = load_game(game_id)
        except FileNotFoundError:
            await ws.close(code=4404, reason="Game not found")
            return

        mgr = get_session_manager()
        existing = mgr.get_pipeline(game_id)
        if existing is None:
            config = get_app_config()
            callbacks = ws_manager.make_callbacks(game_id)
            pipeline, _img = build_pipeline(save, config, callbacks=callbacks)
            mgr.get_or_create(game_id, save, pipeline)
        else:
            mgr.update_save(game_id, save)

        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "ping":
                await ws.send_json({"type": "pong"})
            elif msg_type == "advance":
                choice_id = data.get("choice_id", "")
                from_node_id = data.get("from_node_id", "")
                if not choice_id or not from_node_id:
                    await ws.send_json(
                        {
                            "type": "error",
                            "error": "advance requires choice_id and from_node_id",
                        }
                    )
                    continue

                # Reload save for latest state
                try:
                    save = load_game(game_id)
                except FileNotFoundError:
                    await ws.send_json({"type": "error", "error": "Game not found"})
                    break
                mgr.update_save(game_id, save)

                pipeline = mgr.get_pipeline(game_id)
                if pipeline is None:
                    await ws.send_json({"type": "error", "error": "No pipeline"})
                    break

                callbacks = ws_manager.make_callbacks(game_id)
                try:
                    await pipeline.advance(
                        save,
                        from_node_id=from_node_id,
                        choice_id=choice_id,
                        callbacks=callbacks,
                    )
                    mgr.update_save(game_id, save)
                except Exception as exc:
                    await ws.send_json(
                        {
                            "type": "error",
                            "error": str(exc),
                        }
                    )
            else:
                await ws.send_json(
                    {
                        "type": "error",
                        "error": f"Unknown message type: {msg_type}",
                    }
                )
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(game_id, ws)
