"""Unit tests for text-LLM provider factory."""

from __future__ import annotations

import pytest
from pydantic_ai.models.openai import OpenAIChatModel

from storygen import config as config_module
from storygen.core.models import TextProviderConfig
from storygen.llm.provider_factory import (
    build_text_model,
    resolve_base_url,
    tool_settings_for,
    validate_config,
)
from storygen.storage import app_state


@pytest.mark.parametrize("environment_key_present", [True, False])
def test_custom_text_endpoint_credential_precedence_without_requests(
    monkeypatch: pytest.MonkeyPatch,
    environment_key_present: bool,
) -> None:
    prefs = app_state.ProviderPrefs(
        provider="openai",
        model="custom-model",
        base_url="https://custom.example/v1",
        api_key="FAKE_SETTINGS_VALUE",
    )
    monkeypatch.setattr(app_state, "read_provider_prefs", lambda: prefs)
    for name in ("STORYGEN_TEXT_PROVIDER", "STORYGEN_TEXT_MODEL", "STORYGEN_TEXT_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    if environment_key_present:
        monkeypatch.setenv("OPENAI_API_KEY", "FAKE_ENV_VALUE")
    else:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = config_module._resolve_text_config()  # pyright: ignore[reportPrivateUsage]
    model = build_text_model(cfg)
    assert str(model.client.base_url).rstrip("/") == "https://custom.example/v1"
    assert model.client.api_key == (
        "FAKE_ENV_VALUE" if environment_key_present else "FAKE_SETTINGS_VALUE"
    )


def test_resolve_base_url_defaults() -> None:
    assert resolve_base_url("openai") == "https://api.openai.com/v1"
    assert resolve_base_url("openrouter") == "https://openrouter.ai/api/v1"
    assert resolve_base_url("ollama") == "http://localhost:11434/v1"


def test_resolve_base_url_override() -> None:
    assert resolve_base_url("openai", override="https://custom/v1") == "https://custom/v1"


def test_build_text_model_returns_openai_chat_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = TextProviderConfig(provider="openai", model="gpt-4o-mini")
    model = build_text_model(cfg)
    assert isinstance(model, OpenAIChatModel)


def test_build_text_model_ollama_no_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = TextProviderConfig(provider="ollama", model="llama3.3:70b")
    # Ollama local needs no key; call must not raise.
    model = build_text_model(cfg)
    assert isinstance(model, OpenAIChatModel)


def test_build_text_model_openrouter_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenRouter config resolves to OpenAIChatModel wired to the OpenRouter base URL."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = TextProviderConfig(provider="openrouter", model="anthropic/claude-3.5-sonnet")
    model = build_text_model(cfg)
    assert isinstance(model, OpenAIChatModel)
    # Confirm the OpenAI-compatible client under the provider points at OpenRouter.
    client = model.client  # pyright: ignore[reportUnknownMemberType]
    assert "openrouter.ai" in str(client.base_url)


@pytest.mark.parametrize(
    ("provider", "model_name", "api_key_env"),
    [
        ("openai", "gpt-4o-mini", "OPENAI_API_KEY"),
        ("openrouter", "anthropic/claude-3.5-sonnet", "OPENROUTER_API_KEY"),
        ("ollama", "llama3.3:70b", None),
    ],
)
def test_build_text_model_base_url_override_per_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    model_name: str,
    api_key_env: str | None,
) -> None:
    """`base_url` on the config must survive through `build_text_model` for every provider."""
    if api_key_env is not None:
        monkeypatch.setenv(api_key_env, "sk-test")
    override = "https://custom.example/v1"
    cfg = TextProviderConfig(provider=provider, model=model_name, base_url=override)  # type: ignore[arg-type]
    model = build_text_model(cfg)
    assert isinstance(model, OpenAIChatModel)
    client = model.client  # pyright: ignore[reportUnknownMemberType]
    assert str(client.base_url).rstrip("/") == override.rstrip("/")


def test_validate_config_accepts_defaults() -> None:
    ok, err = validate_config(TextProviderConfig())
    assert ok is True
    assert err == ""


def test_tool_settings_for_luna_disables_reasoning() -> None:
    """gpt-6-luna needs reasoning_effort='none' for Chat Completions tools."""
    settings = tool_settings_for("gpt-6-luna")
    assert settings is not None
    assert settings.get("openai_reasoning_effort") == "none"
    # Dated snapshots are covered too.
    assert tool_settings_for("gpt-6-luna-2026-09-08") is not None
    # OpenRouter-style namespaced IDs are covered too.
    assert tool_settings_for("openai/gpt-6-luna") is not None


def test_tool_settings_for_other_models_is_none() -> None:
    """Non-luna models must not get a forced reasoning effort."""
    assert tool_settings_for("gpt-4o-mini") is None
    assert tool_settings_for("anthropic/claude-3.5-sonnet") is None
    assert tool_settings_for("llama3.3:70b") is None


def test_validate_config_accepts_explicit_base_url() -> None:
    ok, err = validate_config(
        TextProviderConfig(provider="ollama", model="llama3.3", base_url="http://local:11434/v1")
    )
    assert ok is True
    assert err == ""


def test_validate_config_accepts_https_base_url() -> None:
    ok, err = validate_config(
        TextProviderConfig(
            provider="openrouter",
            model="anthropic/claude-3.5-sonnet",
            base_url="https://openrouter.ai/api/v1",
        )
    )
    assert ok is True
    assert err == ""


def test_validate_config_rejects_empty_model() -> None:
    ok, err = validate_config(TextProviderConfig(provider="openai", model=""))
    assert ok is False
    assert "model" in err.lower()


def test_validate_config_rejects_whitespace_model() -> None:
    ok, err = validate_config(TextProviderConfig(provider="openai", model="   "))
    assert ok is False
    assert "model" in err.lower()


def test_validate_config_rejects_malformed_base_url() -> None:
    ok, err = validate_config(
        TextProviderConfig(provider="openai", model="gpt-4o-mini", base_url="not a url")
    )
    assert ok is False
    assert "base_url" in err.lower() or "url" in err.lower()


def test_validate_config_treats_none_base_url_as_empty() -> None:
    ok, err = validate_config(
        TextProviderConfig(provider="openai", model="gpt-4o-mini", base_url=None)
    )
    assert ok is True
    assert err == ""
