"""Unit tests for the shared TTS cache primitives (ENH-006-T1, ENH-006-T2).

Pins the contract ``PrefetchCoordinator`` (Task 2) will rely on:
:func:`storygen.tts.cache.synthesize_to_cache` produces the same byte-identical
cache path PlayScreen uses on demand, calls
:meth:`TTSPlayer.generate` without touching playback state, and tolerates a
``None`` player (TTS disabled) by short-circuiting to ``None``.

T2 also pins the per-node lock contract: two concurrent
:func:`synthesize_to_cache` calls for the same ``(game_id, node_id)`` collapse
into a single ``generate()`` call (the second caller awaits the first, then
sees the cache file and short-circuits).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from storygen.storage.app_state import TTSPrefs
from storygen.tts.cache import (
    clear_synth_locks,
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


class _BlockingRecordingPlayer(_RecordingPlayer):
    """Recording player that blocks inside ``generate()`` until an event fires.

    Used to pin the same-node lock contract: while caller A is blocked inside
    ``generate()``, caller B's :func:`synthesize_to_cache` awaits the per-node
    lock. When A unblocks (writes the cache file), B acquires the lock, calls
    ``generate()``, sees the file exists, and returns immediately — so B's
    ``generate_calls`` stays empty (no second provider call).
    """

    def __init__(self, *, generate_ok: bool, started: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__(generate_ok=generate_ok)
        self._started = started
        self._release = release

    async def generate(self, text: str, cache_path: Path) -> bool:  # type: ignore[override]
        if cache_path.exists():
            return True
        # Record + signal that we entered the synth path, then block until
        # the test releases us. The record happens BEFORE the await so caller A
        # has ``generate_calls == [(text, cache_path)]`` while it's blocked.
        self.generate_calls.append((text, cache_path))
        # Write the cache file before blocking so caller B (which queues on the
        # lock) finds it populated when A releases. This mirrors how the real
        # ``TTSPlayer.generate`` writes the file as part of the synth step.
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(b"AUDIO")
        self._started.set()
        await self._release.wait()
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


# ---------------------------------------------------------------------------
# ENH-006-T2: per-node lock contract
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_synth_lock_registry() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]  # autouse fixture, invoked by pytest
    """Clear the module-level lock registry between tests.

    Without this, a lock registered by an earlier test would still be present
    when a later test starts — the later test's first synth would queue on a
    stale lock instead of creating a fresh one, hiding serial-caller bugs.
    """
    clear_synth_locks()
    yield
    clear_synth_locks()


@pytest.mark.asyncio
async def test_synthesize_to_cache_serializes_same_node_to_one_provider_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two concurrent synths for the same node → exactly one ``generate()``.

    The race this pins: prefetch synth for node X is in flight (blocked inside
    the provider call) when PlayScreen picks X and calls
    ``synthesize_to_cache`` for the same node. The per-node lock must make
    PlayScreen's call await the prefetch, then find the cache file the
    prefetch wrote, and return WITHOUT a second provider call.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    game_id = str(uuid4())
    started = asyncio.Event()
    release = asyncio.Event()
    player = _BlockingRecordingPlayer(generate_ok=True, started=started, release=release)
    prefs = _prefs()

    # Launch caller A (the "prefetch") and wait until it has entered the
    # provider call. Until release is set, A is parked inside generate().
    task_a = asyncio.create_task(
        synthesize_to_cache(player, game_id, "node-race", "narration", prefs)
    )
    await asyncio.wait_for(started.wait(), timeout=1.0)

    # Caller B (the "user pick") arrives while A is still blocked. Without the
    # per-node lock, B would race into generate() and append a second call.
    task_b = asyncio.create_task(
        synthesize_to_cache(player, game_id, "node-race", "narration", prefs)
    )
    # Give B a chance to either queue on the lock (correct) or enter generate
    # (bug). A tiny yield is enough: if B bypassed the lock it would have
    # appended to generate_calls by now.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert len(player.generate_calls) == 1, (
        "B should still be queued on the per-node lock, NOT inside generate()"
    )

    # Release A; both tasks should resolve. B finds the cache populated by A
    # and returns immediately without calling generate().
    release.set()
    path_a = await asyncio.wait_for(task_a, timeout=1.0)
    path_b = await asyncio.wait_for(task_b, timeout=1.0)

    expected = tts_cache_path(player, game_id, "node-race", prefs)
    assert path_a == expected
    assert path_b == expected
    assert len(player.generate_calls) == 1, (
        "exactly one provider call across both concurrent callers"
    )


@pytest.mark.asyncio
async def test_synthesize_to_cache_does_not_serialize_distinct_nodes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Different nodes synthesize concurrently — the lock is per-node, not global."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    game_id = str(uuid4())
    started_a = asyncio.Event()
    started_b = asyncio.Event()
    release = asyncio.Event()

    # Two separate players so each blocks independently on its own node.
    player_a = _BlockingRecordingPlayer(generate_ok=True, started=started_a, release=release)
    player_b = _BlockingRecordingPlayer(generate_ok=True, started=started_b, release=release)
    prefs = _prefs()

    task_a = asyncio.create_task(
        synthesize_to_cache(player_a, game_id, "node-A", "narration", prefs)
    )
    task_b = asyncio.create_task(
        synthesize_to_cache(player_b, game_id, "node-B", "narration", prefs)
    )
    # Both should reach their respective generate() calls concurrently — distinct
    # node ids get distinct locks, so neither blocks the other.
    await asyncio.wait_for(started_a.wait(), timeout=1.0)
    await asyncio.wait_for(started_b.wait(), timeout=1.0)

    release.set()
    await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=1.0)
    assert len(player_a.generate_calls) == 1
    assert len(player_b.generate_calls) == 1
