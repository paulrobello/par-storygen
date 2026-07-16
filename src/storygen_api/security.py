"""Authentication and SSRF defenses for the FastAPI surface (SEC-001, SEC-002).

Exports:
- ``verify_token``: FastAPI dependency that enforces a shared bearer token
  read from the ``STORYGEN_API_TOKEN`` environment variable. Routes that
  mutate state or incur LLM/image cost depend on it.
- ``validate_provider_base_url``: rejects URLs that point at private /
  link-local / loopback address ranges (unless loopback is explicitly
  allowed, e.g. for Ollama) and constrains user-influenced outbound URLs
  to a curated allowlist of sanctioned provider hosts.

The module is intentionally side-effect free and depends only on the
standard library plus FastAPI's ``HTTPException`` so it can be unit-tested
in isolation.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import os
import re
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request, status
from starlette.requests import HTTPConnection

_logger = logging.getLogger(__name__)

# Env var holding the shared bearer token expected on protected routes.
# When unset or empty, protected routes return 503 "auth not configured"
# rather than silently opening up (fail-closed).
TOKEN_ENV_VAR = "STORYGEN_API_TOKEN"


@lru_cache(maxsize=1)
def _expected_token() -> str | None:
    """Return the configured bearer token, or ``None`` if unset/empty.

    Cached so repeated request auth checks do not re-read ``os.environ``.
    Tests should call :func:`reset_token_cache` after mutating the env.
    """
    raw = os.environ.get(TOKEN_ENV_VAR)
    if not raw or not raw.strip():
        return None
    return raw.strip()


def reset_token_cache() -> None:
    """Clear the cached expected-token (test helper)."""
    _expected_token.cache_clear()


def _extract_bearer(conn: HTTPConnection) -> str | None:
    """Pull the bearer token from the Authorization header, or ``None``."""
    header = conn.headers.get("Authorization")
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def verify_token(request: Request) -> None:
    """FastAPI dependency: reject the request unless the bearer token matches.

    Fail-closed semantics: if ``STORYGEN_API_TOKEN`` is not configured the
    dependency returns 503 so a misconfigured deploy cannot expose the API.
    Token comparison uses :func:`hmac.compare_digest`` to avoid timing
    side channels.

    Raise:
        HTTPException(401): missing/malformed Authorization header.
        HTTPException(403): token does not match.
        HTTPException(503): server has no token configured.
    """
    expected = _expected_token()
    if expected is None:
        # Fail closed: refuse to serve protected routes until an admin
        # configures STORYGEN_API_TOKEN. Loopback-only dev can still hit
        # the open /api/health route.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API auth not configured (set STORYGEN_API_TOKEN)",
        )
    presented = _extract_bearer(request)
    if presented is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or malformed Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not hmac.compare_digest(presented, expected):
        # Log the mismatch at debug (do not echo the token); the correlation
        # id below lets operators cross-reference with upstream access logs.
        _logger.warning(
            "rejected bearer token for %s %s",
            request.method,
            request.url.path,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid bearer token",
        )


def ws_authorize(conn: HTTPConnection) -> bool:
    """Authenticate a WebSocket handshake (SEC-001).

    Browser WebSocket clients cannot set arbitrary headers, so the bearer
    token is read from either the ``Sec-WebSocket-Protocol`` subprotocol
    (``bearer.<token>``) — the most broadly supported approach — or the
    standard ``Authorization: Bearer <token>`` header for non-browser clients.

    Args:
        conn: The WebSocket (or its underlying HTTP connection) — both
            ``Request`` and ``WebSocket`` are ``HTTPConnection`` subclasses,
            so either may be passed.

    Returns:
        ``True`` if the connection is authorised; ``False`` if the token is
        missing, malformed, or does not match. Fail-closed: returns ``False``
        when ``STORYGEN_API_TOKEN`` is unset.
    """
    expected = _expected_token()
    if expected is None:
        return False
    # Try subprotocol first (browser-compatible).
    subprotocols = conn.headers.get("sec-websocket-protocol")
    if subprotocols:
        for proto in subprotocols.split(","):
            proto = proto.strip()
            if proto.lower().startswith("bearer."):
                presented = proto[len("bearer.") :]
                return bool(presented) and hmac.compare_digest(presented, expected)
    # Fall back to Authorization header (non-browser clients).
    presented = _extract_bearer(conn)
    if presented is None:
        return False
    return hmac.compare_digest(presented, expected)


# Reusable alias so routes stay readable: ``token: Annotated[None, RequireToken]``.
RequireToken = Annotated[None, Depends(verify_token)]


# ---------------------------------------------------------------------------
# SSRF defense (SEC-002)
# ---------------------------------------------------------------------------

# Curated allowlist of sanctioned provider host patterns. ``base_url`` values
# submitted via PUT /api/settings must resolve to one of these hosts (or be a
# loopback URL when ``allow_loopback`` is True — used for local Ollama).
# The list is deliberately small and case-insensitive.
_SANCTIONED_HOSTS: frozenset[str] = frozenset(
    {
        # Text / OpenAI-compatible
        "api.openai.com",
        "openrouter.ai",
        # Image providers
        "api.z.ai",
        "generativelanguage.googleapis.com",  # Gemini
        # TTS providers
        "api.elevenlabs.io",
        "api.deepgram.com",
    }
)


def _is_loopback_url(host: str) -> bool:
    """Return True if ``host`` is a loopback IPv4/IPv6 or ``localhost``."""
    if host.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback


def _is_private_or_link_local(host: str) -> bool:
    """Return True if ``host`` is a private, link-local, or reserved IP."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # DNS name — not in the IP ranges we filter here. The allowlist
        # gates which DNS names may pass; private-IP filtering is defense
        # in depth against DNS rebinding where an allowlisted name resolves
        # to a private address.
        return False
    return (
        ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


class ProviderURLError(ValueError):
    """Raised when a user-supplied provider ``base_url`` is rejected."""


def validate_provider_base_url(
    base_url: str,
    *,
    provider: str | None = None,
    allow_loopback: bool = True,
) -> None:
    """Validate a user-influenced outbound ``base_url`` (SEC-002).

    Args:
        base_url: The URL to check. ``None`` / empty is always allowed
            (means "use provider default") and should be filtered by the
            caller before invoking this function.
        provider: Optional provider name (e.g. ``"ollama"``) used only to
            tailor the error message.
        allow_loopback: When True (default), ``127.0.0.1``, ``::1``, and
            ``localhost`` URLs are permitted (Ollama runs locally). When
            False, loopback URLs are rejected too.

    Raises:
        ProviderURLError: If the URL is malformed, uses an unsupported
            scheme, points at a private/link-local IP, or its host is not
            on the sanctioned allowlist (when loopback is not allowed).
    """
    if not base_url or not base_url.strip():
        return  # caller decides whether empty is valid

    url = urlparse(base_url.strip())
    if url.scheme not in ("http", "https"):
        raise ProviderURLError(
            f"base_url must use http or https (got {url.scheme!r})"
        )
    host = (url.hostname or "").lower()
    if not host:
        raise ProviderURLError("base_url is missing a host")

    is_loopback = _is_loopback_url(host)
    if is_loopback:
        if allow_loopback:
            return
        raise ProviderURLError(
            "loopback base_url is not permitted for this provider"
        )

    # Reject private / link-local / reserved IP literals regardless of allowlist.
    if _is_private_or_link_local(host):
        raise ProviderURLError(
            "base_url must not point at a private, link-local, or reserved address"
        )

    if host not in _SANCTIONED_HOSTS:
        label = f" for provider {provider!r}" if provider else ""
        raise ProviderURLError(
            f"base_url host {host!r} is not on the sanctioned allowlist{label}"
        )


# Curated mapping of provider name -> URL-validator closure, used by the
# settings PUT handler. ``allow_loopback=True`` only for Ollama (local server).
_PROVIDER_VALIDATORS: dict[str, Callable[[str], None]] = {
    "openai": lambda url: validate_provider_base_url(
        url, provider="openai", allow_loopback=False
    ),
    "openrouter": lambda url: validate_provider_base_url(
        url, provider="openrouter", allow_loopback=False
    ),
    "ollama": lambda url: validate_provider_base_url(
        url, provider="ollama", allow_loopback=True
    ),
    # Image providers
    "gemini": lambda url: validate_provider_base_url(
        url, provider="gemini", allow_loopback=False
    ),
    "zai": lambda url: validate_provider_base_url(
        url, provider="zai", allow_loopback=False
    ),
}


def validate_provider_url_for(provider: str, base_url: str) -> None:
    """Dispatch to the per-provider URL validator (SEC-002).

    Unknown providers fall through to the strictest validator (no loopback).
    """
    validator = _PROVIDER_VALIDATORS.get(provider)
    if validator is None:
        validate_provider_base_url(base_url, provider=provider, allow_loopback=False)
        return
    validator(base_url)


# Module-level regex for the bearer-token format check (used by tests).
_BEARER_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{8,512}$")


def is_valid_token_format(token: str) -> bool:
    """Return True if ``token`` matches the expected bearer format.

    Used only for friendly error messages at startup; auth is enforced by
    :func:`verify_token` regardless of format.
    """
    return bool(_BEARER_TOKEN_PATTERN.fullmatch(token))


# ---------------------------------------------------------------------------
# WebSocket origin allowlist (SEC-011)
# ---------------------------------------------------------------------------

# Comma-separated env var for overriding the WS origin allowlist. Defaults
# mirror the CORS allowlist (web dev server on :8100).
WS_ALLOWED_ORIGINS_ENV = "STORYGEN_WS_ALLOWED_ORIGINS"
_DEFAULT_WS_ORIGINS: tuple[str, ...] = (
    "http://localhost:8100",
    "http://127.0.0.1:8100",
)


@lru_cache(maxsize=1)
def _ws_allowed_origins() -> frozenset[str]:
    """Return the configured WebSocket origin allowlist.

    Reads :data:`WS_ALLOWED_ORIGINS_ENV` (comma-separated); falls back to the
    default localhost dev origins. Tests should call
    :func:`reset_token_cache` (which also clears this cache) after env mutation.
    """
    raw = os.environ.get(WS_ALLOWED_ORIGINS_ENV, "")
    if not raw or not raw.strip():
        return frozenset(_DEFAULT_WS_ORIGINS)
    parts = {p.strip().lower() for p in raw.split(",") if p.strip()}
    return frozenset(parts)


def reset_origin_cache() -> None:
    """Clear the cached WS origin allowlist (test helper)."""
    _ws_allowed_origins.cache_clear()


def ws_check_origin(conn: HTTPConnection) -> bool:
    """Validate the WebSocket handshake ``Origin`` header against the allowlist.

    SEC-011: a browser always sends ``Origin`` on a WS handshake; if the header
    is present and not on the allowlist, the handshake is rejected (defense
    against CSRF-style cross-origin abuse when a token leaks into a cookie
    or browser session). When ``Origin`` is absent (non-browser clients, the
    Starlette ``TestClient``, curl), the check is skipped — bearer-token auth
    remains the gate.

    Args:
        conn: The WebSocket (or its HTTP connection).

    Returns:
        ``True`` if the origin is allowlisted or no ``Origin`` header was sent.
    """
    origin = conn.headers.get("origin")
    if not origin:
        # Non-browser client (curl, native, TestClient). Auth handles gate.
        return True
    return origin.lower() in _ws_allowed_origins()
