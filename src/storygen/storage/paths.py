"""XDG-compliant filesystem layout for par-storygen."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from xdg_base_dirs import xdg_config_home, xdg_data_home

_APP = "storygen"


def safe_join(base: Path, relative: str) -> Path:
    """Join ``relative`` to ``base``, raising ``ValueError`` on path traversal.

    Resolves the joined path and verifies it is still rooted under ``base``.
    This guards against persisted JSON containing paths like ``../../../../.env``
    that would otherwise escape the game directory.

    Args:
        base: The trusted base directory (e.g. ``game_dir(save_id)``).
        relative: A relative path string loaded from persisted data.

    Returns:
        The absolute resolved path, guaranteed to be inside ``base``.

    Raises:
        ValueError: If ``relative`` resolves outside ``base``.
    """
    joined = (base / relative).resolve()
    base_resolved = base.resolve()
    if not str(joined).startswith(str(base_resolved) + "/") and joined != base_resolved:
        raise ValueError(f"path traversal detected: {relative!r} resolves outside {base_resolved}")
    return joined


def data_root() -> Path:
    """Root directory for saves — respects $XDG_DATA_HOME."""
    return xdg_data_home() / _APP


def games_root() -> Path:
    """Directory that contains per-game save folders."""
    return data_root() / "games"


def library_root() -> Path:
    """Directory that contains per-library-character folders.

    Each entry lives at ``<library_root>/<library_id>/`` and bundles the
    character's JSON metadata alongside its portrait snapshot. Exists so
    characters can be exported from one save and imported into a later story.
    """
    return data_root() / "library"


def config_root() -> Path:
    """Root directory for user config — respects $XDG_CONFIG_HOME."""
    return xdg_config_home() / _APP


def game_dir(game_id: str) -> Path:
    """Directory for a single game save."""
    return games_root() / game_id


def game_save_file(game_id: str) -> Path:
    """Absolute path to a game's `game.json`."""
    return game_dir(game_id) / "game.json"


def relative_character_portrait_path(char_id: str, version: int = 1) -> str:
    """Relative portrait path as stored on Character.portrait_path.

    This mirrors the absolute `character_portrait_path(save_id, char_id, version)`
    helper for cases where the caller doesn't yet have a save id (e.g. wizard
    building an optimistic char before the save exists).
    """
    return f"images/characters/{char_id}-v{version}.png"


def character_portrait_path(game_id: str, character_id: str, version: int = 1) -> Path:
    """Absolute path to a versioned character concept portrait PNG.

    Args:
        game_id: The game/save identifier.
        character_id: The character identifier.
        version: 1-based portrait version. Each regeneration writes a new
            version so old portraits remain on disk.
    """
    return game_dir(game_id) / relative_character_portrait_path(character_id, version)


def relative_character_outfit_path(char_id: str, outfit_id: str) -> str:
    """Relative outfit-portrait path as stored on ``CharacterOutfit.portrait_path``.

    Mirrors the absolute :func:`character_outfit_path` for cases where the
    caller doesn't yet have a save id (e.g. a UI optimistic-add flow).
    """
    return f"images/characters/{char_id}-outfit-{outfit_id}.png"


def character_outfit_path(game_id: str, character_id: str, outfit_id: str) -> Path:
    """Absolute path to a character's outfit portrait PNG.

    Outfits live alongside numbered version portraits (``<char>-vN.png``) but
    use a stable per-outfit suffix:
        ``<save-dir>/images/characters/<char_id>-outfit-<outfit_id>.png``

    Args:
        game_id: The game/save identifier.
        character_id: The character identifier.
        outfit_id: The outfit identifier (uuid4 hex).
    """
    return game_dir(game_id) / relative_character_outfit_path(character_id, outfit_id)


def relative_character_reference_path(char_id: str) -> str:
    """Relative reference-image path as stored on Character.reference_image_path."""
    return f"images/characters/{char_id}-ref.png"


def character_reference_path(game_id: str, char_id: str) -> Path:
    """Absolute path to a character's user-uploaded reference image PNG.

    There is one reference image per character (overwritten on re-upload).
    """
    return game_dir(game_id) / relative_character_reference_path(char_id)


def next_portrait_version(game_id: str, character_id: str) -> int:
    """Return the next unused portrait version number for a character.

    Scans the characters directory for files named ``<character_id>-v<N>.png``
    and returns ``max(N) + 1``, or ``1`` if no prior versions exist. Safe for
    single-process use; not race-safe across processes.
    """
    chars_dir = game_dir(game_id) / "images" / "characters"
    if not chars_dir.is_dir():
        return 1
    pattern = re.compile(rf"^{re.escape(character_id)}-v(\d+)\.png$")
    versions: list[int] = []
    for entry in chars_dir.iterdir():
        match = pattern.match(entry.name)
        if match:
            versions.append(int(match.group(1)))
    return (max(versions) + 1) if versions else 1


def latest_portrait_version(game_id: str, character_id: str) -> int | None:
    """Return the highest existing portrait version number, or None if none.

    Used by outfit revert paths to restore the most-recently-regenerated base
    portrait rather than blindly snapping to v1. Returns None when no base
    portrait has ever been written (e.g. art was disabled at wizard time).
    """
    chars_dir = game_dir(game_id) / "images" / "characters"
    if not chars_dir.is_dir():
        return None
    pattern = re.compile(rf"^{re.escape(character_id)}-v(\d+)\.png$")
    versions: list[int] = []
    for entry in chars_dir.iterdir():
        match = pattern.match(entry.name)
        if match:
            versions.append(int(match.group(1)))
    return max(versions) if versions else None


def node_image_path(game_id: str, node_id: str) -> Path:
    """Absolute path to a story node scene PNG."""
    return game_dir(game_id) / "images" / "nodes" / f"{node_id}.png"


def _safe_tts_component(value: str) -> str:
    """Return a filesystem-safe TTS cache filename component."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return cleaned.strip(".-") or "default"


def _voice_cache_hash(voice: str) -> str:
    """Return a short stable cache hash for a configured TTS voice."""
    key = voice or "__default__"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def _normalize_audio_ext(ext: str) -> str:
    """Return a safe extension without a leading dot."""
    cleaned = _safe_tts_component(ext.lstrip("."))
    return cleaned or "mp3"


def relative_tts_audio_path(
    node_id: str,
    *,
    provider: str = "legacy",
    voice: str = "",
    ext: str = "mp3",
) -> str:
    """Relative TTS audio path as stored on StoryNode.tts_audio_path."""
    safe_provider = _safe_tts_component(provider)
    voice_hash = _voice_cache_hash(voice)
    safe_ext = _normalize_audio_ext(ext)
    return f"audio/{node_id}-{safe_provider}-{voice_hash}.{safe_ext}"


def tts_audio_path(
    game_id: str,
    node_id: str,
    *,
    provider: str = "legacy",
    voice: str = "",
    ext: str = "mp3",
) -> Path:
    """Absolute path to a story node TTS audio file."""
    return game_dir(game_id) / relative_tts_audio_path(
        node_id,
        provider=provider,
        voice=voice,
        ext=ext,
    )


def ensure_game_dirs(game_id: str) -> None:
    """Create every subdirectory a game save needs, idempotent.

    The game directory and all children are restricted to owner-only access
    (0o700) so that API keys and story content are not world-traversable.
    ``os.chmod`` is called explicitly on the game dir so that the mode is
    applied even when the directory already existed before this call.
    """
    import os

    gd = game_dir(game_id)
    (gd / "images" / "characters").mkdir(parents=True, exist_ok=True)
    (gd / "images" / "nodes").mkdir(parents=True, exist_ok=True)
    (gd / "audio").mkdir(parents=True, exist_ok=True)
    os.chmod(gd, 0o700)


def node_audio_glob(game_id: str, node_id: str) -> list[Path]:
    """Return all TTS audio files matching a node id on disk."""
    audio_dir = game_dir(game_id) / "audio"
    if not audio_dir.is_dir():
        return []
    return sorted(audio_dir.glob(f"{node_id}-*.*"))
