"""Unit tests for ``PrefetchCoordinator``'s ENH-006-T2 TTS-pregeneration hook.

Pins the four behaviours the task spec requires:

* pref OFF → no synth, no provider call, no file written.
* pref ON → prefetched node has a cached audio file after the prefetch task
  completes, and ``node.tts_audio_path`` is persisted.
* synth failure → prefetch still succeeds (node generated, no audio, no
  exception escapes into the caller).
* per-node lock → covered in ``tests/unit/test_tts_cache.py`` (the lock
  primitive itself) and exercised end-to-end via the same fake player.

The coordinator is constructed directly with a fake ``advance`` and a fake
``TTSPlayer`` so the tests don't need to wire the full ``BeatPipeline``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from storygen.core.models import StoryNode
from storygen.pipeline_prefetch import PrefetchCoordinator
from storygen.storage import app_state
from storygen.storage.app_state import TTSPrefs
from storygen.storage.save import GameSave, save_game
from storygen.tts.cache import clear_synth_locks
from storygen.tts.player import TTSPlayer

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _RecordingTTSPlayer(TTSPlayer):
    """TTSPlayer stub that records ``generate()`` calls without playing.

    Mirrors the real :meth:`TTSPlayer.generate` idempotence contract: if the
    cache file exists, returns True without recording a call. Otherwise the
    call is recorded, the file is written, and ``self._generate_ok`` decides
    whether the call reports success or failure. The player reports
    ``is_configured=True`` so the coordinator's gate lets the synth through.
    """

    def __init__(self, *, generate_ok: bool = True) -> None:
        super().__init__()
        self._generate_ok = generate_ok
        self.generate_calls: list[tuple[str, Path]] = []

    @property
    def is_configured(self) -> bool:  # type: ignore[override]
        return True

    @property
    def preferred_extension(self) -> str:
        return "wav"

    async def generate(self, text: str, cache_path: Path) -> bool:  # type: ignore[override]
        if cache_path.exists():
            return True
        self.generate_calls.append((text, cache_path))
        if not self._generate_ok:
            return False
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(b"AUDIO")
        return True


async def _fake_advance(save: GameSave, *, from_node_id: str, choice_id: str, **_: Any) -> StoryNode:
    """Minimal advance: build + attach a fresh node under the picked choice.

    The real ``BeatPipeline.advance`` does a lot more (LLM call, image plan,
    callbacks); for the TTS hook we only need a node with narration that the
    coordinator can synth. The node IS committed to ``save.nodes`` and the
    parent's ``child_node_id`` is wired so the cache-hit path can find it.
    """
    parent = save.nodes[from_node_id]
    new_id = f"{from_node_id}-{choice_id}-child"
    node = StoryNode(
        id=new_id,
        parent_id=from_node_id,
        chosen_choice_id=choice_id,
        chosen_at=datetime.now(UTC),
        narration="The corridor stretches into darkness.",
        choices=[],
        is_major=False,
        is_ending=False,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save.nodes[new_id] = node
    for c in parent.choices:
        if c.id == choice_id:
            c.child_node_id = new_id
            break
    save_game(save)
    return node


def _bootstrap_save(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GameSave:
    """Build a minimal save with one pending choice ready to be prefetched."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from storygen.core.models import (
        ImageProviderConfig,
        StoredChoice,
        TextProviderConfig,
        Theme,
        Tone,
    )

    root = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="Start.",
        choices=[StoredChoice(id="c1", text="go on")],
        is_major=True,
        is_ending=False,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save = GameSave(
        version=4,
        id=uuid4(),
        theme=Theme(title="t", setting="s", premise="p", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        character_image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        characters=[],
        nodes={"root": root},
        root_node_id="root",
        current_node_id="root",
        endings_reached=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    save_game(save)
    return save


@pytest.fixture(autouse=True)
def _reset_tts_state() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]  # autouse fixture, invoked by pytest
    """Reset module-level TTS lock registry + write a clean TTPrefs each test."""
    clear_synth_locks()
    yield
    clear_synth_locks()


def _write_tts_prefs(monkeypatch: pytest.MonkeyPatch, *, pregenerate: bool) -> None:
    """Persist TTSPrefs to the test's isolated app_state.json."""
    prefs = TTSPrefs(
        provider="openai",
        api_key="sk-test",
        voice="alloy",
        auto_read=False,
        auto_read_recap=False,
        pregenerate_prefetch_audio=pregenerate,
    )
    app_state.write_all_settings(
        image_prefs=app_state.read_image_provider_prefs(),
        text_prefs=app_state.read_provider_prefs(),
        wizard_defaults=app_state.read_wizard_defaults(),
        tts_prefs=prefs,
        art_enabled_value=app_state.art_enabled(),
        prefetch_enabled_value=True,
        prefetch_images_enabled_value=False,
        image_streaming_enabled_value=app_state.image_streaming_enabled(),
        llm_cache_enabled_value=False,
        auto_select_value=False,
        auto_open_art_value=False,
        auto_recap_value=False,
        resume_recap_value=app_state.resume_recap_enabled(),
        recap_interval_value=app_state.recap_interval(),
        graphics_mode_value=app_state.read_graphics_mode(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prefetch_skips_synth_when_pref_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Default behaviour: pref OFF → no provider call, no cache file."""
    _write_tts_prefs(monkeypatch, pregenerate=False)
    save = _bootstrap_save(tmp_path, monkeypatch)
    player = _RecordingTTSPlayer()
    coord = PrefetchCoordinator(_fake_advance, tts_player=player)

    coord.start(save, from_node_id="root", with_images=False)
    node = await coord.await_one(save, from_node_id="root", choice_id="c1")

    assert node is not None
    assert node.narration  # beat itself succeeded
    assert player.generate_calls == [], "no synth when pregenerate_prefetch_audio is OFF"
    # No audio directory entry was created.
    audio_dir = tmp_path / "storygen" / "games" / str(save.id) / "audio"
    assert not audio_dir.exists() or not any(audio_dir.iterdir())


@pytest.mark.asyncio
async def test_prefetch_synthesizes_audio_when_pref_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pref ON + configured player → cached MP3 after prefetch + tts_audio_path persisted."""
    _write_tts_prefs(monkeypatch, pregenerate=True)
    save = _bootstrap_save(tmp_path, monkeypatch)
    player = _RecordingTTSPlayer(generate_ok=True)
    coord = PrefetchCoordinator(_fake_advance, tts_player=player)

    coord.start(save, from_node_id="root", with_images=False)
    node = await coord.await_one(save, from_node_id="root", choice_id="c1")

    assert node is not None
    assert len(player.generate_calls) == 1, "exactly one provider call for the prefetched node"
    text, cache_path = player.generate_calls[0]
    assert text == node.narration
    assert cache_path.exists(), "cache file written by the synth step"
    assert cache_path.read_bytes() == b"AUDIO"
    # Persisted on the node so a subsequent pick finds the audio.
    assert node.tts_audio_path is not None
    assert node.tts_audio_path.endswith(".wav")
    # And persisted on disk (save_game was called with the new path).
    reloaded = _reload_save(save)
    assert reloaded.nodes[node.id].tts_audio_path == node.tts_audio_path


@pytest.mark.asyncio
async def test_prefetch_synthesizes_no_audio_when_player_is_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pref ON but no player → silent skip (matches 'TTS not configured' gate)."""
    _write_tts_prefs(monkeypatch, pregenerate=True)
    save = _bootstrap_save(tmp_path, monkeypatch)
    coord = PrefetchCoordinator(_fake_advance, tts_player=None)

    coord.start(save, from_node_id="root", with_images=False)
    node = await coord.await_one(save, from_node_id="root", choice_id="c1")

    assert node is not None
    # No player → no synth, no audio path, but node still generated.
    assert node.tts_audio_path is None


@pytest.mark.asyncio
async def test_prefetch_succeeds_when_synth_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed synth must not fail the prefetch (silent failure contract)."""
    _write_tts_prefs(monkeypatch, pregenerate=True)
    save = _bootstrap_save(tmp_path, monkeypatch)
    player = _RecordingTTSPlayer(generate_ok=False)  # synth always fails
    coord = PrefetchCoordinator(_fake_advance, tts_player=player)

    coord.start(save, from_node_id="root", with_images=False)
    # await_one must not raise — synth failure is swallowed in _prefetch_one.
    node = await coord.await_one(save, from_node_id="root", choice_id="c1")

    assert node is not None, "prefetch itself succeeded despite synth failure"
    assert len(player.generate_calls) == 1, "synth was attempted"
    assert node.tts_audio_path is None, "no audio path persisted on failure"


@pytest.mark.asyncio
async def test_prefetch_swallows_synth_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An exception out of synth (not just a False return) must not propagate."""
    _write_tts_prefs(monkeypatch, pregenerate=True)
    save = _bootstrap_save(tmp_path, monkeypatch)

    class _ExplodingPlayer(_RecordingTTSPlayer):
        async def generate(self, text: str, cache_path: Path) -> bool:  # type: ignore[override]
            raise RuntimeError("synth exploded")

    player = _ExplodingPlayer()
    coord = PrefetchCoordinator(_fake_advance, tts_player=player)

    coord.start(save, from_node_id="root", with_images=False)
    node = await coord.await_one(save, from_node_id="root", choice_id="c1")

    assert node is not None, "exception in synth didn't kill the prefetch"
    assert node.tts_audio_path is None


@pytest.mark.asyncio
async def test_prefetch_synthesizes_per_pending_choice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Each prefetched choice gets its own synth call (one per pending choice)."""
    _write_tts_prefs(monkeypatch, pregenerate=True)
    save = _bootstrap_save(tmp_path, monkeypatch)
    # Add a second pending choice on the root.
    from storygen.core.models import StoredChoice

    save.nodes["root"].choices.append(StoredChoice(id="c2", text="branch"))
    save_game(save)

    player = _RecordingTTSPlayer(generate_ok=True)
    coord = PrefetchCoordinator(_fake_advance, tts_player=player)

    coord.start(save, from_node_id="root", with_images=False)
    n1 = await coord.await_one(save, from_node_id="root", choice_id="c1")
    n2 = await coord.await_one(save, from_node_id="root", choice_id="c2")

    assert n1 is not None and n2 is not None
    assert n1.id != n2.id
    assert len(player.generate_calls) == 2, "one synth call per pending choice"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _reload_save(save: GameSave) -> GameSave:
    """Reload the save from disk to verify persistence."""
    # Imported here to avoid a circular module-init dependency.
    from storygen.storage.save import load_game

    return load_game(str(save.id))
