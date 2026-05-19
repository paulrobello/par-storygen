from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from storygen.config import AppConfig
from storygen.storage import paths
from storygen.storage.save import load_game

from storygen_api.deps import build_pipeline, get_app_config, get_session_manager
from storygen_api.schemas import SceneEditRequest
from storygen_api.session import PipelineSessionManager
from storygen_api.ws import ws_manager

router = APIRouter(prefix="/api/images", tags=["images"])


@router.get("/{game_id}/scene/{node_id}")
async def get_scene_image(game_id: str, node_id: str) -> FileResponse:
    """Serve a scene PNG for a story node."""
    image_path = paths.node_image_path(game_id, node_id)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Scene image not found")
    return FileResponse(image_path, media_type="image/png")


@router.get("/{game_id}/portrait/{char_id}")
async def get_portrait_image(game_id: str, char_id: str) -> FileResponse:
    """Serve the latest character portrait PNG."""
    version = paths.latest_portrait_version(game_id, char_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Portrait not found")
    portrait_path = paths.character_portrait_path(game_id, char_id, version)
    if not portrait_path.exists():
        raise HTTPException(status_code=404, detail="Portrait file not found")
    return FileResponse(portrait_path, media_type="image/png")


@router.post("/{game_id}/scene/{node_id}/retry")
async def retry_scene(
    game_id: str,
    node_id: str,
    mgr: PipelineSessionManager = Depends(get_session_manager),
    config: AppConfig = Depends(get_app_config),
) -> dict[str, str]:
    """Retry scene image generation for a node."""
    try:
        save = load_game(game_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Game not found")

    pipeline = mgr.get_pipeline(game_id)
    if pipeline is None:
        callbacks = ws_manager.make_callbacks(game_id)
        pipeline, _img = build_pipeline(save, config, callbacks=callbacks)
        mgr.get_or_create(game_id, save, pipeline)

    mgr.update_save(game_id, save)
    callbacks = ws_manager.make_callbacks(game_id)

    try:
        node = await pipeline.retry_scene(save, node_id=node_id, callbacks=callbacks)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    mgr.update_save(game_id, save)
    return {"status": node.image_status}


@router.post("/{game_id}/scene/{node_id}/edit")
async def edit_scene(
    game_id: str,
    node_id: str,
    body: SceneEditRequest,
    mgr: PipelineSessionManager = Depends(get_session_manager),
    config: AppConfig = Depends(get_app_config),
) -> dict[str, str]:
    """Edit scene prompt and regenerate."""
    try:
        save = load_game(game_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Game not found")

    pipeline = mgr.get_pipeline(game_id)
    if pipeline is None:
        callbacks = ws_manager.make_callbacks(game_id)
        pipeline, _img = build_pipeline(save, config, callbacks=callbacks)
        mgr.get_or_create(game_id, save, pipeline)

    mgr.update_save(game_id, save)
    callbacks = ws_manager.make_callbacks(game_id)

    try:
        node = await pipeline.edit_scene(
            save,
            node_id=node_id,
            new_prompt=body.prompt,
            callbacks=callbacks,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    mgr.update_save(game_id, save)
    return {"status": node.image_status}


@router.post("/{game_id}/portrait/{char_id}/regenerate")
async def regenerate_portrait(
    game_id: str,
    char_id: str,
) -> dict[str, str]:
    """Regenerate a character portrait.

    This is a simplified endpoint — full portrait regeneration requires the
    pipeline's image provider which handles reference images. For now, we
    return a placeholder response indicating the operation needs to be done
    through the full pipeline.
    """
    try:
        save = load_game(game_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Game not found")

    char = next((c for c in save.characters if c.id == char_id), None)
    if char is None:
        raise HTTPException(status_code=404, detail="Character not found")

    return {
        "status": "portrait_regeneration_requires_pipeline",
        "character_id": char_id,
    }
