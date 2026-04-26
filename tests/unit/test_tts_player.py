"""Unit tests for StoryGen's async TTS player adapter."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from par_tts import Voice
from par_tts.providers.base import SpeechCallbacks, TTSProvider

from storygen.tts.player import TTSPlayer, TTSState


class _FakeProvider(TTSProvider):
    def __init__(self) -> None:
        super().__init__()
        self.generated: list[tuple[str, str]] = []
        self.listed = False
        self.voices = [Voice(id="nova", name="Nova")]

    @property
    def name(self) -> str:
        return "fake"

    @property
    def supported_formats(self) -> list[str]:
        return ["wav"]

    @property
    def default_model(self) -> str:
        return "fake-model"

    @property
    def default_voice(self) -> str:
        return "nova"

    def list_voices(self) -> list[Voice]:
        raise AssertionError("sync list_voices should not be called")

    async def list_voices_async(self) -> list[Voice]:
        self.listed = True
        return self.voices

    def resolve_voice(self, voice_identifier: str) -> str:
        return voice_identifier

    def generate_speech(
        self,
        text: str,
        voice: str,
        model: str | None = None,
        **kwargs: Any,
    ) -> bytes | Iterator[bytes]:
        raise AssertionError("sync generate_speech should not be called")

    async def generate_speech_async(
        self,
        text: str,
        voice: str,
        model: str | None = None,
        callbacks: SpeechCallbacks | None = None,
        **kwargs: Any,
    ) -> bytes | AsyncIterator[bytes]:
        self.generated.append((text, voice))
        return b"AUDIO"


class _StreamingProvider(_FakeProvider):
    async def generate_speech_async(
        self,
        text: str,
        voice: str,
        model: str | None = None,
        callbacks: SpeechCallbacks | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[bytes]:
        self.generated.append((text, voice))

        async def _chunks() -> AsyncIterator[bytes]:
            yield b"A"
            yield b"B"

        return _chunks()


class _NoFormatsProvider(_FakeProvider):
    @property
    def supported_formats(self) -> list[str]:
        return []


class _BlockingStreamingProvider(_FakeProvider):
    def __init__(self, chunk_written: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__()
        self.chunk_written = chunk_written
        self.release = release

    async def generate_speech_async(
        self,
        text: str,
        voice: str,
        model: str | None = None,
        callbacks: SpeechCallbacks | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[bytes]:
        self.generated.append((text, voice))

        async def _chunks() -> AsyncIterator[bytes]:
            yield b"PARTIAL"
            self.chunk_written.set()
            await self.release.wait()
            yield b"REST"

        return _chunks()


class _BlockingGenerationProvider(_FakeProvider):
    def __init__(self, started: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__()
        self.started = started
        self.release = release
        self.cancelled = False

    async def generate_speech_async(
        self,
        text: str,
        voice: str,
        model: str | None = None,
        callbacks: SpeechCallbacks | None = None,
        **kwargs: Any,
    ) -> bytes:
        self.generated.append((text, voice))
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return b"AUDIO"


@pytest.mark.asyncio
async def test_refresh_voices_uses_async_provider() -> None:
    player = TTSPlayer()
    provider = _FakeProvider()
    player._provider = provider  # pyright: ignore[reportPrivateUsage]

    voices = await player.refresh_voices()

    assert provider.listed is True
    assert voices == [Voice(id="nova", name="Nova")]
    assert player.voices == voices


@pytest.mark.asyncio
async def test_speak_writes_bytes_to_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    player = TTSPlayer()
    provider = _FakeProvider()
    player._provider = provider  # pyright: ignore[reportPrivateUsage]
    player._voice = "nova"  # pyright: ignore[reportPrivateUsage]
    played: list[Path] = []

    async def fake_play(path: Path) -> None:
        played.append(path)
        player._state = TTSState.IDLE  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(player, "_play_file", fake_play)
    cache = tmp_path / "node.wav"

    ok = await player.speak("hello", cache_path=cache)

    assert ok is True
    assert cache.read_bytes() == b"AUDIO"
    assert provider.generated == [("hello", "nova")]
    assert played == [cache]


@pytest.mark.asyncio
async def test_speak_writes_async_stream_to_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    player = TTSPlayer()
    provider = _StreamingProvider()
    player._provider = provider  # pyright: ignore[reportPrivateUsage]
    played: list[Path] = []

    async def fake_play(path: Path) -> None:
        played.append(path)
        player._state = TTSState.IDLE  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(player, "_play_file", fake_play)
    cache = tmp_path / "node.wav"

    ok = await player.speak("hello", cache_path=cache)

    assert ok is True
    assert cache.read_bytes() == b"AB"
    assert played == [cache]


@pytest.mark.asyncio
async def test_cancelling_speak_during_async_stream_cache_write_removes_partial_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    player = TTSPlayer()
    chunk_written = asyncio.Event()
    release = asyncio.Event()
    provider = _BlockingStreamingProvider(chunk_written, release)
    player._provider = provider  # pyright: ignore[reportPrivateUsage]
    played: list[Path] = []

    async def fake_play(path: Path) -> None:
        played.append(path)
        player._state = TTSState.IDLE  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(player, "_play_file", fake_play)
    cache = tmp_path / "node.wav"

    task = asyncio.create_task(player.speak("hello", cache_path=cache))
    await asyncio.wait_for(chunk_written.wait(), timeout=1.0)

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert cache.exists() is False
    assert list(tmp_path.iterdir()) == []
    assert played == []


@pytest.mark.asyncio
async def test_stop_during_async_generation_prevents_cache_write_and_playback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    player = TTSPlayer()
    started = asyncio.Event()
    release = asyncio.Event()
    provider = _BlockingGenerationProvider(started, release)
    player._provider = provider  # pyright: ignore[reportPrivateUsage]
    played: list[Path] = []

    async def fake_play(path: Path) -> None:
        played.append(path)
        player._state = TTSState.IDLE  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(player, "_play_file", fake_play)
    cache = tmp_path / "node.wav"

    task = asyncio.create_task(player.speak("hello", cache_path=cache))
    await asyncio.wait_for(started.wait(), timeout=1.0)

    await player.stop()
    release.set()
    ok = await asyncio.wait_for(task, timeout=1.0)

    assert ok is False
    assert provider.cancelled is True
    assert cache.exists() is False
    assert played == []
    assert player.state == TTSState.IDLE


@pytest.mark.asyncio
async def test_speak_reuses_existing_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    player = TTSPlayer()
    provider = _FakeProvider()
    player._provider = provider  # pyright: ignore[reportPrivateUsage]
    played: list[Path] = []

    async def fake_play(path: Path) -> None:
        played.append(path)
        player._state = TTSState.IDLE  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(player, "_play_file", fake_play)
    cache = tmp_path / "node.wav"
    cache.write_bytes(b"CACHED")

    ok = await player.speak("hello", cache_path=cache)

    assert ok is True
    assert cache.read_bytes() == b"CACHED"
    assert provider.generated == []
    assert played == [cache]


def test_preferred_extension_uses_first_provider_format() -> None:
    player = TTSPlayer()
    player._provider = _FakeProvider()  # pyright: ignore[reportPrivateUsage]

    assert player.preferred_extension == "wav"


def test_preferred_extension_falls_back_to_mp3() -> None:
    player = TTSPlayer()
    player._provider = _NoFormatsProvider()  # pyright: ignore[reportPrivateUsage]

    assert player.preferred_extension == "mp3"
