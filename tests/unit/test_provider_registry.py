"""Consistency test: registry, defaults, config, and provider classes agree.

Pins the ENH-005-T1 contract that the provider registry in
:mod:`storygen.core.providers` is the single source of truth and that the
public constants exported from ``storage.app_state`` (derived from the
registry), ``config.py``'s accepted-provider sets, and each image provider
class's ARC-115 ``supports_reference_images`` attribute all agree with it.

If any of these assertions fires, someone changed one source without
updating the others — the exact inconsistency ENH-005 was created to
prevent.
"""

from __future__ import annotations

from typing import get_args

from storygen.core.providers import IMAGE_PROVIDERS, TEXT_PROVIDERS
from storygen.images.gemini_provider import GeminiImageProvider
from storygen.images.ollama_provider import OllamaImageProvider
from storygen.images.openai_provider import OpenAIImageProvider
from storygen.images.provider_factory import (
    ALLOWED_IMAGE_PROVIDERS as _FACTORY_ALLOWED_IMAGE,
)
from storygen.images.provider_factory import ImageProviderName
from storygen.images.zai_provider import ZaiImageProvider
from storygen.llm.provider_factory import ALLOWED_PROVIDERS as _FACTORY_ALLOWED
from storygen.llm.provider_factory import Provider
from storygen.storage.app_state import (
    IMAGE_API_KEY_ENV,
    IMAGE_PROVIDER_CHOICES,
    PROVIDER_CHOICES,
    PROVIDER_SUPPORTS_REFS,
    SUGGESTED_IMAGE_MODELS,
    SUGGESTED_MODELS,
)
from storygen.storage.app_state.defaults import (
    ALLOWED_IMAGE_PROVIDERS as DEFAULTS_ALLOWED_IMAGE,
)
from storygen.storage.app_state.defaults import ALLOWED_PROVIDERS as DEFAULTS_ALLOWED

# Concrete image-provider classes — the third source of ref-capability truth
# alongside the registry field and PROVIDER_SUPPORTS_REFS. Imported on the test
# side so core/providers.py stays free of provider-class imports.
_IMAGE_PROVIDER_CLASSES: dict[str, type[object]] = {
    "openai": OpenAIImageProvider,
    "gemini": GeminiImageProvider,
    "zai": ZaiImageProvider,
    "ollama": OllamaImageProvider,
}


# ─── Public constants pinned to their pre-ENH-005 values ────────────────────
# These literals are the byte-identity contract: any drift here means the
# registry consolidation changed user-visible options.

_EXPECTED_PROVIDER_CHOICES: tuple[tuple[str, str], ...] = (
    ("OpenAI", "openai"),
    ("OpenRouter", "openrouter"),
    ("Ollama (local)", "ollama"),
)

_EXPECTED_IMAGE_PROVIDER_CHOICES: tuple[tuple[str, str], ...] = (
    ("OpenAI gpt-image", "openai"),
    ("Google Gemini (Nano Banana 2/Pro)", "gemini"),
    ("Z.AI GLM-image", "zai"),
    ("Ollama (local, macOS-only)", "ollama"),
)


def test_provider_choices_pinned() -> None:
    """PROVIDER_CHOICES / IMAGE_PROVIDER_CHOICES equal their pre-ENH-005 values."""
    assert PROVIDER_CHOICES == _EXPECTED_PROVIDER_CHOICES
    assert IMAGE_PROVIDER_CHOICES == _EXPECTED_IMAGE_PROVIDER_CHOICES


def test_provider_choices_derive_from_registry() -> None:
    """``PROVIDER_CHOICES`` / ``IMAGE_PROVIDER_CHOICES`` track the registry order."""
    assert tuple((p.label, p.id) for p in TEXT_PROVIDERS.values()) == PROVIDER_CHOICES
    assert tuple((p.label, p.id) for p in IMAGE_PROVIDERS.values()) == IMAGE_PROVIDER_CHOICES


# ─── Registry coverage == config allowlists ─────────────────────────────────


def test_text_registry_matches_factory_allowlist() -> None:
    """Every text-provider id the registry declares is accepted by config.py.

    config.py imports ``ALLOWED_PROVIDERS`` from ``llm.provider_factory``, which
    derives it from the ``Provider`` Literal type. The registry must cover (and
    not exceed) that set so ``load_config()`` accepts every documented id.
    """
    assert set(TEXT_PROVIDERS.keys()) == set(get_args(Provider))
    assert set(TEXT_PROVIDERS.keys()) == set(_FACTORY_ALLOWED)
    assert set(TEXT_PROVIDERS.keys()) == set(DEFAULTS_ALLOWED)


def test_image_registry_matches_factory_allowlist() -> None:
    """Every image-provider id the registry declares is accepted by config.py."""
    assert set(IMAGE_PROVIDERS.keys()) == set(get_args(ImageProviderName))
    assert set(IMAGE_PROVIDERS.keys()) == set(_FACTORY_ALLOWED_IMAGE)
    assert set(IMAGE_PROVIDERS.keys()) == set(DEFAULTS_ALLOWED_IMAGE)


# ─── Derived maps cover exactly the registry ids ────────────────────────────


def test_image_api_key_env_keys_match_registry() -> None:
    """IMAGE_API_KEY_ENV has exactly the registry's image ids as keys."""
    assert set(IMAGE_API_KEY_ENV.keys()) == set(IMAGE_PROVIDERS.keys())


def test_image_api_key_env_values_match_registry() -> None:
    """IMAGE_API_KEY_ENV values mirror each provider's key_env_var."""
    for pid, info in IMAGE_PROVIDERS.items():
        assert IMAGE_API_KEY_ENV[pid] == info.key_env_var


def test_provider_supports_refs_matches_registry() -> None:
    """PROVIDER_SUPPORTS_REFS is exactly the set of ref-capable image providers."""
    expected = frozenset(
        pid for pid, info in IMAGE_PROVIDERS.items() if info.supports_reference_images
    )
    assert expected == PROVIDER_SUPPORTS_REFS


def test_suggested_models_match_registry() -> None:
    """SUGGESTED_MODELS / SUGGESTED_IMAGE_MODELS mirror the registry's tuples."""
    assert set(SUGGESTED_MODELS.keys()) == set(TEXT_PROVIDERS.keys())
    for pid, info in TEXT_PROVIDERS.items():
        assert list(SUGGESTED_MODELS[pid]) == list(info.suggested_models)

    assert set(SUGGESTED_IMAGE_MODELS.keys()) == set(IMAGE_PROVIDERS.keys())
    for pid, info in IMAGE_PROVIDERS.items():
        assert tuple(SUGGESTED_IMAGE_MODELS[pid]) == tuple(info.suggested_models)


# ─── Three sources of ref-capability truth agree ────────────────────────────


def test_ref_capability_three_sources_agree() -> None:
    """For each image provider: registry field == set membership == class attr.

    ARC-115 requires the static class-level ``supports_reference_images``
    attribute on every image provider to match the declarative registry field
    and the ``PROVIDER_SUPPORTS_REFS`` set. If any one drifts, runtime ref-loss
    wiring (provider_factory._wrap_ref_loss, settings screen guards) will
    disagree with what the registry advertises.
    """
    for pid, info in IMAGE_PROVIDERS.items():
        cls = _IMAGE_PROVIDER_CLASSES[pid]
        cls_attr = getattr(cls, "supports_reference_images", None)
        in_set = pid in PROVIDER_SUPPORTS_REFS
        assert info.supports_reference_images == in_set == cls_attr, (
            f"ref-capability mismatch for {pid!r}: "
            f"registry={info.supports_reference_images}, set={in_set}, class={cls_attr}"
        )


# ─── Structural invariants on ProviderInfo ──────────────────────────────────


def test_text_providers_all_kind_text() -> None:
    """Every text-registry entry carries ``{"text"}`` as its kind."""
    for pid, info in TEXT_PROVIDERS.items():
        assert info.kind == frozenset({"text"}), f"{pid!r} has unexpected kind {info.kind}"


def test_image_providers_all_kind_image() -> None:
    """Every image-registry entry carries ``{"image"}`` as its kind."""
    for pid, info in IMAGE_PROVIDERS.items():
        assert info.kind == frozenset({"image"}), f"{pid!r} has unexpected kind {info.kind}"


def test_text_providers_never_claim_ref_support() -> None:
    """supports_reference_images is False for every text provider."""
    for pid, info in TEXT_PROVIDERS.items():
        assert info.supports_reference_images is False, (
            f"{pid!r} is a text provider advertising ref support (image-only concept)"
        )


def test_ollama_loopback_policy_consistent() -> None:
    """Ollama is the only provider with allows_loopback_base_url=True.

    Mirrors storygen_api.security._PROVIDER_VALIDATORS. If this changes,
    security.py's allow_loopback argument must change too — flag in the
    ENH-005 follow-up that wires this field into security.py.
    """
    for pid, info in TEXT_PROVIDERS.items():
        assert info.allows_loopback_base_url == (pid == "ollama"), (
            f"text {pid!r} loopback flag {info.allows_loopback_base_url} diverges from security.py"
        )
    for pid, info in IMAGE_PROVIDERS.items():
        assert info.allows_loopback_base_url == (pid == "ollama"), (
            f"image {pid!r} loopback flag {info.allows_loopback_base_url} diverges from security.py"
        )
