from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from storygen.config import AppConfig
from storygen.images.constants import PORTRAIT_QUALITY, PORTRAIT_SIZE
from storygen.images.pricing import image_cost
from storygen.storage import paths
from storygen.storage.save import load_game, save_game
from storygen_api.deps import (
    build_pipeline,
    build_split_image_provider,
    get_app_config,
    get_session_manager,
)
from storygen_api.schemas import (
    OutfitActionRequest,
    OutfitRequest,
    PortraitEditRequest,
    SceneEditRequest,
)
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


@router.post("/{game_id}/portrait/{char_id}/retry")
async def retry_portrait(
    game_id: str,
    char_id: str,
    config: AppConfig = Depends(get_app_config),
) -> dict[str, str]:
    """Retry (regenerate) a character portrait using the stored portrait_prompt."""
    try:
        save = load_game(game_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Game not found")

    char_idx = next((i for i, c in enumerate(save.characters) if c.id == char_id), None)
    if char_idx is None:
        raise HTTPException(status_code=404, detail="Character not found")
    char = save.characters[char_idx]

    image_provider = build_split_image_provider(save, config)
    prompt = char.portrait_prompt or char.physical_description

    # Read reference image if available
    ref_bytes: bytes | None = None
    if char.reference_image_path:
        ref_path = paths.character_reference_path(game_id, char_id)
        if ref_path.exists():
            ref_bytes = ref_path.read_bytes()

    try:
        portrait_bytes = await image_provider.generate_portrait(
            prompt,
            transparent=True,
            art_style=save.art_style,
            reference_image=ref_bytes,
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Portrait generation failed")

    # Track cost
    save.total_image_cost_usd += image_cost(
        save.character_image_config.provider,
        model=save.character_image_config.model,
        size=PORTRAIT_SIZE,
        quality=PORTRAIT_QUALITY,
    )

    # Write new versioned portrait (atomic write)
    version = paths.next_portrait_version(game_id, char_id)
    dest = paths.character_portrait_path(game_id, char_id, version)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".png.tmp")
    tmp.write_bytes(portrait_bytes)
    os.replace(tmp, dest)

    # Update character's portrait_path
    rel_path = str(dest.relative_to(paths.game_dir(game_id)))
    save.characters[char_idx] = char.model_copy(update={"portrait_path": rel_path})
    save_game(save)

    return {"status": "done", "character_id": char_id}


@router.post("/{game_id}/portrait/{char_id}/edit")
async def edit_portrait(
    game_id: str,
    char_id: str,
    body: PortraitEditRequest,
    config: AppConfig = Depends(get_app_config),
) -> dict[str, str]:
    """Edit a character portrait prompt and regenerate."""
    try:
        save = load_game(game_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Game not found")

    char_idx = next((i for i, c in enumerate(save.characters) if c.id == char_id), None)
    if char_idx is None:
        raise HTTPException(status_code=404, detail="Character not found")
    char = save.characters[char_idx]

    image_provider = build_split_image_provider(save, config)

    # Build prompt based on mode
    if body.mode == "edit":
        original = char.portrait_prompt or char.physical_description
        description = f"{original}\n\nEdit instructions: {body.prompt}"
    else:
        description = body.prompt

    # Reference image handling
    ref_bytes: bytes | None = None
    if body.use_current_as_ref:
        # Use current portrait as reference
        version = paths.latest_portrait_version(game_id, char_id)
        if version is not None:
            current_path = paths.character_portrait_path(game_id, char_id, version)
            if current_path.exists():
                ref_bytes = current_path.read_bytes()
        # Fall back to stored reference image
        if ref_bytes is None and char.reference_image_path:
            ref_path = paths.character_reference_path(game_id, char_id)
            if ref_path.exists():
                ref_bytes = ref_path.read_bytes()

    try:
        portrait_bytes = await image_provider.generate_portrait(
            description,
            transparent=True,
            art_style=save.art_style,
            reference_image=ref_bytes,
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Portrait generation failed")

    # Track cost
    save.total_image_cost_usd += image_cost(
        save.character_image_config.provider,
        model=save.character_image_config.model,
        size=PORTRAIT_SIZE,
        quality=PORTRAIT_QUALITY,
    )

    # Write new versioned portrait (atomic write)
    version = paths.next_portrait_version(game_id, char_id)
    dest = paths.character_portrait_path(game_id, char_id, version)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".png.tmp")
    tmp.write_bytes(portrait_bytes)
    os.replace(tmp, dest)

    # Update character's portrait_path and portrait_prompt
    rel_path = str(dest.relative_to(paths.game_dir(game_id)))
    save.characters[char_idx] = char.model_copy(
        update={"portrait_path": rel_path, "portrait_prompt": description}
    )
    save_game(save)

    return {"status": "done", "character_id": char_id}


@router.post("/{game_id}/cover/regenerate")
async def regenerate_cover(
    game_id: str,
    mgr: PipelineSessionManager = Depends(get_session_manager),
    config: AppConfig = Depends(get_app_config),
) -> dict[str, str]:
    """Regenerate the cover art (root node scene image)."""
    try:
        save = load_game(game_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Game not found")

    root_node = save.nodes.get(save.root_node_id)
    if root_node is None:
        raise HTTPException(status_code=400, detail="No root node found")

    pipeline = mgr.get_pipeline(game_id)
    if pipeline is None:
        callbacks = ws_manager.make_callbacks(game_id)
        pipeline, _img = build_pipeline(save, config, callbacks=callbacks)
        mgr.get_or_create(game_id, save, pipeline)

    mgr.update_save(game_id, save)
    callbacks = ws_manager.make_callbacks(game_id)

    try:
        node = await pipeline.retry_scene(save, node_id=save.root_node_id, callbacks=callbacks)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    mgr.update_save(game_id, save)
    return {"status": node.image_status}


# ---------------------------------------------------------------------------
# Outfit endpoints
# ---------------------------------------------------------------------------


@router.post("/{game_id}/portrait/{char_id}/outfit")
async def add_outfit(
    game_id: str,
    char_id: str,
    body: OutfitRequest,
    config: AppConfig = Depends(get_app_config),
) -> dict[str, str]:
    """Create a new outfit for a character and generate its portrait."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from storygen.core.models import CharacterOutfit

    try:
        save = load_game(game_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Game not found")

    char_idx = next((i for i, c in enumerate(save.characters) if c.id == char_id), None)
    if char_idx is None:
        raise HTTPException(status_code=404, detail="Character not found")
    char = save.characters[char_idx]

    outfit_id = uuid4().hex
    prompt = f"{char.physical_description}. Outfit: {body.description}"
    image_provider = build_split_image_provider(save, config)

    ref_bytes: bytes | None = None
    if char.reference_image_path:
        ref_path = paths.character_reference_path(game_id, char_id)
        if ref_path.exists():
            ref_bytes = ref_path.read_bytes()

    try:
        portrait_bytes = await image_provider.generate_portrait(
            prompt,
            transparent=True,
            art_style=save.art_style,
            reference_image=ref_bytes,
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Outfit portrait generation failed")

    dest = paths.character_outfit_path(game_id, char_id, outfit_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".png.tmp")
    tmp.write_bytes(portrait_bytes)
    os.replace(tmp, dest)

    rel_path = paths.relative_character_outfit_path(char_id, outfit_id)
    outfit = CharacterOutfit(
        id=outfit_id,
        name=body.name,
        description=body.description,
        portrait_path=rel_path,
        portrait_prompt=prompt,
        created_at=datetime.now(UTC),
    )

    save.characters[char_idx] = char.model_copy(update={"outfits": [*char.outfits, outfit]})
    save_game(save)
    return {"status": "done", "outfit_id": outfit_id}


@router.post("/{game_id}/portrait/{char_id}/outfit/{outfit_id}/set")
async def set_outfit(game_id: str, char_id: str, outfit_id: str) -> dict[str, str]:
    """Set an outfit as the current active outfit."""
    try:
        save = load_game(game_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Game not found")

    char_idx = next((i for i, c in enumerate(save.characters) if c.id == char_id), None)
    if char_idx is None:
        raise HTTPException(status_code=404, detail="Character not found")
    char = save.characters[char_idx]

    outfit = next((o for o in char.outfits if o.id == outfit_id), None)
    if outfit is None:
        raise HTTPException(status_code=404, detail="Outfit not found")

    save.characters[char_idx] = char.model_copy(
        update={
            "portrait_path": outfit.portrait_path,
            "portrait_prompt": outfit.portrait_prompt,
            "current_outfit_id": outfit_id,
        }
    )
    save_game(save)
    return {"status": "done"}


@router.delete("/{game_id}/portrait/{char_id}/outfit/{outfit_id}")
async def delete_outfit(game_id: str, char_id: str, outfit_id: str) -> dict[str, str]:
    """Delete an outfit."""
    try:
        save = load_game(game_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Game not found")

    char_idx = next((i for i, c in enumerate(save.characters) if c.id == char_id), None)
    if char_idx is None:
        raise HTTPException(status_code=404, detail="Character not found")
    char = save.characters[char_idx]

    outfit = next((o for o in char.outfits if o.id == outfit_id), None)
    if outfit is None:
        raise HTTPException(status_code=404, detail="Outfit not found")

    abs_path = paths.safe_join(paths.game_dir(game_id), outfit.portrait_path)
    if abs_path.exists():
        abs_path.unlink()

    updates: dict[str, object] = {
        "outfits": [o for o in char.outfits if o.id != outfit_id],
    }
    if char.current_outfit_id == outfit_id:
        version = paths.latest_portrait_version(game_id, char_id)
        if version is not None:
            base_path = paths.character_portrait_path(game_id, char_id, version)
            if base_path.exists():
                updates["portrait_path"] = str(base_path.relative_to(paths.game_dir(game_id)))
        updates["current_outfit_id"] = None

    save.characters[char_idx] = char.model_copy(update=updates)
    save_game(save)
    return {"status": "done"}


@router.post("/{game_id}/portrait/{char_id}/outfit/revert")
async def revert_outfit(game_id: str, char_id: str) -> dict[str, str]:
    """Revert to the base portrait (unset current outfit)."""
    try:
        save = load_game(game_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Game not found")

    char_idx = next((i for i, c in enumerate(save.characters) if c.id == char_id), None)
    if char_idx is None:
        raise HTTPException(status_code=404, detail="Character not found")
    char = save.characters[char_idx]

    version = paths.latest_portrait_version(game_id, char_id)
    base_rel: str | None = None
    if version is not None:
        base_path = paths.character_portrait_path(game_id, char_id, version)
        if base_path.exists():
            base_rel = str(base_path.relative_to(paths.game_dir(game_id)))

    updates: dict[str, object] = {"current_outfit_id": None}
    if base_rel is not None:
        updates["portrait_path"] = base_rel

    save.characters[char_idx] = char.model_copy(update=updates)
    save_game(save)
    return {"status": "done"}
