"""Unit tests for the shared TTS cache primitives (ENH-006-T1).

Pins the contract ``PrefetchCoordinator`` (Task 2) will rely on:
:func:`storygen.tts.cache.synthesize_to_cache` produces the same byte-identical
cache path PlayScreen uses on demand, calls
:meth:`TTSPlayer.generate` without touching playback state, and tolerates a
``None`` player (TTS disabled) by short-circuiting to ``None``.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from storygen.storage.app_state import TTSPrefs
from storygen.tts.cache import (
    relative_tts_cache_path,
    synthesize_to_cache,
    tts_cache_path,
)
from storygen.tts.player import TTSPlayer


class _WavPlayer(TTSPlayer):
    """Minimal player stub exposing a fixed preferred_extension."""

    @property
    def preferred_extension(self) -> str:
        return "wav"


class _RecordingPlayer(_WavPlayer):
    """Player stub that records generate() calls.

    Mirrors :meth:`TTSPlayer.generate`'s idempotence contract: if the cache
    file already exists, synth is skipped (no call recorded) and ``True`` is
    returned. Otherwise the call is recorded and ``self._generate_ok`` decides
    the result — so callers can pin both the cache-hit and cache-miss paths
    through the same stub.
    """

    def __init__(self, *, generate_ok: bool) -> None:
        super().__init__()
        self._generate_ok = generate_ok
        self.generate_calls: list[tuple[str, Path]] = []

    async def generate(self, text: str, cache_path: Path) -> bool:  # type: ignore[override]
        if cache_path.exists():
            return True
        self.generate_calls.append((text, cache_path))
        return self._generate_ok


def _prefs() -> TTSPrefs:
    return TTSPrefs(provider="gemini", voice="Kore")


def test_tts_cache_path_pins_expected_layout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Pin the on-disk path shape so background pregen lands at the same file."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    game_id = str(uuid4())
    player = _WavPlayer()
    prefs = _prefs()

    path = tts_cache_path(player, game_id, "node-7", prefs)
    voice_hash = relative_tts_cache_path(player, "node-7", prefs).split("-")[-1].split(".")[0]

    assert path == tmp_path / "storygen" / "games" / game_id / "audio" / f"node-7-gemini-{voice_hash}.wav"
    assert path.parent == tmp_path / "storygen" / "games" / game_id / "audio"


def test_tts_cache_path_falls_back_to_mp3_when_player_is_none() -> None:
    """When TTS is disabled the path still resolves, with mp3 extension."""
    prefs = _prefs()
    path = tts_cache_path(None, str(uuid4()), "node-1", prefs)

    assert path.suffix == ".mp3"
    assert path.name.startswith("node-1-gemini-")


@pytest.mark.asyncio
async def test_synthesize_to_cache_returns_none_for_disabled_player() -> None:
    """A None player short-circuits to None without touching the filesystem."""
    result = await synthesize_to_cache(None, str(uuid4()), "node-1", "hi", _prefs())

    assert result is None


@pytest.mark.asyncio
async def test_synthesize_to_cache_computes_path_and_delegates_to_generate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """On success: returns the cache path, calls generate() with that path, no playback."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    game_id = str(uuid4())
    player = _RecordingPlayer(generate_ok=True)
    prefs = _prefs()

    expected_path = tts_cache_path(player, game_id, "node-3", prefs)

    result = await synthesize_to_cache(player, game_id, "node-3", "hello world", prefs)

    assert result == expected_path
    assert player.generate_calls == [("hello world", expected_path)]


@pytest.mark.asyncio
async def test_synthesize_to_cache_returns_none_when_generate_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed synth returns None so the caller can skip persisting the path."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    player = _RecordingPlayer(generate_ok=False)

    result = await synthesize_to_cache(player, str(uuid4()), "node-3", "hello", _prefs())

    assert result is None
    assert len(player.generate_calls) == 1  # generate was attempted


@pytest.mark.asyncio
async def test_synthesize_to_cache_skips_resynth_when_cache_already_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """synthesize_to_cache delegates the idempotence to TTSPlayer.generate.

    generate() short-circuits on an existing cache file, so synthesize_to_cache
    in turn returns the path without re-running synth — exactly what
    background prefetch wants for a node that already has audio on disk.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    game_id = str(uuid4())
    prefs = _prefs()
    player = _RecordingPlayer(generate_ok=True)

    cache_path = tts_cache_path(player, game_id, "node-9", prefs)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(b"ALREADY-CACHED")

    result = await synthesize_to_cache(player, game_id, "node-9", "narration", prefs)

    assert result == cache_path
    assert player.generate_calls == []  # synth never ran — cache was reused


def test_synthesize_to_cache_is_reexported_from_tts_package() -> None:
    """Task 2 imports from the package root — pin the public surface."""
    from storygen.tts import relative_tts_cache_path, synthesize_to_cache, tts_cache_path

    assert callable(synthesize_to_cache)
    assert callable(tts_cache_path)
    assert callable(relative_tts_cache_path)
