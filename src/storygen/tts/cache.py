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

import asyncio
from pathlib import Path

from storygen.storage import paths
from storygen.storage.app_state import TTSPrefs
from storygen.tts.player import TTSPlayer

__all__ = [
    "clear_synth_locks",
    "relative_tts_cache_path",
    "synthesize_to_cache",
    "tts_cache_path",
]

# ENH-006-T2: per-node in-flight synth lock registry. Without this, prefetch
# synthing node X while the user picks X (triggering PlayScreen's on-demand
# speak path) would race: both call ``TTSPlayer.generate`` for the same
# ``cache_path`` → two provider calls + a file-write race. The lock serializes
# concurrent synths for the same ``(game_id, node_id)`` so the second caller
# awaits the first, then sees the cache populated and short-circuits via
# ``generate()``'s ``cache_path.exists()`` check.
#
# The registry is module-level and unbounded by design — locks are tiny
# (~100 B), the key space is ``(game_id, node_id)`` pairs the session has
# synthesized, and a single game's worth of nodes is O(10²). For a long-lived
# multi-game session the registry grows roughly with the union of visited
# nodes; that is still small. A bounded/evicting registry is a viable future
# improvement but would need to coordinate with any in-flight waiter to avoid
# evicting a lock a concurrent caller is about to acquire.
_synth_locks: dict[tuple[str, str], asyncio.Lock] = {}


def _get_synth_lock(game_id: str, node_id: str) -> asyncio.Lock:
    """Return the per-node synth lock, creating it lazily on first request.

    Every caller for a given ``(game_id, node_id)`` must observe the SAME
    ``Lock`` instance, or the per-node exactly-one-provider-call guarantee
    breaks. ``setdefault`` is the single publish point: the first caller to
    reach it installs its Lock; any later caller for the same key gets the
    existing Lock back and discards its own (the ``existing is not lock``
    check adopts the winner). The body has no ``await``, so under the
    single-threaded asyncio loop it cannot interleave with another caller —
    the ``get``-then-``setdefault`` ordering is belt-and-suspenders defense
    against a future await/thread being added here, not a fix for a live race.
    """
    key = (game_id, node_id)
    lock = _synth_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        # setdefault so two concurrent first-callers for the same key observe
        # the same Lock instance (whoever's Lock lost the race is discarded;
        # both callers proceed against the winner).
        existing = _synth_locks.setdefault(key, lock)
        if existing is not lock:
            lock = existing
    return lock


def clear_synth_locks() -> None:
    """Drop every registered synth lock. Test-only — used between tests so the
    registry doesn't leak locks (and therefore false-sharing) across cases."""
    _synth_locks.clear()


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

    The synth runs under a per-node lock (see ``_synth_locks``) so two
    concurrent callers for the same ``(game_id, node_id)`` — e.g. a background
    prefetch synth racing PlayScreen's on-demand speak path for the same node
    — collapse into a single provider call. The second caller awaits the
    first, then ``generate()`` sees the cache file exists and short-circuits.

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
    # Per-node lock: see module docstring + ``_synth_locks`` comment. The lock
    # wraps the full ``generate()`` call (including its cache-existence check)
    # so a concurrent caller that queued on the lock observes the file the
    # first caller wrote and returns immediately without a second provider hit.
    async with _get_synth_lock(game_id, node_id):
        ok = await player.generate(text, cache_path=cache_path)
    return cache_path if ok else None
