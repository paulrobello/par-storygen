"""Unit tests for the consolidated image pricing module."""

from __future__ import annotations

from storygen.images.constants import (
    PORTRAIT_QUALITY,
    PORTRAIT_SIZE,
    SCENE_QUALITY,
    SCENE_SIZE,
)
from storygen.images.pricing import (
    gemini_image_cost,
    image_cost,
    ollama_image_cost,
    openai_image_cost,
    zai_image_cost,
)


def test_openai_image_cost_matches_legacy_table() -> None:
    """The consolidated table must match the v1.0 numbers call sites expect."""
    assert openai_image_cost("1024x1024", "low") == 0.011
    assert openai_image_cost("1024x1024", "medium") == 0.042
    assert openai_image_cost("1024x1024", "high") == 0.167
    assert openai_image_cost("1024x1024", "auto") == 0.042
    assert openai_image_cost("1024x1536", "low") == 0.016
    assert openai_image_cost("1024x1536", "auto") == 0.063


def test_provider_constants_hit_price_table() -> None:
    """The PORTRAIT/SCENE size+quality constants must resolve to a real price.

    Guards against constant drift: if PORTRAIT_SIZE or SCENE_QUALITY ever
    changes to a value missing from the OpenAI table, production cost tracking
    would silently zero out. This catches that regression at test time.
    """
    assert openai_image_cost(PORTRAIT_SIZE, PORTRAIT_QUALITY) > 0.0
    assert openai_image_cost(SCENE_SIZE, SCENE_QUALITY) > 0.0


def test_openai_image_cost_unknown_returns_zero() -> None:
    """Unknown size/quality never raises — pricing must not break gameplay."""
    assert openai_image_cost("fake", "mystery") == 0.0
    # Ref surcharge still applies even when base lookup misses.
    assert openai_image_cost("fake", "mystery", num_input_refs=3) == 3 * 0.003


def test_openai_image_cost_partial_images_surcharge() -> None:
    """Each partial image adds $0.003 (2026-04 gpt-image-2 pricing)."""
    base = openai_image_cost("1024x1024", "auto")
    delta = openai_image_cost("1024x1024", "auto", partial_images=2) - base
    # Allow tiny float slop; the surcharge is $0.003 * 2.
    assert abs(delta - 0.006) < 1e-9
    # Additive with refs: base + 2 refs ($0.003 each) + 2 partials ($0.003 each).
    delta_with_refs = (
        openai_image_cost("1024x1024", "auto", num_input_refs=2, partial_images=2) - base
    )
    assert abs(delta_with_refs - (2 * 0.003 + 2 * 0.003)) < 1e-9


def test_image_cost_dispatch_openai_partial_images() -> None:
    """The dispatcher threads partial_images to the OpenAI table."""
    base = image_cost("openai", model="gpt-image-2", size="1024x1024", quality="auto")
    with_partials = image_cost(
        "openai",
        model="gpt-image-2",
        size="1024x1024",
        quality="auto",
        partial_images=2,
    )
    assert abs((with_partials - base) - 0.006) < 1e-9


def test_image_cost_dispatch_non_openai_ignores_partial_images() -> None:
    """partial_images is OpenAI-only; other providers must not be surcharged."""
    base_gemini = image_cost("gemini", model="gemini-3.1-flash-image-preview", size="1024x1024")
    with_partials_gemini = image_cost(
        "gemini",
        model="gemini-3.1-flash-image-preview",
        size="1024x1024",
        partial_images=2,
    )
    assert with_partials_gemini == base_gemini
    assert image_cost("zai", model="glm-image", size="x", partial_images=2) == zai_image_cost()
    assert image_cost("ollama", model="x", size="x", partial_images=2) == ollama_image_cost()


def test_gemini_flash_image_cost_per_tier() -> None:
    """Nano Banana 2 / Flash pricing per resolution tier (2026-04)."""
    assert gemini_image_cost("gemini-3.1-flash-image-preview", "512x512") == 0.045
    assert gemini_image_cost("gemini-3.1-flash-image-preview", "1024x1024") == 0.067
    assert gemini_image_cost("gemini-3.1-flash-image-preview", "2048x2048") == 0.101
    assert gemini_image_cost("gemini-3.1-flash-image-preview", "4096x4096") == 0.151


def test_gemini_pro_image_cost_per_tier() -> None:
    """Nano Banana Pro pricing per resolution tier."""
    assert gemini_image_cost("gemini-3-pro-image-preview", "1024x1024") == 0.134
    assert gemini_image_cost("gemini-3-pro-image-preview", "2048x2048") == 0.134
    assert gemini_image_cost("gemini-3-pro-image-preview", "4096x4096") == 0.240


def test_gemini_cost_uses_longest_side() -> None:
    """Rectangular outputs (e.g. portrait 1024x1536) bill at the larger tier."""
    # 1536 still fits inside the 1K tier.
    assert gemini_image_cost("gemini-3.1-flash-image-preview", "1024x1536") == 0.067
    # 3000 jumps to 4K.
    assert gemini_image_cost("gemini-3.1-flash-image-preview", "2048x3000") == 0.151


def test_gemini_cost_unknown_size_returns_zero_or_fallback() -> None:
    """Malformed sizes fall back to the 1K tier and never raise."""
    # Unparseable strings land on 1K fallback, which is defined for Flash.
    assert gemini_image_cost("gemini-3.1-flash-image-preview", "garbage") == 0.067


def test_image_cost_dispatch_openai() -> None:
    assert image_cost("openai", model="gpt-image-2", size="1024x1024", quality="low") == 0.011
    assert (
        image_cost(
            "openai",
            model="gpt-image-2",
            size="1024x1024",
            quality="auto",
            num_input_refs=2,
        )
        == 0.042 + 2 * 0.003
    )


def test_image_cost_dispatch_gemini_flash() -> None:
    assert image_cost("gemini", model="gemini-3.1-flash-image-preview", size="1024x1024") == 0.067


def test_image_cost_dispatch_gemini_pro_square() -> None:
    assert image_cost("gemini", model="gemini-3-pro-image-preview", size="1024x1024") == 0.134


def test_image_cost_dispatch_gemini_pro_4k() -> None:
    assert image_cost("gemini", model="gemini-3-pro-image-preview", size="4096x4096") == 0.240


def test_zai_image_cost_is_flat() -> None:
    """Z.AI bills one rate per image regardless of size/quality."""
    assert zai_image_cost() == 0.015


def test_ollama_image_cost_is_zero() -> None:
    """Ollama is local inference — no per-image cost."""
    assert ollama_image_cost() == 0.0


def test_image_cost_dispatch_zai_flat() -> None:
    """Phase 3: Z.AI dispatch returns flat 0.015/image regardless of size."""
    assert image_cost("zai", model="glm-image", size="1024x1024") == 0.015
    assert image_cost("zai", model="glm-image", size="1280x1280") == 0.015
    assert image_cost("zai", model="glm-image", size="2048x2048") == 0.015


def test_image_cost_dispatch_ollama_is_zero() -> None:
    """Phase 3: Ollama dispatch is always 0."""
    assert image_cost("ollama", model="x/z-image-turbo", size="1024x1024") == 0.0
    assert image_cost("ollama", model="x/flux-klein", size="1024x1024") == 0.0


def test_image_cost_dispatch_unknown_provider_returns_zero() -> None:
    assert image_cost("nebula", model="foo", size="1024x1024") == 0.0
