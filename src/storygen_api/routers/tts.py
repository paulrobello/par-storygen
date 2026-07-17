"""Text-to-speech synthesis and cached per-node audio serving routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from storygen.storage import app_state, paths
from storygen.storage.app_state import TTSPrefs
from storygen.tts.player import TTSPlayer
from storygen_api.deps import get_session_manager
from storygen_api.security import verify_token
from storygen_api.session import PipelineSessionManager

router = APIRouter(
    prefix="/api/tts",
    tags=["tts"],
    # SEC-001: TTS generate is cost-incurring; status/audio reads reveal user content.
    dependencies=[Depends(verify_token)],
)


def _build_player(prefs: TTSPrefs) -> TTSPlayer:
    """Build a freshly-configured per-request TTS player (ARC-107).

    TTSPlayer construction is cheap (attribute init only; the provider is
    built lazily inside ``configure``). Audio cache is on disk keyed by
    ``(node_id, provider, voice)``, so per-request instances don't lose it.
    Per-request players eliminate the race class where two concurrent
    generate calls interleave configure→generate on a shared instance.
    """
    player = TTSPlayer()
    player.configure(prefs.provider, api_key=prefs.api_key, voice=prefs.voice)
    return player


@router.post("/{game_id}/{node_id}/generate")
async def generate_tts(
    game_id: str,
    node_id: str,
    mgr: PipelineSessionManager = Depends(get_session_manager),
) -> JSONResponse:
    """Generate TTS audio for a node's narration and return the audio URL."""
    prefs = app_state.read_tts_prefs()
    player = _build_player(prefs)
    try:
        save = mgr.get_or_load_save(game_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game not found") from exc

    node = save.nodes.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    if not node.narration:
        raise HTTPException(status_code=400, detail="Node has no narration")

    audio_path = paths.tts_audio_path(
        game_id,
        node_id,
        provider=prefs.provider,
        voice=prefs.voice,
    )

    success = await player.generate(node.narration, audio_path)
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
