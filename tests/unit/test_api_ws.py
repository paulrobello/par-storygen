"""Contract + auth tests for the FastAPI WebSocket event surface (ARC-001, SEC-001).

Two test groups:

1. **Broadcast-shape contract** — every event emitted by
   :func:`storygen_api.ws.make_callbacks` must validate against a pydantic
   schema mirroring ``web/src/lib/ws-types.ts`` (the source-of-truth TS
   contract). Catches the three-way divergence the audit flagged: server
   emitting fields the React hook doesn't read (``delta`` vs ``text``,
   missing ``choices[]``, ``status`` vs ``error``, etc.).
2. **WebSocket auth (SEC-001)** — handshake is rejected (close code 4403)
   when no token is configured, with a wrong token, and accepted with the
   correct token via the ``Sec-WebSocket-Protocol: bearer.<token>`` path.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from storygen.core.models import ImageStatus
from storygen_api.main import create_app
from storygen_api.security import reset_token_cache
from storygen_api.ws import WebSocketManager

# ---------------------------------------------------------------------------
# ws-types.ts contract — single source of truth (mirror of the TS file)
# ---------------------------------------------------------------------------


class NarrationDeltaPayload(BaseModel):
    """Mirrors web/src/lib/ws-types.ts::ServerNarrationDelta."""

    type: str  # "narration_delta"
    node_id: str
    text: str


class BeatCommittedPayload(BaseModel):
    """Mirrors ServerBeatCommitted — includes the choices[] the hook renders."""

    type: str  # "beat_committed"
    node_id: str
    is_ending: bool
    choices: list[dict[str, Any]]


class ImageStatusPayload(BaseModel):
    type: str  # "image_status"
    node_id: str
    status: str  # "not_planned" | "generating" | "done" | "failed"


class ImageCommittedPayload(BaseModel):
    """Mirrors ServerImageCommitted — emitted when a scene illustration lands."""

    type: str  # "image_committed"
    node_id: str
    image_path: str


class ImageFailedPayload(BaseModel):
    """Mirrors ServerImageFailed — field is ``error`` (not ``status``)."""

    type: str  # "image_failed"
    node_id: str
    error: str


class NewCharactersPayload(BaseModel):
    """Mirrors ServerNewCharacters — each character carries the full card."""

    type: str  # "new_characters"
    characters: list[dict[str, Any]]


class ErrorPayload(BaseModel):
    """Mirrors ServerError — field is ``message`` (not ``error``)."""

    type: str  # "error"
    message: str


# Registry of valid event-type → schema, mirroring the ServerEvent union.
_EVENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "narration_delta": NarrationDeltaPayload,
    "beat_committed": BeatCommittedPayload,
    "image_status": ImageStatusPayload,
    "image_committed": ImageCommittedPayload,
    "image_failed": ImageFailedPayload,
    "new_characters": NewCharactersPayload,
    "error": ErrorPayload,
}


def _validate_broadcast(payload: dict[str, Any]) -> None:
    """Assert ``payload`` matches the ws-types.ts contract for its ``type``."""
    assert "type" in payload, f"broadcast missing 'type' field: {payload!r}"
    msg_type = payload["type"]
    schema = _EVENT_SCHEMAS.get(msg_type)
    assert schema is not None, (
        f"broadcast type {msg_type!r} is not in the ws-types.ts ServerEvent union"
    )
    schema.model_validate(payload)  # raises ValidationError on mismatch


# ---------------------------------------------------------------------------
# Test fixtures: a WebSocketManager with _broadcast captured
# ---------------------------------------------------------------------------


class _CapturingManager(WebSocketManager):
    """WebSocketManager subclass that records broadcasts instead of sending."""

    def __init__(self) -> None:
        super().__init__()
        self.broadcasts: list[dict[str, Any]] = []

    async def _broadcast(self, game_id: str, data: dict[str, Any]) -> None:  # type: ignore[override]
        # Tag with the game_id so tests can assert routing too.
        data = {**data, "_game_id": game_id}
        self.broadcasts.append(data)


def _sample_node(
    *,
    image_status: ImageStatus = "done",
    image_path: str | None = "games/abc/scene-root.png",
    choices: list[dict[str, Any]] | None = None,
) -> Any:
    """Build a minimal StoryNode-like object for callback invocation."""
    from storygen.core.models import StoredChoice, StoryNode

    return StoryNode(
        id="node-1",
        parent_id="root",
        chosen_choice_id="c1",
        chosen_at=datetime.now(UTC),
        narration="The door creaks open.",
        choices=[StoredChoice(id="c1", text="Enter")] if choices is None else [],
        is_major=True,
        is_ending=False,
        image_prompt="a creaking door",
        image_path=image_path,
        image_status=image_status,
        illustration_reasoning=None,
        featured_character_ids=["alyx"],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Contract tests: every broadcast validates against ws-types.ts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_narration_delta_broadcast_matches_contract() -> None:
    """``on_narration_delta`` emits the contract's {node_id, text} fields.

    Pre-ARC-001 the server emitted ``{delta, ts}`` which the React hook read
    as ``msg.text`` (undefined). This contract pins the post-fix shape.
    """
    mgr = _CapturingManager()
    cb = mgr.make_callbacks("game-123")
    await cb.on_narration_delta("The door creaks.")

    assert len(mgr.broadcasts) == 1
    payload = {k: v for k, v in mgr.broadcasts[0].items() if k != "_game_id"}
    _validate_broadcast(payload)
    assert payload["type"] == "narration_delta"
    assert payload["text"] == "The door creaks."
    # node_id is a contract-required string field; it can be empty here because
    # the pipeline fires narration deltas before the child node is committed
    # (the hook keys narration onto the eventual beat_committed.node_id).
    assert "node_id" in payload and isinstance(payload["node_id"], str)
    assert mgr.broadcasts[0]["_game_id"] == "game-123"


@pytest.mark.asyncio
async def test_beat_committed_broadcast_includes_choices() -> None:
    """``on_beat_committed`` emits ``choices[]`` so the player can pick.

    Pre-ARC-101 the server omitted choices[], so the web client rendered a
    beat but never offered the next pick.
    """
    mgr = _CapturingManager()
    cb = mgr.make_callbacks("game-123")
    node = _sample_node()
    await cb.on_beat_committed(node)

    assert len(mgr.broadcasts) == 1
    payload = {k: v for k, v in mgr.broadcasts[0].items() if k != "_game_id"}
    _validate_broadcast(payload)
    assert payload["type"] == "beat_committed"
    assert payload["node_id"] == "node-1"
    assert payload["is_ending"] is False
    assert isinstance(payload["choices"], list)
    assert payload["choices"], "beat_committed must include non-empty choices[]"


@pytest.mark.asyncio
async def test_image_committed_broadcast_uses_image_committed_type() -> None:
    """``on_image_committed`` must emit type='image_committed' with image_path.

    Pre-ARC-001 the server emitted type='image_status' from the
    on_image_committed hook, so the React ``image_committed`` case branch
    (which renders the scene art) never fired.
    """
    mgr = _CapturingManager()
    cb = mgr.make_callbacks("game-123")
    node = _sample_node(image_status="done", image_path="games/abc/scene-node-1.png")
    await cb.on_image_committed(node)

    assert len(mgr.broadcasts) == 1
    payload = {k: v for k, v in mgr.broadcasts[0].items() if k != "_game_id"}
    _validate_broadcast(payload)
    assert payload["type"] == "image_committed"
    assert payload["image_path"]


@pytest.mark.asyncio
async def test_image_failed_broadcast_uses_error_field() -> None:
    """``on_image_failed`` must emit ``error`` (contract) not ``status``.

    Pre-ARC-001 the server sent ``status`` which the React hook read as
    ``msg.error`` (undefined).
    """
    mgr = _CapturingManager()
    cb = mgr.make_callbacks("game-123")
    node = _sample_node(image_status="failed", image_path=None)
    await cb.on_image_failed(node)

    assert len(mgr.broadcasts) == 1
    payload = {k: v for k, v in mgr.broadcasts[0].items() if k != "_game_id"}
    _validate_broadcast(payload)
    assert payload["type"] == "image_failed"
    assert "error" in payload
    assert isinstance(payload["error"], str) and payload["error"]


@pytest.mark.asyncio
async def test_new_characters_broadcast_includes_full_character_fields() -> None:
    """``on_new_characters`` emits per-character fields the hook's Character type expects."""
    from storygen.core.models import Character

    mgr = _CapturingManager()
    cb = mgr.make_callbacks("game-123")
    chars = [
        Character(
            id="alyx",
            name="Alyx",
            backstory="A retired pilot",
            personality="Stoic",
            physical_description="Tall, grey eyes",
            portrait_path="games/abc/portraits/alyx-v1.png",
            portrait_prompt="tall, grey eyes",
            introduced_at_node_id="node-1",
        )
    ]
    await cb.on_new_characters(chars)

    assert len(mgr.broadcasts) == 1
    payload = {k: v for k, v in mgr.broadcasts[0].items() if k != "_game_id"}
    _validate_broadcast(payload)
    assert payload["type"] == "new_characters"
    assert isinstance(payload["characters"], list)
    assert payload["characters"], "new_characters must emit non-empty characters[]"
    first: dict[str, Any] = payload["characters"][0]  # pyright: ignore[reportUnknownVariableType]
    assert first["id"] == "alyx"
    assert first["name"] == "Alyx"
    # The TS contract expects these fields on each character.
    for required in ("backstory", "personality", "physical_description", "portrait_path"):
        assert required in first, f"character object missing contract field {required!r}"


# ---------------------------------------------------------------------------
# WebSocket auth (SEC-001)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_ws_token_cache() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]  # autouse fixture, invoked by pytest
    """Clear the bearer-token cache before and after each test."""
    reset_token_cache()
    yield
    reset_token_cache()


def _ws_headers_with_token(token: str) -> dict[str, str]:
    """Build the Sec-WebSocket-Protocol header for bearer-token auth."""
    # Starlette's TestClient accepts headers via the `headers` kwarg.
    return {"sec-websocket-protocol": f"bearer.{token}"}


def test_ws_handshake_rejected_when_no_token_configured(xdg_tmp: Any) -> None:
    """SEC-001 fail-closed: WS handshake refuses when STORYGEN_API_TOKEN is unset."""
    import os

    os.environ.pop("STORYGEN_API_TOKEN", None)
    reset_token_cache()

    app = create_app()
    game_id = str(uuid4()).replace("-", "") * 1  # any non-empty segment
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect),  # SEC-001 fail-closed handshake reject
        client.websocket_connect(
            f"/api/ws/{game_id}",
            headers=_ws_headers_with_token("anything"),
        ),
    ):
        pass


def test_ws_handshake_rejected_with_wrong_token(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-001: a wrong token is rejected (close code 4403)."""
    monkeypatch.setenv("STORYGEN_API_TOKEN", "correct-token")
    reset_token_cache()

    app = create_app()
    game_id = str(uuid4()).replace("-", "")
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect), client.websocket_connect(
        f"/api/ws/{game_id}",
        headers=_ws_headers_with_token("wrong-token"),
    ):
        pass


def test_ws_handshake_accepted_with_correct_token_then_closes_on_unknown_game(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-001: correct token passes the auth gate; unknown game_id then closes 4404.

    This proves the auth check runs *before* the save lookup — the connection
    is accepted past the auth gate and then closed with code 4404 (game not
    found), distinct from the 4403 auth-reject path.
    """
    monkeypatch.setenv("STORYGEN_API_TOKEN", "correct-token")
    reset_token_cache()

    app = create_app()
    game_id = "0" * 32  # 32-hex format passes paths.py SEC-003 validation but doesn't exist
    with (
        TestClient(app) as client,
        client.websocket_connect(
            f"/api/ws/{game_id}",
            headers=_ws_headers_with_token("correct-token"),
        ) as ws,
        pytest.raises(WebSocketDisconnect),
    ):
        # The auth gate accepted us; the router then tried to load the
        # (nonexistent) save and should close the connection. A subsequent
        # receive should raise.
        ws.receive_json()


def test_error_event_broadcast_validates_against_contract() -> None:
    """Sanity: the ErrorPayload schema accepts the contract's {type, message} shape."""
    ErrorPayload.model_validate({"type": "error", "message": "internal error"})
    with pytest.raises(ValidationError):
        ErrorPayload.model_validate({"type": "error", "error": "internal error"})


# ---------------------------------------------------------------------------
# SEC-103: per-frame rate limit on the WS advance path
# ---------------------------------------------------------------------------


def test_ws_advance_frame_is_rate_limited(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-103: the Nth advance frame gets a ``rate_limited`` error frame and
    the socket stays open. Ping frames are never counted.

    Drives a real WS handshake against a persisted save with a stub pipeline
    injected (no LLM/image work). With a 1/minute cap, the first advance
    consumes the budget; the second is rejected at the rate-limit gate before
    the advance lock or ``pipeline.advance`` is touched.
    """
    from storygen.core.models import (
        ImageProviderConfig,
        StoredChoice,
        StoryNode,
        TextProviderConfig,
        Theme,
        Tone,
    )
    from storygen.storage.save import GameSave, save_game
    from storygen_api import deps
    from storygen_api.rate_limit import (
        configure_rate_limit,
        reset_rate_limiter,
    )
    from storygen_api.routers import ws as ws_router

    # Build a minimal save on disk so the handshake's get_or_load_save finds it.
    root = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="A fork in the road.",
        choices=[
            StoredChoice(id="c1", text="left"),
            StoredChoice(id="c2", text="right"),
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
    game_id = str(save.id)

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("STORYGEN_API_TOKEN", "ws-rate-token")
    reset_token_cache()
    deps.get_app_config.cache_clear()

    # Tight 1/minute cap: frame 1 passes, frame 2 is throttled.
    configure_rate_limit("1/minute")
    reset_rate_limiter()

    # Inject a no-op pipeline so advance returns instantly (no callbacks fire,
    # so no broadcast frames precede the rate-limited error on frame 2).
    class _SilentPipeline:
        async def advance(
            self,
            save: Any,
            *,
            from_node_id: str,
            choice_id: str,
            skip_image: bool = False,
            suppress_side_effects: bool = False,
            callbacks: Any = None,
        ) -> Any:
            del save, from_node_id, choice_id, skip_image, suppress_side_effects, callbacks
            return root

        async def cancel_all_prefetches(self) -> None:
            return None

    def _fake_build_pipeline(save: Any, *, callbacks: Any = None) -> tuple[Any, None]:
        del save, callbacks
        return (_SilentPipeline(), None)

    monkeypatch.setattr(  # type: ignore[arg-type]
        ws_router, "build_pipeline", _fake_build_pipeline
    )

    app = create_app()
    headers = {"sec-websocket-protocol": "bearer.ws-rate-token"}
    try:
        with TestClient(app) as client, client.websocket_connect(
            f"/api/ws/{game_id}", headers=headers
        ) as ws:
            # Frame 1: consumes the single allowed advance (stub runs silently).
            ws.send_json(
                {"type": "advance", "from_node_id": "root", "choice_id": "c1"}
            )
            # Frame 2: over budget → rate_limited error, socket stays open.
            ws.send_json(
                {"type": "advance", "from_node_id": "root", "choice_id": "c2"}
            )
            # The stub fires no callbacks, so the first inbound frame is the
            # rate_limited error. Drain a couple of slots defensively.
            rate_limited: dict[str, Any] | None = None
            for _ in range(5):
                raw: Any = ws.receive_json()
                if isinstance(raw, dict):
                    frame = cast(dict[str, Any], raw)
                    if (
                        frame.get("type") == "error"
                        and frame.get("code") == "rate_limited"
                    ):
                        rate_limited = frame
                        break
            assert rate_limited is not None, "expected a rate_limited error frame"
            assert rate_limited.get("message")
            # Socket is still usable: a ping still pongs (connection not closed).
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            assert pong == {"type": "pong"}
    finally:
        # Restore the limiter spec so a leaked tight cap doesn't poison later
        # tests (the autouse conftest fixture clears counters but not the spec).
        configure_rate_limit("30/minute")
        reset_rate_limiter()
        reset_token_cache()
        deps.get_app_config.cache_clear()
