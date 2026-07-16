from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from typing import cast

from storygen.config import AppConfig
from storygen.core.models import NodeId, StoryNode
from storygen.storage import paths
from storygen.storage.save import delete_game, load_game, prune_subtree, save_game
from storygen.storage.tree import path_from_root

from storygen_api.deps import build_pipeline, get_app_config, get_session_manager
from storygen_api.rate_limit import enforce_rate_limit
from storygen_api.schemas import (
    AdvanceRequest,
    AdvanceResponse,
    ChoiceOption,
    GameDetail,
    GameListResponse,
    GameSummary,
    GraphEdge,
    GraphResponse,
    JumpRequest,
    NodeDetail,
    PruneRequest,
    RegenerateNodeRequest,
)
from storygen_api.security import verify_token
from storygen.export.book import export_book, sanitize_title
from storygen_api.session import PipelineSessionManager
from storygen_api.ws import ws_manager

router = APIRouter(
    prefix="/api/games",
    tags=["games"],
    # SEC-001: every games route reads or mutates user content; gate all of them
    # behind the shared bearer token. GET /api/health on the root app stays open.
    dependencies=[Depends(verify_token)],
)

_logger = logging.getLogger(__name__)


def _node_to_detail(node: StoryNode) -> NodeDetail:
    return NodeDetail(
        id=node.id,
        parent_id=node.parent_id,
        chosen_choice_id=node.chosen_choice_id,
        narration=node.narration,
        is_major=node.is_major,
        is_ending=node.is_ending,
        image_status=node.image_status,
        image_path=node.image_path,
        image_prompt=node.image_prompt,
        summary_to_here=node.summary_to_here,
        choices=[
            ChoiceOption(id=c.id, text=c.text, child_node_id=c.child_node_id) for c in node.choices
        ],
        created_at=node.created_at,
    )


@router.get("", response_model=GameListResponse)
async def list_games() -> GameListResponse:
    """List all saved games with summary metadata."""
    root = paths.games_root()
    if not root.exists():
        return GameListResponse(games=[])
    summaries: list[GameSummary] = []
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        game_file = directory / "game.json"
        if not game_file.exists():
            continue
        try:
            raw: object = json.loads(game_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        data = cast(dict[str, object], raw)
        theme_obj = data.get("theme")
        if not isinstance(theme_obj, dict):
            continue
        theme_data = cast(dict[str, object], theme_obj)
        title = theme_data.get("title")
        if not isinstance(title, str):
            continue
        game_id = directory.name
        updated_at_raw = data.get("updated_at", "")
        updated_at = (
            datetime.fromisoformat(updated_at_raw)
            if isinstance(updated_at_raw, str) and updated_at_raw
            else datetime.min
        )
        nodes_obj = data.get("nodes")
        node_count: int = 0
        current_node: dict[str, object] | None = None
        if isinstance(nodes_obj, dict):
            typed_nodes = cast(dict[str, object], nodes_obj)
            node_count = len(typed_nodes)
            current_id = data.get("current_node_id")
            if isinstance(current_id, str):
                candidate = typed_nodes.get(current_id)
                if isinstance(candidate, dict):
                    current_node = cast(dict[str, object], candidate)
        is_ending = False
        if current_node is not None:
            is_ending = bool(current_node.get("is_ending", False))
        # Check if root node has cover art
        has_cover = False
        if isinstance(nodes_obj, dict):
            typed_nodes = cast(dict[str, object], nodes_obj)
            root_id = data.get("root_node_id")
            if isinstance(root_id, str):
                root_node_raw = typed_nodes.get(root_id)
                if isinstance(root_node_raw, dict):
                    root_node_data = cast(dict[str, object], root_node_raw)
                    img_status = root_node_data.get("image_status")
                    has_cover = img_status == "done"
        summaries.append(
            GameSummary(
                id=game_id,
                title=title,
                updated_at=updated_at,
                node_count=node_count,
                is_ending=is_ending,
                has_cover=has_cover,
            )
        )
    summaries.sort(key=lambda s: s.updated_at, reverse=True)
    return GameListResponse(games=summaries)


@router.get("/{game_id}", response_model=GameDetail)
async def get_game(game_id: str) -> GameDetail:
    """Return full game state."""
    try:
        save = load_game(game_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game not found") from exc
    node_details = {nid: _node_to_detail(n) for nid, n in save.nodes.items()}
    return GameDetail(
        id=str(save.id),
        title=save.theme.title,
        theme=save.theme.model_dump(),
        tone=save.tone.model_dump(),
        characters=[c.model_dump() for c in save.characters],
        current_node_id=save.current_node_id,
        root_node_id=save.root_node_id,
        nodes=node_details,
        endings_reached=save.endings_reached,
        art_style=save.art_style,
        total_image_cost_usd=save.total_image_cost_usd,
        text_total_input_tokens=save.text_total_input_tokens,
        text_total_output_tokens=save.text_total_output_tokens,
        text_total_requests=save.text_total_requests,
        relationships=[r.model_dump() for r in save.relationships],
        created_at=save.created_at,
        updated_at=save.updated_at,
    )


@router.post(
    "/{game_id}/advance",
    response_model=AdvanceResponse,
    dependencies=[Depends(enforce_rate_limit)],
)
async def advance_game(
    game_id: str,
    body: AdvanceRequest,
    mgr: PipelineSessionManager = Depends(get_session_manager),
    config: AppConfig = Depends(get_app_config),
) -> AdvanceResponse:
    """Pick a choice and advance the story."""
    try:
        save = load_game(game_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game not found") from exc

    pipeline = mgr.get_pipeline(game_id)
    if pipeline is None:
        callbacks = ws_manager.make_callbacks(game_id)
        pipeline, _img = build_pipeline(save, config, callbacks=callbacks)
        mgr.get_or_create(game_id, save, pipeline)

    # Refresh the save reference in the session manager
    mgr.update_save(game_id, save)

    callbacks = ws_manager.make_callbacks(game_id)
    try:
        node = await pipeline.advance(
            save,
            from_node_id=body.from_node_id,
            choice_id=body.choice_id,
            callbacks=callbacks,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # SEC-004: do not leak the provider/pipeline exception string.
        _logger.exception("advance_game failed for game %s", game_id)
        raise HTTPException(status_code=500, detail="internal error") from exc

    mgr.update_save(game_id, save)

    # Reload save to pick up the latest mutations
    save = load_game(game_id)
    new_char_ids = [c for c in save.characters if c.introduced_at_node_id == node.id]

    return AdvanceResponse(
        node=_node_to_detail(node),
        new_characters=new_char_ids,
        image_status=node.image_status,
    )


@router.delete("/{game_id}", status_code=204)
async def delete_game_endpoint(
    game_id: str,
    mgr: PipelineSessionManager = Depends(get_session_manager),
) -> None:
    """Delete a game save."""
    await mgr.cleanup(game_id)
    try:
        delete_game(game_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game not found") from exc


@router.post("/{game_id}/jump", response_model=GameDetail)
async def jump_to_node(game_id: str, body: JumpRequest) -> GameDetail:
    """Set the current node to a target node."""
    try:
        save = load_game(game_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game not found") from exc
    if body.target_node_id not in save.nodes:
        raise HTTPException(status_code=404, detail="Node not found")
    save.current_node_id = body.target_node_id
    save_game(save)
    return await get_game(game_id)


@router.get("/{game_id}/graph", response_model=GraphResponse)
async def get_graph(game_id: str) -> GraphResponse:
    """Return all choice edges for the story graph (visited + unvisited)."""
    try:
        save = load_game(game_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game not found") from exc
    edges: list[GraphEdge] = []
    for parent_id, node in save.nodes.items():
        for c in node.choices:
            child_id = c.child_node_id
            edges.append(
                GraphEdge(
                    parent_id=parent_id,
                    choice_text=c.text,
                    child_id=child_id,
                )
            )
    return GraphResponse(edges=edges)


@router.get("/{game_id}/endings", response_model=list[NodeId])
async def list_endings(game_id: str) -> list[NodeId]:
    """List reached ending node IDs."""
    try:
        save = load_game(game_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game not found") from exc
    return save.endings_reached


@router.post("/{game_id}/prune")
async def prune_subtree_endpoint(
    game_id: str,
    body: PruneRequest,
) -> dict[str, int]:
    """Prune a subtree starting at the given node."""
    try:
        save = load_game(game_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game not found") from exc
    try:
        count = prune_subtree(save, node_id=body.node_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"removed_count": count}


@router.post(
    "/{game_id}/regenerate-node",
    response_model=AdvanceResponse,
    dependencies=[Depends(enforce_rate_limit)],
)
async def regenerate_node(
    game_id: str,
    body: RegenerateNodeRequest,
    mgr: PipelineSessionManager = Depends(get_session_manager),
    config: AppConfig = Depends(get_app_config),
) -> AdvanceResponse:
    """Regenerate the current node by pruning it and re-advending from parent."""
    try:
        save = load_game(game_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game not found") from exc

    node = save.nodes.get(save.current_node_id)
    if node is None:
        raise HTTPException(status_code=400, detail="No current node")
    if node.parent_id is None or node.chosen_choice_id is None:
        raise HTTPException(status_code=400, detail="Cannot regenerate root node")
    if any(c.child_node_id for c in node.choices):
        raise HTTPException(status_code=400, detail="Cannot regenerate — node has descendants")

    parent_id = node.parent_id
    choice_id = node.chosen_choice_id

    # Prune the current node
    prune_subtree(save, node_id=node.id)

    # Re-advance from parent with the same choice
    pipeline = mgr.get_pipeline(game_id)
    if pipeline is None:
        callbacks = ws_manager.make_callbacks(game_id)
        pipeline, _img = build_pipeline(save, config, callbacks=callbacks)
        mgr.get_or_create(game_id, save, pipeline)
    mgr.update_save(game_id, save)
    callbacks = ws_manager.make_callbacks(game_id)

    try:
        new_node = await pipeline.advance(
            save,
            from_node_id=parent_id,
            choice_id=choice_id,
            callbacks=callbacks,
        )
    except Exception as exc:
        # SEC-004: do not leak the provider/pipeline exception string.
        _logger.exception("regenerate_node failed for game %s", game_id)
        raise HTTPException(status_code=500, detail="internal error") from exc

    mgr.update_save(game_id, save)
    save = load_game(game_id)
    new_char_ids = [c for c in save.characters if c.introduced_at_node_id == new_node.id]

    return AdvanceResponse(
        node=_node_to_detail(new_node),
        new_characters=new_char_ids,
    )


@router.get("/{game_id}/path", response_model=list[NodeDetail])
async def get_path(
    game_id: str,
    target_node_id: str,
) -> list[NodeDetail]:
    """Return the path from root to target node."""
    try:
        save = load_game(game_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game not found") from exc
    if target_node_id not in save.nodes:
        raise HTTPException(status_code=404, detail="Node not found")
    chain = path_from_root(save, target_node_id)
    return [_node_to_detail(n) for n in chain]


@router.post("/{game_id}/export-book")
async def export_book_endpoint(
    game_id: str,
) -> dict[str, str]:
    """Export the current ending path as an HTML book."""
    import asyncio
    import os

    try:
        save = load_game(game_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game not found") from exc

    node = save.nodes.get(save.current_node_id)
    if node is None:
        raise HTTPException(status_code=400, detail="No current node")

    try:
        out = await asyncio.to_thread(export_book, save, node.id, open_browser=False)
    except Exception as exc:
        # SEC-004: log full traceback server-side; return generic message.
        _logger.exception("export_book failed for game %s", game_id)
        raise HTTPException(status_code=500, detail="internal error") from exc

    return {"path": str(out), "filename": os.path.basename(out)}


@router.get("/{game_id}/export-book/download")
async def download_book(
    game_id: str,
) -> FileResponse:
    """Download the exported HTML book as a file."""
    import os

    try:
        save = load_game(game_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game not found") from exc

    node = save.nodes.get(save.current_node_id)
    if node is None:
        raise HTTPException(status_code=400, detail="No current node")

    try:
        out = await __import__("asyncio").to_thread(export_book, save, node.id, open_browser=False)
    except Exception as exc:
        # SEC-004: log full traceback server-side; return generic message.
        _logger.exception("download_book failed for game %s", game_id)
        raise HTTPException(status_code=500, detail="internal error") from exc

    # out is the directory path; the main file is index.html inside it
    html_path = out / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Book file not found")

    # SEC-009: theme.title is LLM-generated; run it through sanitize_title so
    # the Content-Disposition filename can't carry path separators or other
    # surprising characters. Defense-in-depth — Starlette also escapes.
    filename = f"{sanitize_title(save.theme.title)}_Book.html"
    return FileResponse(html_path, media_type="text/html", filename=filename)
