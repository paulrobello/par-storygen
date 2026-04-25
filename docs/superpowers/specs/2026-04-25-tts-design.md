# TTS (Text-to-Speech) Integration Design

**Date:** 2026-04-25
**Status:** Approved

## Overview

Add text-to-speech support to par-storygen so narrated story beats can be read aloud. Three providers supported: ElevenLabs (cloud), OpenAI (cloud), Kokoro ONNX (offline). Interactive playback with pause/resume/restart via pygame mixer.

## Architecture

New `tts/` module at the same layer as `images/` and `llm/`:

```
src/storygen/tts/
    __init__.py          # re-exports
    base.py              # TTSProvider protocol, Voice, TTSError
    player.py            # AudioPlayer (pygame mixer wrapper)
    elevenlabs.py        # ElevenLabsProvider
    openai.py            # OpenAITTSProvider
    kokoro.py            # KokoroONNXProvider
    voice_cache.py       # Voice list fetch + cache (XDG-compliant)
```

Layer rule: `tts/` never imports from `screens/`, `widgets/`, or `app.py`.

## AudioPlayer (`tts/player.py`)

Wraps `pygame.mixer` for cross-platform playback with state tracking.

```python
class PlaybackState(Enum):
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"

class AudioPlayer:
    def __init__(self) -> None:
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)

    async def play(self, audio_bytes: bytes, format: str = "mp3") -> None:
        """Write bytes to temp file, load into mixer channel, play."""

    def pause(self) -> None:
        """Pause current playback."""

    def resume(self) -> None:
        """Resume paused playback."""

    def stop(self) -> None:
        """Stop playback, reset to IDLE."""

    def restart(self) -> None:
        """Stop and replay from cached audio bytes."""

    @property
    def state(self) -> PlaybackState: ...

    def cleanup(self) -> None:
        """pygame.mixer.quit()."""
```

- Stores last-played audio bytes in memory for restart
- Uses a single `pygame.mixer.Channel` for state tracking
- Thread-safe: play/write ops run via `asyncio.to_thread` or are non-blocking
- Auto-cleanup temp files after playback ends

## TTSProvider Protocol (`tts/base.py`)

```python
@dataclass
class Voice:
    id: str
    name: str
    labels: list[str] | None = None
    category: str | None = None

class TTSProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def speak(self, text: str, voice_id: str, **kwargs: Any) -> bytes:
        """Generate audio bytes for text. Returns MP3/WAV bytes."""
        ...

    async def list_voices(self) -> Sequence[Voice]:
        """Return available voices."""
        ...
```

## Providers

### ElevenLabs (`tts/elevenlabs.py`)

- Uses `elevenlabs` Python SDK (`elevenlabs.client.ElevenLabs`)
- Default model: `eleven_multilingual_v2`
- Streaming API returns `Iterator[bytes]`, collected into full audio
- Voices fetched via `client.voices.get_all()`
- Voice resolution: supports voice IDs (20+ alphanumeric), names, and partial name matching

### OpenAI (`tts/openai.py`)

- Uses `openai` Python SDK (already a dep)
- Default model: `gpt-4o-mini-tts`
- 13 built-in voices: alloy, ash, ballad, coral, echo, fable, nova, onyx, sage, shimmer, verse, marin, cedar
- No API call needed for voice list — hardcoded
- Supports `speed` (0.25-4.0) and `instructions` (voice style guidance for gpt-4o-mini-tts)

### Kokoro ONNX (`tts/kokoro.py`)

- Uses `kokoro-onnx` for local inference, no API key needed
- Models auto-downloaded on first use (~106 MB)
- Default voice: `af_heart`
- Supported voices loaded from model metadata
- Output: WAV via `soundfile`, converted to bytes

## Voice Cache (`tts/voice_cache.py`)

Adapted from par-cli-tts. Only used for ElevenLabs (OpenAI has fixed voices, Kokoro loads from model).

- Cache location: `$XDG_CACHE_HOME/storygen/elevenlabs_voices.json`
- 24-hour TTL with stale-while-revalidate
- SHA256 change detection (skip write if voices unchanged)
- `VoiceCache.get_voices(api_key)` returns cached or fresh voices
- `VoiceCache.refresh(api_key)` forces API fetch

## Settings

New **Text-to-Speech** section in SettingsScreen, after "Branch prefetch":

| Control | Type | Description |
|---------|------|-------------|
| TTS Enabled | Switch | Master on/off toggle |
| Provider | Select | ElevenLabs / OpenAI / Kokoro ONNX |
| API Key | Input (password) | For ElevenLabs (uses `ELEVENLABS_API_KEY` env); OpenAI uses existing `OPENAI_API_KEY` |
| Voice | Select | Populated from provider voice list |
| Refresh Voices | Button | Fetches fresh voice list from API |
| Model | Select | Provider-specific model options |
| Auto-read | Switch | Automatically read beat narration after generation |

**Persistence** — new `tts_prefs` key in `state.json`:

```python
@dataclass
class TTSPrefs:
    enabled: bool = False
    provider: str = "elevenlabs"      # elevenlabs | openai | kokoro
    api_key: str = ""                 # elevenlabs key (openai uses existing)
    voice_id: str = ""                # provider-specific voice ID
    model: str = ""                   # provider-specific model
    auto_read: bool = False
```

Voice select and model select update dynamically when provider changes. Kokoro provider hides API key field. OpenAI provider hides API key (uses existing `OPENAI_API_KEY`).

## Play Screen

### New Bindings

```python
("t", "tts_toggle", "Read / Pause"),       # main toggle
("ctrl+t", "tts_restart", "Restart audio"), # restart from beginning
```

Both hidden when: TTS not configured, or during loading (`_loading=True`).

### State Machine

```
IDLE --[t]--> PLAYING (generate + play narration)
PLAYING --[t]--> PAUSED
PAUSED --[t]--> PLAYING (resume)
Any --[ctrl+t]--> PLAYING (stop + replay from start)
```

### Auto-read

After `on_beat_committed` callback fires (narration committed to node), if `auto_read` is enabled and TTS is configured:
1. Stop any current playback
2. Generate audio for the new narration
3. Play via AudioPlayer

### Visual Indicator

A `Static` widget below the story panel shows current TTS state:
- IDLE: hidden (no widget visible)
- PLAYING: "▶ Reading..."
- PAUSED: "⏸ Paused"
- LOADING: "⏳ Generating audio..."

Styled with Rich markup, updates via reactive state.

### Implementation in PlayScreen

```python
_tts_state: PlaybackState = PlaybackState.IDLE
_tts_audio_task: asyncio.Task | None = None
_tts_player: AudioPlayer  # from app

async def action_tts_toggle(self) -> None:
    if self._tts_state == PlaybackState.IDLE:
        await self._tts_start()
    elif self._tts_state == PlaybackState.PLAYING:
        self._tts_player.pause()
        self._tts_state = PlaybackState.PAUSED
    elif self._tts_state == PlaybackState.PAUSED:
        self._tts_player.resume()
        self._tts_state = PlaybackState.PLAYING

async def _tts_start(self) -> None:
    narration = self._current_node.narration
    self._tts_audio_task = asyncio.create_task(self._tts_generate_and_play(narration))

async def _tts_generate_and_play(self, text: str) -> None:
    # 1. Show "generating" indicator
    # 2. Call tts_provider.speak(text, voice_id)
    # 3. Play result via AudioPlayer
    # 4. Update state

async def action_tts_restart(self) -> None:
    self._tts_player.restart()
```

On screen leave (`on_unmount` or navigating away): stop playback.

## App Wiring

`app.py` changes:

- `on_mount`: initialize `pygame.mixer` + `AudioPlayer`
- `_build_tts_provider()`: factory reading `TTSPrefs`, returns provider instance or `None`
- `on_tts_prefs_changed(TTSPrefsChanged)`: message handler, rebuilds provider
- `on_unmount`: `AudioPlayer.cleanup()`
- New message types: `TTSPrefsChanged`, analogous to `TextProviderChanged`

## Dependencies

Add to `pyproject.toml`:

```
dependencies = [
    ...,
    "pygame>=2.5.0",
    "elevenlabs>=1.0.0",
    "kokoro-onnx>=0.5.0",
    "soundfile>=0.13.1",
]
```

Note: `openai` is already a dependency. `pygame` is the only truly new audio-specific dep.

## Error Handling

- No API key configured → toast "Configure TTS API key in Settings", severity=warning
- API error / network timeout → toast with error detail, severity=error, fallback to IDLE
- Audio playback failure → toast, fallback to IDLE
- Kokoro model download failure → toast with instructions, severity=error
- Text too long for single API call → chunk narration into paragraphs, concatenate audio

## Testing

- Unit tests for AudioPlayer with mocked pygame mixer
- Unit tests for each provider with mocked API clients
- Unit tests for voice cache with temp directories
- Screen test: PlayScreen TTS bindings visible/hidden correctly
- Screen test: Settings TTS section renders and saves prefs
- Integration test: auto-read triggers after beat commit
