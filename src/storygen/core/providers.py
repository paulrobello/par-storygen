"""Declarative provider metadata registry — single source for all surfaces.

Other modules (``storage/app_state/defaults.py``, ``config.py``, the TUI
Settings screen, the FastAPI surface, the web UI) consume this registry
instead of maintaining their own parallel dicts of provider facts.

The registry is dependency-free apart from the standard library: it imports
nothing above the core layer and no provider class. Per-class capability
attributes (e.g. ``OpenAIImageProvider.supports_reference_images``) are kept
on the classes themselves for runtime consultation; this module's
``supports_reference_images`` field is the static declarative mirror, and
``tests/unit/test_provider_registry.py`` asserts the three sources agree.

See ENH-005 for the consolidation rationale.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderInfo:
    """Immutable metadata for a single provider (text or image).

    Attributes:
        id: Stable identifier used in storage, env vars, and ``Literal`` type
            declarations (e.g. ``"openai"``, ``"ollama"``).
        label: Human-readable name shown in UI selects and labels.
        kind: ``{"text"}`` or ``{"image"}`` — surfaces that mix provider tabs
            filter on this. TTS providers are out of scope for ENH-005.
        key_env_var: Environment variable holding the provider's API key, or
            ``None`` for local / no-auth providers (Ollama).
        default_model: Hardcoded default model for the provider (OpenAI text
            ``gpt-4o-mini`` and image ``gpt-image-2``), or ``None`` when the
            user must pick one (OpenRouter, Ollama, Gemini, Z.AI images).
        default_base_url: Provider's default OpenAI-compatible base URL, or
            ``None`` when not applicable (Gemini's ``google-genai`` SDK ignores
            OpenAI-style URLs).
        allows_loopback_base_url: Mirrors
            :func:`storygen_api.security.validate_provider_base_url`'s
            ``allow_loopback`` policy — ``True`` only for Ollama (local server).
            The SSRF host allowlist itself stays in ``security.py``; this
            boolean is the per-provider fact. Wired into security.py by a
            later ENH-005 task — T1 only records the value.
        supports_reference_images: Image-provider capability (ARC-115).
            ``True`` for OpenAI / Gemini, ``False`` for Z.AI / Ollama. Always
            ``False`` for text providers (image-only concept).
        suggested_models: Curated model suggestions for the Settings screen.
    """

    id: str
    label: str
    kind: frozenset[str]
    key_env_var: str | None
    default_model: str | None
    default_base_url: str | None
    allows_loopback_base_url: bool
    supports_reference_images: bool
    suggested_models: tuple[str, ...] = ()


# ─── Text providers ──────────────────────────────────────────────────────────
# Source citations per field (verify against these lines if a value drifts):
#   label / suggested_models:
#     storage/app_state/defaults.py PROVIDER_CHOICES + SUGGESTED_MODELS
#   key_env_var:
#     config.py text-side ``_KEY_ENV`` map (pre-ENH-005)
#   default_base_url:
#     llm/provider_factory.py:13-17 ``_DEFAULT_BASE_URLS``
#   allows_loopback_base_url:
#     storygen_api/security.py:294-311 ``_PROVIDER_VALIDATORS``
#   default_model:
#     storage/app_state/defaults.py DEFAULT_TEXT_MODEL (OpenAI only)
#   supports_reference_images:
#     always False for text providers (image-only concept)
TEXT_PROVIDERS: dict[str, ProviderInfo] = {
    "openai": ProviderInfo(
        id="openai",
        label="OpenAI",
        kind=frozenset({"text"}),
        key_env_var="OPENAI_API_KEY",
        default_model="gpt-4o-mini",
        default_base_url="https://api.openai.com/v1",
        allows_loopback_base_url=False,
        supports_reference_images=False,
        suggested_models=("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"),
    ),
    "openrouter": ProviderInfo(
        id="openrouter",
        label="OpenRouter",
        kind=frozenset({"text"}),
        key_env_var="OPENROUTER_API_KEY",
        default_model=None,
        default_base_url="https://openrouter.ai/api/v1",
        allows_loopback_base_url=False,
        supports_reference_images=False,
        suggested_models=(
            "anthropic/claude-3.5-sonnet",
            "meta-llama/llama-3.3-70b-instruct",
        ),
    ),
    "ollama": ProviderInfo(
        id="ollama",
        label="Ollama (local)",
        kind=frozenset({"text"}),
        key_env_var=None,
        default_model=None,
        default_base_url="http://localhost:11434/v1",
        allows_loopback_base_url=True,
        supports_reference_images=False,
        suggested_models=("llama3.3:70b", "qwen2.5:32b-instruct"),
    ),
}


# ─── Image providers ─────────────────────────────────────────────────────────
# Source citations per field (verify against these lines if a value drifts):
#   label / suggested_models / key_env_var:
#     storage/app_state/defaults.py IMAGE_PROVIDER_CHOICES +
#     SUGGESTED_IMAGE_MODELS + IMAGE_API_KEY_ENV (pre-ENH-005)
#   default_base_url:
#     images/provider_factory.py:183-188 ``resolve_image_base_url``
#     (Gemini returns "" → recorded as None here, see docstring)
#   allows_loopback_base_url:
#     storygen_api/security.py:294-311 ``_PROVIDER_VALIDATORS``
#   default_model:
#     storage/app_state/defaults.py DEFAULT_IMAGE_MODEL (OpenAI only)
#   supports_reference_images:
#     images/<name>_provider.py class attribute (ARC-115)
IMAGE_PROVIDERS: dict[str, ProviderInfo] = {
    "openai": ProviderInfo(
        id="openai",
        label="OpenAI gpt-image",
        kind=frozenset({"image"}),
        key_env_var="OPENAI_API_KEY",
        default_model="gpt-image-2",
        default_base_url="https://api.openai.com/v1",
        allows_loopback_base_url=False,
        supports_reference_images=True,
        suggested_models=("gpt-image-2", "gpt-image-1.5", "gpt-image-1"),
    ),
    "gemini": ProviderInfo(
        id="gemini",
        label="Google Gemini (Nano Banana 2/Pro)",
        kind=frozenset({"image"}),
        key_env_var="GEMINI_API_KEY",
        default_model=None,
        default_base_url=None,
        allows_loopback_base_url=False,
        supports_reference_images=True,
        suggested_models=(
            "gemini-3.1-flash-image-preview",
            "gemini-3-pro-image-preview",
        ),
    ),
    "zai": ProviderInfo(
        id="zai",
        label="Z.AI GLM-image",
        kind=frozenset({"image"}),
        key_env_var="ZAI_API_KEY",
        default_model=None,
        default_base_url="https://api.z.ai/api/paas/v4/",
        allows_loopback_base_url=False,
        supports_reference_images=False,
        suggested_models=("glm-image",),
    ),
    "ollama": ProviderInfo(
        id="ollama",
        label="Ollama (local, macOS-only)",
        kind=frozenset({"image"}),
        key_env_var=None,
        default_model=None,
        default_base_url="http://localhost:11434/v1/",
        allows_loopback_base_url=True,
        supports_reference_images=False,
        suggested_models=("x/z-image-turbo", "x/flux2-klein:4b", "x/flux2-klein:9b"),
    ),
}
