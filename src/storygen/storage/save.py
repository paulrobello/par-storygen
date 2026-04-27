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
    ReaderLevel,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.storage import paths
from storygen.storage.app_state import DEFAULT_ART_STYLE, DEFAULT_TARGET_MAJOR_BEATS

__all__ = [
    "GameSave",
    "NarrationStyle",
    "ReaderLevel",
    "delete_game",
    "load_game",
    "save_game",
]


class GameSave(BaseModel):
    """Entire persisted state of one story."""

    version: int
    id: UUID
    theme: Theme
    tone: Tone
    narration_style: NarrationStyle
    art_style: str = DEFAULT_ART_STYLE
    target_major_beats: int = DEFAULT_TARGET_MAJOR_BEATS
    reader_level: ReaderLevel = "ages_11_15"
    text_config: TextProviderConfig
    image_config: ImageProviderConfig
    character_image_config: ImageProviderConfig = Field(
        default_factory=lambda: ImageProviderConfig(provider="openai", model="gpt-image-1.5")
    )
    characters: list[Character]
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
    At version 1 the function is a no-op — it exists to establish the
    pattern and give callers a stable hook point.

    Example future migration::

        if from_version < 2:
            # Rename old_field → new_field
            for node in data.get("nodes", {}).values():
                node["new_field"] = node.pop("old_field", None)

    Args:
        data: The raw decoded JSON dict from ``game.json``.
        from_version: The ``version`` integer stored in that dict.

    Returns:
        The (possibly mutated) data dict, ready for ``model_validate``.
    """
    # v1 → current: nothing to migrate yet.
    del from_version
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
