"""Regression tests for ARC-101 / ARC-102 / ARC-106 / ARC-103.

ARC-101: stale-save closure aliasing — ``get_or_load_save`` must return the
same ``GameSave`` object across calls so the pipeline's ``_on_usage`` closure
(captured at construction time) records usage on the object that subsequent
advances mutate and persist.

ARC-102: per-game advance serialization — two concurrent advances must be
serialized by the per-game ``asyncio.Lock`` so both children land in the tree.

ARC-106: idle-session eviction — ``evict_idle`` clears idle pipeline/save/lock
entries and a subsequent ``get_or_load_save`` transparently reloads from disk.

ARC-103: settings update invalidates ``get_app_config``'s ``lru_cache``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from storygen.core.models import (
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.llm.usage import record_usage_on_save
from storygen.storage.save import GameSave, load_game, save_game
from storygen_api.session import PipelineSessionManager

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_save(xdg_tmp: Any) -> tuple[GameSave, str]:
    """Build a minimal save with a root node offering two choices.

    Returns (save, game_id_hex). The save is persisted to disk under the
    xdg_tmp-isolated XDG_DATA_HOME.
    """
    root = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="You stand at a fork in the road.",
        choices=[
            StoredChoice(id="c1", text="Take the left path"),
            StoredChoice(id="c2", text="Take the right path"),
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
        version=4,
        id=uuid4(),
        theme=Theme(title="T", setting="S", premise="P", keywords=[]),
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
    return save, str(save.id)


class _Usage:
    """Minimal stand-in for pydantic-ai's RunUsage (getattr-read by record_usage_on_save)."""

    def __init__(self, input_tokens: int = 10, output_tokens: int = 20) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.requests = 1


class _UsageRecordingStub:
    """Stub BeatPipeline mirroring deps.build_pipeline's _on_usage closure.

    The closure captures the construction-time save. ARC-101: with
    ``get_or_load_save``, the save passed to ``advance`` IS the construction
    save, so usage recording + node mutation land on the same object.
    """

    def __init__(self, construction_save: GameSave) -> None:
        self._construction_save = construction_save
        self.advance_count = 0

    async def advance(
        self,
        save: Any,
        *,
        from_node_id: str,
        choice_id: str,
        skip_image: bool = False,
        suppress_side_effects: bool = False,
        callbacks: Any = None,
    ) -> StoryNode:
        del skip_image, suppress_side_effects, callbacks
        self.advance_count += 1
        new_node_id = f"child-{choice_id}-{self.advance_count}"
        new_node = StoryNode(
            id=new_node_id,
            parent_id=from_node_id,
            chosen_choice_id=choice_id,
            chosen_at=datetime.now(UTC),
            narration=f"Child {self.advance_count}.",
            choices=[StoredChoice(id=f"next-{self.advance_count}", text="continue")],
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
        # Wire child into parent (mirrors real pipeline behavior on the save
        # object passed to advance).
        parent = save.nodes.get(from_node_id)
        if parent is not None:
            updated_choices = [
                c.model_copy(update={"child_node_id": new_node_id}) if c.id == choice_id else c
                for c in parent.choices
            ]
            save.nodes[from_node_id] = parent.model_copy(update={"choices": updated_choices})
        save.nodes[new_node_id] = new_node
        save.current_node_id = new_node_id

        # deps.build_pipeline's _on_usage closure records on the CONSTRUCTION
        # save and persists it. ARC-101: with get_or_load_save, save IS
        # self._construction_save, so this is correct. Pre-fix (load_game +
        # reload), they diverged and usage was lost.
        record_usage_on_save(self._construction_save, model="gpt-4o-mini", usage=_Usage())
        save_game(self._construction_save)
        return new_node

    async def cancel_all_prefetches(self) -> None:
        return None


# ---------------------------------------------------------------------------
# ARC-101: stale-save closure aliasing
# ---------------------------------------------------------------------------


def test_arc101_get_or_load_save_returns_cached_object(xdg_tmp: Any) -> None:
    """ARC-101 contract: repeated get_or_load_save returns the SAME object.

    This is the object-identity guarantee that makes the pipeline's _on_usage
    closure correct: the save captured at construction and the save passed to
    every subsequent advance are the same instance.
    """
    _save, game_id = _make_save(xdg_tmp)
    mgr = PipelineSessionManager()

    save_first = mgr.get_or_load_save(game_id)
    save_second = mgr.get_or_load_save(game_id)
    assert save_first is save_second, (
        "get_or_load_save must return the cached instance, not a fresh load"
    )


def test_arc101_usage_accumulates_across_two_api_advances(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ARC-101 regression: two advances through the REST API accumulate usage.

    Before ARC-101 the advance endpoint reloaded the save after each advance
    (``save = load_game(game_id)``), creating a second GameSave instance. The
    pipeline's _on_usage closure still pointed at the first instance, so usage
    from the second advance was recorded on the orphaned first save and lost
    when it went out of scope. With get_or_load_save the owned save is the
    same object across both advances, so usage accumulates correctly and
    persists to game.json.
    """
    _save, game_id = _make_save(xdg_tmp)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("STORYGEN_API_TOKEN", "arc101-token")
    from storygen_api.security import reset_token_cache

    reset_token_cache()

    from storygen_api.deps import get_session_manager
    from storygen_api.routers import games as games_router

    mgr = get_session_manager()
    # Clean any prior registration for this game (test isolation).
    import asyncio as _asyncio

    _asyncio.run(mgr.cleanup(game_id))

    owned_save = mgr.get_or_load_save(game_id)
    stub = _UsageRecordingStub(owned_save)
    mgr.get_or_create(game_id, owned_save, stub)  # type: ignore[arg-type]
    # Defense-in-depth: if the registry is reset, build_pipeline returns the stub.
    monkeypatch.setattr(games_router, "build_pipeline", lambda *a, **kw: (stub, None))  # type: ignore[arg-type]

    from storygen_api.main import create_app

    app = create_app()
    headers = {"Authorization": "Bearer arc101-token"}
    with TestClient(app) as client:
        # First advance: pick c1 from root.
        r1 = client.post(
            f"/api/games/{game_id}/advance",
            json={"from_node_id": "root", "choice_id": "c1"},
            headers=headers,
        )
        assert r1.status_code == 200, r1.text
        node1 = r1.json()["node"]

        # Second advance: pick the child's "next" choice.
        r2 = client.post(
            f"/api/games/{game_id}/advance",
            json={"from_node_id": node1["id"], "choice_id": "next-1"},
            headers=headers,
        )
        assert r2.status_code == 200, r2.text

    # The persisted game.json must reflect BOTH advances' usage. Each
    # _Usage() stub records 1 request, so text_total_requests must be 2.
    reloaded = load_game(game_id)
    assert reloaded.text_total_requests == 2, (
        f"expected 2 text_total_requests (one per advance), "
        f"got {reloaded.text_total_requests} — usage from an advance was lost"
    )

    # Cleanup the stub registration.
    _asyncio.run(mgr.cleanup(game_id))
    reset_token_cache()


# ---------------------------------------------------------------------------
# ARC-102: per-game advance serialization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arc102_advance_lock_serializes_concurrent_advances(xdg_tmp: Any) -> None:
    """ARC-102: two concurrent advances are serialized by advance_lock.

    Without the lock, concurrent dict mutations on the shared save can lose a
    child node. With the lock, one advance fully completes before the other
    starts, and both children appear in the final tree.
    """
    _save, game_id = _make_save(xdg_tmp)
    mgr = PipelineSessionManager()

    owned = mgr.get_or_load_save(game_id)
    stub = _UsageRecordingStub(owned)
    mgr.get_or_create(game_id, owned, stub)  # type: ignore[arg-type]

    order: list[str] = []

    async def advance_choice(choice_id: str) -> None:
        save = mgr.get_or_load_save(game_id)
        async with mgr.advance_lock(game_id):
            order.append(f"start-{choice_id}")
            # Yield to force overlap — without the lock, both tasks would
            # interleave here (start-c1, start-c2, end-c1, end-c2).
            await asyncio.sleep(0.01)
            await stub.advance(save, from_node_id="root", choice_id=choice_id)
            order.append(f"end-{choice_id}")

    await asyncio.gather(advance_choice("c1"), advance_choice("c2"))

    # Serialization: one advance fully completes before the other starts.
    # (Either order is valid — what matters is no interleaving.)
    valid_orders = [
        ["start-c1", "end-c1", "start-c2", "end-c2"],
        ["start-c2", "end-c2", "start-c1", "end-c1"],
    ]
    assert order in valid_orders, f"advance lock failed to serialize: {order}"

    # Both children must exist in the tree (no lost node).
    child_ids = {nid for nid in owned.nodes if nid.startswith("child-")}
    assert len(child_ids) == 2, (
        f"expected 2 children after concurrent advances, got {child_ids}"
    )


# ---------------------------------------------------------------------------
# ARC-106: idle eviction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arc106_evict_idle_clears_and_reloads(xdg_tmp: Any) -> None:
    """ARC-106: evict_idle removes idle sessions; get_or_load_save reloads.

    Registers a game, artificially ages its _last_used stamp, calls
    evict_idle, then asserts the maps are empty and a subsequent
    get_or_load_save transparently re-opens the save from disk.
    """
    _save, game_id = _make_save(xdg_tmp)
    mgr = PipelineSessionManager()

    owned = mgr.get_or_load_save(game_id)
    stub = _UsageRecordingStub(owned)
    mgr.get_or_create(game_id, owned, stub)  # type: ignore[arg-type]

    # Age the last-used stamp into the distant past.
    import time

    mgr._last_used[game_id] = time.monotonic() - 99999.0  # pyright: ignore[reportPrivateUsage]

    evicted = await mgr.evict_idle(max_idle_seconds=1800.0)
    assert game_id in evicted, f"expected {game_id} to be evicted, got {evicted}"

    # All maps should be empty for this game.
    assert game_id not in mgr._pipelines  # pyright: ignore[reportPrivateUsage]
    assert game_id not in mgr._saves  # pyright: ignore[reportPrivateUsage]
    assert game_id not in mgr._advance_locks  # pyright: ignore[reportPrivateUsage]
    assert game_id not in mgr._last_used  # pyright: ignore[reportPrivateUsage]

    # A subsequent get_or_load_save must transparently reload from disk.
    reloaded = mgr.get_or_load_save(game_id)
    assert reloaded.id == owned.id
    assert reloaded is not owned, "evicted save must be a fresh load, not the evicted object"


@pytest.mark.asyncio
async def test_arc106_evict_idle_skips_locked_game(xdg_tmp: Any) -> None:
    """ARC-106: evict_idle must NOT evict a game whose advance lock is held."""
    _save, game_id = _make_save(xdg_tmp)
    mgr = PipelineSessionManager()

    owned = mgr.get_or_load_save(game_id)
    stub = _UsageRecordingStub(owned)
    mgr.get_or_create(game_id, owned, stub)  # type: ignore[arg-type]

    import time

    mgr._last_used[game_id] = time.monotonic() - 99999.0  # pyright: ignore[reportPrivateUsage]

    # Hold the advance lock while eviction runs.
    async with mgr.advance_lock(game_id):
        evicted = await mgr.evict_idle(max_idle_seconds=1800.0)

    assert game_id not in evicted, "must not evict a game whose advance lock is held"
    assert game_id in mgr._saves  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# ARC-103: settings update invalidates get_app_config cache
# ---------------------------------------------------------------------------


def test_arc103_settings_update_clears_config_cache(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ARC-103: PUT /api/settings calls get_app_config.cache_clear().

    Before ARC-103 the lru_cache held stale config after a settings write; the
    next route that depended on get_app_config saw the pre-update values.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("STORYGEN_API_TOKEN", "arc103-token")
    from storygen_api import deps
    from storygen_api.security import reset_token_cache

    reset_token_cache()
    deps.get_app_config.cache_clear()

    call_count = 0
    original_load = deps.load_config

    def counting_load() -> Any:
        nonlocal call_count
        call_count += 1
        return original_load()

    monkeypatch.setattr(deps, "load_config", counting_load)

    # Prime the cache — load_config called once.
    deps.get_app_config()
    assert call_count == 1, f"expected 1 load_config call, got {call_count}"

    # Cached — no additional call.
    deps.get_app_config()
    assert call_count == 1, "lru_cache should prevent a second load_config call"

    # Drive the settings update route, which must clear the cache (ARC-103).
    from storygen_api.main import create_app

    app = create_app()
    with TestClient(app) as client:
        r = client.put(
            "/api/settings",
            json={"art_enabled": False},
            headers={"Authorization": "Bearer arc103-token"},
        )
        assert r.status_code == 200, r.text

    # After the PUT, the cache was cleared → next get_app_config reloads.
    deps.get_app_config()
    assert call_count == 2, (
        f"expected load_config to be called again after settings update (ARC-103 "
        f"cache_clear), got {call_count} calls"
    )

    deps.get_app_config.cache_clear()
    reset_token_cache()
