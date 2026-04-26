"""Async TTS player with play / pause / resume / stop / restart controls.

Wraps the synchronous ``par_tts`` library so it works inside Textual's async
event loop. Audio playback uses ``asyncio.create_subprocess_exec`` (``afplay``
on macOS) so the caller retains control via SIGSTOP / SIGCONT / SIGTERM.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import tempfile
from enum import Enum
from pathlib import Path

from par_tts import Voice, get_provider
from par_tts.providers.base import TTSProvider

_logger = logging.getLogger(__name__)


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
        self._generation_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> TTSState:
        return self._state

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
        """Fetch voices from the current provider (runs in a thread).

        Returns the fetched list and caches it on this instance.
        """
        if self._provider is None:
            return []
        try:
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

        try:
            audio_data = await asyncio.to_thread(self._provider.generate_speech, text, self._voice)
        except Exception as exc:
            _logger.warning("TTS generation failed: %s", exc)
            self._state = TTSState.IDLE
            return False

        if not audio_data:
            self._state = TTSState.IDLE
            return False

        # Determine save location.
        save_path = cache_path
        if save_path:
            save_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            suffix = (
                f".{self._provider.supported_formats[0]}"
                if self._provider.supported_formats
                else ".mp3"
            )
            with tempfile.NamedTemporaryFile(
                suffix=suffix, delete=False, prefix="storygen_tts_"
            ) as tmp:
                save_path = Path(tmp.name)

        try:
            if isinstance(audio_data, bytes):
                save_path.write_bytes(audio_data)
            else:
                # Iterator[bytes] — drain into the file.
                with open(save_path, "wb") as f:
                    for chunk in audio_data:
                        f.write(chunk)
        except Exception:
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

    async def _play_file(self, path: Path) -> None:
        """Start ``afplay`` as an async subprocess and await completion."""
        self._state = TTSState.PLAYING
        try:
            self._process = await asyncio.create_subprocess_exec(
                "afplay",
                "-v",
                str(self._volume),
                str(path),
            )
            await self._process.wait()
        except FileNotFoundError:
            _logger.warning("afplay not found — TTS playback unavailable")
        except asyncio.CancelledError:
            # Task was cancelled (e.g. stop() was called); clean up.
            if self._process and self._process.returncode is None:
                self._process.kill()
        finally:
            # State may have changed to PAUSED via SIGSTOP between setting
            # PLAYING and reaching this finally block.
            if self._state == TTSState.PLAYING:  # pyright: ignore[reportUnnecessaryComparison]
                self._state = TTSState.IDLE
            self._process = None
