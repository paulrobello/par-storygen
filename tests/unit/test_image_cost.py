"""Unit tests for the image_cost helper."""

from __future__ import annotations

from storygen.images.openai_provider import (
    PORTRAIT_QUALITY,
    PORTRAIT_SIZE,
    SCENE_QUALITY,
    SCENE_SIZE,
    image_cost,
)


def test_image_cost_low_square() -> None:
    assert image_cost("1024x1024", "low") == 0.011


def test_image_cost_low_portrait() -> None:
    assert image_cost("1024x1536", "low") == 0.016


def test_image_cost_auto_with_refs() -> None:
    # Auto on 1024x1024 = 0.042 base; +0.003 per ref image.
    assert image_cost("1024x1024", "auto", num_input_refs=2) == 0.042 + 2 * 0.003


def test_image_cost_unknown_returns_zero() -> None:
    """Unknown size/quality combos must return 0.0 — never raise."""
    assert image_cost("unknown", "fake") == 0.0
    # Unknown size with refs still adds the ref input cost (this is consistent
    # with how the function is composed: base + ref overhead).
    assert image_cost("unknown", "fake", num_input_refs=1) == 0.003


def test_provider_constants_resolve_to_known_prices() -> None:
    """The provider constants must hit the price table — guard against drift."""
    assert image_cost(PORTRAIT_SIZE, PORTRAIT_QUALITY) > 0.0
    assert image_cost(SCENE_SIZE, SCENE_QUALITY) > 0.0
