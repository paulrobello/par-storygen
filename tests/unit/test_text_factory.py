"""Unit tests for text-LLM provider factory."""

from __future__ import annotations

import pytest
from pydantic_ai.models.openai import OpenAIChatModel

from storygen.core.models import TextProviderConfig
from storygen.llm.provider_factory import build_text_model, resolve_base_url, validate_config


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
