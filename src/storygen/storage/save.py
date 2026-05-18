"""GameSave Pydantic model + atomic load/save."""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, cast
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
    "StoryCreationPrompts",
    "delete_game",
    "list_existing_story_titles",
    "load_game",
    "prune_subtree",
    "save_game",
]


class StoryCreationPrompts(BaseModel):
    """User-entered wizard prompts used when creating a story."""

    theme_prompt: str = ""
    character_prompt: str = ""


def _first_user_prompt_from_debug(path: Path) -> str:
    """Extract the first user-prompt content from a pydantic-ai debug cache file."""
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(raw, list):
        return ""
    messages = cast(list[object], raw)
    for message_obj in messages:
        if not isinstance(message_obj, dict):
            continue
        message = cast(dict[str, object], message_obj)
        parts_obj = message.get("parts")
        if not isinstance(parts_obj, list):
            continue
        parts = cast(list[object], parts_obj)
        for part_obj in parts:
            if not isinstance(part_obj, dict):
                continue
            part = cast(dict[str, object], part_obj)
            if part.get("part_kind") != "user-prompt":
                continue
            content = part.get("content")
            if isinstance(content, str):
                return content.strip()
    return ""


_CHARACTER_REQUIREMENTS_RE = re.compile(
    r"User-specified character requirements:\s*(?P<requirements>.*?)(?:\n\n[A-Z][^\n]*:|\Z)",
    re.DOTALL,
)


def _user_character_requirements_from_debug_prompt(prompt: str) -> str:
    """Extract character requirements, falling back to the cached user prompt."""
    cleaned = prompt.strip()
    match = _CHARACTER_REQUIREMENTS_RE.search(cleaned)
    if match is None:
        return cleaned
    return match.group("requirements").strip()


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
    creation_prompts: StoryCreationPrompts = Field(default_factory=StoryCreationPrompts)
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


def list_existing_story_titles(*, limit: int = 50) -> list[str]:
    """Return existing save titles newest-first without loading full saves."""
    root = paths.games_root()
    if not root.exists():
        return []
    rows: list[tuple[str, str]] = []
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
        theme = cast(dict[str, object], theme_obj)
        title = theme.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        updated_at = data.get("updated_at")
        rows.append((updated_at if isinstance(updated_at, str) else "", title.strip()))
    rows.sort(key=lambda row: row[0], reverse=True)
    return [title for _updated, title in rows[: max(0, limit)]]


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


def _backfill_creation_prompts_from_debug_cache(save: GameSave) -> bool:
    """Populate missing creation prompts from wizard LLM debug sidecars.

    Returns True if ``save`` was mutated. Debug cache files are optional and
    best-effort; missing/corrupt files simply leave fields blank.
    """
    prompts = save.creation_prompts
    updates: dict[str, str] = {}
    llm_dir = paths.game_dir(str(save.id)) / "llm"
    if not prompts.theme_prompt:
        theme_prompt = _first_user_prompt_from_debug(llm_dir / "wizard-theme.json")
        if theme_prompt:
            updates["theme_prompt"] = theme_prompt
    if not prompts.character_prompt:
        character_debug_prompt = _first_user_prompt_from_debug(llm_dir / "wizard-characters.json")
        character_prompt = _user_character_requirements_from_debug_prompt(character_debug_prompt)
        if character_prompt:
            updates["character_prompt"] = character_prompt
    if not updates:
        return False
    save.creation_prompts = prompts.model_copy(update=updates)
    return True


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
    save = GameSave.model_validate(data)
    if _backfill_creation_prompts_from_debug_cache(save):
        save_game(save)
    return save
