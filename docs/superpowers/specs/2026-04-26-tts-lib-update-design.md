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

StoryGen already has TTS support centered on `src/storygen/tts/player.py` and wired through `src/storygen/screens/play.py`, `src/storygen/screens/settings.py`, and `src/storygen/storage/app_state.py`.

Current limitations:

- The lockfile currently resolves `par-cli-tts` to 0.5.0.
- `TTSPlayer` manually calls synchronous provider methods inside `asyncio.to_thread(...)`.
- Persistent audio cache paths are always `audio/{node_id}.mp3`, even for providers whose preferred output is WAV or another format.
- Cache reuse is keyed only by node id, so switching provider or voice can replay stale narration generated with an earlier provider/voice.

## Architecture

`TTSPlayer` remains StoryGen's adapter between Textual screens and `par_tts` providers. It owns provider configuration, voice listing, generation state, current audio file tracking, and playback subprocess control.

The new integration should use `par_tts` 0.5.1 provider async methods:

- `provider.list_voices_async()` for voice refresh.
- `provider.generate_speech_async(...)` for synthesis.

StoryGen should not switch to `par_tts.audio.play_audio_with_player()` in this pass because that helper blocks in subprocess calls and does not expose StoryGen's current interactive pause/resume/stop controls. StoryGen keeps its own `asyncio.create_subprocess_exec(...)` playback path.

## Cache path design

Persistent TTS cache paths should include:

- Story node id.
- TTS provider id.
- Effective voice id, or a stable sentinel for provider default voice.
- Preferred file extension based on the active provider's `supported_formats`.

Recommended shape:

```text
audio/{node_id}-{provider}-{voice_hash}.{ext}
```

Examples:

```text
audio/root-openai-0a4f21.mp3
audio/root-gemini-93bd10.wav
audio/root-kokoro-onnx-e91c2a.wav
```

The voice component should be a short deterministic hash of the configured voice string. Blank voice should hash a sentinel such as `__default__`, so default-voice cache files are stable and do not collide with explicit custom voice names.

Provider ids should be sanitized to filesystem-safe characters before use. Current provider ids are already simple (`openai`, `elevenlabs`, `deepgram`, `gemini`, `kokoro-onnx`), but the helper should avoid assuming that forever.

The extension should come from the provider's first supported format when available. If the provider is unavailable or does not declare formats, fall back to `mp3` to preserve current behavior.

## Data flow

Manual or auto-read flow:

1. `PlayScreen` reads current TTS prefs with `app_state.read_tts_prefs()`.
2. `PlayScreen` configures `TTSPlayer` with provider, API key, and voice.
3. `PlayScreen` asks `TTSPlayer` or a storage helper for the active cache file extension and computes the persistent cache path using game id, node id, provider, and voice.
4. If the cache file exists, `TTSPlayer.speak(...)` skips generation and plays that file.
5. If no cache file exists, `TTSPlayer.speak(...)` generates speech through `provider.generate_speech_async(...)`, writes the resulting bytes or async stream to the cache path, then plays it.
6. After successful first generation, `PlayScreen` stores the relative cache path on `StoryNode.tts_audio_path` and saves the game.

`StoryNode.tts_audio_path` remains a convenience pointer to the last generated TTS file for that node. Cache lookup should still be based on current prefs and path helpers, not blindly on the stored path, because the stored path may refer to a previous provider/voice.

## Error handling

- Provider configuration failures leave `TTSPlayer.is_configured == False` and log a warning, matching current behavior.
- Voice refresh failures log a warning and return an empty list, matching current behavior.
- Generation failures return `False`, reset state to `IDLE`, and do not create or preserve partial cache files.
- Cache file write failures delete the partial target and return `False`.
- Existing old cache files are left in place but no longer reused across provider/voice changes because new lookup paths include provider and voice.

## Testing strategy

Add focused unit tests around the changed seams:

1. `TTSPlayer.refresh_voices()` uses provider async voice listing and preserves the returned voices.
2. `TTSPlayer.speak()` can write generated byte responses to a cache path and play the cached file.
3. `TTSPlayer.speak()` can write async iterator audio responses to a cache path.
4. Existing cache files skip provider generation.
5. Cache paths differ when provider differs.
6. Cache paths differ when voice differs.
7. Cache path extension follows provider-supported format, with fallback to `mp3`.

Full verification should run the repository's canonical command:

```sh
make checkall
```

## Implementation notes

This design intentionally avoids adding `SpeechPipeline` in the first implementation unless it materially simplifies the code. Direct use of provider async methods is enough for the requested update and keeps the change surgical.

A later phase can introduce `SpeechPipeline` if StoryGen adopts text chunking, pronunciation dictionaries, audio post-processing, or provider-specific options.
