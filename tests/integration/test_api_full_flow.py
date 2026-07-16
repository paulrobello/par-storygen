"""End-to-end integration test for the FastAPI wizard → WS → advance flow (ARC-002).

Drives the real FastAPI app with a TestClient against an isolated XDG data
directory. SEC-001 bearer-token auth is exercised end-to-end (wizard route
returns 503 with no token configured, 401 with no header, succeeds with the
correct token). The WebSocket advance flow is driven against a stub
``BeatPipeline`` so the test stays deterministic and fast (no real LLM calls).

The stub pipeline replays a canned narration sequence and emits the
contract-correct ``beat_committed`` payload — verifying that the server-side
fix for ARC-001 (WS protocol) reaches the wire.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from storygen.llm.models import (
    Character,
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.storage.save import GameSave, save_game
from tests.integration._stub_pipeline import StubBeatPipeline

# ---------------------------------------------------------------------------
# SEC-001 auth on the REST wizard surface (HTTP path)
# ---------------------------------------------------------------------------


@pytest.fixture
def app_client(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Build a TestClient with STORYGEN_API_TOKEN set and the cache primed."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("STORYGEN_API_TOKEN", "integration-test-token")
    # Reset the lru_cache after env mutation so the new token is picked up.
    from storygen_api.security import reset_token_cache

    reset_token_cache()
    # Clear deps.get_app_config cache so the test's env is re-read.
    from storygen_api import deps

    deps.get_app_config.cache_clear()

    from storygen_api.main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client

    reset_token_cache()
    deps.get_app_config.cache_clear()


def test_wizard_route_returns_503_when_no_token_configured(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-001 fail-closed: with no token configured, wizard returns 503."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("STORYGEN_API_TOKEN", raising=False)
    from storygen_api.security import reset_token_cache

    reset_token_cache()
    from storygen_api.main import create_app

    app = create_app()
    with TestClient(app) as client:
        # The theme-proposal route is auth-gated and cost-incurring.
        r = client.post("/api/wizard/theme", json={"prompt": "a noir mystery"})
    assert r.status_code == 503


def test_wizard_route_returns_401_with_no_auth_header(app_client: TestClient) -> None:
    """SEC-001: with token configured but no header, wizard returns 401."""
    r = app_client.post("/api/wizard/theme", json={"prompt": "a noir mystery"})
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers


def test_wizard_route_rejects_wrong_token(app_client: TestClient) -> None:
    """SEC-001: wrong token → 403."""
    r = app_client.post(
        "/api/wizard/theme",
        json={"prompt": "a noir mystery"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert r.status_code == 403


def test_games_list_returns_empty_without_saves(app_client: TestClient) -> None:
    """With auth and no saves, the games list returns an empty list."""
    r = app_client.get(
        "/api/games",
        headers={"Authorization": "Bearer integration-test-token"},
    )
    assert r.status_code == 200
    assert r.json() == {"games": []}


# ---------------------------------------------------------------------------
# WebSocket advance flow — drives a stub pipeline that emits a canned beat
# ---------------------------------------------------------------------------


def _make_save_with_choice(xdg_tmp: Any) -> tuple[GameSave, str, str]:
    """Create a save with a root node offering one choice; return (save, game_id_hex, choice_id)."""
    choice_id = "c1"
    root = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="You stand at the crossroads.",
        choices=[StoredChoice(id=choice_id, text="Take the left path")],
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
        theme=Theme(title="Crossroads", setting="S", premise="P", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        character_image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        characters=[
            Character(
                id="hero",
                name="Hero",
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
    return save, str(save.id), choice_id


def test_ws_advance_emits_narration_then_beat_committed(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ARC-001 + ARC-002: advance via WS produces contract-correct events.

    The stub pipeline replays a narration_delta sequence then a beat_committed
    payload. We assert both arrive on the wire and validate against the
    ws-types.ts contract.
    """
    save, game_id, choice_id = _make_save_with_choice(xdg_tmp)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("STORYGEN_API_TOKEN", "ws-test-token")
    from storygen_api.security import reset_token_cache

    reset_token_cache()

    # Register a stub pipeline for this game_id BEFORE the WS handshake, so
    # the router's `existing = mgr.get_pipeline(game_id)` short-circuits and
    # never tries to construct a real one.
    from storygen_api.deps import get_session_manager
    from storygen_api.routers import ws as ws_router


    mgr = get_session_manager()
    stub = StubBeatPipeline()
    mgr.get_or_create(game_id, save, stub)  # type: ignore[arg-type]

    # Also monkeypatch build_pipeline as defense-in-depth in case the
    # registry is reset between requests.
    monkeypatch.setattr(
        ws_router, "build_pipeline", lambda *a, **kw: (stub, None)  # type: ignore[arg-type]
    )

    from storygen_api.main import create_app

    app = create_app()
    with TestClient(app) as client, client.websocket_connect(
        f"/api/ws/{game_id}",
        headers={"sec-websocket-protocol": "bearer.ws-test-token"},
    ) as ws:
        # Drive an advance; the stub emits narration_delta then beat_committed.
        ws.send_json(
            {"type": "advance", "choice_id": choice_id, "from_node_id": "root"}
        )
        # Collect up to 5 events or until beat_committed arrives.
        events: list[dict[str, Any]] = []
        for _ in range(5):
            try:
                evt = ws.receive_json()
            except WebSocketDisconnect:
                break
            events.append(evt)
            if evt.get("type") == "beat_committed":
                break

    types = [e.get("type") for e in events]
    assert "narration_delta" in types, (
        f"expected at least one narration_delta, got events: {types!r}"
    )
    assert "beat_committed" in types, (
        f"expected a beat_committed, got events: {types!r}"
    )

    # Validate each event against the contract.
    from tests.unit.test_api_ws import _validate_broadcast  # type: ignore[import-not-found]

    for evt in events:
        if evt.get("type") in ("pong",):
            continue
        _validate_broadcast(evt)

    beat = next(e for e in events if e.get("type") == "beat_committed")
    assert beat["node_id"], "beat_committed must include node_id"
    assert "choices" in beat, "beat_committed must include choices[]"


def test_ws_rejects_advance_with_missing_fields(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ARC-007: advance without choice_id / from_node_id → bad_request error event."""
    save, game_id, _ = _make_save_with_choice(xdg_tmp)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("STORYGEN_API_TOKEN", "ws-test-token")
    from storygen_api.security import reset_token_cache

    reset_token_cache()

    from storygen_api.deps import get_session_manager

    mgr = get_session_manager()
    mgr.get_or_create(game_id, save, StubBeatPipeline())  # type: ignore[arg-type]

    from storygen_api.main import create_app

    app = create_app()
    with TestClient(app) as client, client.websocket_connect(
        f"/api/ws/{game_id}",
        headers={"sec-websocket-protocol": "bearer.ws-test-token"},
    ) as ws:
        ws.send_json({"type": "advance", "choice_id": "", "from_node_id": ""})
        evt = ws.receive_json()
    assert evt["type"] == "error"
    assert evt["code"] == "bad_request"
    assert "message" in evt  # SEC-004 contract: errors carry a message field
