"""Tests for the WebSocket origin allowlist + message-size cap (SEC-011).

Verifies:
1. ``ws_check_origin`` accepts (a) no Origin header (non-browser clients),
   and (b) allowlisted origins; rejects non-allowlisted browser origins.
2. The allowlist reads ``STORYGEN_WS_ALLOWED_ORIGINS`` (configurable).
3. Integration via TestClient: an oversized WS frame closes with code 1009
   rather than being parsed; an invalid JSON frame returns a bad_request
   error event instead of crashing the endpoint.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from starlette.requests import HTTPConnection
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from storygen_api.security import reset_origin_cache, ws_check_origin

# ---------------------------------------------------------------------------
# ws_check_origin unit tests
# ---------------------------------------------------------------------------


def _conn_with_origin(origin: str | None) -> HTTPConnection:
    headers: list[tuple[bytes, bytes]] = []
    if origin is not None:
        headers.append((b"origin", origin.encode("latin-1")))
    return HTTPConnection({"type": "http", "headers": headers})


@pytest.fixture(autouse=True)
def _reset_origin_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.delenv("STORYGEN_WS_ALLOWED_ORIGINS", raising=False)
    reset_origin_cache()


def test_ws_check_origin_allows_missing_origin_header() -> None:
    """SEC-011: non-browser clients omit Origin; auth alone gates them."""
    assert ws_check_origin(_conn_with_origin(origin=None)) is True


def test_ws_check_origin_accepts_default_allowlisted_hosts() -> None:
    assert ws_check_origin(_conn_with_origin("http://localhost:8100")) is True
    assert ws_check_origin(_conn_with_origin("http://127.0.0.1:8100")) is True


def test_ws_check_origin_rejects_non_allowlisted_host() -> None:
    """SEC-011: a browser cross-origin handshake from an attacker page is refused."""
    assert ws_check_origin(_conn_with_origin("https://attacker.example.com")) is False


def test_ws_check_origin_reads_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The allowlist is configurable via ``STORYGEN_WS_ALLOWED_ORIGINS``."""
    monkeypatch.setenv(
        "STORYGEN_WS_ALLOWED_ORIGINS",
        "https://prod.example.com,http://localhost:3000",
    )
    reset_origin_cache()
    assert ws_check_origin(_conn_with_origin("https://prod.example.com")) is True
    assert ws_check_origin(_conn_with_origin("http://localhost:3000")) is True
    # The default localhost:8100 is no longer allowlisted once overridden.
    assert ws_check_origin(_conn_with_origin("http://localhost:8100")) is False


def test_ws_check_origin_case_insensitive() -> None:
    assert ws_check_origin(_conn_with_origin("http://LOCALHOST:8100")) is True


# ---------------------------------------------------------------------------
# Message-size cap integration test
# ---------------------------------------------------------------------------


def _auth_headers(token: str) -> dict[str, str]:
    return {"sec-websocket-protocol": f"bearer.{token}"}


def test_ws_oversized_message_closes_with_1009(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-011: a frame larger than 64 KiB closes with code 1009.

    Uses a stub pipeline so the test doesn't depend on real LLM calls; the
    size cap fires before any handler runs.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("STORYGEN_API_TOKEN", "size-cap-token")
    from storygen_api.security import reset_token_cache

    reset_token_cache()

    # Create a save so the WS handshake passes the game-id check.
    from datetime import UTC, datetime

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

    root = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="...",
        choices=[StoredChoice(id="c1", text="x")],
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
        theme=Theme(title="T", setting="s", premise="p", keywords=[]),
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
    game_id = str(save.id)

    # Register a stub pipeline so the endpoint doesn't try to build a real one.
    from storygen_api.deps import get_session_manager
    from tests.integration._stub_pipeline import StubBeatPipeline

    mgr = get_session_manager()
    mgr.get_or_create(game_id, save, StubBeatPipeline())  # type: ignore[arg-type]

    from storygen_api.main import create_app

    app = create_app()
    with TestClient(app) as client, client.websocket_connect(
        f"/api/ws/{game_id}",
        headers=_auth_headers("size-cap-token"),
    ) as ws:
        # Send an oversized text frame (>64 KiB of JSON).
        big_payload = '{"type":"ping","padding":"' + ("x" * (70 * 1024)) + '"}'
        ws.send_text(big_payload)
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
        assert exc_info.value.code == 1009


def test_ws_invalid_json_returns_bad_request_event(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-011 (defense-in-depth): malformed JSON returns a clean error event."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("STORYGEN_API_TOKEN", "json-err-token")
    from storygen_api.security import reset_token_cache

    reset_token_cache()

    # Reuse the save-creation helper from the integration tests.
    from tests.integration.test_api_full_flow import (
        _make_save_with_choice,  # pyright: ignore[reportPrivateUsage]
    )

    save, game_id, _ = _make_save_with_choice(xdg_tmp)

    from storygen_api.deps import get_session_manager
    from tests.integration._stub_pipeline import StubBeatPipeline

    mgr = get_session_manager()
    mgr.get_or_create(game_id, save, StubBeatPipeline())  # type: ignore[arg-type]

    from storygen_api.main import create_app

    app = create_app()
    with TestClient(app) as client, client.websocket_connect(
        f"/api/ws/{game_id}",
        headers=_auth_headers("json-err-token"),
    ) as ws:
        ws.send_text("this is not json")
        evt = ws.receive_json()
    assert evt["type"] == "error"
    assert evt["code"] == "bad_request"
    assert "message" in evt
