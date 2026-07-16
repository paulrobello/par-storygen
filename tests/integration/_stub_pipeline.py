"""Stub BeatPipeline for integration tests — replays canned events, no LLM calls.

Used by ``tests/integration/test_api_full_flow.py`` to drive the WebSocket
advance flow deterministically. The stub invokes the caller-supplied
``PipelineCallbacks`` with the same sequence a real pipeline would emit:

    on_narration_delta("…")   # one or more times
    on_beat_committed(node)   # once, with a non-empty choices list

so the WS layer's ``make_callbacks`` broadcasts are exercised end-to-end.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from storygen.llm.models import StoredChoice, StoryNode
from storygen.pipeline import PipelineCallbacks


class StubBeatPipeline:
    """Drop-in ``BeatPipeline`` for tests. Only ``advance`` is exercised."""

    async def advance(
        self,
        save: Any,
        *,
        from_node_id: str,
        choice_id: str,
        skip_image: bool = False,
        suppress_side_effects: bool = False,
        callbacks: PipelineCallbacks | None = None,
    ) -> StoryNode:
        del skip_image
        new_node = StoryNode(
            id=f"child-{from_node_id}-{choice_id}",
            parent_id=from_node_id,
            chosen_choice_id=choice_id,
            chosen_at=None,
            narration="The path winds onward.",
            choices=[StoredChoice(id="c2", text="Continue")],
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
        # Wire the new node into the parent's choices so downstream fetches find it.
        parent = save.nodes.get(from_node_id)
        if parent is not None:
            updated_choices = [
                c.model_copy(update={"child_node_id": new_node.id})
                if c.id == choice_id
                else c
                for c in parent.choices
            ]
            save.nodes[from_node_id] = parent.model_copy(update={"choices": updated_choices})
        save.nodes[new_node.id] = new_node
        save.current_node_id = new_node.id

        if suppress_side_effects or callbacks is None:
            return new_node

        # Replay a small narration sequence then commit the beat.
        await callbacks.on_narration_delta("The path winds onward.")
        await callbacks.on_beat_committed(new_node)
        return new_node

    async def cancel_all_prefetches(self) -> None:
        """Match the real pipeline's interface (no-op for the stub)."""
        return None
