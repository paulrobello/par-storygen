"""Background prefetch coordinator extracted from :mod:`storygen.pipeline` (ARC-011).

``PrefetchCoordinator`` owns the branch-prefetch lifecycle: the in-flight task
registry, the per-key failure-log dedup set, and the LLM-call concurrency
semaphore. It wraps a node-generation callable — :meth:`BeatPipeline.advance`
invoked with ``suppress_side_effects=True`` — so a background generation reuses
the exact advance path without jumping the player's cursor or refreshing the UI
mid-read.

Recursion is bounded by ``advance``'s ``suppress_side_effects`` guard: a
prefetch calls ``advance(suppress=True)``, which skips the fast path that would
otherwise await a sibling prefetch task.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from storygen.llm.models import StoryNode
from storygen.storage.save import GameSave

_logger = logging.getLogger(__name__)

# Cap on the number of in-flight prefetch LLM calls. At typical 2-4 choices per
# node a single prefetch wave fits unthrottled, but rapid back-and-forth
# navigation (or wide branching) could otherwise stack tasks faster than they
# complete. The semaphore is per-BeatPipeline — one game session — so each save
# gets its own budget. The full task set still spawns immediately so the task
# registry's idempotency keys remain dense; the cap only gates the LLM call
# inside ``_prefetch_one``.
_PREFETCH_CONCURRENCY: int = 3


class PrefetchCoordinator:
    """Background prefetch lifecycle for :class:`storygen.pipeline.BeatPipeline`.

    Each task wraps ``advance`` invoked with ``suppress_side_effects=True`` so a
    background generation reuses the exact advance path without jumping the
    player's cursor or refreshing the UI mid-read. Concurrency and
    failure-logging semantics are unchanged from the pre-extraction code.
    """

    def __init__(
        self,
        advance: Callable[..., Awaitable[StoryNode]],
        *,
        concurrency: int = _PREFETCH_CONCURRENCY,
    ) -> None:
        self._advance = advance
        # Tasks keyed by (parent_node_id, choice_id). Each is ``_prefetch_one``,
        # which wraps ``advance(...)`` with side-effect suppression and silent
        # failure logging. Live-pick advance calls drain a matching task via
        # ``await_one``.
        self._tasks: dict[tuple[str, str], asyncio.Task[StoryNode | None]] = {}
        # Dedupe per-key failure logging so a down provider doesn't flood the
        # log on every render. Cleared per-key on a successful prefetch so a
        # recovered provider re-logs the next time it fails.
        self._failure_logged: set[tuple[str, str]] = set()
        # Throttle the LLM-call phase of in-flight prefetches. See the
        # ``_PREFETCH_CONCURRENCY`` module-level docstring above.
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(concurrency)

    def start(
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
        ``advance`` for the same ``(parent, choice)`` pair picks up the
        in-flight task via :meth:`await_one`.
        """
        parent = save.nodes.get(from_node_id)
        if parent is None or parent.is_ending:
            return
        for choice in parent.choices:
            if choice.child_node_id is not None:
                continue  # already cached
            key = (from_node_id, choice.id)
            existing = self._tasks.get(key)
            if existing is not None and not existing.done():
                continue
            task: asyncio.Task[StoryNode | None] = asyncio.create_task(
                self._prefetch_one(save, from_node_id, choice.id, with_images)
            )
            self._tasks[key] = task

    async def _prefetch_one(
        self,
        save: GameSave,
        parent_id: str,
        choice_id: str,
        with_images: bool,
    ) -> StoryNode | None:
        """Wrap :meth:`BeatPipeline.advance` with suppression + silent failure.

        Returns the generated node on success, or ``None`` on failure (the
        consumer in :meth:`await_one` then returns ``None`` and the caller
        falls through to a fresh ``advance``).
        """
        key = (parent_id, choice_id)
        # Gate the LLM-call phase behind the semaphore. Tasks still spawn
        # immediately (so ``start``'s idempotency dict is populated) and queue
        # here until a slot frees up.
        async with self._semaphore:
            try:
                result = await self._advance(
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
                if key not in self._failure_logged:
                    self._failure_logged.add(key)
                    _logger.info(
                        "prefetch failed for (%s, %s): %s", parent_id, choice_id, exc
                    )
                return None
            # Recovered (or first-time success) — clear any prior failure
            # record for this key so the next failure logs again instead of
            # being silently deduped.
            self._failure_logged.discard(key)
            return result

    async def await_one(
        self,
        save: GameSave,
        *,
        from_node_id: str,
        choice_id: str,
    ) -> StoryNode | None:
        """Await any in-flight prefetch task for ``(parent, choice)``.

        Returns the StoryNode on success, ``None`` on failure or when no task
        exists. Removes the task from the registry either way so a second
        concurrent caller falls through to the normal generate path (where the
        cache-hit logic catches the just-persisted node).
        """
        key = (from_node_id, choice_id)
        task = self._tasks.pop(key, None)
        if task is None:
            return None
        try:
            return await task
        except Exception:
            # ``_prefetch_one`` already swallows + dedup-logs the normal
            # failure path; reaching here means the task was cancelled or
            # raised outside ``_prefetch_one``'s try/except (e.g. during await
            # cleanup). Warning rather than info because this branch is
            # exceptional and the per-key dedup log does not cover it.
            _logger.warning(
                "prefetch await raised for (%s, %s); falling through to normal advance",
                from_node_id,
                choice_id,
                exc_info=True,
            )
            return None

    async def cancel_all(self) -> None:
        """Cancel any in-flight prefetch tasks and await their cleanup.

        Call from app shutdown to avoid mid-``save_game`` cancellation. Safe
        to call when no prefetches are in flight (no-op).
        """
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        # Allow cancellations to propagate; swallow CancelledError + any other
        # exception per-task so one stuck task doesn't abort cleanup of the
        # others.
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
