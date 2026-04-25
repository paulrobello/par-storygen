"""Integration test: walk path A, branch to path B, reload, replay A cache-hit."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pytest import MonkeyPatch

from storygen.llm.models import (
    IllustrationPlan,
    ImageProviderConfig,
    StoredChoice,
    StoryBeat,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.pipeline import BeatPipeline, PipelineCallbacks
from storygen.storage.save import GameSave, load_game, save_game


class StubBeatAgent:
    def __init__(self, beats: list[StoryBeat]) -> None:
        self._beats = list(beats)
        self.calls = 0

    async def run(self, prompt, on_narration_delta, raw_sink=None):  # type: ignore[no-untyped-def]
        del raw_sink
        self.calls += 1
        beat = self._beats.pop(0)
        await on_narration_delta(beat.narration)
        return beat


class StubIllustrationAgent:
    async def run(self, beat, characters, raw_sink=None):  # type: ignore[no-untyped-def]
        del raw_sink
        return IllustrationPlan(
            should_illustrate=False, image_prompt="", featured_character_ids=[], reasoning=""
        )


class StubImageProvider:
    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        on_partial: object = None,
        reference_image: bytes | None = None,
    ) -> bytes:
        del on_partial, reference_image
        return b"P"

    async def generate_scene(
        self,
        prompt: str,
        *,
        reference_portraits: list[bytes],
        art_style: str = "children's story book",
        on_partial: object = None,
    ) -> bytes:
        del on_partial
        return b"S"


def _seed_save(tmp_path: Path) -> GameSave:
    root = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="Root.",
        choices=[
            StoredChoice(id="a", text="path A"),
            StoredChoice(id="b", text="path B"),
        ],
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
        version=1,
        id=uuid4(),
        theme=Theme(title="t", setting="s", premise="p", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
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


@pytest.mark.asyncio
async def test_walk_branch_reload_replay(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _seed_save(tmp_path)

    beats_for_a = StoryBeat(narration="Beat A", choices=[], is_major=False, is_ending=True)
    beats_for_b = StoryBeat(narration="Beat B", choices=[], is_major=False, is_ending=True)

    beat_agent = StubBeatAgent([beats_for_a, beats_for_b])
    pipeline = BeatPipeline(
        beat_agent=beat_agent,
        illustration_agent=StubIllustrationAgent(),
        summary_agent=None,
        image_provider=StubImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    # First walk: A (ends) then B (ends), starting fresh from root each time.
    node_a = await pipeline.advance(save, from_node_id="root", choice_id="a")
    assert node_a.narration == "Beat A"
    save.current_node_id = "root"
    node_b = await pipeline.advance(save, from_node_id="root", choice_id="b")
    assert node_b.narration == "Beat B"
    assert beat_agent.calls == 2
    assert len(save.endings_reached) == 2

    # Reload and replay A — should be cache hits, zero agent calls.
    reloaded = load_game(str(save.id))
    # Use a fresh beat_agent to confirm it's never invoked.
    spy_agent = StubBeatAgent([])
    pipeline2 = BeatPipeline(
        beat_agent=spy_agent,
        illustration_agent=StubIllustrationAgent(),
        summary_agent=None,
        image_provider=StubImageProvider(),
        callbacks=PipelineCallbacks(),
    )
    replay = await pipeline2.advance(reloaded, from_node_id="root", choice_id="a")
    assert replay.narration == "Beat A"
    assert spy_agent.calls == 0
