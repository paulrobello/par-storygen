"""GameSave Pydantic model + atomic load/save."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from storygen.core.models import (
    Character,
    ImageProviderConfig,
    NarrationStyle,
    NodeId,
    Pacing,
    ReaderLevel,
    Relationship,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.storage import paths
from storygen.storage.app_state import DEFAULT_ART_STYLE, DEFAULT_TARGET_MAJOR_BEATS

SAVE_VERSION: int = 4

__all__ = [
    "GameSave",
    "NarrationStyle",
    "ReaderLevel",
    "delete_game",
    "load_game",
    "prune_subtree",
    "save_game",
]


class GameSave(BaseModel):
    """Entire persisted state of one story."""

    version: int = SAVE_VERSION
    id: UUID
    theme: Theme
    tone: Tone
    narration_style: NarrationStyle
    art_style: str = DEFAULT_ART_STYLE
    target_major_beats: int = DEFAULT_TARGET_MAJOR_BEATS
    reader_level: ReaderLevel = "ages_11_15"
    pacing: Pacing = "moderate"
    text_config: TextProviderConfig
    image_config: ImageProviderConfig
    character_image_config: ImageProviderConfig = Field(
        default_factory=lambda: ImageProviderConfig(provider="openai", model="gpt-image-2")
    )
    characters: list[Character]
    relationships: list[Relationship] = Field(default_factory=list[Relationship])
    nodes: dict[NodeId, StoryNode]
    root_node_id: NodeId
    current_node_id: NodeId
    endings_reached: list[NodeId]
    total_image_cost_usd: float = 0.0
    text_total_input_tokens: int = 0
    text_total_output_tokens: int = 0
    text_total_requests: int = 0
    text_calls_by_model: dict[str, int] = Field(default_factory=dict[str, int])
    created_at: datetime
    updated_at: datetime


def save_game(save: GameSave) -> None:
    """Atomically persist `save` to `~/.local/share/storygen/games/<id>/game.json`.

    Writes to `<target>.tmp` first, then `os.replace`s onto the final path so
    a crash mid-write leaves the previous valid save intact.
    """
    paths.ensure_game_dirs(str(save.id))
    final = paths.game_save_file(str(save.id))
    tmp = final.with_suffix(".json.tmp")
    tmp.write_text(save.model_dump_json(indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, final)


def _migrate(data: dict[str, Any], *, from_version: int) -> dict[str, Any]:
    """Apply forward migrations from ``from_version`` to the current schema.

    This is the canonical place for future non-additive schema changes.

    Args:
        data: The raw decoded JSON dict from ``game.json``.
        from_version: The ``version`` integer stored in that dict.

    Returns:
        The (possibly mutated) data dict, ready for ``model_validate``.
    """
    if from_version < 2:
        for node in data.get("nodes", {}).values():
            node.setdefault("recap_text", None)
    if from_version < 3:
        data.setdefault("relationships", [])
    if from_version < 4:
        for char in data.get("characters", []):
            char.setdefault("backstory_summary", None)
    return data


def delete_game(game_id: str) -> None:
    """Permanently remove the save at ``game_id`` (directory + all contents).

    Raises:
        FileNotFoundError: if the save directory does not exist.
    """
    directory = paths.game_dir(game_id)
    if not directory.exists():
        raise FileNotFoundError(f"No save directory at {directory}")
    shutil.rmtree(directory)


def prune_subtree(save: GameSave, *, node_id: NodeId) -> int:
    """Remove *node_id* and all its descendants from the save and disk.

    Mutates ``save`` in place: removes nodes from ``save.nodes``, clears
    the parent's ``child_node_id`` link, relocates ``current_node_id`` if
    it was inside the pruned subtree, removes pruned nodes from
    ``endings_reached``, deletes associated image and audio files, and
    persists the result.

    Args:
        save: The game save to mutate.
        node_id: The root of the subtree to prune. Must not be the root node.

    Returns:
        The number of nodes removed (including ``node_id`` itself).

    Raises:
        ValueError: If ``node_id`` is the save's root node.
    """
    if node_id == save.root_node_id:
        raise ValueError("Cannot prune the root node")

    from storygen.storage.tree import descendants  # lazy import to avoid circular dependency

    doomed = descendants(save, node_id)
    doomed_set = set(doomed)

    # Clear parent's child_node_id link so the choice reverts to unexplored.
    target_node = save.nodes[node_id]
    parent = save.nodes[target_node.parent_id]  # type: ignore[arg-type]
    for choice in parent.choices:
        if choice.child_node_id == node_id:
            choice.child_node_id = None
            break

    # Relocate current_node_id if it was in the pruned subtree.
    if save.current_node_id in doomed_set:
        save.current_node_id = target_node.parent_id  # type: ignore[assignment]

    # Clean endings_reached.
    save.endings_reached = [e for e in save.endings_reached if e not in doomed_set]

    # Delete image and audio files from disk.
    game_id = str(save.id)
    for nid in doomed:
        node = save.nodes[nid]
        # Scene illustration.
        if node.image_path:
            img_abs = paths.safe_join(paths.game_dir(game_id), node.image_path)
            if img_abs.exists():
                img_abs.unlink()
        # TTS audio.
        if node.tts_audio_path:
            audio_abs = paths.safe_join(paths.game_dir(game_id), node.tts_audio_path)
            if audio_abs.exists():
                audio_abs.unlink()
        else:
            for p in paths.node_audio_glob(game_id, nid):
                p.unlink(missing_ok=True)

    # Remove nodes from the dict.
    for nid in doomed:
        del save.nodes[nid]

    save_game(save)
    return len(doomed)


def load_game(game_id: str) -> GameSave:
    """Load `game.json` for the given game id.

    Raises:
        FileNotFoundError: if no save exists for `game_id`.
    """
    path = paths.game_save_file(game_id)
    if not path.exists():
        raise FileNotFoundError(f"No save at {path}")
    raw_text = path.read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(raw_text)
    version = int(data.get("version", 1))
    data = _migrate(data, from_version=version)
    return GameSave.model_validate(data)
