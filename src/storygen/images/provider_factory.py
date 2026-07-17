"""Image provider factory.

v1.0 shipped OpenAI only. v1.1 widens the config surface to
``openai | gemini | zai | ollama`` and validates it. All four backends now
have real adapters (Phase 2 added Gemini; Phase 3 added Z.AI + Ollama).
Phase 4 adds :func:`build_routed_image_provider` — primary + optional
fallback with ref-loss wiring.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, get_args

from storygen.core.models import ImageProviderConfig
from storygen.images.base import ImageProvider
from storygen.images.gemini_provider import GeminiImageProvider
from storygen.images.ollama_provider import OllamaImageProvider
from storygen.images.openai_provider import OpenAIImageProvider
from storygen.images.routed_provider import RoutedImageProvider
from storygen.images.zai_provider import ZaiImageProvider
from storygen.storage.app_state import (
    PROVIDER_SUPPORTS_REFS,
    SUGGESTED_IMAGE_MODELS,
)

ImageProviderName = Literal["openai", "gemini", "zai", "ollama"]

# Public so ``config.py`` can import rather than duplicate the allow-list.
ALLOWED_IMAGE_PROVIDERS: frozenset[str] = frozenset(get_args(ImageProviderName))
# Keep the underscore alias for backward compatibility with internal references.
_ALLOWED_IMAGE_PROVIDERS = ALLOWED_IMAGE_PROVIDERS


def _build(
    provider: str,
    model: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    on_ref_loss: Callable[[], None] | None = None,
) -> ImageProvider:
    if provider == "openai":
        # OpenAI supports refs natively — ignore on_ref_loss.
        return OpenAIImageProvider(model=model, base_url=base_url, api_key=api_key)
    if provider == "gemini":
        # Gemini supports refs natively — ignore on_ref_loss. ``base_url`` is
        # accepted for call-parity but ignored; the Google SDK does not
        # support OpenAI-style base URLs. ``api_key`` of ``None`` / empty
        # defers to the SDK's ``GEMINI_API_KEY`` env lookup.
        return GeminiImageProvider(model=model, api_key=api_key or None, base_url=base_url)
    if provider == "zai":
        return ZaiImageProvider(
            model=model,
            api_key=api_key,
            base_url=base_url,
            on_ref_loss=on_ref_loss,
        )
    if provider == "ollama":
        # Ollama ignores api_key; base_url lets users point at a non-default host.
        return OllamaImageProvider(
            model=model,
            base_url=base_url,
            on_ref_loss=on_ref_loss,
        )
    raise ValueError(f"unsupported image provider: {provider!r}")


def validate_image_config(config: ImageProviderConfig) -> tuple[bool, str]:
    """Return ``(ok, error_message)``; ``error_message`` is empty on success.

    Checks:
    - ``provider`` is in the allowlist (openai / gemini / zai / ollama).
    - ``model`` is a non-empty, non-whitespace string.
    - ``base_url`` is either ``None`` / empty or a plausible URL
      (starts with ``http://`` or ``https://``).

    ``api_key`` is NOT validated here — it's a per-save env-key pin that may
    legitimately be ``None`` or empty at config-resolution time.
    """
    if config.provider not in _ALLOWED_IMAGE_PROVIDERS:
        return False, f"provider must be one of {sorted(_ALLOWED_IMAGE_PROVIDERS)}"
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


def build_image_provider(
    config: ImageProviderConfig,
    *,
    on_ref_loss: Callable[[], None] | None = None,
) -> ImageProvider:
    """Construct the image provider named by ``config``.

    ``on_ref_loss`` is forwarded only to non-ref providers (Z.AI, Ollama);
    OpenAI and Gemini ignore it. See :data:`PROVIDER_SUPPORTS_REFS`.
    """
    return _build(
        config.provider,
        config.model,
        base_url=config.base_url,
        api_key=config.api_key,
        on_ref_loss=on_ref_loss,
    )


def build_routed_image_provider(
    primary_cfg: ImageProviderConfig,
    *,
    fallback_cfg: ImageProviderConfig | None = None,
    on_ref_loss: Callable[[str], None] | None = None,
    on_fallback: Callable[[str, Exception], None] | None = None,
) -> RoutedImageProvider:
    """Build primary + optional fallback with ref-loss callbacks wired.

    ``on_ref_loss(provider_label)`` is wrapped into a per-provider no-arg
    callable and passed into each non-ref provider's constructor. The label
    passed back identifies which provider dropped refs (``"zai"`` /
    ``"ollama"``).

    ``on_fallback(fallback_label, exc)`` is attached to the router and fires
    when the primary fails terminally (retries already spent).

    The router always returns; callers can treat the result as an
    :class:`storygen.images.base.ImageProvider` at runtime.
    """
    primary = build_image_provider(
        primary_cfg,
        on_ref_loss=_wrap_ref_loss(on_ref_loss, primary_cfg.provider),
    )
    fallback: ImageProvider | None
    if fallback_cfg is not None:
        fallback = build_image_provider(
            fallback_cfg,
            on_ref_loss=_wrap_ref_loss(on_ref_loss, fallback_cfg.provider),
        )
        fallback_label = fallback_cfg.provider
    else:
        fallback = None
        fallback_label = "fallback"
    return RoutedImageProvider(
        primary,
        fallback,
        primary_label=primary_cfg.provider,
        fallback_label=fallback_label,
        on_fallback=on_fallback,
    )


def _wrap_ref_loss(
    on_ref_loss: Callable[[str], None] | None,
    provider: str,
) -> Callable[[], None] | None:
    """Bind the provider label to a no-arg callback, or return None.

    Ref-support providers (OpenAI, Gemini) ignore the callback regardless,
    so we skip the wrap for them to keep the surface narrow and obvious.
    """
    if on_ref_loss is None:
        return None
    if provider in PROVIDER_SUPPORTS_REFS:
        return None
    return lambda: on_ref_loss(provider)


def resolve_image_base_url(provider: str) -> str:
    """Human-readable default base URL label for a provider, for UI hints.

    Used by :class:`~storygen.screens.settings.SettingsScreen` to populate
    placeholder text on the image-provider base-URL Input. Returns an empty
    string for providers where ``base_url`` is not applicable (Gemini's
    ``google-genai`` SDK doesn't accept OpenAI-style base URLs); the caller
    is responsible for surfacing a user-facing "(not used by <provider>)"
    label in that case.
    """
    return {
        "openai": "https://api.openai.com/v1",
        "zai": "https://api.z.ai/api/paas/v4/",
        "ollama": "http://localhost:11434/v1/",
        "gemini": "",
    }.get(provider, "")


def default_fallback_model(provider: str) -> str:
    """Return the first curated suggestion for ``provider``.

    Callers use this when the user has configured a fallback provider but
    not a specific fallback model. Returns an empty string if the provider
    has no curated suggestions (shouldn't happen for allow-listed providers).
    """
    suggestions = SUGGESTED_IMAGE_MODELS.get(provider, ())
    return suggestions[0] if suggestions else ""
