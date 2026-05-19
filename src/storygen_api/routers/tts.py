from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from storygen.storage import app_state, paths
from storygen.storage.save import load_game
from storygen.tts.player import TTSPlayer

router = APIRouter(prefix="/api/tts", tags=["tts"])

# Module-level TTS player (configured from app state on each request).
_player = TTSPlayer()


def _configure_player() -> None:
    """Re-read TTS prefs and configure the player."""
    prefs = app_state.read_tts_prefs()
    _player.configure(
        prefs.provider,
        api_key=prefs.api_key,
        voice=prefs.voice,
    )


@router.post("/{game_id}/{node_id}/generate")
async def generate_tts(game_id: str, node_id: str) -> JSONResponse:
    """Generate TTS audio for a node's narration and return the audio URL."""
    _configure_player()
    try:
        save = load_game(game_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Game not found")

    node = save.nodes.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    if not node.narration:
        raise HTTPException(status_code=400, detail="Node has no narration")

    prefs = app_state.read_tts_prefs()
    audio_path = paths.tts_audio_path(
        game_id,
        node_id,
        provider=prefs.provider,
        voice=prefs.voice,
    )

    success = await _player.generate(node.narration, audio_path)
    if not success:
        raise HTTPException(status_code=500, detail="TTS generation failed")

    # Update the node with the audio path.
    rel_path = paths.relative_tts_audio_path(
        node_id,
        provider=prefs.provider,
        voice=prefs.voice,
    )
    if node.tts_audio_path != rel_path:
        from storygen.storage.save import save_game

        save.nodes[node_id] = node.model_copy(update={"tts_audio_path": rel_path})
        save_game(save)

    return JSONResponse(
        {
            "audio_url": f"/api/tts/{game_id}/{node_id}/audio",
            "status": "ready",
        }
    )


@router.get("/{game_id}/{node_id}/audio")
async def get_tts_audio(game_id: str, node_id: str) -> FileResponse:
    """Serve cached TTS audio for a node."""
    # Find any audio file for this node.
    audio_files = paths.node_audio_glob(game_id, node_id)
    if not audio_files:
        raise HTTPException(status_code=404, detail="No TTS audio found for this node")

    # Serve the most recent one (sorted by name).
    return FileResponse(audio_files[-1], media_type="audio/mpeg")


@router.get("/{game_id}/{node_id}/status")
async def tts_status(game_id: str, node_id: str) -> JSONResponse:
    """Check if TTS audio exists for a node."""
    audio_files = paths.node_audio_glob(game_id, node_id)
    return JSONResponse(
        {
            "has_audio": len(audio_files) > 0,
            "audio_url": f"/api/tts/{game_id}/{node_id}/audio" if audio_files else None,
        }
    )
