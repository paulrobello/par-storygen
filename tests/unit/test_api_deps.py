"""Unit tests for ``storygen_api.deps`` — the FastAPI dependency/composition layer.

Covers the public surface that routers depend on:

- :func:`build_split_image_provider_for_wizard` returns a
  :class:`SplitImageProvider` instance; :func:`build_split_provider_for_save`
  (the save-pinned builder in :mod:`storygen.runtime.adapters`) likewise.
- :func:`build_pipeline` wires the shared adapters (:mod:`storygen.runtime.adapters`)
  into a :class:`BeatPipeline`.
- :func:`get_app_config` caches the loaded :class:`AppConfig`.
- :func:`get_session_manager` returns the singleton :class:`PipelineSessionManager`.

Also re-asserts the ARC-003 regression: the shared ``BeatAgentAdapter`` must
read ``result.usage`` (the pydantic-ai 2.x property form), not call
``result.usage()`` — the historical ``deps.py`` copy silently dropped usage
tracking because the resulting ``TypeError`` was swallowed by the
``contextlib.suppress(Exception)`` around the call.
"""

from __future__ import annotations

from typing import Any

import pytest

from storygen.config import AppConfig
from storygen.core.models import (
    Character,
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.runtime.adapters import BeatAgentAdapter, IllustrationAdapter, SummaryAdapter
from storygen.storage.save import GameSave, save_game
from storygen_api import deps

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_save(xdg_tmp: Any) -> GameSave:
    """Build a minimal pinned GameSave (no LLM calls, no portrait gen)."""
    from datetime import UTC, datetime
    from uuid import uuid4

    root = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="You open your eyes.",
        choices=[StoredChoice(id="c1", text="Look around")],
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
        theme=Theme(title="T", setting="S", premise="P", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        character_image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        characters=[
            Character(
                id="alyx",
                name="Alyx",
                backstory="b",
                personality="p",
                physical_description="d",
                portrait_path=None,
                portrait_prompt=None,
                introduced_at_node_id="root",
            )
        ],
        nodes={"root": root},
        root_node_id="root",
        current_node_id="root",
        endings_reached=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    save_game(save)
    return save


class _UsagePropertyResult:
    """Stub matching pydantic-ai 2.x: ``usage`` is a property, not callable."""

    def __init__(self, output: Any, usage: Any) -> None:
        self._output = output
        self._usage = usage

    @property
    def output(self) -> Any:
        return self._output

    @property
    def usage(self) -> Any:
        return self._usage

    def all_messages_json(self) -> bytes:
        return b"[]"


class _UsageMethodResult:
    """Stub matching the broken form: ``usage`` is a callable that returns the value.

    Used to prove the adapter reads the property, not the method — if the adapter
    called ``result.usage()`` against this stub's property, it would raise
    ``TypeError: 'Usage' object is not callable``.
    """

    def __init__(self, output: Any, usage_obj: Any) -> None:
        self._output = output
        # ``usage`` is the OBJECT itself; calling it raises TypeError, matching
        # pydantic-ai 2.x where RunUsage is not callable.
        self._usage_obj = usage_obj

    @property
    def output(self) -> Any:
        return self._output

    @property
    def usage(self) -> Any:
        return self._usage_obj

    def all_messages_json(self) -> bytes:
        return b"[]"


# ---------------------------------------------------------------------------
# ARC-003 regression: shared adapters must read ``result.usage`` (property)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_beat_agent_adapter_reads_usage_property() -> None:
    """ARC-003 regression: adapter must read result.usage as a property.

    Before ARC-003, deps.py called ``result.usage()`` which raised
    ``TypeError: 'RunUsage' object is not callable`` on pydantic-ai 2.x —
    silently swallowed by the surrounding ``contextlib.suppress(Exception)``,
    dropping usage tracking on the entire API surface.
    """
    captured: list[object] = []

    class _FakeBeat:
        narration = "Hello world."

    class _FakeAgent:
        async def run(self, prompt: str) -> _UsagePropertyResult:
            return _UsagePropertyResult(output=_FakeBeat(), usage={"input": 10})

    adapter = BeatAgentAdapter(_FakeAgent(), on_usage=captured.append)
    deltas: list[str] = []

    class _Sink:
        async def __call__(self, delta: str) -> None:
            deltas.append(delta)

    await adapter.run("ignored", _Sink())  # type: ignore[arg-type]

    assert captured == [{"input": 10}], "adapter must invoke on_usage with result.usage"
    assert deltas == ["Hello world."]


@pytest.mark.asyncio
async def test_beat_agent_adapter_does_not_call_usage_as_method() -> None:
    """If ``usage`` is not callable, the adapter must still succeed (read property).

    A defensive test: if a future pydantic-ai version makes ``usage`` callable
    again, the adapter should still surface the value, not silently swallow.
    """
    captured: list[object] = []

    class _FakeBeat:
        narration = "Beat."

    class _FakeAgent:
        async def run(self, prompt: str) -> _UsageMethodResult:
            # Pass a non-callable object; calling it would TypeError.
            return _UsageMethodResult(output=_FakeBeat(), usage_obj={"input": 5})

    adapter = BeatAgentAdapter(_FakeAgent(), on_usage=captured.append)

    class _Sink:
        async def __call__(self, delta: str) -> None:
            pass

    await adapter.run("ignored", _Sink())  # type: ignore[arg-type]
    assert captured == [{"input": 5}]


@pytest.mark.asyncio
async def test_summary_and_illustration_adapters_read_usage_property() -> None:
    """Both other shared adapters must read result.usage (property)."""
    summary_captured: list[object] = []
    illu_captured: list[object] = []

    class _SummaryAgent:
        async def run(self, prompt: str) -> _UsagePropertyResult:
            return _UsagePropertyResult(output="summary", usage={"input": 1})

    class _IllustrationAgent:
        async def run(self, prompt: str) -> _UsagePropertyResult:
            return _UsagePropertyResult(output=object(), usage={"input": 2})

    class _Beat:
        narration = "n"

    summary_adapter = SummaryAdapter(_SummaryAgent(), on_usage=summary_captured.append)
    illustration_adapter = IllustrationAdapter(
        _IllustrationAgent(), on_usage=illu_captured.append
    )
    # SummaryAdapter.run / IllustrationAdapter.run carry `# type: ignore[no-untyped-def]`
    # at the definition site (see src/storygen/runtime/adapters.py) to match the loose-typed
    # pydantic-ai adapter style documented in CLAUDE.md. The unknown-member cascade here is
    # the downstream consequence of that intentional looseness.
    summary_out: object = await summary_adapter.run("p")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    illustration_out: object = await illustration_adapter.run(_Beat(), [])  # type: ignore[arg-type]  # pyright: ignore[reportUnknownMemberType]

    assert summary_out == "summary"
    assert summary_captured == [{"input": 1}]
    assert illu_captured == [{"input": 2}]
    assert illustration_out is not None


# ---------------------------------------------------------------------------
# Public deps surface
# ---------------------------------------------------------------------------


def test_get_app_config_caches(monkeypatch: pytest.MonkeyPatch, xdg_tmp: Any) -> None:
    """``get_app_config`` returns the same instance on repeated calls (lru_cache)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    deps.get_app_config.cache_clear()
    cfg1 = deps.get_app_config()
    cfg2 = deps.get_app_config()
    assert cfg1 is cfg2
    assert isinstance(cfg1, AppConfig)


def test_get_session_manager_returns_singleton() -> None:
    """``get_session_manager`` returns the same singleton each call."""
    mgr1 = deps.get_session_manager()
    mgr2 = deps.get_session_manager()
    assert mgr1 is mgr2


def test_build_split_image_provider_for_wizard_returns_split(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wizard provider builder returns a SplitImageProvider without raising."""
    # The OpenAI client refuses to construct without a key; provide a dummy
    # one so this test does not depend on a real OPENAI_API_KEY in the env.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from storygen.config import load_config
    from storygen.images.split_provider import SplitImageProvider

    cfg = load_config()
    provider = deps.build_split_image_provider_for_wizard(cfg)
    assert isinstance(provider, SplitImageProvider)


def test_build_split_image_provider_returns_split(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Save-pinned provider builder returns a SplitImageProvider without raising."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from storygen.images.split_provider import SplitImageProvider
    from storygen.runtime.adapters import build_split_provider_for_save

    save = _make_save(xdg_tmp)
    provider = build_split_provider_for_save(save)
    assert isinstance(provider, SplitImageProvider)


@pytest.mark.asyncio
async def test_build_pipeline_wires_shared_adapters(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``build_pipeline`` wires BeatAgentAdapter/IllustrationAdapter/SummaryAdapter.

    Verifies the shared adapter classes (ARC-003) are what the pipeline sees —
    not the historical duplicated copies.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    save = _make_save(xdg_tmp)

    pipeline, image_provider = deps.build_pipeline(save)

    assert isinstance(pipeline._beat, BeatAgentAdapter)  # pyright: ignore[reportPrivateUsage]
    assert isinstance(pipeline._illustration, IllustrationAdapter)  # pyright: ignore[reportPrivateUsage]
    assert isinstance(pipeline._summary, SummaryAdapter)  # pyright: ignore[reportPrivateUsage]
    # image_provider is whatever build_split_provider_for_save returns.
    from storygen.images.split_provider import SplitImageProvider

    assert isinstance(image_provider, SplitImageProvider)
