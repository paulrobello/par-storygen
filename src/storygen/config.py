"""Application-level config: dotenv loading + defaults + overrides."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import cast

from dotenv import find_dotenv, load_dotenv

from storygen.images.provider_factory import (
    ALLOWED_IMAGE_PROVIDERS as _ALLOWED_IMAGE_PROVIDERS,
)
from storygen.images.provider_factory import (
    ImageProviderName,
    validate_image_config,
)
from storygen.llm.models import ImageProviderConfig, TextProviderConfig
from storygen.llm.provider_factory import (
    ALLOWED_PROVIDERS as _ALLOWED_PROVIDERS,
)
from storygen.llm.provider_factory import (
    Provider,
    validate_config,
)
from storygen.storage import app_state

_logger = logging.getLogger(__name__)

# Lowercase so pyright doesn't treat it as an immutable module constant.
_dotenv_loaded: bool = False


def _load_dotenv_once() -> None:
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    # find_dotenv(usecwd=True) searches upward from CWD for a .env file,
    # so the app works correctly when launched from any subdirectory of the
    # project root (e.g. via `uv run` from a nested dir).
    # override=False -> real env always wins over .env file.
    load_dotenv(dotenv_path=find_dotenv(usecwd=True), override=False)
    _dotenv_loaded = True


def reset_dotenv_cache_for_tests() -> None:
    """Reset the dotenv-loaded flag so tests can re-run load_dotenv in isolation."""
    global _dotenv_loaded
    _dotenv_loaded = False


@dataclass(frozen=True)
class AppConfig:
    """Immutable runtime config resolved from env + .env + CLI overrides."""

    openai_api_key: str
    text_config: TextProviderConfig
    image_config: ImageProviderConfig


def _env_or_none(key: str) -> str | None:
    """Return the env var value, or None if unset OR empty-string."""
    value = os.environ.get(key)
    if value is None or value == "":
        return None
    return value


def _resolve_text_config() -> TextProviderConfig:
    """Merge env vars over ProviderPrefs over hardcoded defaults.

    Real env wins on any field it sets; prefs fill the rest; validation failure
    on the merged result drops everything back to ``TextProviderConfig()``.
    """
    prefs = app_state.read_provider_prefs()

    # Provider: env if valid, else prefs (already validated on read), else default.
    env_provider_raw = _env_or_none("STORYGEN_TEXT_PROVIDER")
    if env_provider_raw is not None and env_provider_raw in _ALLOWED_PROVIDERS:
        provider = env_provider_raw
    else:
        if env_provider_raw is not None:
            _logger.warning(
                "ignoring invalid STORYGEN_TEXT_PROVIDER=%r",
                env_provider_raw,
            )
        provider = prefs.provider

    model = _env_or_none("STORYGEN_TEXT_MODEL") or prefs.model

    env_base_url = _env_or_none("STORYGEN_TEXT_BASE_URL")
    base_url_raw = env_base_url if env_base_url is not None else prefs.base_url
    # Normalize "" → None so the factory uses its per-provider default URL.
    base_url: str | None = base_url_raw if base_url_raw else None

    # cast: provider was checked against _ALLOWED_PROVIDERS (which mirrors the
    # TextProviderConfig.provider literal), so the cast is sound at runtime.
    candidate = TextProviderConfig(
        provider=cast(Provider, provider),
        model=model,
        base_url=base_url,
    )
    ok, err = validate_config(candidate)
    if not ok:
        _logger.warning("falling back to default text config (%s)", err)
        return TextProviderConfig()
    return candidate


def _resolve_image_config() -> ImageProviderConfig:
    """Merge env vars over ImageProviderPrefs over hardcoded defaults.

    Real env wins on any field it sets; prefs fill the rest; validation failure
    on the merged result drops everything back to ``ImageProviderConfig()``.

    ``STORYGEN_IMAGE_API_KEY`` is read straight from env and never comes from
    prefs (api_key is an env-time pin, not a persisted preference).
    """
    prefs = app_state.read_image_provider_prefs()

    env_provider_raw = _env_or_none("STORYGEN_IMAGE_PROVIDER")
    if env_provider_raw is not None and env_provider_raw in _ALLOWED_IMAGE_PROVIDERS:
        provider = env_provider_raw
    else:
        if env_provider_raw is not None:
            _logger.warning(
                "ignoring invalid STORYGEN_IMAGE_PROVIDER=%r",
                env_provider_raw,
            )
        provider = prefs.provider

    model = _env_or_none("STORYGEN_IMAGE_MODEL") or prefs.model

    env_base_url = _env_or_none("STORYGEN_IMAGE_BASE_URL")
    base_url_raw = env_base_url if env_base_url is not None else prefs.base_url
    # Normalize "" → None so the factory uses the provider's default URL.
    base_url: str | None = base_url_raw if base_url_raw else None

    api_key = os.environ.get("STORYGEN_IMAGE_API_KEY")

    # cast: provider was checked against _ALLOWED_IMAGE_PROVIDERS (which mirrors
    # the ImageProviderConfig.provider literal), so the cast is sound at runtime.
    candidate = ImageProviderConfig(
        provider=cast(ImageProviderName, provider),
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    ok, err = validate_image_config(candidate)
    if not ok:
        _logger.warning("falling back to default image config (%s)", err)
        # Drop the api_key on fallback: if the user paired a provider-specific key
        # (e.g. Gemini) with a malformed base_url, we don't want to smuggle that
        # key into the default OpenAI config and trigger a confusing 401. Once
        # the user fixes their config, the key flows through again.
        return ImageProviderConfig()
    return candidate


def load_config() -> AppConfig:
    """Resolve config from (real env union .env file) using real env on conflicts."""
    _load_dotenv_once()

    text_config = _resolve_text_config()
    image_config = _resolve_image_config()
    return AppConfig(
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        text_config=text_config,
        image_config=image_config,
    )
