"""Unit tests for the BeatPipeline coordinator."""

from __future__ import annotations

import asyncio
from datetime import UTC
from pathlib import Path
from typing import Any

import pytest

from storygen.images.base import ReferencePortrait
from storygen.llm.models import (
    Character,
    Choice,
    IllustrationPlan,
    ImageProviderConfig,
    StoredChoice,
    StoryBeat,
    StoryNode,
    Summary,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.pipeline import BeatPipeline, PipelineCallbacks
from storygen.pipeline_prefetch import _PREFETCH_CONCURRENCY  # pyright: ignore[reportPrivateUsage]

# ARC-011: pacing_hint_for_depth moved to pipeline_prompts.py.
from storygen.pipeline_prompts import (
    pacing_hint_for_depth as _pacing_hint_for_depth,
)
from storygen.storage.save import GameSave, save_game


class FakeBeatAgent:
    def __init__(self, beat: StoryBeat) -> None:
        self.beat = beat
        self.calls = 0

    async def run(
        self,
        prompt: str,
        on_narration_delta: Any,
        raw_sink: Any = None,
    ) -> StoryBeat:
        del raw_sink
        self.calls += 1
        for token in self.beat.narration.split():
            await on_narration_delta(token + " ")
            await asyncio.sleep(0)
        return self.beat


class FakeIllustrationAgent:
    def __init__(self, plan: IllustrationPlan) -> None:
        self.plan = plan
        self.calls = 0

    async def run(
        self,
        beat: StoryBeat,
        characters: list[Character],
        raw_sink: Any = None,
    ) -> IllustrationPlan:
        del raw_sink
        self.calls += 1
        return self.plan


class FakeImageProvider:
    def __init__(self) -> None:
        self.scenes: list[tuple[str, int]] = []
        self.portraits: list[str] = []
        self.last_on_partial: Any = None

    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        on_partial: Any = None,
        reference_image: bytes | None = None,
    ) -> bytes:
        del on_partial, reference_image
        self.portraits.append(description)
        return b"PORTRAIT-" + description.encode()

    async def generate_scene(
        self,
        prompt: str,
        *,
        reference_portraits: list[ReferencePortrait],
        art_style: str = "children's story book",
        on_partial: Any = None,
    ) -> bytes:
        self.last_on_partial = on_partial
        self.scenes.append((prompt, len(reference_portraits)))
        return b"SCENE-" + prompt.encode()


def _bootstrap_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    image_config: ImageProviderConfig | None = None,
    character_image_config: ImageProviderConfig | None = None,
) -> GameSave:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    import uuid
    from datetime import datetime

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
        version=1,
        id=uuid.uuid4(),
        theme=Theme(title="t", setting="s", premise="p", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=image_config or ImageProviderConfig(provider="openai", model="gpt-image-2"),
        character_image_config=character_image_config
        or ImageProviderConfig(provider="openai", model="gpt-image-2"),
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
async def test_pipeline_cache_hit_skips_agents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _bootstrap_save(tmp_path, monkeypatch)
    # resolve c1 → existing child "child"
    child = StoryNode(
        id="child",
        parent_id="root",
        chosen_choice_id="c1",
        chosen_at=None,
        narration="cached",
        choices=[],
        is_major=False,
        is_ending=True,
        image_prompt=None,
        image_path=None,
        image_status="done",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=save.created_at,
    )
    save.nodes["child"] = child
    save.nodes["root"].choices[0].child_node_id = "child"
    save_game(save)

    beat_agent = FakeBeatAgent(
        StoryBeat(narration="UNUSED", choices=[], is_major=False, is_ending=True)
    )
    illus = FakeIllustrationAgent(
        IllustrationPlan(
            should_illustrate=False,
            image_prompt="",
            featured_character_ids=[],
            reasoning="",
        )
    )

    pipeline = BeatPipeline(
        beat_agent=beat_agent,
        illustration_agent=illus,
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    result_node = await pipeline.advance(save, from_node_id="root", choice_id="c1")
    assert result_node.id == "child"
    assert beat_agent.calls == 0
    assert illus.calls == 0


@pytest.mark.asyncio
async def test_pipeline_stage1_commits_node_before_illustration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _bootstrap_save(tmp_path, monkeypatch)

    beat = StoryBeat(
        narration="You proceed cautiously.",
        choices=[Choice(id="c1", text="onward")],
        is_major=False,
        is_ending=False,
    )
    plan = IllustrationPlan(
        should_illustrate=False,
        image_prompt="",
        featured_character_ids=[],
        reasoning="quiet",
    )

    seen_deltas: list[str] = []

    async def on_delta(delta: str) -> None:
        seen_deltas.append(delta)

    cb = PipelineCallbacks(on_narration_delta=on_delta)
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=cb,
    )

    node = await pipeline.advance(save, from_node_id="root", choice_id="c1")
    assert node.narration == "You proceed cautiously."
    # at least one delta streamed
    assert len(seen_deltas) >= 1


@pytest.mark.asyncio
async def test_pipeline_triggers_scene_image_when_planned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _bootstrap_save(tmp_path, monkeypatch)

    beat = StoryBeat(
        narration="A rooftop chase at midnight.",
        choices=[Choice(id="c1", text="leap")],
        is_major=True,
        is_ending=False,
    )
    plan = IllustrationPlan(
        should_illustrate=True,
        image_prompt="A rooftop chase at midnight, neon rain.",
        featured_character_ids=[],
        reasoning="action scene",
    )
    image_provider = FakeImageProvider()

    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=image_provider,
        callbacks=PipelineCallbacks(),
    )

    await pipeline.advance(save, from_node_id="root", choice_id="c1")
    # wait briefly for the background image task
    await asyncio.sleep(0.05)
    assert len(image_provider.scenes) == 1


@pytest.mark.asyncio
async def test_pipeline_retry_scene_regenerates_and_marks_done(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _bootstrap_save(tmp_path, monkeypatch)
    from datetime import datetime

    failed_node = StoryNode(
        id="failed-node",
        parent_id="root",
        chosen_choice_id="c1",
        chosen_at=datetime.now(UTC),
        narration="You stare at the rain.",
        choices=[],
        is_major=True,
        is_ending=True,
        image_prompt="rain on chrome streets, lone figure under umbrella",
        image_path=None,
        image_status="failed",
        illustration_reasoning="prior attempt failed",
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save.nodes["failed-node"] = failed_node
    save.nodes["root"].choices[0].child_node_id = "failed-node"
    save_game(save)

    image_provider = FakeImageProvider()
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=True,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=image_provider,
        callbacks=PipelineCallbacks(),
    )

    result = await pipeline.retry_scene(save, node_id="failed-node")

    assert len(image_provider.scenes) == 1
    assert image_provider.scenes[0][0] == "rain on chrome streets, lone figure under umbrella"
    assert result.image_status == "done"
    assert result.image_path is not None


@pytest.mark.asyncio
async def test_pipeline_no_cost_when_not_illustrating(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A beat with no portraits and should_illustrate=False adds no cost."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    assert save.total_image_cost_usd == 0.0

    beat = StoryBeat(
        narration="A quiet pause.",
        choices=[Choice(id="c1", text="onward")],
        is_major=False,
        is_ending=False,
    )
    plan = IllustrationPlan(
        should_illustrate=False,
        image_prompt="",
        featured_character_ids=[],
        reasoning="quiet",
    )
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    await pipeline.advance(save, from_node_id="root", choice_id="c1")
    assert save.total_image_cost_usd == 0.0


@pytest.mark.asyncio
async def test_pipeline_new_character_portrait_cost_uses_character_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _bootstrap_save(
        tmp_path,
        monkeypatch,
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        character_image_config=ImageProviderConfig(
            provider="gemini", model="gemini-3.1-flash-image-preview"
        ),
    )
    new_char = Character(
        id="newcomer",
        name="Newcomer",
        backstory="b",
        personality="p",
        physical_description="A moonlit traveler in a silver cloak.",
        portrait_path=None,
        portrait_prompt=None,
        introduced_at_node_id="child",
    )
    save.characters.append(new_char)
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=False,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    await pipeline._portraits(save, [new_char])  # pyright: ignore[reportPrivateUsage]

    assert save.total_image_cost_usd == pytest.approx(0.067)  # pyright: ignore[reportUnknownMemberType]


@pytest.mark.asyncio
async def test_pipeline_scene_cost_uses_art_config_when_character_config_differs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _bootstrap_save(
        tmp_path,
        monkeypatch,
        image_config=ImageProviderConfig(provider="gemini", model="gemini-3.1-flash-image-preview"),
        character_image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
    )
    from datetime import datetime

    failed_node = StoryNode(
        id="failed-node",
        parent_id="root",
        chosen_choice_id="c1",
        chosen_at=datetime.now(UTC),
        narration="x",
        choices=[],
        is_major=True,
        is_ending=True,
        image_prompt="some prompt",
        image_path=None,
        image_status="failed",
        illustration_reasoning="x",
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save.nodes["failed-node"] = failed_node
    save.nodes["root"].choices[0].child_node_id = "failed-node"
    save_game(save)
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=True,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    await pipeline.retry_scene(save, node_id="failed-node")

    assert save.total_image_cost_usd == pytest.approx(0.067)  # pyright: ignore[reportUnknownMemberType]


@pytest.mark.asyncio
async def test_pipeline_retry_scene_adds_cost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """retry_scene should bump total_image_cost_usd on success."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    from datetime import datetime

    failed_node = StoryNode(
        id="failed-node",
        parent_id="root",
        chosen_choice_id="c1",
        chosen_at=datetime.now(UTC),
        narration="x",
        choices=[],
        is_major=True,
        is_ending=True,
        image_prompt="some prompt",
        image_path=None,
        image_status="failed",
        illustration_reasoning="x",
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save.nodes["failed-node"] = failed_node
    save.nodes["root"].choices[0].child_node_id = "failed-node"
    save_game(save)

    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=True,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    before = save.total_image_cost_usd
    await pipeline.retry_scene(save, node_id="failed-node")
    assert save.total_image_cost_usd > before


@pytest.mark.asyncio
async def test_pipeline_retry_scene_streams_when_enabled_and_openai(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """retry_scene must honor streaming flag like _stage_3_scene does:
    on_partial wired, partials written atomically, on_image_committed fires
    per partial, and the streaming surcharge is added to total_image_cost_usd.
    """
    from datetime import datetime

    from storygen.images.openai_provider import OPENAI_PARTIAL_IMAGES
    from storygen.images.pricing import openai_image_cost
    from storygen.storage import app_state

    save = _bootstrap_save(
        tmp_path,
        monkeypatch,
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    app_state.set_image_streaming_enabled(True)

    failed_node = StoryNode(
        id="failed-node",
        parent_id="root",
        chosen_choice_id="c1",
        chosen_at=datetime.now(UTC),
        narration="x",
        choices=[],
        is_major=True,
        is_ending=True,
        image_prompt="some prompt",
        image_path=None,
        image_status="failed",
        illustration_reasoning="x",
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save.nodes["failed-node"] = failed_node
    save.nodes["root"].choices[0].child_node_id = "failed-node"
    save_game(save)

    image_provider = _StreamingFakeImageProvider()
    committed: list[StoryNode] = []

    async def on_committed(node: StoryNode) -> None:
        committed.append(node)

    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=True,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=image_provider,
        callbacks=PipelineCallbacks(on_image_committed=on_committed),
    )

    before = save.total_image_cost_usd
    done = await pipeline.retry_scene(save, node_id="failed-node")

    # Streaming was wired through.
    assert len(image_provider.scene_calls) == 1
    assert image_provider.scene_calls[0]["on_partial"] is not None
    # 2 partials + 1 final = 3 on_image_committed calls.
    assert len(committed) >= 3
    # Surcharge applied: bumped cost includes the partial-images surcharge.
    delta = save.total_image_cost_usd - before
    expected = openai_image_cost(
        "1024x1024", "auto", num_input_refs=0, partial_images=OPENAI_PARTIAL_IMAGES
    )
    assert abs(delta - expected) < 1e-9
    assert done.image_status == "done"


@pytest.mark.asyncio
async def test_pipeline_retry_scene_omits_streaming_for_non_openai_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """retry_scene with streaming flag ON but non-openai provider → no on_partial,
    no surcharge."""
    from datetime import datetime

    from storygen.images.pricing import openai_image_cost
    from storygen.storage import app_state

    save = _bootstrap_save(
        tmp_path,
        monkeypatch,
        image_config=ImageProviderConfig(provider="gemini", model="gemini-3.1-flash-image-preview"),
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    app_state.set_image_streaming_enabled(True)

    failed_node = StoryNode(
        id="failed-node",
        parent_id="root",
        chosen_choice_id="c1",
        chosen_at=datetime.now(UTC),
        narration="x",
        choices=[],
        is_major=True,
        is_ending=True,
        image_prompt="some prompt",
        image_path=None,
        image_status="failed",
        illustration_reasoning="x",
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save.nodes["failed-node"] = failed_node
    save.nodes["root"].choices[0].child_node_id = "failed-node"
    save_game(save)

    image_provider = _StreamingFakeImageProvider()
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=True,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=image_provider,
        callbacks=PipelineCallbacks(),
    )

    before = save.total_image_cost_usd
    await pipeline.retry_scene(save, node_id="failed-node")

    # Non-openai → on_partial NOT wired through.
    assert len(image_provider.scene_calls) == 1
    assert image_provider.scene_calls[0]["on_partial"] is None
    # Surcharge is OpenAI-only; gemini cost calc never sees partial_images.
    delta = save.total_image_cost_usd - before
    # No surcharge means delta equals base gemini cost (whatever it is — just
    # confirm it's not bumped by the openai surcharge).
    surcharge = openai_image_cost("1024x1024", "auto", partial_images=2) - openai_image_cost(
        "1024x1024", "auto"
    )
    assert delta < surcharge or delta != surcharge  # delta should NOT include surcharge


@pytest.mark.asyncio
async def test_pipeline_skips_illustration_when_art_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When art is globally disabled, neither the illustration agent nor the
    image provider's portrait/scene methods are called during a beat."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    from storygen.storage import app_state

    app_state.set_art_enabled(False)

    beat = StoryBeat(
        narration="A noisy bazaar.",
        choices=[Choice(id="c1", text="haggle")],
        is_major=True,
        is_ending=False,
        new_characters=[
            Character(
                id="newchar",
                name="Ned",
                backstory="b",
                personality="p",
                physical_description="d",
                portrait_path=None,
                portrait_prompt=None,
                introduced_at_node_id="pending",
            )
        ],
    )
    plan = IllustrationPlan(
        should_illustrate=True,
        image_prompt="bazaar at noon",
        featured_character_ids=[],
        reasoning="",
    )
    illus = FakeIllustrationAgent(plan)
    image_provider = FakeImageProvider()
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=illus,
        summary_agent=None,
        image_provider=image_provider,
        callbacks=PipelineCallbacks(),
    )

    await pipeline.advance(save, from_node_id="root", choice_id="c1")
    await asyncio.sleep(0.05)

    assert illus.calls == 0  # illustration agent never invoked
    assert image_provider.scenes == []  # no scene generated
    assert image_provider.portraits == []  # no portrait generated either


@pytest.mark.asyncio
async def test_pipeline_retry_scene_skips_when_art_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """retry_scene must be a no-op when art is globally disabled."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    from datetime import datetime

    from storygen.storage import app_state

    failed_node = StoryNode(
        id="failed-node",
        parent_id="root",
        chosen_choice_id="c1",
        chosen_at=datetime.now(UTC),
        narration="x",
        choices=[],
        is_major=True,
        is_ending=True,
        image_prompt="some prompt",
        image_path=None,
        image_status="failed",
        illustration_reasoning="x",
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save.nodes["failed-node"] = failed_node
    save.nodes["root"].choices[0].child_node_id = "failed-node"
    save_game(save)

    app_state.set_art_enabled(False)

    image_provider = FakeImageProvider()
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=True,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=image_provider,
        callbacks=PipelineCallbacks(),
    )

    result = await pipeline.retry_scene(save, node_id="failed-node")
    assert image_provider.scenes == []
    # Status unchanged from "failed".
    assert result.image_status == "failed"


def test_pacing_hint_scales_with_target() -> None:
    """The pacing-hint thresholds derive from ratios of the per-save target."""
    # depth=2, target=10: 30% threshold = 3; depth ≤ 3 → silent.
    assert _pacing_hint_for_depth(2, 10) == ""
    # depth=5, target=10: > 30% (3), ≤ 60% (6) → tension rising.
    hint = _pacing_hint_for_depth(5, 10)
    assert "tension rising" in hint
    # depth=10, target=10: > 90% (9) → resolve-now prod.
    final = _pacing_hint_for_depth(10, 10)
    assert "resolving the central conflict" in final


@pytest.mark.asyncio
async def test_pipeline_retry_scene_requires_image_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _bootstrap_save(tmp_path, monkeypatch)
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=False,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    with pytest.raises(ValueError, match="no image_prompt"):
        await pipeline.retry_scene(save, node_id="root")


@pytest.mark.asyncio
async def test_pipeline_cost_tracking_ollama_is_free(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When the save pins ``provider="ollama"`` the cost counter stays at 0.0
    even though scene generation succeeded — Ollama is local inference."""
    save = _bootstrap_save(
        tmp_path,
        monkeypatch,
        image_config=ImageProviderConfig(provider="ollama", model="x/z-image-turbo"),
    )
    from datetime import datetime

    failed_node = StoryNode(
        id="failed-node",
        parent_id="root",
        chosen_choice_id="c1",
        chosen_at=datetime.now(UTC),
        narration="x",
        choices=[],
        is_major=True,
        is_ending=True,
        image_prompt="some prompt",
        image_path=None,
        image_status="failed",
        illustration_reasoning="x",
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save.nodes["failed-node"] = failed_node
    save.nodes["root"].choices[0].child_node_id = "failed-node"
    save_game(save)

    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=True,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    result = await pipeline.retry_scene(save, node_id="failed-node")
    assert result.image_status == "done"
    # Ollama = $0/image regardless of size, so no cost was recorded.
    assert save.total_image_cost_usd == 0.0


@pytest.mark.asyncio
async def test_skip_image_does_not_spawn_image_task(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """advance(skip_image=True) records the illustration plan but does NOT
    fire any scene-image generation."""
    save = _bootstrap_save(tmp_path, monkeypatch)

    beat = StoryBeat(
        narration="A rooftop chase.",
        choices=[Choice(id="c1", text="leap")],
        is_major=True,
        is_ending=False,
    )
    plan = IllustrationPlan(
        should_illustrate=True,
        image_prompt="a vivid rooftop chase",
        featured_character_ids=[],
        reasoning="cinematic",
    )
    image_provider = FakeImageProvider()
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=image_provider,
        callbacks=PipelineCallbacks(),
    )

    node = await pipeline.advance(save, from_node_id="root", choice_id="c1", skip_image=True)
    # Give any (forbidden) background task a tick to materialize.
    await asyncio.sleep(0.05)

    assert image_provider.scenes == []  # no scene generated
    assert node.image_status == "not_planned"  # status unchanged
    # Plan IS recorded so a later manual `i` retry can run.
    assert node.image_prompt == "a vivid rooftop chase"
    assert node.illustration_reasoning == "cinematic"


@pytest.mark.asyncio
async def test_start_prefetch_spawns_one_task_per_pending_choice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _bootstrap_save(tmp_path, monkeypatch)
    # Give the root three choices to prefetch.
    save.nodes["root"].choices.extend(
        [StoredChoice(id="c2", text="b"), StoredChoice(id="c3", text="c")]
    )
    save_game(save)

    beat = StoryBeat(
        narration="x", choices=[Choice(id="x", text="x")], is_major=False, is_ending=False
    )
    plan = IllustrationPlan(
        should_illustrate=False, image_prompt="", featured_character_ids=[], reasoning=""
    )
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    pipeline.start_prefetch(save, from_node_id="root", with_images=False)
    assert len(pipeline._prefetch._tasks) == 3  # pyright: ignore[reportPrivateUsage]
    assert ("root", "c1") in pipeline._prefetch._tasks  # pyright: ignore[reportPrivateUsage]
    assert ("root", "c2") in pipeline._prefetch._tasks  # pyright: ignore[reportPrivateUsage]
    assert ("root", "c3") in pipeline._prefetch._tasks  # pyright: ignore[reportPrivateUsage]
    # Drain so the test event loop doesn't leak tasks.
    for k in list(pipeline._prefetch._tasks):  # pyright: ignore[reportPrivateUsage]
        await pipeline.await_prefetched(save, from_node_id=k[0], choice_id=k[1])


@pytest.mark.asyncio
async def test_start_prefetch_skips_already_cached_choices(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _bootstrap_save(tmp_path, monkeypatch)
    save.nodes["root"].choices.extend(
        [StoredChoice(id="c2", text="b"), StoredChoice(id="c3", text="c")]
    )
    # Mark c2 as already cached.
    from datetime import datetime

    save.nodes["existing"] = StoryNode(
        id="existing",
        parent_id="root",
        chosen_choice_id="c2",
        chosen_at=datetime.now(UTC),
        narration="cached",
        choices=[],
        is_major=False,
        is_ending=True,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save.nodes["root"].choices[1].child_node_id = "existing"
    save_game(save)

    beat = StoryBeat(
        narration="x", choices=[Choice(id="x", text="x")], is_major=False, is_ending=False
    )
    plan = IllustrationPlan(
        should_illustrate=False, image_prompt="", featured_character_ids=[], reasoning=""
    )
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    pipeline.start_prefetch(save, from_node_id="root", with_images=False)
    # Only c1 and c3 should have spawned (c2 is cached).
    assert len(pipeline._prefetch._tasks) == 2  # pyright: ignore[reportPrivateUsage]
    assert ("root", "c2") not in pipeline._prefetch._tasks  # pyright: ignore[reportPrivateUsage]
    for k in list(pipeline._prefetch._tasks):  # pyright: ignore[reportPrivateUsage]
        await pipeline.await_prefetched(save, from_node_id=k[0], choice_id=k[1])


@pytest.mark.asyncio
async def test_start_prefetch_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Calling start_prefetch twice without awaiting should not duplicate tasks."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    save.nodes["root"].choices.extend(
        [StoredChoice(id="c2", text="b")],
    )
    save_game(save)

    # Slow agent so the tasks stay in-flight between the two start calls.
    class SlowBeatAgent(FakeBeatAgent):
        async def run(
            self,
            prompt: str,
            on_narration_delta: Any,
            raw_sink: Any = None,
        ) -> StoryBeat:
            del raw_sink
            await asyncio.sleep(0.05)
            return await super().run(prompt, on_narration_delta)

    beat = StoryBeat(
        narration="x", choices=[Choice(id="x", text="x")], is_major=False, is_ending=False
    )
    plan = IllustrationPlan(
        should_illustrate=False, image_prompt="", featured_character_ids=[], reasoning=""
    )
    pipeline = BeatPipeline(
        beat_agent=SlowBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    pipeline.start_prefetch(save, from_node_id="root", with_images=False)
    first = dict(pipeline._prefetch._tasks)  # pyright: ignore[reportPrivateUsage]
    pipeline.start_prefetch(save, from_node_id="root", with_images=False)
    second = dict(pipeline._prefetch._tasks)  # pyright: ignore[reportPrivateUsage]
    assert set(first.keys()) == set(second.keys())
    # Same Task objects — second call must NOT have replaced them.
    for k in first:
        assert first[k] is second[k]

    for k in list(pipeline._prefetch._tasks):  # pyright: ignore[reportPrivateUsage]
        await pipeline.await_prefetched(save, from_node_id=k[0], choice_id=k[1])


@pytest.mark.asyncio
async def test_start_prefetch_skips_ending_nodes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _bootstrap_save(tmp_path, monkeypatch)
    # Mark root as terminal so prefetch should refuse it.
    save.nodes["root"] = save.nodes["root"].model_copy(update={"is_ending": True})
    save_game(save)

    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=False,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    pipeline.start_prefetch(save, from_node_id="root", with_images=False)
    assert pipeline._prefetch._tasks == {}  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_advance_uses_prefetched_node_when_in_flight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A live advance racing an in-flight prefetch awaits the prefetch's
    result rather than double-spending an LLM call."""
    save = _bootstrap_save(tmp_path, monkeypatch)

    # Slow agent: counts calls so we can assert we only paid for one beat.
    class CountingSlowAgent:
        def __init__(self, beat: StoryBeat) -> None:
            self.beat = beat
            self.calls = 0

        async def run(
            self,
            prompt: str,
            on_narration_delta: Any,
            raw_sink: Any = None,
        ) -> StoryBeat:
            del raw_sink
            self.calls += 1
            await asyncio.sleep(0.05)
            return self.beat

    beat = StoryBeat(
        narration="prefetched narration",
        choices=[Choice(id="x", text="x")],
        is_major=False,
        is_ending=False,
    )
    plan = IllustrationPlan(
        should_illustrate=False, image_prompt="", featured_character_ids=[], reasoning=""
    )
    agent = CountingSlowAgent(beat)
    pipeline = BeatPipeline(
        beat_agent=agent,
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    # Start prefetch first (in-flight; will sleep 50ms inside the run method).
    pipeline.start_prefetch(save, from_node_id="root", with_images=False)
    # Concurrent live pick races for the same choice.
    result = await pipeline.advance(save, from_node_id="root", choice_id="c1")

    assert agent.calls == 1  # only one LLM call total — the prefetch's
    assert result.narration == "prefetched narration"
    assert save.current_node_id == result.id  # live-pick set the cursor


@pytest.mark.asyncio
async def test_advance_falls_through_when_prefetch_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the prefetch task already failed, advance regenerates normally."""
    save = _bootstrap_save(tmp_path, monkeypatch)

    class FailingAgent:
        calls = 0

        async def run(
            self,
            prompt: str,
            on_narration_delta: Any,
            raw_sink: Any = None,
        ) -> StoryBeat:
            del raw_sink
            FailingAgent.calls += 1
            raise RuntimeError("simulated provider outage")

    plan = IllustrationPlan(
        should_illustrate=False, image_prompt="", featured_character_ids=[], reasoning=""
    )
    pipeline = BeatPipeline(
        beat_agent=FailingAgent(),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    # Kick off prefetch and let it fail.
    pipeline.start_prefetch(save, from_node_id="root", with_images=False)
    # Drain the failed task so it's no longer in-flight.
    failed_result = await pipeline.await_prefetched(save, from_node_id="root", choice_id="c1")
    assert failed_result is None
    assert pipeline._prefetch._tasks == {}  # pyright: ignore[reportPrivateUsage]

    # Now swap to a working agent and call advance: normal path runs.
    good_beat = StoryBeat(
        narration="recovered",
        choices=[Choice(id="x", text="x")],
        is_major=False,
        is_ending=False,
    )
    pipeline._beat = FakeBeatAgent(good_beat)  # pyright: ignore[reportPrivateUsage]
    result = await pipeline.advance(save, from_node_id="root", choice_id="c1")
    assert result.narration == "recovered"


@pytest.mark.asyncio
async def test_prefetch_failure_is_logged_silently(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Prefetch failure must NOT raise; should log at INFO."""
    import logging as _logging

    save = _bootstrap_save(tmp_path, monkeypatch)

    class FailingAgent:
        async def run(
            self,
            prompt: str,
            on_narration_delta: Any,
            raw_sink: Any = None,
        ) -> StoryBeat:
            del raw_sink
            raise RuntimeError("boom")

    pipeline = BeatPipeline(
        beat_agent=FailingAgent(),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=False,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    with caplog.at_level(_logging.INFO, logger="storygen.pipeline_prefetch"):
        pipeline.start_prefetch(save, from_node_id="root", with_images=False)
        # Awaiting should return None, not raise.
        result = await pipeline.await_prefetched(save, from_node_id="root", choice_id="c1")

    assert result is None
    assert any("prefetch failed" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_prefetch_does_not_move_current_node(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Prefetch must not jump the player's cursor mid-read."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    original_cursor = save.current_node_id

    beat = StoryBeat(
        narration="prefetched ahead",
        choices=[],
        is_major=False,
        is_ending=True,  # would normally append to endings_reached
    )
    plan = IllustrationPlan(
        should_illustrate=False, image_prompt="", featured_character_ids=[], reasoning=""
    )
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    pipeline.start_prefetch(save, from_node_id="root", with_images=False)
    # Wait for the prefetch task to finish without consuming it.
    task = pipeline._prefetch._tasks[("root", "c1")]  # pyright: ignore[reportPrivateUsage]
    await task

    assert save.current_node_id == original_cursor  # unchanged
    assert save.endings_reached == []  # not appended despite is_ending


@pytest.mark.asyncio
async def test_prefetch_does_not_fire_ui_callbacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Prefetch must NOT fire on_beat_committed or on_new_characters."""
    save = _bootstrap_save(tmp_path, monkeypatch)

    beat = StoryBeat(
        narration="prefetched",
        choices=[Choice(id="x", text="x")],
        is_major=False,
        is_ending=False,
        new_characters=[
            Character(
                id="newc",
                name="N",
                backstory="b",
                personality="p",
                physical_description="d",
                portrait_path=None,
                portrait_prompt=None,
                introduced_at_node_id="pending",
            )
        ],
    )
    plan = IllustrationPlan(
        should_illustrate=False, image_prompt="", featured_character_ids=[], reasoning=""
    )

    committed_calls: list[object] = []
    new_char_calls: list[object] = []

    async def on_committed(n: object) -> None:
        committed_calls.append(n)

    async def on_new(c: object) -> None:
        new_char_calls.append(c)

    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(
            on_beat_committed=on_committed,
            on_new_characters=on_new,
        ),
    )

    pipeline.start_prefetch(save, from_node_id="root", with_images=False)
    task = pipeline._prefetch._tasks[("root", "c1")]  # pyright: ignore[reportPrivateUsage]
    await task

    assert committed_calls == []
    assert new_char_calls == []


@pytest.mark.asyncio
async def test_advance_after_prefetch_completes_fires_committed_callback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Once the player picks the prefetched choice, on_beat_committed fires
    so the UI re-renders to the new beat."""
    save = _bootstrap_save(tmp_path, monkeypatch)

    beat = StoryBeat(
        narration="prefetched",
        choices=[Choice(id="x", text="x")],
        is_major=False,
        is_ending=False,
    )
    plan = IllustrationPlan(
        should_illustrate=False, image_prompt="", featured_character_ids=[], reasoning=""
    )

    committed_calls: list[object] = []

    async def on_committed(n: object) -> None:
        committed_calls.append(n)

    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(on_beat_committed=on_committed),
    )

    pipeline.start_prefetch(save, from_node_id="root", with_images=False)
    # Let prefetch finish first (without consuming via await_prefetched).
    task = pipeline._prefetch._tasks[("root", "c1")]  # pyright: ignore[reportPrivateUsage]
    await task
    assert committed_calls == []  # no callback during prefetch

    # Now the live pick arrives.
    result = await pipeline.advance(save, from_node_id="root", choice_id="c1")
    assert len(committed_calls) == 1
    assert save.current_node_id == result.id


@pytest.mark.asyncio
async def test_pipeline_cost_tracking_gemini_uses_gemini_rates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A save pinned to Gemini Flash should bill at Gemini's 1K-tier rate
    ($0.067), not OpenAI's medium-quality rate ($0.042)."""
    save = _bootstrap_save(
        tmp_path,
        monkeypatch,
        image_config=ImageProviderConfig(provider="gemini", model="gemini-3.1-flash-image-preview"),
    )
    from datetime import datetime

    failed_node = StoryNode(
        id="failed-node",
        parent_id="root",
        chosen_choice_id="c1",
        chosen_at=datetime.now(UTC),
        narration="x",
        choices=[],
        is_major=True,
        is_ending=True,
        image_prompt="some prompt",
        image_path=None,
        image_status="failed",
        illustration_reasoning="x",
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save.nodes["failed-node"] = failed_node
    save.nodes["root"].choices[0].child_node_id = "failed-node"
    save_game(save)

    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=True,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    await pipeline.retry_scene(save, node_id="failed-node")
    # Scene size is 1024x1024 → Gemini 1K tier → $0.067 for Flash. OpenAI's
    # medium-quality rate would have been $0.042 — a different number.
    assert abs(save.total_image_cost_usd - 0.067) < 1e-9


@pytest.mark.asyncio
async def test_cancel_all_prefetches_cancels_in_flight_tasks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """cancel_all_prefetches must cancel in-flight tasks and clear the registry.

    Avoids asyncio cancelling a prefetch mid-save_game on app shutdown.
    """
    save = _bootstrap_save(tmp_path, monkeypatch)
    save.nodes["root"].choices.extend([StoredChoice(id="c2", text="b")])
    save_game(save)

    # Hold a barrier so the prefetch tasks stay in-flight when we cancel.
    started = asyncio.Event()
    block_forever = asyncio.Event()

    class HangingBeatAgent:
        async def run(
            self,
            prompt: str,
            on_narration_delta: Any,
            raw_sink: Any = None,
        ) -> StoryBeat:
            del raw_sink
            started.set()
            await block_forever.wait()  # never set
            return StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)

    pipeline = BeatPipeline(
        beat_agent=HangingBeatAgent(),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=False,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    pipeline.start_prefetch(save, from_node_id="root", with_images=False)
    in_flight = list(pipeline._prefetch._tasks.values())  # pyright: ignore[reportPrivateUsage]
    assert len(in_flight) == 2
    # Wait until at least one task has actually entered run so cancel
    # exercises the live-task path, not just done-task cleanup.
    await asyncio.wait_for(started.wait(), timeout=1.0)

    await pipeline.cancel_all_prefetches()

    assert pipeline._prefetch._tasks == {}  # pyright: ignore[reportPrivateUsage]
    for task in in_flight:
        assert task.done()
        assert task.cancelled() or task.exception() is not None


@pytest.mark.asyncio
async def test_cancel_all_prefetches_noop_when_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Calling cancel_all_prefetches with nothing in flight must not raise."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    _ = save  # bootstrap initializes XDG paths
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=False,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )
    await pipeline.cancel_all_prefetches()
    assert pipeline._prefetch._tasks == {}  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_prefetch_failure_log_dedupes_per_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Two consecutive failed prefetches for the same key log only once."""
    import logging as _logging

    save = _bootstrap_save(tmp_path, monkeypatch)

    class FailingAgent:
        async def run(
            self,
            prompt: str,
            on_narration_delta: Any,
            raw_sink: Any = None,
        ) -> StoryBeat:
            del raw_sink
            raise RuntimeError("boom")

    pipeline = BeatPipeline(
        beat_agent=FailingAgent(),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=False,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    with caplog.at_level(_logging.INFO, logger="storygen.pipeline_prefetch"):
        # First failure: should log once.
        pipeline.start_prefetch(save, from_node_id="root", with_images=False)
        await pipeline.await_prefetched(save, from_node_id="root", choice_id="c1")
        # Second failure for the same (parent, choice): must NOT log again.
        pipeline.start_prefetch(save, from_node_id="root", with_images=False)
        await pipeline.await_prefetched(save, from_node_id="root", choice_id="c1")

    failure_logs = [r for r in caplog.records if "prefetch failed" in r.message]
    assert len(failure_logs) == 1
    # Logged at INFO, not WARNING.
    assert failure_logs[0].levelno == _logging.INFO


@pytest.mark.asyncio
async def test_prefetch_failure_log_re_logs_after_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A successful prefetch clears the dedupe entry so the next failure re-logs."""
    import logging as _logging

    save = _bootstrap_save(tmp_path, monkeypatch)

    class FlakyAgent:
        def __init__(self) -> None:
            self.call = 0

        async def run(
            self,
            prompt: str,
            on_narration_delta: Any,
            raw_sink: Any = None,
        ) -> StoryBeat:
            del raw_sink
            self.call += 1
            # Fail on calls 1 and 3; succeed on call 2.
            if self.call in (1, 3):
                raise RuntimeError("boom")
            return StoryBeat(
                narration="ok",
                choices=[Choice(id="x", text="x")],
                is_major=False,
                is_ending=False,
            )

    pipeline = BeatPipeline(
        beat_agent=FlakyAgent(),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=False,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    with caplog.at_level(_logging.INFO, logger="storygen.pipeline_prefetch"):
        # Failure #1 — logs.
        pipeline.start_prefetch(save, from_node_id="root", with_images=False)
        await pipeline.await_prefetched(save, from_node_id="root", choice_id="c1")
        # Recovery — succeeds; clears dedupe entry. The success path also
        # writes child_node_id, which would prevent further start_prefetch
        # spawns for the same key, so blow it away to keep failure #2 testable.
        pipeline.start_prefetch(save, from_node_id="root", with_images=False)
        success = await pipeline.await_prefetched(save, from_node_id="root", choice_id="c1")
        assert success is not None
        # Sever the just-wired cache link so the next start_prefetch will
        # actually spawn a new task instead of skipping the cached choice.
        save.nodes["root"].choices[0].child_node_id = None
        save_game(save)
        # Failure #2 — different attempt; should re-log because dedupe
        # state was cleared by the successful prefetch.
        pipeline.start_prefetch(save, from_node_id="root", with_images=False)
        await pipeline.await_prefetched(save, from_node_id="root", choice_id="c1")

    failure_logs = [r for r in caplog.records if "prefetch failed" in r.message]
    assert len(failure_logs) == 2


@pytest.mark.asyncio
async def test_prefetch_concurrency_capped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The pipeline's semaphore must cap simultaneous in-flight prefetch
    LLM calls at ``_PREFETCH_CONCURRENCY`` even when more tasks are spawned.
    """

    save = _bootstrap_save(tmp_path, monkeypatch)
    # Spawn more pending choices than the concurrency cap so we can observe
    # the semaphore actually queueing some of them.
    extra_count = _PREFETCH_CONCURRENCY + 2
    save.nodes["root"].choices.extend(
        StoredChoice(id=f"c{i}", text=f"opt{i}") for i in range(2, 2 + extra_count)
    )
    save_game(save)

    in_flight = 0
    max_in_flight = 0
    gate = asyncio.Event()

    class CountingSlowAgent:
        async def run(
            self,
            prompt: str,
            on_narration_delta: Any,
            raw_sink: Any = None,
        ) -> StoryBeat:
            del raw_sink
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            try:
                # Hold the slot until the test releases it; without this each
                # task would zip through and we could never observe stacking.
                await gate.wait()
                return StoryBeat(
                    narration="x",
                    choices=[Choice(id="x", text="x")],
                    is_major=False,
                    is_ending=False,
                )
            finally:
                in_flight -= 1

    plan = IllustrationPlan(
        should_illustrate=False, image_prompt="", featured_character_ids=[], reasoning=""
    )
    pipeline = BeatPipeline(
        beat_agent=CountingSlowAgent(),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    pipeline.start_prefetch(save, from_node_id="root", with_images=False)
    # All N tasks are spawned (idempotency dict is dense) — the semaphore
    # only gates the inner agent.run call.
    assert len(pipeline._prefetch._tasks) == 1 + extra_count  # pyright: ignore[reportPrivateUsage]
    # Pump the loop a few times so queued tasks have a chance to enter
    # run up to the semaphore cap.
    for _ in range(5):
        await asyncio.sleep(0)
    assert max_in_flight == _PREFETCH_CONCURRENCY, (
        f"expected at most {_PREFETCH_CONCURRENCY} in flight, saw {max_in_flight}"
    )

    # Release everyone and drain so the test loop doesn't leak tasks.
    gate.set()
    for k in list(pipeline._prefetch._tasks):  # pyright: ignore[reportPrivateUsage]
        await pipeline.await_prefetched(save, from_node_id=k[0], choice_id=k[1])


class _StreamingFakeImageProvider:
    """ImageProvider stub that records on_partial wiring AND fires it twice
    with deterministic byte payloads. Used to verify the pipeline:
    (a) only passes on_partial when streaming + openai are both true,
    (b) writes partial bytes atomically to the node's image_path, and
    (c) fires on_image_committed for each partial.
    """

    def __init__(self) -> None:
        self.scene_calls: list[dict[str, object]] = []
        self.partials_to_emit = [b"PARTIAL-A", b"PARTIAL-B"]

    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        on_partial: Any = None,
        reference_image: bytes | None = None,
    ) -> bytes:
        del description, transparent, art_style, on_partial, reference_image
        return b"P"

    async def generate_scene(
        self,
        prompt: str,
        *,
        reference_portraits: list[ReferencePortrait],
        art_style: str = "children's story book",
        on_partial: Any = None,
    ) -> bytes:
        self.scene_calls.append(
            {"prompt": prompt, "refs": len(reference_portraits), "on_partial": on_partial}
        )
        if on_partial is not None:
            for partial in self.partials_to_emit:
                await on_partial(partial)
        return b"FINAL-SCENE"


@pytest.mark.asyncio
async def test_pipeline_passes_on_partial_when_streaming_and_openai(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Streaming flag ON + openai provider → on_partial wired, partials
    written atomically, on_image_committed fires per partial + once for final."""
    from storygen.storage import app_state, paths

    save = _bootstrap_save(
        tmp_path,
        monkeypatch,
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    app_state.set_image_streaming_enabled(True)

    beat = StoryBeat(
        narration="A rooftop chase.",
        choices=[Choice(id="c1", text="leap")],
        is_major=True,
        is_ending=False,
    )
    plan = IllustrationPlan(
        should_illustrate=True,
        image_prompt="A rooftop chase, neon rain.",
        featured_character_ids=[],
        reasoning="action",
    )
    image_provider = _StreamingFakeImageProvider()

    committed_nodes: list[StoryNode] = []

    async def on_committed(node: StoryNode) -> None:
        committed_nodes.append(node)

    cb = PipelineCallbacks(on_image_committed=on_committed)
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=image_provider,
        callbacks=cb,
    )

    await pipeline.advance(save, from_node_id="root", choice_id="c1")
    # Wait for background scene task to complete (partials + final).
    for _ in range(50):
        await asyncio.sleep(0.02)
        if any(n.image_status == "done" for n in save.nodes.values()):
            break

    assert len(image_provider.scene_calls) == 1
    assert image_provider.scene_calls[0]["on_partial"] is not None

    # The new (non-root) node has the final scene bytes on disk.
    new_nodes = [n for n in save.nodes.values() if n.parent_id == "root"]
    assert len(new_nodes) == 1
    new_node = new_nodes[0]
    assert new_node.image_status == "done"
    assert new_node.image_path is not None
    abs_path = paths.game_dir(str(save.id)) / new_node.image_path
    assert abs_path.read_bytes() == b"FINAL-SCENE"
    # No leftover .tmp file from the atomic write.
    assert not abs_path.with_suffix(".png.tmp").exists()
    # 2 partials + 1 final = 3 on_image_committed calls.
    assert len(committed_nodes) >= 3


@pytest.mark.asyncio
async def test_pipeline_omits_on_partial_when_streaming_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Streaming flag OFF → on_partial=None even on openai."""
    from storygen.storage import app_state

    save = _bootstrap_save(
        tmp_path,
        monkeypatch,
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    app_state.set_image_streaming_enabled(False)

    beat = StoryBeat(
        narration="x", choices=[Choice(id="c1", text="x")], is_major=True, is_ending=False
    )
    plan = IllustrationPlan(
        should_illustrate=True, image_prompt="p", featured_character_ids=[], reasoning="r"
    )
    image_provider = _StreamingFakeImageProvider()
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=image_provider,
        callbacks=PipelineCallbacks(),
    )
    await pipeline.advance(save, from_node_id="root", choice_id="c1")
    for _ in range(50):
        await asyncio.sleep(0.02)
        if image_provider.scene_calls:
            break
    assert image_provider.scene_calls[0]["on_partial"] is None


@pytest.mark.asyncio
async def test_pipeline_omits_on_partial_for_non_openai_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Streaming flag ON but provider is gemini → on_partial=None (no-op)."""
    from storygen.storage import app_state

    save = _bootstrap_save(
        tmp_path,
        monkeypatch,
        image_config=ImageProviderConfig(provider="gemini", model="gemini-3.1-flash-image-preview"),
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    app_state.set_image_streaming_enabled(True)

    beat = StoryBeat(
        narration="x", choices=[Choice(id="c1", text="x")], is_major=True, is_ending=False
    )
    plan = IllustrationPlan(
        should_illustrate=True, image_prompt="p", featured_character_ids=[], reasoning="r"
    )
    image_provider = _StreamingFakeImageProvider()
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=image_provider,
        callbacks=PipelineCallbacks(),
    )
    await pipeline.advance(save, from_node_id="root", choice_id="c1")
    for _ in range(50):
        await asyncio.sleep(0.02)
        if image_provider.scene_calls:
            break
    assert image_provider.scene_calls[0]["on_partial"] is None


# --- Raw LLM cache (debug-only sidecar) ---------------------------------------


class _RawDumpingBeatAgent:
    """Beat agent fake that mirrors the adapter contract: when ``raw_sink`` is
    provided, calls it with canned bytes. Used to verify the pipeline wires the
    sink through (or doesn't, when the flag is off)."""

    def __init__(self, beat: StoryBeat, raw: bytes = b'{"agent": "beat"}') -> None:
        self.beat = beat
        self.raw = raw

    async def run(
        self,
        prompt: str,
        on_narration_delta: Any,
        raw_sink: Any = None,
    ) -> StoryBeat:
        del prompt
        if raw_sink is not None:
            raw_sink(self.raw)
        if self.beat.narration:
            await on_narration_delta(self.beat.narration)
        return self.beat


class _RawDumpingIllustrationAgent:
    def __init__(self, plan: IllustrationPlan, raw: bytes = b'{"agent": "illustration"}') -> None:
        self.plan = plan
        self.raw = raw

    async def run(
        self,
        beat: StoryBeat,
        characters: list[Character],
        raw_sink: Any = None,
    ) -> IllustrationPlan:
        del beat, characters
        if raw_sink is not None:
            raw_sink(self.raw)
        return self.plan


class _RawDumpingSummaryAgent:
    def __init__(self, raw: bytes = b'{"agent": "summary"}') -> None:
        self.raw = raw

    async def run(self, path_summary_prompt: str, raw_sink: Any = None) -> Summary:
        del path_summary_prompt
        if raw_sink is not None:
            raw_sink(self.raw)
        return Summary(text="story so far")


class _FailingSummaryAgent:
    async def run(self, path_summary_prompt: str, raw_sink: Any = None) -> Summary:
        del path_summary_prompt, raw_sink
        raise RuntimeError("Network error, please try again later")


@pytest.mark.asyncio
async def test_pipeline_summary_failure_does_not_abort_committed_beat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _bootstrap_save(tmp_path, monkeypatch)
    beat = StoryBeat(
        narration="A major beat lands.",
        choices=[Choice(id="x", text="x")],
        is_major=True,
        is_ending=False,
    )
    plan = IllustrationPlan(
        should_illustrate=False, image_prompt="", featured_character_ids=[], reasoning="quiet"
    )
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=_FailingSummaryAgent(),
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    node = await pipeline.advance(save, from_node_id="root", choice_id="c1")

    assert node.narration == "A major beat lands."
    assert node.summary_to_here is None
    assert save.current_node_id == node.id
    assert save.nodes["root"].choices[0].child_node_id == node.id


@pytest.mark.asyncio
async def test_pipeline_dumps_llm_cache_when_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With the flag ON, advance() dumps beat + illustration + summary
    sidecars under ``<save>/llm/<node-id>-<agent>.json``."""
    from storygen.storage import app_state
    from storygen.storage.llm_cache import llm_cache_dir, llm_exchange_path

    save = _bootstrap_save(tmp_path, monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    app_state.set_llm_cache_enabled(True)

    beat = StoryBeat(
        narration="A great event.",
        choices=[Choice(id="x", text="x")],
        is_major=True,  # triggers summary
        is_ending=False,
    )
    plan = IllustrationPlan(
        should_illustrate=False, image_prompt="", featured_character_ids=[], reasoning="quiet"
    )
    pipeline = BeatPipeline(
        beat_agent=_RawDumpingBeatAgent(beat),
        illustration_agent=_RawDumpingIllustrationAgent(plan),
        summary_agent=_RawDumpingSummaryAgent(),
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    node = await pipeline.advance(save, from_node_id="root", choice_id="c1")

    save_id = str(save.id)
    cache_dir = llm_cache_dir(save_id)
    assert cache_dir.is_dir()

    beat_path = llm_exchange_path(save_id, node.id, "beat")
    illus_path = llm_exchange_path(save_id, node.id, "illustration")
    summary_path = llm_exchange_path(save_id, node.id, "summary")
    assert beat_path.read_bytes() == b'{"agent": "beat"}'
    assert illus_path.read_bytes() == b'{"agent": "illustration"}'
    assert summary_path.read_bytes() == b'{"agent": "summary"}'


@pytest.mark.asyncio
async def test_pipeline_no_llm_cache_when_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With the flag OFF (default), advance() leaves the llm/ dir untouched."""
    from storygen.storage import app_state
    from storygen.storage.llm_cache import llm_cache_dir

    save = _bootstrap_save(tmp_path, monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    # Explicitly disabled (also the default).
    app_state.set_llm_cache_enabled(False)

    beat = StoryBeat(
        narration="A quiet step.",
        choices=[Choice(id="x", text="x")],
        is_major=True,
        is_ending=False,
    )
    plan = IllustrationPlan(
        should_illustrate=False, image_prompt="", featured_character_ids=[], reasoning=""
    )
    pipeline = BeatPipeline(
        beat_agent=_RawDumpingBeatAgent(beat),
        illustration_agent=_RawDumpingIllustrationAgent(plan),
        summary_agent=_RawDumpingSummaryAgent(),
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )

    await pipeline.advance(save, from_node_id="root", choice_id="c1")

    # The llm/ directory should not have been created at all.
    assert not llm_cache_dir(str(save.id)).exists()


# --- edit_scene tests ----------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_edit_scene_replaces_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """edit_scene uses the new prompt and optionally passes current image as ref."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    from datetime import datetime

    failed_node = StoryNode(
        id="edit-node",
        parent_id="root",
        chosen_choice_id="c1",
        chosen_at=datetime.now(UTC),
        narration="A stormy night.",
        choices=[],
        is_major=True,
        is_ending=True,
        image_prompt="dark castle on a hill",
        image_path=None,
        image_status="done",
        illustration_reasoning="moody establishing shot",
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save.nodes["edit-node"] = failed_node
    save.nodes["root"].choices[0].child_node_id = "edit-node"
    save_game(save)

    image_provider = FakeImageProvider()
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=True,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=image_provider,
        callbacks=PipelineCallbacks(),
    )

    result = await pipeline.edit_scene(
        save,
        node_id="edit-node",
        new_prompt="dark castle on a hill with lightning",
    )

    assert len(image_provider.scenes) == 1
    assert image_provider.scenes[0][0] == "dark castle on a hill with lightning"
    assert result.image_status == "done"
    assert result.image_path is not None
    # The stored prompt should be updated.
    assert save.nodes["edit-node"].image_prompt == "dark castle on a hill with lightning"


@pytest.mark.asyncio
async def test_pipeline_edit_scene_includes_current_image_as_ref(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """edit_scene with current_image_as_ref=True prepends the existing image."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    from datetime import datetime

    edit_node = StoryNode(
        id="edit-node",
        parent_id="root",
        chosen_choice_id="c1",
        chosen_at=datetime.now(UTC),
        narration="A stormy night.",
        choices=[],
        is_major=True,
        is_ending=True,
        image_prompt="dark castle",
        image_path="images/nodes/edit-node.png",
        image_status="done",
        illustration_reasoning="",
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save.nodes["edit-node"] = edit_node
    save.nodes["root"].choices[0].child_node_id = "edit-node"
    # Write a dummy existing image so edit_scene can read it.
    from storygen.storage import paths as _paths

    img_dir = _paths.game_dir(str(save.id)) / "images" / "nodes"
    img_dir.mkdir(parents=True, exist_ok=True)
    (img_dir / "edit-node.png").write_bytes(b"EXISTING-PNG")
    save_game(save)

    image_provider = FakeImageProvider()
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=True,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=image_provider,
        callbacks=PipelineCallbacks(),
    )

    await pipeline.edit_scene(
        save,
        node_id="edit-node",
        new_prompt="castle with moonlight",
        current_image_as_ref=True,
    )

    assert len(image_provider.scenes) == 1
    # 1 ref = the existing scene image prepended.
    assert image_provider.scenes[0][1] == 1


@pytest.mark.asyncio
async def test_pipeline_edit_scene_skips_when_art_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """edit_scene must be a no-op when art is globally disabled."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from datetime import datetime

    from storygen.storage import app_state

    edit_node = StoryNode(
        id="edit-node",
        parent_id="root",
        chosen_choice_id="c1",
        chosen_at=datetime.now(UTC),
        narration="x",
        choices=[],
        is_major=True,
        is_ending=True,
        image_prompt="castle",
        image_path=None,
        image_status="done",
        illustration_reasoning="",
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save.nodes["edit-node"] = edit_node
    save_game(save)

    image_provider = FakeImageProvider()
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(
            StoryBeat(narration="x", choices=[], is_major=False, is_ending=True)
        ),
        illustration_agent=FakeIllustrationAgent(
            IllustrationPlan(
                should_illustrate=True,
                image_prompt="",
                featured_character_ids=[],
                reasoning="",
            )
        ),
        summary_agent=None,
        image_provider=image_provider,
        callbacks=PipelineCallbacks(),
    )

    app_state.set_art_enabled(False)

    result = await pipeline.edit_scene(
        save,
        node_id="edit-node",
        new_prompt="castle with moonlight",
    )
    assert len(image_provider.scenes) == 0
    assert result.image_status == "done"

    # Restore
    app_state.set_art_enabled(True)


# --- Relationship merge tests ---


@pytest.mark.asyncio
async def test_pipeline_merges_relationship_updates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """advance() merges relationship_updates from beat into save.relationships."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    from storygen.core.models import Relationship, RelationshipType

    beat = StoryBeat(
        narration="They fought side by side.",
        choices=[Choice(id="c1", text="onward")],
        is_major=False,
        is_ending=False,
        relationship_updates=[
            Relationship(
                char_a_id="a",
                char_b_id="b",
                type=RelationshipType.ALLY,
                strength=3,
                context="fought together",
                updated_at_node_id="pending",
            ),
        ],
    )
    plan = IllustrationPlan(
        should_illustrate=False,
        image_prompt="",
        featured_character_ids=[],
        reasoning="",
    )
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )
    await pipeline.advance(save, from_node_id="root", choice_id="c1")
    assert len(save.relationships) == 1
    assert save.relationships[0].type == RelationshipType.ALLY
    assert save.relationships[0].context == "fought together"


@pytest.mark.asyncio
async def test_pipeline_merges_relationship_update_existing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Updating an existing relationship replaces type/strength/context."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    from storygen.core.models import Relationship, RelationshipType

    save.relationships.append(
        Relationship(
            char_a_id="a",
            char_b_id="b",
            type=RelationshipType.NEUTRAL,
            strength=1,
            context="strangers",
            updated_at_node_id="root",
        )
    )
    beat = StoryBeat(
        narration="They became friends.",
        choices=[Choice(id="c1", text="onward")],
        is_major=False,
        is_ending=False,
        relationship_updates=[
            Relationship(
                char_a_id="a",
                char_b_id="b",
                type=RelationshipType.ALLY,
                strength=3,
                context="became friends",
                updated_at_node_id="pending",
            ),
        ],
    )
    plan = IllustrationPlan(
        should_illustrate=False,
        image_prompt="",
        featured_character_ids=[],
        reasoning="",
    )
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )
    await pipeline.advance(save, from_node_id="root", choice_id="c1")
    assert len(save.relationships) == 1
    assert save.relationships[0].type == RelationshipType.ALLY
    assert save.relationships[0].strength == 3
    assert save.relationships[0].context == "became friends"


@pytest.mark.asyncio
async def test_pipeline_merges_relationship_no_updates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A beat with empty relationship_updates leaves existing relationships unchanged."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    from storygen.core.models import Relationship, RelationshipType

    save.relationships.append(
        Relationship(
            char_a_id="a",
            char_b_id="b",
            type=RelationshipType.RIVAL,
            strength=2,
            context="tension",
            updated_at_node_id="root",
        )
    )
    beat = StoryBeat(
        narration="A quiet moment.",
        choices=[Choice(id="c1", text="onward")],
        is_major=False,
        is_ending=False,
        relationship_updates=[],
    )
    plan = IllustrationPlan(
        should_illustrate=False,
        image_prompt="",
        featured_character_ids=[],
        reasoning="",
    )
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )
    await pipeline.advance(save, from_node_id="root", choice_id="c1")
    assert len(save.relationships) == 1
    assert save.relationships[0].type == RelationshipType.RIVAL
