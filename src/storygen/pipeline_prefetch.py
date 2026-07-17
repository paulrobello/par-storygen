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

ENH-006-T2 added optional TTS audio pregeneration: after a prefetched node
commits, the coordinator can speculatively synthesize its narration into the
per-node cache so picking the choice plays instantly. The synth runs OUTSIDE
the LLM-concurrency semaphore (a slow TTS call would otherwise serialize
prefetch waves) but still INSIDE this task's try/except so a synth failure is
swallowed like any other prefetch failure. A per-node lock in
:mod:`storygen.tts.cache` collapses the same-node race with PlayScreen's
on-demand speak path into exactly one provider call.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from storygen.core.models import StoryNode
from storygen.storage import app_state
from storygen.storage.save import GameSave, save_game
from storygen.tts.cache import relative_tts_cache_path, synthesize_to_cache
from storygen.tts.player import TTSPlayer

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
        tts_player: TTSPlayer | None = None,
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
        # ENH-006-T2: optional TTS pregeneration. ``None`` (or an unconfigured
        # player) short-circuits the synth step. The player is shared with
        # PlayScreen; ``synthesize_to_cache`` only calls the state-safe
        # ``generate()`` (never ``speak()`` / ``configure()``) so it cannot
        # disturb active playback.
        self._tts_player = tts_player

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

        On success, optionally pre-synthesizes the node's TTS audio when the
        user has enabled ``TTSPrefs.pregenerate_prefetch_audio`` and a
        configured player is wired in. The synth runs OUTSIDE the LLM-call
        semaphore (it would otherwise hold an LLM-concurrency slot during a
        slow TTS call and serialize prefetch waves). A synth failure is
        swallowed like any other prefetch failure (debug-log only); the node
        itself is unaffected.
        """
        key = (parent_id, choice_id)
        # Gate the LLM-call phase behind the semaphore. Tasks still spawn
        # immediately (so ``start``'s idempotency dict is populated) and queue
        # here until a slot frees up. The block exits before TTS synth so a
        # slow TTS call doesn't pin an LLM-concurrency slot.
        try:
            async with self._semaphore:
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

        # ENH-006-T2: speculative TTS synth. Runs after the node has committed
        # (so ``node.id`` / ``node.narration`` are durable) and outside the
        # semaphore. The per-node lock in ``synthesize_to_cache`` collapses
        # the same-node race with PlayScreen's on-demand speak path. Any
        # failure here is swallowed — the prefetch itself already succeeded;
        # a missed audio synth just means the user hears a brief generate
        # delay on pick.
        await self._maybe_pregenerate_tts(save, result)
        return result

    async def _maybe_pregenerate_tts(self, save: GameSave, node: StoryNode) -> None:
        """Synthesize ``node.narration`` into the cache when the user has opted in.

        Skipped silently when: TTS pregeneration is OFF, no player is wired in,
        the player isn't configured, or the node has no narration. All errors
        are caught and logged at debug — prefetch never surfaces failures.
        """
        player = self._tts_player
        if player is None or not player.is_configured or not node.narration:
            return
        tts_prefs = app_state.read_tts_prefs()
        if not tts_prefs.pregenerate_prefetch_audio:
            return
        game_id = str(save.id)
        try:
            cache_path = await synthesize_to_cache(
                player, game_id, node.id, node.narration, tts_prefs
            )
        except Exception as exc:
            # Don't fail the prefetch — the node is already persisted; this
            # only means the user will hear a synth delay on pick.
            _logger.debug(
                "TTS pregeneration failed for node %s: %s", node.id, exc
            )
            return
        if cache_path is None:
            _logger.debug("TTS pregeneration skipped (synth returned None) for node %s", node.id)
            return
        relative = relative_tts_cache_path(player, node.id, tts_prefs)
        if node.tts_audio_path != relative:
            node.tts_audio_path = relative
            # Persist the path so a subsequent pick finds the audio without a
            # re-synth. Wrapped so a save failure never propagates into the
            # prefetch caller.
            try:
                save_game(save)
            except Exception as exc:
                _logger.debug("persisting tts_audio_path for %s failed: %s", node.id, exc)

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
