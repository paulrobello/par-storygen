"""Factory that turns a TextProviderConfig into a pydantic-ai Model instance."""

from __future__ import annotations

import os
from typing import Literal, get_args

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from storygen.llm.models import TextProviderConfig

_DEFAULT_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
}

Provider = Literal["openai", "openrouter", "ollama"]

# Public so ``config.py`` can import rather than duplicate the allow-list.
ALLOWED_PROVIDERS: frozenset[str] = frozenset(get_args(Provider))
# Keep the underscore alias for backward compatibility with internal references.
_ALLOWED_PROVIDERS = ALLOWED_PROVIDERS


def resolve_base_url(provider: Provider, override: str | None = None) -> str:
    """Pick the request URL for a given provider, honoring an explicit override."""
    if override:
        return override
    return _DEFAULT_BASE_URLS[provider]


def api_key_env_var(provider: Provider) -> str | None:
    """Return the env var name holding the API key for ``provider``.

    Returns ``None`` when no key is required (Ollama runs locally).
    """
    if provider == "openai":
        return "OPENAI_API_KEY"
    if provider == "openrouter":
        return "OPENROUTER_API_KEY"
    return None  # ollama


def _api_key_for(provider: Provider) -> str:
    """Return the API key appropriate for `provider`.

    Ollama runs locally and expects no auth, so any non-empty sentinel works
    for the OpenAI-compatible client. OpenAI and OpenRouter read from env.
    """
    env = api_key_env_var(provider)
    if env is None:
        return "ollama-local"
    return os.environ.get(env, "")


def validate_config(config: TextProviderConfig) -> tuple[bool, str]:
    """Return ``(ok, error_message)``; ``error_message`` is empty on success.

    Checks:
    - ``provider`` is in the allowlist (openai / openrouter / ollama).
    - ``model`` is a non-empty, non-whitespace string.
    - ``base_url`` is either ``None`` / empty or a plausible URL
      (starts with ``http://`` or ``https://``).
    """
    if config.provider not in _ALLOWED_PROVIDERS:
        return False, f"provider must be one of {sorted(_ALLOWED_PROVIDERS)}"
    if not config.model or not config.model.strip():
        return False, "model must be a non-empty string"
    base_url = config.base_url
    if (
        base_url is not None
        and base_url != ""
        and not (base_url.startswith("http://") or base_url.startswith("https://"))
    ):
        return False, f"base_url {base_url!r} must start with http:// or https://"
    return True, ""


def build_text_model(config: TextProviderConfig) -> OpenAIChatModel:
    """Construct a pydantic-ai model pointed at the configured provider."""
    base_url = resolve_base_url(config.provider, override=config.base_url)
    api_key = config.api_key if config.api_key else _api_key_for(config.provider)
    provider = OpenAIProvider(
        api_key=api_key,
        base_url=base_url,
    )
    return OpenAIChatModel(model_name=config.model, provider=provider)
