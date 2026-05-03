"""Async TTS player with play / pause / resume / stop / restart controls.

Wraps the synchronous ``par_tts`` library so it works inside Textual's async
event loop. Audio playback uses ``asyncio.create_subprocess_exec`` with a
runtime-detected backend (``ffplay`` or ``afplay``) so the caller retains
control via SIGSTOP / SIGCONT / SIGTERM.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import signal
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from enum import Enum
from pathlib import Path
from typing import cast

from par_tts import Voice, get_provider
from par_tts.providers.base import TTSProvider

_logger = logging.getLogger(__name__)

AudioResult = bytes | Iterator[bytes] | AsyncIterator[bytes]

# Supported audio player backends, in priority order.
_PLAYER_CANDIDATES: tuple[str, ...] = ("ffplay", "afplay")


def _detect_player() -> str:
    """Return the first available audio player binary, or empty string."""
    for candidate in _PLAYER_CANDIDATES:
        if shutil.which(candidate):
            return candidate
    return ""


class TTSState(Enum):
    """Playback state machine."""

    IDLE = "idle"
    GENERATING = "generating"
    PLAYING = "playing"
    PAUSED = "paused"


class TTSPlayer:
    """Async TTS player with full playback controls.

    Usage::

        player = TTSPlayer()
        player.configure("openai", api_key="sk-...", voice="nova")
        await player.speak("Hello, world!")
        await player.pause()
        await player.resume()
        await player.stop()
    """

    def __init__(self) -> None:
        self._provider: TTSProvider | None = None
        self._provider_name: str = ""
        self._state: TTSState = TTSState.IDLE
        self._process: asyncio.subprocess.Process | None = None
        self._audio_file: Path | None = None
        self._current_text: str = ""
        self._voice: str = ""
        self._volume: float = 1.0
        self._voices: list[Voice] = []
        self._api_key: str = ""
        self._generation_task: asyncio.Task[bool] | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> TTSState:
        return self._state

    def set_state(self, state: TTSState) -> None:
        """Set the playback state directly.

        Used by the UI layer to eagerly transition to GENERATING before the
        async worker runs, so the user gets immediate feedback.
        """
        self._state = state

    @property
    def voices(self) -> list[Voice]:
        return list(self._voices)

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def current_voice(self) -> str:
        return self._voice

    @property
    def is_configured(self) -> bool:
        return self._provider is not None

    @property
    def preferred_extension(self) -> str:
        """Preferred audio file extension for the configured provider."""
        if self._provider is None or not self._provider.supported_formats:
            return "mp3"
        return self._provider.supported_formats[0].lstrip(".") or "mp3"

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure(
        self,
        provider: str,
        *,
        api_key: str = "",
        voice: str = "",
    ) -> None:
        """Rebuild the TTS provider from config values.

        Safe to call repeatedly (e.g. on Settings save). Clears cached voices
        so the next ``refresh_voices`` call fetches fresh ones.
        """
        self._api_key = api_key
        self._voice = voice
        self._provider_name = provider
        self._voices = []
        try:
            cls = get_provider(provider)
            resolved_key = api_key or None
            self._provider = cls(api_key=resolved_key)
            _logger.info("TTS provider configured: %s", provider)
        except Exception as exc:
            _logger.warning("Failed to configure TTS provider %s: %s", provider, exc)
            self._provider = None

    # ------------------------------------------------------------------
    # Voice management
    # ------------------------------------------------------------------

    async def refresh_voices(self) -> list[Voice]:
        """Fetch voices from the current provider.

        Returns the fetched list and caches it on this instance.
        """
        if self._provider is None:
            return []
        try:
            list_async = getattr(self._provider, "list_voices_async", None)
            if callable(list_async):
                voices = await cast(Callable[[], Awaitable[list[Voice]]], list_async)()
            else:
                voices = await asyncio.to_thread(self._provider.list_voices)
            self._voices = voices
            return list(voices)
        except Exception as exc:
            _logger.warning("Failed to fetch voices: %s", exc)
            return []

    def voice_options(self) -> list[tuple[str, str]]:
        """Return (label, value) pairs suitable for a Textual Select widget."""
        return [(f"{v.name} ({v.id})", v.id) for v in self._voices]

    # ------------------------------------------------------------------
    # Playback controls
    # ------------------------------------------------------------------

    async def speak(self, text: str, cache_path: Path | None = None) -> bool:
        """Generate audio for *text* and play it.

        If *cache_path* is given and the file already exists, skips generation
        and plays the cached file directly.  If generation succeeds, the audio
        is saved to *cache_path* for future reuse.

        Returns ``True`` if playback started (or completed), ``False`` if
        generation was skipped due to a missing provider.
        """
        if self._provider is None:
            return False
        await self.stop()

        # Reuse persistent cache if file exists.
        if cache_path and cache_path.exists():
            self._current_text = text
            self._audio_file = cache_path
            await self._play_file(cache_path)
            return True

        # Reuse temp cache if text hasn't changed.
        if (
            not cache_path
            and self._audio_file
            and self._audio_file.exists()
            and self._current_text == text
        ):
            await self._play_file(self._audio_file)
            return True

        self._current_text = text
        self._state = TTSState.GENERATING

        # Determine save location before starting generation so stop() can
        # cancel the full generate/write phase via _generation_task.
        save_path = cache_path
        if save_path:
            save_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            suffix = f".{self.preferred_extension}"
            with tempfile.NamedTemporaryFile(
                suffix=suffix, delete=False, prefix="storygen_tts_"
            ) as tmp:
                save_path = Path(tmp.name)

        generation_task = asyncio.create_task(self._generate_and_write(text, save_path))
        self._generation_task = generation_task
        try:
            wrote_audio = await generation_task
        except asyncio.CancelledError:
            self._state = TTSState.IDLE
            save_path.unlink(missing_ok=True)
            current_task = asyncio.current_task()
            if current_task is not None and current_task.cancelling():
                raise
            return False
        except Exception as exc:
            _logger.warning("TTS generation failed: %s", exc)
            self._state = TTSState.IDLE
            save_path.unlink(missing_ok=True)
            return False
        finally:
            if self._generation_task is generation_task:
                self._generation_task = None

        if not wrote_audio:
            self._state = TTSState.IDLE
            save_path.unlink(missing_ok=True)
            return False

        # Clean up previous temp file (not persistent cache).
        if self._audio_file and self._audio_file != save_path and not cache_path:
            self._audio_file.unlink(missing_ok=True)

        self._audio_file = save_path
        await self._play_file(save_path)
        return True

    async def pause(self) -> None:
        """Pause the audio subprocess (SIGSTOP)."""
        if self._state == TTSState.PLAYING and self._process and self._process.returncode is None:
            try:
                self._process.send_signal(signal.SIGSTOP)
                self._state = TTSState.PAUSED
            except ProcessLookupError:
                pass

    async def resume(self) -> None:
        """Resume a paused audio subprocess (SIGCONT)."""
        if self._state == TTSState.PAUSED and self._process and self._process.returncode is None:
            try:
                self._process.send_signal(signal.SIGCONT)
                self._state = TTSState.PLAYING
            except ProcessLookupError:
                pass

    async def stop(self) -> None:
        """Kill the audio subprocess and return to IDLE."""
        if self._generation_task and not self._generation_task.done():
            self._generation_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._generation_task
            self._generation_task = None

        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except (ProcessLookupError, TimeoutError):
                with contextlib.suppress(ProcessLookupError):
                    self._process.kill()
            self._process = None

        self._state = TTSState.IDLE

    async def restart(self) -> None:
        """Stop current playback and replay the cached audio from the start."""
        text = self._current_text
        if self._audio_file and self._audio_file.exists():
            await self.stop()
            await self._play_file(self._audio_file)
        elif text:
            await self.stop()
            await self.speak(text)

    async def toggle(self) -> None:
        """Context-dependent: speak / pause / resume based on current state."""
        if self._state == TTSState.IDLE:
            if self._current_text:
                await self.speak(self._current_text)
        elif self._state == TTSState.PLAYING:
            await self.pause()
        elif self._state == TTSState.PAUSED:
            await self.resume()

    async def speak_text(self, text: str) -> None:
        """Public entry point: generate and speak *text*, cancelling any current playback."""
        await self.speak(text)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup(self) -> None:
        """Stop playback and remove temp files."""
        await self.stop()
        if self._audio_file:
            self._audio_file.unlink(missing_ok=True)
            self._audio_file = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _generate_speech(self, text: str) -> AudioResult | None:
        """Generate speech using the provider's async API when available."""
        if self._provider is None:
            return None
        generate_async = getattr(self._provider, "generate_speech_async", None)
        if callable(generate_async):
            generate = cast(Callable[[str, str], Awaitable[AudioResult]], generate_async)
            return await generate(text, self._voice)
        return await asyncio.to_thread(self._provider.generate_speech, text, self._voice)

    async def _generate_and_write(self, text: str, save_path: Path) -> bool:
        """Generate speech and write it to *save_path* while cancellable by stop()."""
        audio_data = await self._generate_speech(text)
        if not audio_data:
            return False
        await self._write_audio_data(audio_data, save_path)
        return True

    async def _write_audio_data(self, audio_data: AudioResult, save_path: Path) -> None:
        """Write bytes, sync byte iterators, or async byte iterators to disk atomically."""
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=save_path.parent,
            prefix=f".{save_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
        try:
            await self._write_audio_data_direct(audio_data, tmp_path)
            tmp_path.replace(save_path)
        except (Exception, asyncio.CancelledError):
            tmp_path.unlink(missing_ok=True)
            raise

    async def _write_audio_data_direct(self, audio_data: AudioResult, save_path: Path) -> None:
        """Write bytes, sync byte iterators, or async byte iterators to disk."""
        if isinstance(audio_data, bytes):
            save_path.write_bytes(audio_data)
            return
        if isinstance(audio_data, AsyncIterator):
            with save_path.open("wb") as f:
                async for chunk in audio_data:
                    f.write(chunk)
            return
        with save_path.open("wb") as f:
            for chunk in audio_data:
                f.write(chunk)

    async def _play_file(self, path: Path) -> None:
        """Start audio playback with the detected backend subprocess."""
        player = _detect_player()
        if not player:
            _logger.warning(
                "No audio player found (tried %s) — TTS unavailable", ", ".join(_PLAYER_CANDIDATES)
            )
            return
        args = self._player_args(player, path)
        self._state = TTSState.PLAYING
        try:
            self._process = await asyncio.create_subprocess_exec(*args)
            await self._process.wait()
        except FileNotFoundError:
            _logger.warning("%s not found — TTS playback unavailable", player)
        except asyncio.CancelledError:
            if self._process and self._process.returncode is None:
                self._process.kill()
        finally:
            if self._state == TTSState.PLAYING:  # pyright: ignore[reportUnnecessaryComparison]
                self._state = TTSState.IDLE
            self._process = None

    def _player_args(self, player: str, path: Path) -> list[str]:
        """Build the subprocess argument list for the given player."""
        if player == "ffplay":
            # ffplay volume is 0-100 integer; clamp to valid range.
            vol = max(0, min(100, int(self._volume * 100)))
            return [
                player,
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "quiet",
                "-volume",
                str(vol),
                str(path),
            ]
        # afplay (macOS default) -- volume is 0.0-1.0 float.
        return [player, "-v", str(self._volume), str(path)]
