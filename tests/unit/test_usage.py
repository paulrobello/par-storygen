"""Unit tests for the per-save LLM token-usage tracker."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from storygen.llm.models import (
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.llm.usage import UsageTotals, record_usage_on_save
from storygen.storage.save import GameSave


def _make_save() -> GameSave:
    root = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="",
        choices=[StoredChoice(id="c1", text="go")],
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
    return GameSave(
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


class _StubUsage:
    """Minimal duck-typed stand-in for pydantic-ai's RunUsage."""

    def __init__(
        self,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        requests: int | None = None,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.requests = requests


def test_usage_totals_record_accumulates() -> None:
    totals = UsageTotals()
    totals.record(model="m1", input_tokens=10, output_tokens=20)
    totals.record(model="m1", input_tokens=5, output_tokens=7, requests=2)
    totals.record(model="m2", input_tokens=1, output_tokens=2)
    assert totals.input_tokens == 16
    assert totals.output_tokens == 29
    assert totals.requests == 4
    assert totals.calls_by_model == {"m1": 2, "m2": 1}


def test_usage_totals_record_handles_none_tokens() -> None:
    totals = UsageTotals()
    totals.record(model="m", input_tokens=None, output_tokens=None)
    assert totals.input_tokens == 0
    assert totals.output_tokens == 0
    assert totals.requests == 1
    assert totals.calls_by_model == {"m": 1}


def test_usage_totals_apply_to_save_merges_existing() -> None:
    save = _make_save()
    save.text_total_input_tokens = 100
    save.text_total_output_tokens = 200
    save.text_total_requests = 3
    save.text_calls_by_model = {"m1": 5}

    totals = UsageTotals(
        input_tokens=10, output_tokens=20, requests=2, calls_by_model={"m1": 1, "m2": 4}
    )
    totals.apply_to_save(save)

    assert save.text_total_input_tokens == 110
    assert save.text_total_output_tokens == 220
    assert save.text_total_requests == 5
    assert save.text_calls_by_model == {"m1": 6, "m2": 4}


def test_record_usage_on_save_increments_counts() -> None:
    save = _make_save()
    record_usage_on_save(
        save,
        model="gpt-4o-mini",
        usage=_StubUsage(input_tokens=42, output_tokens=99, requests=1),
    )
    assert save.text_total_input_tokens == 42
    assert save.text_total_output_tokens == 99
    assert save.text_total_requests == 1
    assert save.text_calls_by_model == {"gpt-4o-mini": 1}

    # Second call adds onto the totals and bumps the per-model counter.
    record_usage_on_save(
        save,
        model="gpt-4o-mini",
        usage=_StubUsage(input_tokens=8, output_tokens=1, requests=1),
    )
    assert save.text_total_input_tokens == 50
    assert save.text_total_output_tokens == 100
    assert save.text_total_requests == 2
    assert save.text_calls_by_model == {"gpt-4o-mini": 2}


def test_record_usage_on_save_tolerates_missing_attrs() -> None:
    """A usage object missing fields shouldn't blow up — defaults to 0/1."""

    class _Empty:
        pass

    save = _make_save()
    record_usage_on_save(save, model="m", usage=_Empty())
    assert save.text_total_input_tokens == 0
    assert save.text_total_output_tokens == 0
    # Default requests=1 when attribute is missing.
    assert save.text_total_requests == 1
    assert save.text_calls_by_model == {"m": 1}
