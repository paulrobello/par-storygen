# TTS library update design

## Goal

Update par-storygen's existing text-to-speech integration to use `par-cli-tts` 0.5.1's async library API and provider metadata while preserving the current user-facing Settings and Play screen controls.

The update should improve correctness and integration quality without expanding the Settings UI in this pass.

## Scope

In scope:

- Update the project lockfile so `par-cli-tts` resolves to 0.5.1.
- Replace StoryGen's manual `asyncio.to_thread(...)` wrappers around synchronous TTS provider calls with the new async provider methods where appropriate.
- Make TTS cache filenames provider-aware, voice-aware, and format-aware.
- Keep StoryGen's existing asynchronous playback process for pause, resume, stop, and restart controls.
- Add focused unit coverage for the changed TTS player and cache-path behavior.

Out of scope for this pass:

- Dynamic provider discovery in Settings.
- TTS diagnostics UI.
- TTS cost estimates.
- Provider-specific Settings controls such as speed, OpenAI instructions, ElevenLabs stability, or Deepgram sample rate.
- Replacing StoryGen playback with `par_tts.audio` playback helpers.
- Deleting or migrating old cached audio files.

## Current state

StoryGen has TTS support centered on `src/storygen/tts/player.py` and wired through `src/storygen/screens/play.py`, `src/storygen/screens/settings.py`, and `src/storygen/storage/app_state.py`.

The lockfile resolves `par-cli-tts` to 0.5.1. `TTSPlayer` calls provider async methods (`list_voices_async`, `generate_speech_async`) with `asyncio.to_thread` fallback for providers that lack async variants. Persistent audio cache paths are provider-aware, voice-aware, and format-aware via `audio/{node_id}-{provider}-{voice_hash}.{ext}` (see `src/storygen/storage/paths.py`). Cache reuse is keyed by node id, provider, and voice hash, so switching provider or voice generates a fresh file rather than replaying stale narration.

## Architecture

`TTSPlayer` remains StoryGen's adapter between Textual screens and `par_tts` providers. It owns provider configuration, voice listing, generation state, current audio file tracking, and playback subprocess control.

The integration uses `par_tts` 0.5.1 provider async methods:

- `provider.list_voices_async()` for voice refresh (with `asyncio.to_thread` fallback to `list_voices`).
- `provider.generate_speech_async(...)` for synthesis (with `asyncio.to_thread` fallback to `generate_speech`).

StoryGen does not use `par_tts.audio.play_audio_with_player()` because that helper blocks in subprocess calls and does not expose StoryGen's current interactive pause/resume/stop controls. StoryGen keeps its own `asyncio.create_subprocess_exec(...)` playback path.

## Cache path design

Persistent TTS cache paths include:

- Story node id.
- TTS provider id.
- Effective voice id, or a stable sentinel for provider default voice.
- Preferred file extension based on the active provider's `supported_formats`.

Shape:

```text
audio/{node_id}-{provider}-{voice_hash}.{ext}
```

Examples:

```text
audio/root-openai-0a4f21.mp3
audio/root-gemini-93bd10.wav
audio/root-kokoro-onnx-e91c2a.wav
```

The voice component is a short deterministic hash of the configured voice string (8 hex characters from SHA-256). Blank voice hashes a sentinel `__default__`, so default-voice cache files are stable and do not collide with explicit custom voice names.

Provider ids are sanitized to filesystem-safe characters before use. Current provider ids are already simple (`openai`, `elevenlabs`, `deepgram`, `gemini`, `kokoro-onnx`), but the helper (`_safe_tts_component`) handles arbitrary input.

The extension comes from the provider's first supported format when available. If the provider is unavailable or does not declare formats, the helper falls back to `mp3`.

## Data flow

Manual or auto-read flow:

1. `PlayScreen` reads current TTS prefs with `app_state.read_tts_prefs()`.
2. `PlayScreen` configures `TTSPlayer` with provider, API key, and voice.
3. `PlayScreen` asks `TTSPlayer` for the active cache file extension via `preferred_extension` and computes the persistent cache path using `paths.tts_audio_path(game_id, node_id, provider, voice, ext)`.
4. If the cache file exists, `TTSPlayer.speak(...)` skips generation and plays that file.
5. If no cache file exists, `TTSPlayer.speak(...)` generates speech through `provider.generate_speech_async(...)`, writes the resulting bytes or async stream to the cache path via atomic temp-file write, then plays it.
6. After successful first generation, `PlayScreen` stores the relative cache path on `StoryNode.tts_audio_path` and saves the game.

`StoryNode.tts_audio_path` remains a convenience pointer to the last generated TTS file for that node. Cache lookup should still be based on current prefs and path helpers, not blindly on the stored path, because the stored path may refer to a previous provider/voice.

## Error handling

- Provider configuration failures leave `TTSPlayer.is_configured == False` and log a warning.
- Voice refresh failures log a warning and return an empty list.
- Generation failures return `False`, reset state to `IDLE`, and do not create or preserve partial cache files.
- Cache file write failures delete the partial target and return `False`.
- Existing old cache files are left in place but are not reused across provider/voice changes because lookup paths include provider and voice.

## Testing strategy

Unit tests cover the following seams (see `tests/unit/test_tts_player.py`, `tests/unit/test_paths.py`, and `tests/unit/test_play_screen.py`):

1. `TTSPlayer.refresh_voices()` uses provider async voice listing and preserves the returned voices.
2. `TTSPlayer.speak()` writes generated byte responses to a cache path and plays the cached file.
3. `TTSPlayer.speak()` writes async iterator audio responses to a cache path.
4. Existing cache files skip provider generation.
5. Cache paths differ when provider differs.
6. Cache paths differ when voice differs.
7. Cache path extension follows provider-supported format, with fallback to `mp3`.
8. Cancelling speak during async stream write removes the partial cache file.
9. Calling stop during generation prevents cache write and playback.
10. `PlayScreen._speak_current_node()` refreshes a stale `StoryNode.tts_audio_path` after successful generation.

Full verification should run the repository's canonical command:

```sh
make checkall
```

## Implementation notes

This implementation intentionally avoids `SpeechPipeline`. Direct use of provider async methods was sufficient for the update and kept the change surgical.

A later phase can introduce `SpeechPipeline` if StoryGen adopts text chunking, pronunciation dictionaries, audio post-processing, or provider-specific options.
