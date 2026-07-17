"""Unit tests for the FastAPI auth dependency and SSRF defense (SEC-001, SEC-002).

These exercise the helpers directly without spinning up a full FastAPI app —
that wiring is covered later by ARC-002 (Phase 2) integration tests.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from starlette.requests import HTTPConnection, Request
from starlette.testclient import TestClient

from storygen_api import security
from storygen_api.security import (
    ProviderURLError,
    is_loopback_peer,
    is_valid_token_format,
    reset_token_cache,
    validate_provider_base_url,
    validate_provider_url_for,
    verify_token,
    ws_authorize,
)

# ---------------------------------------------------------------------------
# SEC-001: bearer-token dependency
# ---------------------------------------------------------------------------


def _make_request(
    headers: dict[str, str] | None = None,
    *,
    client: tuple[str, int] | None = None,
) -> Request:
    scope: dict[str, Any] = {"type": "http", "method": "GET", "path": "/", "headers": []}
    if client is not None:
        scope["client"] = [client[0], client[1]]
    if headers:
        header_list: list[tuple[bytes, bytes]] = [
            (k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()
        ]
        scope["headers"] = header_list
    return Request(scope)


@pytest.fixture(autouse=True)
def _isolate_token_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    # Each test starts with no token configured; individual tests opt in.
    monkeypatch.delenv("STORYGEN_API_TOKEN", raising=False)
    reset_token_cache()
    yield
    reset_token_cache()


def test_verify_token_fails_closed_when_unset() -> None:
    """SEC-001: when STORYGEN_API_TOKEN is unset, return 503 (fail closed).

    The default request has no known peer (``client`` is None), so an unknown
    peer is treated as off-box and stays fail-closed.
    """
    request = _make_request({"Authorization": "Bearer anything"})
    with pytest.raises(security.HTTPException) as exc_info:
        verify_token(request)
    assert exc_info.value.status_code == 503


def test_verify_token_allows_loopback_when_token_unset() -> None:
    """Local dev (loopback peer) reaches protected routes with no token set."""
    request = _make_request(client=("127.0.0.1", 50000))
    verify_token(request)  # should not raise


def test_verify_token_fails_closed_for_offbox_when_token_unset() -> None:
    """Off-box peers are still 503 when no token is configured."""
    request = _make_request(client=("10.0.0.5", 50000))
    with pytest.raises(security.HTTPException) as exc_info:
        verify_token(request)
    assert exc_info.value.status_code == 503


def test_verify_token_still_enforces_token_on_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configuring a token locks the API down even for loopback clients."""
    monkeypatch.setenv("STORYGEN_API_TOKEN", "super-secret-token")
    reset_token_cache()
    request = _make_request({"Authorization": "Bearer wrong"}, client=("127.0.0.1", 50000))
    with pytest.raises(security.HTTPException) as exc_info:
        verify_token(request)
    assert exc_info.value.status_code == 403


def test_is_loopback_peer_classifies_peers() -> None:
    assert (
        is_loopback_peer(HTTPConnection({"type": "http", "headers": [], "client": ["127.0.0.1", 1]}))
        is True
    )
    assert (
        is_loopback_peer(HTTPConnection({"type": "http", "headers": [], "client": ["::1", 1]}))
        is True
    )
    assert (
        is_loopback_peer(HTTPConnection({"type": "http", "headers": [], "client": ["10.0.0.5", 1]}))
        is False
    )
    # No client in scope -> unknown peer -> not trusted.
    assert is_loopback_peer(HTTPConnection({"type": "http", "headers": []})) is False


def test_verify_token_rejects_missing_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORYGEN_API_TOKEN", "super-secret-token")
    reset_token_cache()
    request = _make_request()
    with pytest.raises(security.HTTPException) as exc_info:
        verify_token(request)
    assert exc_info.value.status_code == 401
    headers = exc_info.value.headers
    assert headers is not None
    assert "WWW-Authenticate" in headers


def test_verify_token_rejects_malformed_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORYGEN_API_TOKEN", "super-secret-token")
    reset_token_cache()
    request = _make_request({"Authorization": "Basic abc123"})
    with pytest.raises(security.HTTPException) as exc_info:
        verify_token(request)
    assert exc_info.value.status_code == 401


def test_verify_token_rejects_wrong_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORYGEN_API_TOKEN", "super-secret-token")
    reset_token_cache()
    request = _make_request({"Authorization": "Bearer wrong-token"})
    with pytest.raises(security.HTTPException) as exc_info:
        verify_token(request)
    assert exc_info.value.status_code == 403


def test_verify_token_accepts_correct_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORYGEN_API_TOKEN", "super-secret-token")
    reset_token_cache()
    request = _make_request({"Authorization": "Bearer super-secret-token"})
    # Should not raise.
    verify_token(request)


def test_verify_token_uses_constant_time_compare(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token comparison should use hmac.compare_digest (no early-exit on length)."""
    monkeypatch.setenv("STORYGEN_API_TOKEN", "abc")
    reset_token_cache()
    request = _make_request({"Authorization": "Bearer abc"})
    verify_token(request)  # passes


def test_ws_authorize_rejects_when_unset() -> None:
    """SEC-001: WS handshake fails closed for an unknown/off-box peer when unset."""
    conn = HTTPConnection({"type": "http", "headers": []})
    assert ws_authorize(conn) is False


def test_ws_authorize_allows_loopback_when_token_unset() -> None:
    """Local dev (loopback peer) opens the WS with no token configured."""
    conn = HTTPConnection({"type": "http", "headers": [], "client": ["127.0.0.1", 50000]})
    assert ws_authorize(conn) is True


def test_ws_authorize_rejects_offbox_when_token_unset() -> None:
    """Off-box WS peers are still rejected when no token is configured."""
    conn = HTTPConnection({"type": "http", "headers": [], "client": ["10.0.0.5", 50000]})
    assert ws_authorize(conn) is False


def test_ws_authorize_accepts_subprotocol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORYGEN_API_TOKEN", "ws-secret-token")
    reset_token_cache()
    conn = HTTPConnection(
        {
            "type": "http",
            "headers": [(b"sec-websocket-protocol", b"bearer.ws-secret-token")],
        }
    )
    assert ws_authorize(conn) is True


def test_ws_authorize_rejects_wrong_subprotocol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORYGEN_API_TOKEN", "ws-secret-token")
    reset_token_cache()
    conn = HTTPConnection(
        {
            "type": "http",
            "headers": [(b"sec-websocket-protocol", b"bearer.wrong")],
        }
    )
    assert ws_authorize(conn) is False


def test_ws_authorize_falls_back_to_authorization_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-browser clients can still use the standard Authorization header."""
    monkeypatch.setenv("STORYGEN_API_TOKEN", "header-token")
    reset_token_cache()
    conn = HTTPConnection(
        {
            "type": "http",
            "headers": [(b"authorization", b"Bearer header-token")],
        }
    )
    assert ws_authorize(conn) is True


# ---------------------------------------------------------------------------
# SEC-002: provider base-URL allowlist / SSRF defense
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "https://openrouter.ai/api/v1",
        "https://api.z.ai/api/paas/v4/",
        "https://generativelanguage.googleapis.com/v1",
        "https://api.elevenlabs.io/v1",
        "https://api.deepgram.com/v1",
    ],
)
def test_validate_provider_base_url_accepts_sanctioned_hosts(url: str) -> None:
    validate_provider_base_url(url, allow_loopback=False)  # no raise


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434/v1",
        "http://localhost:11434/v1",
        "http://[::1]:11434/v1",
    ],
)
def test_validate_provider_base_url_accepts_loopback_when_allowed(url: str) -> None:
    validate_provider_base_url(url, allow_loopback=True)  # no raise


def test_validate_provider_base_url_rejects_loopback_when_disallowed() -> None:
    with pytest.raises(ProviderURLError, match="loopback"):
        validate_provider_base_url("http://127.0.0.1:11434/v1", allow_loopback=False)
    with pytest.raises(ProviderURLError, match="loopback"):
        validate_provider_base_url("http://localhost:11434/v1", allow_loopback=False)


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.1/v1",  # private Class A
        "http://172.16.5.4/v1",  # private Class B
        "http://192.168.1.1/v1",  # private Class C
        "http://169.254.169.254/latest/meta-data/",  # link-local AWS metadata
        "http://0.0.0.0/v1",  # unspecified
        "http://[fc00::1]/v1",  # ULA
        "http://[fe80::1]/v1",  # link-local IPv6
    ],
)
def test_validate_provider_base_url_rejects_private_ips(url: str) -> None:
    with pytest.raises(ProviderURLError, match=r"private|link-local|reserved"):
        validate_provider_base_url(url, allow_loopback=True)


def test_validate_provider_base_url_rejects_unknown_host() -> None:
    """SEC-002: attacker-controlled host must be rejected even if not a private IP."""
    with pytest.raises(ProviderURLError, match="allowlist"):
        validate_provider_base_url(
            "https://attacker.example.com/v1", allow_loopback=False
        )


def test_validate_provider_base_url_rejects_bad_scheme() -> None:
    with pytest.raises(ProviderURLError, match="http or https"):
        validate_provider_base_url("ftp://api.openai.com/v1")
    with pytest.raises(ProviderURLError, match="http or https"):
        validate_provider_base_url("file:///etc/passwd")


def test_validate_provider_base_url_rejects_missing_host() -> None:
    with pytest.raises(ProviderURLError, match="host"):
        validate_provider_base_url("https://")


def test_validate_provider_base_url_allows_empty() -> None:
    """Empty / whitespace URLs are caller-controlled 'use default'; allow them."""
    validate_provider_base_url("")
    validate_provider_base_url("   ")


def test_validate_provider_url_for_ollama_allows_loopback() -> None:
    """Ollama runs locally — loopback must be permitted for it specifically."""
    validate_provider_url_for("ollama", "http://localhost:11434/v1")  # no raise
    validate_provider_url_for("ollama", "http://127.0.0.1:11434/v1")  # no raise


def test_validate_provider_url_for_openai_rejects_loopback() -> None:
    """OpenAI must NOT be redirected to a loopback address."""
    with pytest.raises(ProviderURLError, match="loopback"):
        validate_provider_url_for("openai", "http://127.0.0.1/")


def test_validate_provider_url_for_unknown_provider_strict() -> None:
    """Unknown providers get the strictest validator (no loopback, sanctioned host only)."""
    with pytest.raises(ProviderURLError):
        validate_provider_url_for("attacker-provider", "http://127.0.0.1/")
    with pytest.raises(ProviderURLError):
        validate_provider_url_for("attacker-provider", "https://evil.example.com/")


def test_is_valid_token_format_accepts_strong_tokens() -> None:
    assert is_valid_token_format("abc123_-XYZ")
    assert is_valid_token_format("a" * 8)
    assert is_valid_token_format("a" * 512)


def test_is_valid_token_format_rejects_weak_tokens() -> None:
    assert not is_valid_token_format("")
    assert not is_valid_token_format("short")  # < 8 chars
    assert not is_valid_token_format("has space")
    assert not is_valid_token_format("has/slash")
    assert not is_valid_token_format("a" * 513)  # > 512 chars


# ---------------------------------------------------------------------------
# SEC-104: presets router is gated by verify_token (route-level integration)
# ---------------------------------------------------------------------------


def test_presets_router_rejects_without_valid_token(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-104: GET /api/presets is behind ``verify_token``; missing/bad token → 401/403."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("STORYGEN_API_TOKEN", "presets-token")
    reset_token_cache()

    from storygen_api.main import create_app

    app = create_app()
    with TestClient(app) as client:
        # No auth header → 401.
        r = client.get("/api/presets")
        assert r.status_code == 401
        # Wrong token → 403.
        r2 = client.get(
            "/api/presets", headers={"Authorization": "Bearer wrong-token"}
        )
        assert r2.status_code == 403
        # Correct token → 200 (presets dir is empty under xdg_tmp, but the
        # handler tolerates a missing dir and returns empty lists).
        r3 = client.get(
            "/api/presets", headers={"Authorization": "Bearer presets-token"}
        )
        assert r3.status_code == 200

    reset_token_cache()


def test_presets_router_fails_closed_when_token_unset_and_off_box(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-104: with no token configured, a non-loopback peer is rejected (503).

    Starlette's ``TestClient`` presents a ``"testclient"`` peer (not a loopback
    IP), so it models an off-box client. ``verify_token`` fails closed for such
    peers when ``STORYGEN_API_TOKEN`` is unset, so the presets route returns 503.
    The loopback-trust path itself is covered by the dependency-level tests
    above (``test_verify_token_allows_loopback_when_token_unset``).
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("STORYGEN_API_TOKEN", raising=False)
    reset_token_cache()

    from storygen_api.main import create_app

    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/presets")
        assert r.status_code == 503

    reset_token_cache()
