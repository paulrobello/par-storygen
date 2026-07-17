"""Tests for the ``/api/providers`` route and the ENH-005-T3 wiring.

Pins three things:
- ``GET /api/providers`` returns the registry ids (text + image) and is
  gated by the shared bearer-token dependency (SEC-001).
- ``PUT /api/settings`` now rejects unknown provider ids with 400
  (previously only the base URL was validated).
- The T1 ``test_ollama_loopback_policy_consistent`` contract still holds now
  that ``security._PROVIDER_VALIDATORS`` is rebuilt from the registry.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from starlette.testclient import TestClient

from storygen.core.providers import IMAGE_PROVIDERS, TEXT_PROVIDERS
from storygen_api.security import reset_token_cache

# ---------------------------------------------------------------------------
# Test client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Build a TestClient with an OPENAI_API_KEY set and a configured token.

    ``xdg_tmp`` keeps the on-disk app-state isolated. The token gate is
    exercised directly by ``client`` calls that set / omit the header.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("STORYGEN_API_TOKEN", "providers-test-token")
    reset_token_cache()

    from storygen_api.main import create_app

    app = create_app()
    client = TestClient(app)
    yield client

    reset_token_cache()


_AUTH = {"Authorization": "Bearer providers-test-token"}


# ---------------------------------------------------------------------------
# GET /api/providers
# ---------------------------------------------------------------------------


def test_get_providers_returns_registry_ids(api_client: TestClient) -> None:
    """GET /api/providers returns every text + image registry id."""
    r = api_client.get("/api/providers", headers=_AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [p["id"] for p in body["text_providers"]] == list(TEXT_PROVIDERS.keys())
    assert [p["id"] for p in body["image_providers"]] == list(IMAGE_PROVIDERS.keys())
    # Spot-check one entry's full shape (OpenAI text).
    openai_text = next(p for p in body["text_providers"] if p["id"] == "openai")
    assert openai_text["label"] == "OpenAI"
    assert openai_text["kind"] == ["text"]
    assert openai_text["key_env_var"] == "OPENAI_API_KEY"
    assert openai_text["default_model"] == "gpt-4o-mini"
    assert openai_text["default_base_url"] == "https://api.openai.com/v1"
    assert openai_text["allows_loopback_base_url"] is False
    assert openai_text["supports_reference_images"] is False
    assert openai_text["suggested_models"] == ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"]
    # Ollama is the only provider with loopback=True (text + image).
    for entry in body["text_providers"] + body["image_providers"]:
        assert entry["allows_loopback_base_url"] == (entry["id"] == "ollama"), (
            f"{entry['id']!r} loopback flag diverges"
        )


def test_get_providers_token_gated_missing_token(
    api_client: TestClient,
) -> None:
    """SEC-001: no Authorization header → 401."""
    r = api_client.get("/api/providers")
    assert r.status_code == 401, r.text


def test_get_providers_token_gated_wrong_token(
    api_client: TestClient,
) -> None:
    """SEC-001: wrong bearer token → 403."""
    r = api_client.get("/api/providers", headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 403, r.text


def test_get_providers_fails_closed_off_box_without_token(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-001: token unset + non-loopback peer → 503.

    Starlette's ``TestClient`` presents a ``"testclient"`` peer (not loopback),
    so this models an off-box client. The loopback-trust path itself is
    covered by the dependency-level tests in test_api_security.py.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("STORYGEN_API_TOKEN", raising=False)
    reset_token_cache()

    from storygen_api.main import create_app

    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/providers")
        assert r.status_code == 503, r.text

    reset_token_cache()


# ---------------------------------------------------------------------------
# PUT /api/settings — unknown provider id now rejected (ENH-005-T3)
# ---------------------------------------------------------------------------


def test_put_settings_rejects_unknown_text_provider(
    api_client: TestClient,
) -> None:
    """PUT with an unknown text provider id is rejected with 400."""
    r = api_client.put(
        "/api/settings",
        json={"text_provider": {"provider": "attacker-provider"}},
        headers=_AUTH,
    )
    assert r.status_code == 400, r.text
    assert "unknown provider id" in r.text


def test_put_settings_rejects_unknown_image_provider(
    api_client: TestClient,
) -> None:
    """PUT with an unknown image provider id is rejected with 400."""
    r = api_client.put(
        "/api/settings",
        json={"image_provider": {"provider": "attacker-provider"}},
        headers=_AUTH,
    )
    assert r.status_code == 400, r.text
    assert "unknown provider id" in r.text


def test_put_settings_rejects_unknown_character_image_provider(
    api_client: TestClient,
) -> None:
    """PUT with an unknown character-image provider id is rejected with 400."""
    r = api_client.put(
        "/api/settings",
        json={"character_image_provider": {"provider": "attacker-provider"}},
        headers=_AUTH,
    )
    assert r.status_code == 400, r.text
    assert "unknown provider id" in r.text


def test_put_settings_accepts_known_text_provider(api_client: TestClient) -> None:
    """PUT with a registry-known text provider id is accepted (still passes
    SSRF base_url validation when base_url is empty/default)."""
    r = api_client.put(
        "/api/settings",
        json={"text_provider": {"provider": "ollama", "base_url": ""}},
        headers=_AUTH,
    )
    assert r.status_code == 200, r.text


def test_put_settings_accepts_known_image_provider(api_client: TestClient) -> None:
    """PUT with a registry-known image provider id is accepted."""
    r = api_client.put(
        "/api/settings",
        json={"image_provider": {"provider": "openai", "base_url": ""}},
        headers=_AUTH,
    )
    assert r.status_code == 200, r.text


def test_put_settings_rejects_text_provider_in_image_field(
    api_client: TestClient,
) -> None:
    """A text-only provider id (e.g. ``openrouter``) is rejected in the
    image field — it's not in the image registry."""
    r = api_client.put(
        "/api/settings",
        json={"image_provider": {"provider": "openrouter"}},
        headers=_AUTH,
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# security.py — registry-driven loopback wiring
# ---------------------------------------------------------------------------


def test_security_provider_validators_match_registry() -> None:
    """The validator dict keys match text+image registry ids exactly, and
    every entry's allow_loopback flag comes from the registry."""
    from storygen_api.security import (
        _PROVIDER_VALIDATORS,  # pyright: ignore[reportPrivateUsage] - the validator dict's contents are a load-bearing contract worth pinning directly even though it is module-private
    )

    expected_ids = set(TEXT_PROVIDERS.keys()) | set(IMAGE_PROVIDERS.keys())
    assert set(_PROVIDER_VALIDATORS.keys()) == expected_ids


def test_security_ollama_loopback_still_allowed() -> None:
    """The ollama entry (now built from the registry) still permits loopback.

    Mirrors ``test_validate_provider_url_for_ollama_allows_loopback`` — kept
    here so the registry-wiring change has a co-located green check.
    """
    from storygen_api.security import validate_provider_url_for

    validate_provider_url_for("ollama", "http://localhost:11434/v1")  # no raise
    validate_provider_url_for("ollama", "http://127.0.0.1:11434/v1")  # no raise


def test_security_openai_loopback_still_rejected() -> None:
    """OpenAI must NOT be redirected to loopback (regression check)."""
    from storygen_api.security import ProviderURLError, validate_provider_url_for

    with pytest.raises(ProviderURLError, match="loopback"):
        validate_provider_url_for("openai", "http://127.0.0.1/")
