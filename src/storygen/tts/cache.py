"""Shared TTS cache primitives.

Sits at the ``tts`` layer so it is importable by both
:class:`storygen.screens.play.PlayScreen` (on-demand synth + playback) and
:class:`storygen.pipeline_prefetch.PrefetchCoordinator` (background
pregeneration during branch prefetch) without forcing the middle layer to
import :mod:`storygen.screens`.

Two storage primitives already exist at the lower :mod:`storygen.storage.paths`
layer and are not re-implemented here:

* :func:`storygen.storage.paths.tts_audio_path` — absolute cache path math.
* :meth:`storygen.tts.player.TTSPlayer.generate` — cache-only synth (writes the
  MP3 if missing, never touches playback state).

What this module adds is the small glue contract every call site was duplicating
— derive the audio extension from the configured player, unpack
:class:`~storygen.storage.app_state.TTSPrefs`, and (for
:func:`synthesize_to_cache`) compose path + synth into the single callable the
ENH-006 prefetch hook needs.
"""

from __future__ import annotations

from pathlib import Path

from storygen.storage import paths
from storygen.storage.app_state import TTSPrefs
from storygen.tts.player import TTSPlayer

__all__ = ["relative_tts_cache_path", "synthesize_to_cache", "tts_cache_path"]


def _preferred_extension(player: TTSPlayer | None) -> str:
    """Return the player's preferred audio ext, or ``"mp3"`` when unconfigured.

    Mirrors the inline fallback ``PlayScreen`` used in its
    ``_tts_cache_path`` / ``_relative_tts_cache_path`` so the produced paths
    stay byte-identical.
    """
    return player.preferred_extension if player is not None else "mp3"


def tts_cache_path(
    player: TTSPlayer | None,
    game_id: str,
    node_id: str,
    tts_prefs: TTSPrefs,
) -> Path:
    """Return the absolute TTS audio cache path for a node.

    Pure path math: derives the extension from the configured provider and
    delegates to :func:`storygen.storage.paths.tts_audio_path`. Byte-identical
    to what :meth:`PlayScreen._tts_cache_path` produces for the same inputs —
    both funnels go through the same storage helper.
    """
    return paths.tts_audio_path(
        game_id,
        node_id,
        provider=tts_prefs.provider,
        voice=tts_prefs.voice,
        ext=_preferred_extension(player),
    )


def relative_tts_cache_path(
    player: TTSPlayer | None,
    node_id: str,
    tts_prefs: TTSPrefs,
) -> str:
    """Return the relative TTS audio cache path as stored on ``StoryNode``.

    Companion to :func:`tts_cache_path` for callers that need the
    persistence-shaped string (``audio/<node-id>-<provider>-<voice-hash>.<ext>``)
    rather than the absolute path. Byte-identical to what
    :meth:`PlayScreen._relative_tts_cache_path` produces.
    """
    return paths.relative_tts_audio_path(
        node_id,
        provider=tts_prefs.provider,
        voice=tts_prefs.voice,
        ext=_preferred_extension(player),
    )


async def synthesize_to_cache(
    player: TTSPlayer | None,
    game_id: str,
    node_id: str,
    text: str,
    tts_prefs: TTSPrefs,
) -> Path | None:
    """Synthesize *text* into the node's TTS cache without touching playback.

    Computes the per-node cache path via :func:`tts_cache_path` and delegates
    to :meth:`TTSPlayer.generate`, which is idempotent on an existing cache
    file (skips synth, returns ``True``) and creates the parent directory on
    demand. Playback state is never touched — this is the cache-only primitive
    ENH-006's prefetch hook calls in the background.

    Args:
        player: The TTS player to synthesize with. ``None`` is tolerated and
            short-circuits to ``None`` so prefetch callers can hand in an
            unconfigured player without branching.
        game_id: The game/save identifier (validated by ``paths``).
        node_id: The story node identifier the audio will be attributed to.
        text: The narration text to synthesize.
        tts_prefs: Provider/voice used to derive the cache key.

    Returns:
        The cache path if synthesis succeeded (or the file was already
        cached), ``None`` if the player is ``None`` or synthesis failed.
        Callers that also need the relative path for persistence should call
        :func:`relative_tts_cache_path` with the same ``player`` /
        ``tts_prefs`` values.
    """
    if player is None:
        return None
    cache_path = tts_cache_path(player, game_id, node_id, tts_prefs)
    ok = await player.generate(text, cache_path=cache_path)
    return cache_path if ok else None
