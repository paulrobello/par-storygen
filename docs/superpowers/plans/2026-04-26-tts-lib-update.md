# TTS Library Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update StoryGen's TTS integration to use `par-cli-tts` 0.5.1 async provider APIs and provider/voice/format-aware audio cache paths.

**Architecture:** Keep `TTSPlayer` as StoryGen's async/Textual adapter and keep StoryGen-owned subprocess playback controls. Add cache-key helpers in `storygen.storage.paths`, then update `PlayScreen` to compute current-prefs cache paths instead of node-only `.mp3` paths.

**Tech Stack:** Python 3.13, uv, pytest, pyright strict, ruff, `par-cli-tts`/`par_tts` 0.5.1, Textual.

---

## File map

- Modify `pyproject.toml`: raise minimum `par-cli-tts` dependency to `>=0.5.1` so future resolves cannot select 0.5.0.
- Modify `uv.lock`: resolve installed dependency to `par-cli-tts` 0.5.1.
- Modify `src/storygen/storage/paths.py`: add provider/voice/format-aware TTS cache filename helpers while preserving old helper signatures as compatibility wrappers if needed.
- Modify `src/storygen/tts/player.py`: use `list_voices_async()` and `generate_speech_async()` when available; write async iterator audio streams safely; expose the provider's preferred audio extension.
- Modify `src/storygen/screens/play.py`: compute TTS cache paths from current provider, voice, and player extension.
- Add `tests/unit/test_tts_player.py`: focused TTSPlayer async API/cache tests.
- Modify `tests/unit/test_paths.py`: add TTS cache path tests.
- Optionally modify `docs/ARCHITECTURE.md` and `README.md` only if wording becomes inaccurate; do not expand docs for deferred features.

---

### Task 1: Update dependency resolve to par-cli-tts 0.5.1

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Confirm current resolved version**

Run:

```bash
uv run python - <<'PY'
import par_tts
print(par_tts.__version__)
PY
```

Expected before implementation: prints `0.5.0`.

- [ ] **Step 2: Raise dependency floor in `pyproject.toml`**

Replace this dependency entry:

```toml
"par-cli-tts>=0.5.0",
```

with:

```toml
"par-cli-tts>=0.5.1",
```

- [ ] **Step 3: Refresh lockfile**

Run:

```bash
uv lock --upgrade-package par-cli-tts
```

Expected: command exits 0 and `uv.lock` contains `name = "par-cli-tts"` with `version = "0.5.1"`.

- [ ] **Step 4: Verify import uses new version**

Run:

```bash
uv run python - <<'PY'
import par_tts
print(par_tts.__version__)
PY
```

Expected after implementation: prints `0.5.1`.

- [ ] **Step 5: Commit dependency update**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: update par-cli-tts to 0.5.1"
```

---

### Task 2: Add provider/voice/format-aware TTS cache path helpers

**Files:**
- Modify: `src/storygen/storage/paths.py`
- Modify: `tests/unit/test_paths.py`

- [ ] **Step 1: Write failing tests in `tests/unit/test_paths.py`**

Append these tests:

```python
def test_tts_audio_path_includes_provider_voice_and_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    p = paths.tts_audio_path("abc", "node-1", provider="openai", voice="nova", ext="mp3")

    assert p.parent == tmp_path / "storygen" / "games" / "abc" / "audio"
    assert p.name.startswith("node-1-openai-")
    assert p.suffix == ".mp3"


def test_tts_audio_path_changes_when_voice_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    first = paths.tts_audio_path("abc", "node-1", provider="openai", voice="nova", ext="mp3")
    second = paths.tts_audio_path("abc", "node-1", provider="openai", voice="alloy", ext="mp3")

    assert first != second


def test_tts_audio_path_changes_when_provider_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    first = paths.tts_audio_path("abc", "node-1", provider="openai", voice="nova", ext="mp3")
    second = paths.tts_audio_path("abc", "node-1", provider="gemini", voice="nova", ext="wav")

    assert first != second
    assert second.suffix == ".wav"


def test_relative_tts_audio_path_matches_absolute_filename() -> None:
    rel = paths.relative_tts_audio_path("node-1", provider="openai", voice="nova", ext="mp3")

    assert rel.startswith("audio/node-1-openai-")
    assert rel.endswith(".mp3")


def test_tts_audio_path_sanitizes_provider_and_extension(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    p = paths.tts_audio_path("abc", "node-1", provider="custom/provider", voice="", ext=".wav")

    assert p.name.startswith("node-1-custom-provider-")
    assert p.suffix == ".wav"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_paths.py -k "tts_audio" -v
```

Expected: FAIL with `TypeError` because `tts_audio_path()` and `relative_tts_audio_path()` do not yet accept provider/voice/ext keyword arguments.

- [ ] **Step 3: Implement helpers in `src/storygen/storage/paths.py`**

Add imports near the existing imports if absent:

```python
import hashlib
import re
```

Replace the current TTS helpers with:

```python
def _safe_tts_component(value: str) -> str:
    """Return a filesystem-safe TTS cache filename component."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return cleaned.strip(".-") or "default"


def _voice_cache_hash(voice: str) -> str:
    """Return a short stable cache hash for a configured TTS voice."""
    key = voice or "__default__"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def _normalize_audio_ext(ext: str) -> str:
    """Return a safe extension without a leading dot."""
    cleaned = _safe_tts_component(ext.lstrip("."))
    return cleaned or "mp3"


def relative_tts_audio_path(
    node_id: str,
    *,
    provider: str = "legacy",
    voice: str = "",
    ext: str = "mp3",
) -> str:
    """Relative TTS audio path as stored on StoryNode.tts_audio_path."""
    safe_provider = _safe_tts_component(provider)
    voice_hash = _voice_cache_hash(voice)
    safe_ext = _normalize_audio_ext(ext)
    return f"audio/{node_id}-{safe_provider}-{voice_hash}.{safe_ext}"


def tts_audio_path(
    game_id: str,
    node_id: str,
    *,
    provider: str = "legacy",
    voice: str = "",
    ext: str = "mp3",
) -> Path:
    """Absolute path to a story node TTS audio file."""
    return game_dir(game_id) / relative_tts_audio_path(
        node_id,
        provider=provider,
        voice=voice,
        ext=ext,
    )
```

Keep the rest of `paths.py` unchanged.

- [ ] **Step 4: Run path tests**

Run:

```bash
uv run pytest tests/unit/test_paths.py -k "tts_audio" -v
```

Expected: all selected tests PASS.

- [ ] **Step 5: Commit path helpers**

```bash
git add src/storygen/storage/paths.py tests/unit/test_paths.py
git commit -m "feat: key tts cache paths by provider and voice"
```

---

### Task 3: Update TTSPlayer to use par_tts async provider methods

**Files:**
- Modify: `src/storygen/tts/player.py`
- Create: `tests/unit/test_tts_player.py`

- [ ] **Step 1: Add failing TTSPlayer tests**

Create `tests/unit/test_tts_player.py` with:

```python
"""Unit tests for StoryGen's async TTS player adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from par_tts import Voice
from storygen.tts.player import TTSPlayer, TTSState


class _FakeProvider:
    supported_formats = ["wav"]

    def __init__(self) -> None:
        self.generated: list[tuple[str, str]] = []
        self.listed = False
        self.voices = [Voice(id="nova", name="Nova")]

    async def list_voices_async(self) -> list[Voice]:
        self.listed = True
        return self.voices

    async def generate_speech_async(self, text: str, voice: str) -> bytes:
        self.generated.append((text, voice))
        return b"AUDIO"


class _StreamingProvider(_FakeProvider):
    async def generate_speech_async(self, text: str, voice: str) -> AsyncIterator[bytes]:
        self.generated.append((text, voice))

        async def _chunks() -> AsyncIterator[bytes]:
            yield b"A"
            yield b"B"

        return _chunks()


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
async def test_speak_writes_async_stream_to_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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

    assert player.preferred_extension == "mp3"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_tts_player.py -v
```

Expected: FAIL because `preferred_extension` does not exist and `speak()` cannot write async iterators yet. If one async-listing test passes due current `to_thread` fallback shape, continue implementing the full async API update.

- [ ] **Step 3: Implement async provider support in `src/storygen/tts/player.py`**

Add imports near the top:

```python
from collections.abc import AsyncIterator
from typing import Any
```

Add a property near `is_configured`:

```python
    @property
    def preferred_extension(self) -> str:
        """Preferred audio file extension for the configured provider."""
        if self._provider is None or not self._provider.supported_formats:
            return "mp3"
        return self._provider.supported_formats[0].lstrip(".") or "mp3"
```

Replace `refresh_voices()` body with:

```python
        if self._provider is None:
            return []
        try:
            list_async = getattr(self._provider, "list_voices_async", None)
            if callable(list_async):
                voices = await list_async()
            else:
                voices = await asyncio.to_thread(self._provider.list_voices)
            self._voices = voices
            return list(voices)
        except Exception as exc:
            _logger.warning("Failed to fetch voices: %s", exc)
            return []
```

Add helpers before `speak()` or in the internal helpers section:

```python
    async def _generate_speech(self, text: str) -> Any:
        """Generate speech using the provider's async API when available."""
        if self._provider is None:
            return None
        generate_async = getattr(self._provider, "generate_speech_async", None)
        if callable(generate_async):
            return await generate_async(text, self._voice)
        return await asyncio.to_thread(self._provider.generate_speech, text, self._voice)

    async def _write_audio_data(self, audio_data: Any, save_path: Path) -> None:
        """Write bytes, sync byte iterators, or async byte iterators to disk."""
        if isinstance(audio_data, bytes):
            save_path.write_bytes(audio_data)
            return
        if hasattr(audio_data, "__aiter__"):
            with open(save_path, "wb") as f:
                async for chunk in audio_data:
                    f.write(chunk)
            return
        with open(save_path, "wb") as f:
            for chunk in audio_data:
                f.write(chunk)
```

In `speak()`, replace generation:

```python
            audio_data = await asyncio.to_thread(self._provider.generate_speech, text, self._voice)
```

with:

```python
            audio_data = await self._generate_speech(text)
```

Replace the existing bytes-or-iterator write block with:

```python
            await self._write_audio_data(audio_data, save_path)
```

Remove imports that become unused. If `AsyncIterator` is unused after implementation, do not keep it.

- [ ] **Step 4: Run TTSPlayer tests**

Run:

```bash
uv run pytest tests/unit/test_tts_player.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run typecheck for touched TTS file**

Run:

```bash
uv run pyright src/storygen/tts/player.py tests/unit/test_tts_player.py
```

Expected: 0 errors.

- [ ] **Step 6: Commit TTSPlayer async update**

```bash
git add src/storygen/tts/player.py tests/unit/test_tts_player.py
git commit -m "feat: use async tts provider APIs"
```

---

### Task 4: Wire provider-aware cache paths into PlayScreen

**Files:**
- Modify: `src/storygen/screens/play.py`
- Modify: `tests/unit/test_tts_player.py` or add focused tests if a better seam emerges

- [ ] **Step 1: Add a focused helper method in PlayScreen design before editing call sites**

Implement a private helper in `PlayScreen` near `_speak_current_node()`:

```python
    def _tts_cache_path(self, node_id: str, prefs: app_state.TTSPrefs) -> Path:
        """Return the current provider/voice-aware TTS cache path for a node."""
        ext = self._tts_player.preferred_extension if self._tts_player is not None else "mp3"
        return paths.tts_audio_path(
            str(self._save.id),
            node_id,
            provider=prefs.provider,
            voice=prefs.voice,
            ext=ext,
        )

    def _relative_tts_cache_path(self, node_id: str, prefs: app_state.TTSPrefs) -> str:
        """Return the relative current provider/voice-aware TTS cache path for a node."""
        ext = self._tts_player.preferred_extension if self._tts_player is not None else "mp3"
        return paths.relative_tts_audio_path(
            node_id,
            provider=prefs.provider,
            voice=prefs.voice,
            ext=ext,
        )
```

This exact code may need import adjustment for `Path`; `play.py` already imports `Path` if present. If not present, add:

```python
from pathlib import Path
```

- [ ] **Step 2: Update manual TTS cache notifications**

Replace each current call shaped like:

```python
cache = paths.tts_audio_path(str(self._save.id), node.id)
```

inside TTS action methods with:

```python
tts_prefs = app_state.read_tts_prefs()
cache = self._tts_cache_path(node.id, tts_prefs)
```

Apply this in `action_tts_toggle()`, `action_tts_restart()`, and `_maybe_auto_read()`.

- [ ] **Step 3: Update `_speak_current_node()` cache path and stored relative path**

In `_speak_current_node()`, after configuring the player, replace:

```python
cache = paths.tts_audio_path(str(self._save.id), node.id)
```

with:

```python
cache = self._tts_cache_path(node.id, tts_prefs)
```

Replace:

```python
node.tts_audio_path = paths.relative_tts_audio_path(node.id)
```

with:

```python
node.tts_audio_path = self._relative_tts_cache_path(node.id, tts_prefs)
```

- [ ] **Step 4: Add or update tests only if a stable existing PlayScreen seam is available**

Inspect `tests/unit/test_play_screen.py`. If it already has a simple PlayScreen construction seam, add a test that instantiates the screen with a fake `TTSPlayer.preferred_extension == "wav"` and verifies `_tts_cache_path()` ends with `.wav` and includes provider/voice-aware filename components.

Use this test shape if it fits the existing constructors:

```python
def test_play_screen_tts_cache_path_uses_current_provider_voice_and_extension(fake_save: GameSave) -> None:
    player = TTSPlayer()
    player._provider = _FakeWavProvider()  # pyright: ignore[reportPrivateUsage]
    screen = PlayScreen(save=fake_save, pipeline=fake_pipeline, tts_player=player)
    prefs = app_state.TTSPrefs(provider="gemini", voice="Kore")

    path = screen._tts_cache_path("node-1", prefs)  # pyright: ignore[reportPrivateUsage]

    assert path.name.startswith("node-1-gemini-")
    assert path.suffix == ".wav"
```

If constructing `PlayScreen` requires too many unrelated dependencies, skip this test and rely on the path-helper and TTSPlayer tests. Do not introduce brittle screen tests for private plumbing.

- [ ] **Step 5: Run relevant tests**

Run:

```bash
uv run pytest tests/unit/test_paths.py tests/unit/test_tts_player.py -v
```

If a PlayScreen test was added, also run:

```bash
uv run pytest tests/unit/test_play_screen.py -v
```

Expected: all selected tests PASS.

- [ ] **Step 6: Commit PlayScreen wiring**

```bash
git add src/storygen/screens/play.py tests/unit/test_play_screen.py tests/unit/test_tts_player.py
git commit -m "fix: use provider-aware tts cache paths"
```

If no test file changed in this task, omit it from `git add`.

---

### Task 5: Final docs and verification

**Files:**
- Modify: `docs/ARCHITECTURE.md` only if current TTS section still claims node-only `audio/{node_id}.mp3` cache paths.
- Modify: `README.md` only if current TTS section still claims node-only `.mp3` cache paths.

- [ ] **Step 1: Search docs for stale TTS cache wording**

Run:

```bash
rg "audio/\{node_id\}|node_id\}\.mp3|tts_audio_path|per-node audio" README.md docs/ARCHITECTURE.md
```

Expected: identify any stale descriptions of node-only `.mp3` caching.

- [ ] **Step 2: Update stale docs if needed**

Use this replacement wording where appropriate:

```markdown
Audio files are cached per node, provider, and voice in the save's `audio/` directory. The cache file extension follows the active TTS provider's preferred output format, so changing provider or voice generates a separate cache entry instead of replaying stale narration.
```

- [ ] **Step 3: Run formatting**

Run:

```bash
make fmt
```

Expected: command exits 0.

- [ ] **Step 4: Run full verification**

Run:

```bash
make checkall
```

Expected: formatting, lint, typecheck, and tests all PASS.

- [ ] **Step 5: Commit docs/format changes if any**

If files changed after docs or formatting:

```bash
git add README.md docs/ARCHITECTURE.md src tests pyproject.toml uv.lock
git commit -m "docs: update tts cache documentation"
```

If no files changed, do not create an empty commit.

- [ ] **Step 6: Report verification evidence**

Final response must include:

- Changed files.
- Whether `make checkall` passed, with the command's result.
- Any deferred features from the design: dynamic provider discovery, diagnostics UI, cost estimates, provider-specific Settings controls.
