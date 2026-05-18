"""Pipeline coordinator for the 3-stage beat flow.

Stage 1: stream a StoryBeat; commit it; unblock player.
Stage 2: ask the illustration agent what to draw.
Stage 3: if should_illustrate, kick off scene-image generation in the bg.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from storygen.core.models import one_sentence as _one_sentence
from storygen.images.base import ReferencePortrait
from storygen.images.constants import (
    OPENAI_PARTIAL_IMAGES,
    PORTRAIT_QUALITY,
    PORTRAIT_SIZE,
    SCENE_QUALITY,
    SCENE_SIZE,
)
from storygen.images.pricing import image_cost
from storygen.llm.models import (
    Character,
    Choice,
    IllustrationPlan,
    Relationship,
    StoredChoice,
    StoryBeat,
    StoryNode,
    Summary,
)
from storygen.storage import app_state, paths
from storygen.storage.llm_cache import dump_llm_exchange
from storygen.storage.save import GameSave, save_game
from storygen.storage.tree import path_from_root, segment_since_last_summary

# Cap on the number of in-flight prefetch LLM calls. At typical 2-4 choices per
# node a single prefetch wave fits unthrottled, but rapid back-and-forth
# navigation (or wide branching) could otherwise stack tasks faster than they
# complete. The semaphore is per-BeatPipeline — one game session — so each save
# gets its own budget. The full task set still spawns immediately so
# `_prefetch_tasks` idempotency keys remain dense; the cap only gates the LLM
# call inside `_prefetch_one`.
_PREFETCH_CONCURRENCY: int = 3


class BeatAgentLike(Protocol):
    """Protocol for a beat agent that delivers narration.

    Despite the historical streaming name, implementations may deliver the
    full narration in a single ``on_narration_delta`` call — see
    :class:`_BeatAgentAdapter` in ``app.py``.
    """

    async def run(
        self,
        prompt: str,
        on_narration_delta: Callable[[str], Awaitable[None]],
        raw_sink: Callable[[bytes], None] | None = None,
    ) -> StoryBeat: ...


class IllustrationAgentLike(Protocol):
    """Protocol for an illustration planning agent."""

    async def run(
        self,
        beat: StoryBeat,
        characters: list[Character],
        raw_sink: Callable[[bytes], None] | None = None,
    ) -> IllustrationPlan: ...


class SummaryAgentLike(Protocol):
    """Protocol for a summary agent."""

    async def run(
        self,
        path_summary_prompt: str,
        raw_sink: Callable[[bytes], None] | None = None,
    ) -> Summary: ...


class ImageProviderLike(Protocol):
    """Protocol for an image generation provider."""

    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
        reference_image: bytes | None = None,
    ) -> bytes: ...

    async def generate_scene(
        self,
        prompt: str,
        *,
        reference_portraits: list[ReferencePortrait],
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
    ) -> bytes: ...


def _atomic_write_png(dest: Path, png_bytes: bytes) -> None:
    """Write ``png_bytes`` to ``dest`` via ``.png.tmp`` + ``os.replace``.

    Mirrors the atomic-write pattern in :mod:`storygen.storage.library` /
    :mod:`storygen.storage.save`. Critical for streaming partials: the
    ImagePanel renderer reads the file as a PNG, so a half-written file
    would crash PIL.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".png.tmp")
    tmp.write_bytes(png_bytes)
    os.replace(tmp, dest)


# Module-level set that holds references to fire-and-forget background tasks
# spawned by BeatPipeline._run_stage_2_and_3 (scene generation) and
# StoryGenApp._start_game (cover-art backfill).  Prevents the GC from
# collecting tasks before they finish.  Each task removes itself via
# add_done_callback so the set doesn't accumulate indefinitely.
#
# Exported without leading underscore so ``app.py`` can add cover-art tasks
# to the same set without a private-usage pyright violation.
background_tasks: set[asyncio.Task[None]] = set()
_background_tasks = background_tasks  # module-internal alias


async def _noop() -> None:
    """No-op coroutine for default callbacks."""
    return None


@dataclass
class PipelineCallbacks:
    """UI callbacks invoked as the pipeline progresses."""

    on_narration_delta: Callable[[str], Awaitable[None]] = field(default=lambda _delta: _noop())
    on_beat_committed: Callable[[StoryNode], Awaitable[None]] = field(default=lambda _node: _noop())
    on_image_committed: Callable[[StoryNode], Awaitable[None]] = field(
        default=lambda _node: _noop()
    )
    on_image_failed: Callable[[StoryNode], Awaitable[None]] = field(default=lambda _node: _noop())
    # Fires once per beat that introduces new characters; the list is the
    # subset of save.characters added by this beat (their portraits may
    # still be generating in the background).
    on_new_characters: Callable[[list[Character]], Awaitable[None]] = field(
        default=lambda _chars: _noop()
    )


class BeatPipeline:
    """Coordinates the 3-stage beat flow: generate, illustrate, render."""

    def __init__(
        self,
        *,
        beat_agent: BeatAgentLike,
        illustration_agent: IllustrationAgentLike,
        summary_agent: SummaryAgentLike | None,
        image_provider: ImageProviderLike,
        callbacks: PipelineCallbacks | None = None,
    ) -> None:
        self._beat = beat_agent
        self._illustration = illustration_agent
        self._summary = summary_agent
        self._image = image_provider
        # ``_callbacks`` is kept as a convenience default for call sites that
        # don't pass per-call callbacks (e.g. tests).  Live picks in
        # ``PlayScreen`` pass an explicit ``PipelineCallbacks`` per ``advance``
        # call rather than mutating this field from outside the class.
        self._callbacks: PipelineCallbacks = callbacks or PipelineCallbacks()
        # Background prefetch tasks keyed by (parent_node_id, choice_id). Each
        # task is `_prefetch_one(...)`, which wraps `advance(...)` with
        # side-effect suppression and silent failure logging. Live-pick advance
        # calls drain matching tasks via `await_prefetched`.
        self._prefetch_tasks: dict[tuple[str, str], asyncio.Task[StoryNode | None]] = {}
        # Dedupe per-key failure logging so a down provider doesn't flood the
        # log on every render. Cleared per-key on a successful prefetch so a
        # recovered provider re-logs the next time it fails.
        self._prefetch_failure_logged: set[tuple[str, str]] = set()
        # Throttle the actual LLM-call phase of in-flight prefetches. See the
        # `_PREFETCH_CONCURRENCY` module-level docstring above.
        self._prefetch_semaphore: asyncio.Semaphore = asyncio.Semaphore(_PREFETCH_CONCURRENCY)

    async def advance(
        self,
        save: GameSave,
        *,
        from_node_id: str,
        choice_id: str,
        skip_image: bool = False,
        suppress_side_effects: bool = False,
        callbacks: PipelineCallbacks | None = None,
    ) -> StoryNode:
        """Advance the story from `from_node_id` by selecting `choice_id`.

        Returns the resulting StoryNode (either from cache or newly created).

        Args:
            skip_image: If True, the illustration plan still runs and is
                recorded on the node, but the background scene-image task is
                NOT spawned. Used by branch prefetch when the user has not
                opted into prefetched images.
            suppress_side_effects: If True, do NOT mutate
                `save.current_node_id`, do NOT append to `save.endings_reached`,
                and do NOT fire UI callbacks. Used by branch prefetch so a
                background generation does not jump the player's cursor or
                refresh the UI mid-read. The new node is still persisted and
                wired into the parent's `child_node_id` so a later live-pick
                cache-hit path can find it. The `await_prefetched` consumer
                fires `on_beat_committed` once the player actually picks the
                prefetched choice.
            callbacks: Per-call UI callbacks.  When omitted, falls back to the
                instance-level ``_callbacks`` (no-op by default).  Pass an
                explicit value from ``PlayScreen._pick`` so the per-pick UI
                handlers are scoped to the call rather than mutated on the
                shared pipeline object.

        Raises:
            ValueError: if `choice_id` is not found on the `from_node_id` node.

        Note on concurrency: callers must serialize live `advance` calls for the
        same (from_node_id, choice_id) pair — typically via PlayScreen's
        `_loading` flag. Two concurrent live calls would each pop+await any
        prefetch task and could fall through to redundant generation if the
        second arrives before the first writes parent.choice.child_node_id.
        Background prefetch (suppress_side_effects=True) is naturally safe via
        the _prefetch_tasks idempotency check in start_prefetch.
        """
        cb = callbacks if callbacks is not None else self._callbacks
        # --- Branch-prefetch fast path ---
        # If a prefetch task is in flight (or already finished) for this exact
        # (parent, choice), prefer its result over double-spending. The task's
        # node is already persisted and the parent's child_node_id wired —
        # below we still set current_node_id and fire on_beat_committed so the
        # live-pick path looks identical to a fresh advance. Suppressed picks
        # (suppress_side_effects=True) skip this; another prefetch wouldn't
        # benefit from awaiting a sibling task it didn't start.
        if not suppress_side_effects:
            prefetched = await self.await_prefetched(
                save, from_node_id=from_node_id, choice_id=choice_id
            )
            if prefetched is not None:
                save.current_node_id = prefetched.id
                save.updated_at = datetime.now(UTC)
                save_game(save)
                await cb.on_beat_committed(prefetched)
                await self._maybe_deferred_illustration(save, prefetched, callbacks=cb)
                return prefetched

        parent = save.nodes[from_node_id]
        choice = next((c for c in parent.choices if c.id == choice_id), None)
        if choice is None:
            raise ValueError(f"choice {choice_id!r} not found on node {from_node_id!r}")

        # --- Cache hit ---
        # Use .get() because the LLM occasionally fills in child_node_id with
        # an invented string (it's an optional field on the Choice schema).
        # Real cache links always point at a node that exists in save.nodes.
        if choice.child_node_id is not None:
            existing = save.nodes.get(choice.child_node_id)
            if existing is not None:
                if not suppress_side_effects:
                    save.current_node_id = existing.id
                    save.updated_at = datetime.now(UTC)
                    save_game(save)
                    await cb.on_beat_committed(existing)
                    await self._maybe_deferred_illustration(save, existing, callbacks=cb)
                return existing
            # Bogus link — clear it so we don't repeatedly hit the same miss
            # and persist the cleanup once we re-write the parent below.
            choice.child_node_id = None

        # --- Stage 1: stream beat ---
        # Allocate the new node id BEFORE the LLM call so the raw-exchange
        # sink (debug-only; see ``_maybe_build_raw_sink``) can write its
        # sidecar file keyed to this id. The id is just a uuid4 — no
        # filesystem or LLM dependency. All downstream code that previously
        # referenced ``new_node_id`` continues to work unchanged.
        new_node_id = uuid.uuid4().hex
        beat_prompt = _build_beat_prompt(save, from_node_id, choice.text)
        narration_cb: Callable[[str], Awaitable[None]] = (
            (lambda _d: _noop()) if suppress_side_effects else cb.on_narration_delta
        )
        beat = await self._beat.run(
            beat_prompt,
            narration_cb,
            raw_sink=self._maybe_build_raw_sink(str(save.id), new_node_id, "beat"),
        )
        # Lift each LLM-side Choice (id + text) to a StoredChoice with no
        # child link. The link is the pipeline's bookkeeping; only we set it.
        stored_choices = [StoredChoice(id=c.id, text=c.text) for c in beat.choices]

        new_characters_ids: list[str] = []
        for new_char in beat.new_characters:
            new_char_with_id = new_char.model_copy(update={"introduced_at_node_id": "pending"})
            save.characters.append(new_char_with_id)
            new_characters_ids.append(new_char_with_id.id)

        for idx, c in enumerate(save.characters):
            if c.id in new_characters_ids and c.introduced_at_node_id == "pending":
                save.characters[idx] = c.model_copy(update={"introduced_at_node_id": new_node_id})

        # Merge relationship updates from the beat.
        if beat.relationship_updates:
            _merge_relationships(save, beat.relationship_updates, new_node_id)

        new_node = StoryNode(
            id=new_node_id,
            parent_id=parent.id,
            chosen_choice_id=choice.id,
            chosen_at=datetime.now(UTC),
            narration=beat.narration,
            choices=stored_choices,
            is_major=beat.is_major,
            is_ending=beat.is_ending,
            image_prompt=None,
            image_path=None,
            image_status="not_planned",
            illustration_reasoning=None,
            featured_character_ids=[],
            summary_to_here=None,
            created_at=datetime.now(UTC),
        )
        save.nodes[new_node_id] = new_node
        # Update the parent choice to point at the new node.
        updated_choices = [
            c.model_copy(update={"child_node_id": new_node_id}) if c.id == choice_id else c
            for c in parent.choices
        ]
        save.nodes[from_node_id] = parent.model_copy(update={"choices": updated_choices})
        if not suppress_side_effects:
            save.current_node_id = new_node_id
            if beat.is_ending:
                save.endings_reached.append(new_node_id)
        save.updated_at = datetime.now(UTC)
        save_game(save)
        if not suppress_side_effects:
            await cb.on_beat_committed(new_node)

            # Notify the UI about new characters so it can surface a "X joined
            # the cast" toast. Their portraits will land asynchronously via
            # _run_stage_2_and_3 below.
            if beat.new_characters:
                added = [c for c in save.characters if c.id in new_characters_ids]
                await cb.on_new_characters(added)

        # --- Stage 2 + 3: illustration planning + background scene ---
        await self._run_stage_2_and_3(
            save, new_node, beat.new_characters, skip_image=skip_image, callbacks=cb
        )

        # --- Summary (optional) ---
        if beat.is_major and self._summary is not None:
            prev_summary, segment = segment_since_last_summary(save, new_node_id)
            parts: list[str] = []
            if prev_summary:
                parts.append("PREVIOUS SUMMARY:\n" + prev_summary)
            if segment:
                beat_texts = "\n\n".join(
                    f"--- Beat {i + 1} ---\n{narration}"
                    for i, narration in enumerate(
                        n.narration for n in segment if n.id != new_node_id
                    )
                    if narration
                )
                if beat_texts:
                    parts.append("BEATS SINCE LAST SUMMARY:\n" + beat_texts)
            parts.append("CURRENT BEAT:\n" + beat.narration)
            summary_input = "\n\n".join(parts)
            try:
                summary = await self._summary.run(
                    summary_input,
                    raw_sink=self._maybe_build_raw_sink(str(save.id), new_node_id, "summary"),
                )
            except Exception:
                logging.getLogger(__name__).warning(
                    "Summary generation failed for node %s; continuing without recap anchor",
                    new_node_id,
                    exc_info=True,
                )
            else:
                updated = save.nodes[new_node_id].model_copy(
                    update={"summary_to_here": summary.text}
                )
                save.nodes[new_node_id] = updated
                save.updated_at = datetime.now(UTC)
                save_game(save)

        return save.nodes[new_node_id]

    def start_prefetch(
        self,
        save: GameSave,
        *,
        from_node_id: str,
        with_images: bool,
    ) -> None:
        """Spawn background tasks to pre-generate every pending choice.

        Idempotent: skips choices whose ``child_node_id`` is already set, AND
        skips choices whose prefetch task is still running. Skips entirely
        when the parent node is missing or terminal (``is_ending``).

        Tasks complete in the background; failures are logged at INFO (deduped
        per ``(parent, choice)`` key so a down provider doesn't flood the log)
        and swallowed — prefetch never surfaces errors to the UI. A live
        ``advance`` for the same ``(parent, choice)`` pair will pick up the
        in-flight task via :meth:`await_prefetched`.
        """
        parent = save.nodes.get(from_node_id)
        if parent is None or parent.is_ending:
            return
        for choice in parent.choices:
            if choice.child_node_id is not None:
                continue  # already cached
            key = (from_node_id, choice.id)
            existing = self._prefetch_tasks.get(key)
            if existing is not None and not existing.done():
                continue
            task: asyncio.Task[StoryNode | None] = asyncio.create_task(
                self._prefetch_one(save, from_node_id, choice.id, with_images)
            )
            self._prefetch_tasks[key] = task

    async def _prefetch_one(
        self,
        save: GameSave,
        parent_id: str,
        choice_id: str,
        with_images: bool,
    ) -> StoryNode | None:
        """Wrap :meth:`advance` with side-effect suppression + silent failure.

        Returns the generated node on success, or ``None`` on failure (the
        consumer in :meth:`await_prefetched` then returns ``None`` and the
        caller falls through to a fresh ``advance``).
        """
        key = (parent_id, choice_id)
        # Gate the LLM-call phase behind the semaphore. Tasks still spawn
        # immediately (so start_prefetch's idempotency dict is populated) and
        # just queue here until a slot frees up.
        async with self._prefetch_semaphore:
            try:
                result = await self.advance(
                    save,
                    from_node_id=parent_id,
                    choice_id=choice_id,
                    skip_image=not with_images,
                    suppress_side_effects=True,
                )
            except Exception as exc:
                # Silent failure is the contract — prefetch must NEVER surface
                # errors to the UI; the caller falls through to a normal
                # advance. Dedupe per-key so a persistently-down provider
                # doesn't flood the log on every render.
                if key not in self._prefetch_failure_logged:
                    self._prefetch_failure_logged.add(key)
                    logging.getLogger(__name__).info(
                        "prefetch failed for (%s, %s): %s", parent_id, choice_id, exc
                    )
                return None
            # Recovered (or first-time success) — clear any prior failure
            # record for this key so the next failure for the same (parent,
            # choice) logs again instead of being silently deduped.
            self._prefetch_failure_logged.discard(key)
            return result

    async def await_prefetched(
        self,
        save: GameSave,
        *,
        from_node_id: str,
        choice_id: str,
    ) -> StoryNode | None:
        """Await any in-flight prefetch task for ``(parent, choice)``.

        Returns the StoryNode on success, ``None`` on failure or when no
        task exists. Removes the task from the registry either way so a
        second concurrent caller falls through to the normal generate path
        (where the cache-hit logic catches the just-persisted node).
        """
        key = (from_node_id, choice_id)
        task = self._prefetch_tasks.pop(key, None)
        if task is None:
            return None
        try:
            return await task
        except Exception:
            # _prefetch_one already swallows; defense in depth in case the
            # task was cancelled or otherwise raised outside _prefetch_one.
            return None

    async def cancel_all_prefetches(self) -> None:
        """Cancel any in-flight prefetch tasks and await their cleanup.

        Call from app shutdown to avoid mid-``save_game`` cancellation. Safe to
        call when no prefetches are in flight (no-op).
        """
        tasks = list(self._prefetch_tasks.values())
        self._prefetch_tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        # Allow cancellations to propagate; swallow CancelledError + any other
        # exception per-task so one stuck task doesn't abort cleanup of the
        # others.
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    def _maybe_build_raw_sink(
        self, save_id: str, node_id: str, agent_name: str
    ) -> Callable[[bytes], None] | None:
        """Return a raw-exchange dumper closure, or None when the flag is off.

        Called at every agent-call site. Builds a per-call closure keyed to
        (``node_id``, ``agent_name``) so concurrent calls (e.g. prefetch
        racing a live pick on sibling choices) don't collide. The flag is
        re-read on every call so toggling ``app_state.llm_cache_enabled``
        takes effect on the next pipeline action without restart.
        """
        if not app_state.llm_cache_enabled():
            return None

        def _sink(raw_bytes: bytes) -> None:
            dump_llm_exchange(save_id, node_id, agent_name, raw_bytes)

        return _sink

    async def retry_scene(
        self,
        save: GameSave,
        *,
        node_id: str,
        callbacks: PipelineCallbacks | None = None,
    ) -> StoryNode:
        """Regenerate the scene image for `node_id` using its stored image_prompt.

        Honors `app_state.image_streaming_enabled()` for OpenAI providers so
        retries get the same partial-preview UX (and the same per-partial
        surcharge) as live `_stage_3_scene` calls.

        Args:
            callbacks: Per-call UI callbacks.  When omitted, falls back to the
                instance-level ``_callbacks`` (no-op by default).

        Raises:
            ValueError: if the node has no stored image_prompt to retry from.
        """
        cb = callbacks if callbacks is not None else self._callbacks
        node = save.nodes[node_id]
        if not node.image_prompt:
            raise ValueError("node has no image_prompt to retry")
        if not app_state.art_enabled():
            # Art disabled globally — silently skip without mutating status.
            return node

        save_id = str(save.id)
        dest = paths.node_image_path(save_id, node_id)
        rel_path = str(dest.relative_to(paths.game_dir(save_id)))
        # Pre-assign image_path and status so partial writes have a known target.
        # Mirrors _stage_3_scene's pre-assignment pattern.
        updated = node.model_copy(update={"image_status": "generating", "image_path": rel_path})
        save.nodes[node_id] = updated
        save_game(save)

        return await self._render_scene(
            save, node_id, node.image_prompt, list(node.featured_character_ids), cb=cb
        )

    async def edit_scene(
        self,
        save: GameSave,
        *,
        node_id: str,
        new_prompt: str,
        current_image_as_ref: bool = True,
        callbacks: PipelineCallbacks | None = None,
    ) -> StoryNode:
        """Regenerate the scene image with a modified prompt.

        Like :meth:`retry_scene` but accepts a new prompt and optionally uses
        the current scene image as an additional reference for the provider.

        Args:
            new_prompt: The replacement image prompt.
            current_image_as_ref: If True, read the current image from disk and
                prepend it to the reference portraits list.
            callbacks: Per-call UI callbacks.
        """
        cb = callbacks if callbacks is not None else self._callbacks
        node = save.nodes[node_id]
        if not app_state.art_enabled():
            return node

        save_id = str(save.id)
        dest = paths.node_image_path(save_id, node_id)
        rel_path = str(dest.relative_to(paths.game_dir(save_id)))

        # Update the stored prompt before rendering.
        updated = node.model_copy(
            update={
                "image_prompt": new_prompt,
                "image_status": "generating",
                "image_path": rel_path,
            }
        )
        save.nodes[node_id] = updated
        save_game(save)

        return await self._render_scene(
            save,
            node_id,
            new_prompt,
            list(node.featured_character_ids),
            cb=cb,
            current_image_as_ref=current_image_as_ref,
        )

    async def _run_stage_2_and_3(
        self,
        save: GameSave,
        node: StoryNode,
        new_characters: list[Character],
        *,
        skip_image: bool = False,
        callbacks: PipelineCallbacks | None = None,
    ) -> None:
        """Run illustration planning (Stage 2) concurrently with portrait generation.

        If should_illustrate, launch scene generation as a background task (Stage 3).

        When ``skip_image`` is True, the illustration plan is still recorded
        (so a later manual ``i`` retry has a stored image_prompt to work
        with), but the actual scene-generation task is NOT spawned. The node
        keeps its initial ``image_status="not_planned"``.
        """
        cb = callbacks if callbacks is not None else self._callbacks
        if not app_state.art_enabled():
            # Image generation disabled app-wide. Skip the illustration agent
            # call (saves tokens) and any portrait generation; leave the node's
            # image_* fields at their initial "not_planned" defaults.
            return
        portrait_task = asyncio.create_task(self._portraits(save, new_characters))
        try:
            plan = await self._illustration.run(
                StoryBeat(
                    narration=node.narration,
                    choices=[Choice(id=c.id, text=c.text) for c in node.choices],
                    is_major=node.is_major,
                    is_ending=node.is_ending,
                    new_characters=[],
                ),
                save.characters,
                raw_sink=self._maybe_build_raw_sink(str(save.id), node.id, "illustration"),
            )
        finally:
            await portrait_task

        updated = save.nodes[node.id].model_copy(
            update={
                "image_prompt": plan.image_prompt or None,
                "illustration_reasoning": plan.reasoning,
                "featured_character_ids": plan.featured_character_ids,
            }
        )
        save.nodes[node.id] = updated
        save_game(save)

        if not plan.should_illustrate:
            return

        if skip_image:
            # Illustration plan is recorded above; intentionally do NOT mark
            # image_status="generating" or spawn the background task. The
            # node stays "not_planned" with a stored image_prompt so a later
            # manual `i` retry (or the player re-visiting the node) can
            # generate the image on demand.
            return

        updated = save.nodes[node.id].model_copy(update={"image_status": "generating"})
        save.nodes[node.id] = updated
        save_game(save)

        task: asyncio.Task[None] = asyncio.create_task(
            self._stage_3_scene(save, node.id, plan, callbacks=cb)
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    async def _maybe_deferred_illustration(
        self,
        save: GameSave,
        node: StoryNode,
        *,
        callbacks: PipelineCallbacks | None = None,
    ) -> None:
        """If *node* has an illustration plan but no image, generate it now.

        Handles the case where a node was prefetched with ``skip_image=True``
        (so the illustration agent ran and saved a prompt, but image generation
        was deferred).  When the player later picks that cached choice, this
        method kicks off the scene render so the node gets its image.
        """
        if not app_state.art_enabled():
            return
        if node.image_status != "not_planned" or not node.image_prompt:
            return
        plan = IllustrationPlan(
            should_illustrate=True,
            image_prompt=node.image_prompt,
            featured_character_ids=node.featured_character_ids,
            reasoning=node.illustration_reasoning or "",
        )
        updated = node.model_copy(update={"image_status": "generating"})
        save.nodes[node.id] = updated
        save_game(save)
        cb = callbacks if callbacks is not None else self._callbacks
        task: asyncio.Task[None] = asyncio.create_task(
            self._stage_3_scene(save, node.id, plan, callbacks=cb)
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    async def _portraits(self, save: GameSave, new_characters: list[Character]) -> None:
        """Generate reference portraits for newly introduced characters.

        Mid-story characters are persisted with the same shape as wizard-time
        characters: portrait_path + portrait_prompt + introduced_at_node_id.
        Saving portrait_prompt lets PortraitsScreen regenerate them later
        with the same description rather than blanking the field. The roster
        in `_build_beat_prompt` already pulls every save.characters entry
        into subsequent beats' CAST section, and `_stage_3_scene` already
        looks up portrait_path via featured_character_ids — so once we land
        these on disk, downstream beats keep the new characters visually
        consistent automatically.

        Failures on one portrait don't block the others; a missing
        portrait_path just means future scene-gen calls won't have a
        reference image for that character (the character still appears
        in the prompt cast roster).
        """
        if not app_state.art_enabled() or not new_characters:
            return
        save_id = str(save.id)
        for char in new_characters:
            try:
                portrait_bytes = await self._image.generate_portrait(
                    char.physical_description,
                    transparent=True,
                    art_style=save.art_style,
                )
            except Exception:
                # Skip this character; leave portrait_path empty. The next
                # PortraitsScreen open will let the user retry.
                continue
            save.total_image_cost_usd += image_cost(
                save.character_image_config.provider,
                model=save.character_image_config.model,
                size=PORTRAIT_SIZE,
                quality=PORTRAIT_QUALITY,
            )
            # First portrait for a character is always v1; PortraitsScreen
            # uses next_portrait_version for subsequent regenerations.
            dest = paths.character_portrait_path(save_id, char.id, version=1)
            _atomic_write_png(dest, portrait_bytes)
            rel_path = str(dest.relative_to(paths.game_dir(save_id)))
            for idx, c in enumerate(save.characters):
                if c.id == char.id:
                    save.characters[idx] = c.model_copy(
                        update={
                            "portrait_path": rel_path,
                            # Mirror the wizard so PortraitsScreen regenerate
                            # has a stable prompt source (the original
                            # physical_description as written by the LLM).
                            "portrait_prompt": char.physical_description,
                        }
                    )
        save_game(save)

    async def _render_scene(
        self,
        save: GameSave,
        node_id: str,
        image_prompt: str,
        featured_character_ids: list[str],
        *,
        cb: PipelineCallbacks,
        current_image_as_ref: bool = False,
    ) -> StoryNode:
        """Stream a scene image to disk and fire UI callbacks; return final node.

        Shared implementation for :meth:`retry_scene`, :meth:`edit_scene`, and
        :meth:`_stage_3_scene`. Both callers must pre-assign ``image_path``
        (and optionally ``image_status``) before calling this method.

        On success: sets ``image_status="done"`` and fires ``on_image_committed``.
        On failure: sets ``image_status="failed"`` and fires ``on_image_failed``.
        """
        save_id = str(save.id)
        dest = paths.node_image_path(save_id, node_id)
        rel_path = str(dest.relative_to(paths.game_dir(save_id)))

        stream_partials = (
            app_state.image_streaming_enabled() and save.image_config.provider == "openai"
        )

        async def _on_partial(partial_bytes: bytes) -> None:
            _atomic_write_png(dest, partial_bytes)
            await cb.on_image_committed(save.nodes[node_id])

        try:
            refs: list[ReferencePortrait] = []
            # Optionally prepend the current scene image as the first reference.
            if current_image_as_ref:
                cur_node = save.nodes[node_id]
                if cur_node.image_path:
                    try:
                        cur_path = paths.safe_join(paths.game_dir(save_id), cur_node.image_path)
                        if cur_path.exists():
                            refs.append(
                                ReferencePortrait("current scene artwork", cur_path.read_bytes())
                            )
                    except ValueError:
                        pass
            # Reserve slots for character portraits (OpenAI images.edit allows ≤16).
            max_char_refs = 16 - len(refs)
            for cid in featured_character_ids[:max_char_refs]:
                for c in save.characters:
                    if c.id == cid and c.portrait_path:
                        try:
                            ref_path = paths.safe_join(paths.game_dir(save_id), c.portrait_path)
                            refs.append(ReferencePortrait(c.name, ref_path.read_bytes()))
                        except ValueError:
                            pass
            scene_bytes = await self._image.generate_scene(
                image_prompt,
                reference_portraits=refs,
                art_style=save.art_style,
                on_partial=_on_partial if stream_partials else None,
            )
            _atomic_write_png(dest, scene_bytes)
            save.total_image_cost_usd += image_cost(
                save.image_config.provider,
                model=save.image_config.model,
                size=SCENE_SIZE,
                quality=SCENE_QUALITY,
                num_input_refs=len(refs),
                partial_images=OPENAI_PARTIAL_IMAGES if stream_partials else 0,
            )
            done = save.nodes[node_id].model_copy(
                update={
                    "image_status": "done",
                    "image_path": rel_path,
                }
            )
            save.nodes[node_id] = done
            save_game(save)
            await cb.on_image_committed(done)
            return done
        except Exception:
            failed = save.nodes[node_id].model_copy(update={"image_status": "failed"})
            save.nodes[node_id] = failed
            save_game(save)
            await cb.on_image_failed(failed)
            return failed

    async def _stage_3_scene(
        self,
        save: GameSave,
        node_id: str,
        plan: IllustrationPlan,
        *,
        callbacks: PipelineCallbacks | None = None,
    ) -> None:
        """Generate a scene image for the node and persist it.

        When OpenAI streaming is enabled (``app_state.image_streaming_enabled``
        AND ``save.image_config.provider == "openai"``) we wire an
        ``on_partial`` callback that writes each intermediate preview to
        ``node.image_path`` atomically and re-fires ``on_image_committed`` so
        the PlayScreen re-renders as the image sharpens. ``image_path`` is
        pre-assigned BEFORE the call so PlayScreen's renderer (which reads
        ``image_path`` from the node) can find the partial bytes on disk.
        """
        cb = callbacks if callbacks is not None else self._callbacks
        save_id = str(save.id)
        dest = paths.node_image_path(save_id, node_id)
        rel_path = str(dest.relative_to(paths.game_dir(save_id)))
        # Pre-assign image_path so partial writes have a known target; status
        # stays "generating" until the final lands.
        pre = save.nodes[node_id].model_copy(update={"image_path": rel_path})
        save.nodes[node_id] = pre
        save_game(save)

        await self._render_scene(
            save, node_id, plan.image_prompt, list(plan.featured_character_ids), cb=cb
        )


# --- Beat prompt construction --------------------------------------------------


def _merge_relationships(save: GameSave, updates: list[Relationship], node_id: str) -> None:
    """Merge relationship deltas from a beat into the save's relationship list."""
    for update in updates:
        key = (update.char_a_id, update.char_b_id)
        existing = next(
            (r for r in save.relationships if (r.char_a_id, r.char_b_id) == key),
            None,
        )
        if existing is not None:
            save.relationships.remove(existing)
        save.relationships.append(update.model_copy(update={"updated_at_node_id": node_id}))


def _build_beat_prompt(save: GameSave, from_node_id: str, choice_text: str) -> str:
    """Compose the user-side prompt sent to the beat agent.

    Includes:
      - Cast roster (names + brief descriptions) so the model doesn't drift
        on character traits or invent new ones.
      - The last major beat's accumulated summary (if any).
      - Full narration of all beats since that major beat, in order.
      - The choice the player just made.
    """
    sections: list[str] = []

    # Cast - one-liner for quick ID plus full backstory so the beat agent
    # can naturally reference character history and relationships.
    if save.characters:
        cast_lines: list[str] = []
        for c in save.characters:
            line = (
                f"- [{c.id}] {c.name}: {_one_sentence(c.personality)}"
                + (f" {_one_sentence(c.backstory_summary)}" if c.backstory_summary else "")
                + f" ({_one_sentence(c.physical_description)})"
            )
            if c.backstory:
                line += f"\n  Backstory: {c.backstory}"
            cast_lines.append(line)
        sections.append("CAST:\n" + "\n".join(cast_lines))

    if save.relationships:
        char_names = {c.id: c.name for c in save.characters}
        name_to_id = {c.name: c.id for c in save.characters}

        def _resolve(key: str) -> str:
            if key in char_names:
                return char_names[key]
            return key  # already a name or unknown

        known = set(char_names) | set(name_to_id)
        rel_lines = [
            f"- {_resolve(r.char_a_id)} ↔ {_resolve(r.char_b_id)}:"
            f" {r.type.value} (strength {r.strength}) — {r.context}"
            for r in save.relationships
            if r.char_a_id in known and r.char_b_id in known
        ]
        if rel_lines:
            sections.append("RELATIONSHIPS:\n" + "\n".join(rel_lines))

    prev_summary, segment = segment_since_last_summary(save, from_node_id)
    if prev_summary:
        sections.append(f"STORY-SO-FAR SUMMARY:\n{prev_summary}")

    if segment:
        beat_lines: list[str] = []
        for node in segment:
            chosen = _resolve_chosen_text(save, node)
            line = f"- {node.narration}"
            if chosen:
                line += f"\n  -> player chose: {chosen}"
            beat_lines.append(line)
        sections.append("BEATS SINCE LAST SUMMARY:\n" + "\n".join(beat_lines))

    sections.append(f"PLAYER JUST CHOSE: {choice_text}")

    # Pacing is measured in MAJOR beats so far (the unit target_major_beats
    # is denominated in), not total beats. Count across the full ancestor path.
    full_chain = path_from_root(save, from_node_id)
    major_so_far = sum(1 for n in full_chain if n.is_major)
    pacing_hint = _pacing_hint_for_depth(major_so_far, save.target_major_beats, save.pacing)
    if pacing_hint:
        sections.append(pacing_hint.strip())
    return "\n\n".join(sections)


def _pacing_hint_for_depth(depth: int, target: int, pacing: str = "moderate") -> str:
    """Encourage the model to wind down rather than meander indefinitely.

    Uses ratios of the per-save ``target`` so very short stories don't get a
    "tighten" prod at beat 5 of 5 and very long stories don't get told to
    "resolve now" at beat 11 of 30.
    """
    multiplier = {"slow": 1.4, "fast": 0.7}.get(pacing, 1.0)
    silent_threshold = max(int(target * 0.3 * multiplier), 1)
    tension_threshold = max(int(target * 0.6 * multiplier), 1)
    climax_threshold = max(int(target * 0.9 * multiplier), 1)
    if depth <= silent_threshold:
        return ""
    if depth <= tension_threshold:
        return f" This will be beat #{depth + 1}; keep tension rising."
    if depth <= climax_threshold:
        return (
            f" This will be beat #{depth + 1}; start tightening toward a"
            " climax — set up the resolution rather than introducing new"
            " unrelated mysteries."
        )
    return (
        f" This will be beat #{depth + 1}; the story has run long. Strongly"
        " consider resolving the central conflict in this beat or the next."
        " Set is_ending=true once the resolution lands."
    )


def _resolve_chosen_text(save: GameSave, node: StoryNode) -> str:
    """Look up the player-facing text of the choice that led to ``node``."""
    if node.chosen_choice_id is None or node.parent_id is None:
        return ""
    parent = save.nodes.get(node.parent_id)
    if parent is None:
        return ""
    for c in parent.choices:
        if c.id == node.chosen_choice_id:
            return c.text
    return ""
