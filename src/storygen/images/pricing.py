"""Per-provider image cost tables, consolidated.

v1.0 had OpenAI's table inside ``openai_provider.py``. That was fine for a
single backend; once we have Gemini, Z.AI, and Ollama — each with a different
pricing shape (per-size-quality pair for OpenAI, per-resolution-tier for
Gemini, free for Ollama, etc.) — the PlayScreen header and wizard need one
number regardless of provider.

This module is that single dispatch point. All call sites import
``image_cost`` from here; the legacy ``openai_provider.image_cost`` shim
was removed in the QA-008 cleanup (it had a different signature from this
function, creating a silent-wrong-pricing footgun).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# OpenAI gpt-image-2 / gpt-image-1.5 / gpt-image-1 Standard pricing (USD per image).
# ---------------------------------------------------------------------------
# Based on published Standard pricing as of 2026-04. gpt-image-2 uses token-
# based pricing ($8/1M image input, $30/1M image output) that maps to very
# similar per-image costs as gpt-image-1.5. Treat as best-effort estimates —
# the real charged value is not returned in the response, so we approximate
# from the request parameters.
_OPENAI_IMAGE_COST_USD: dict[tuple[str, str], float] = {
    ("1024x1024", "low"): 0.011,
    ("1024x1024", "medium"): 0.042,
    ("1024x1024", "high"): 0.167,
    ("1024x1024", "auto"): 0.042,  # auto typically resolves to medium
    ("1024x1536", "low"): 0.016,
    ("1024x1536", "medium"): 0.063,
    ("1024x1536", "high"): 0.25,
    ("1024x1536", "auto"): 0.063,
    ("1536x1024", "low"): 0.016,
    ("1536x1024", "medium"): 0.063,
    ("1536x1024", "high"): 0.25,
    ("1536x1024", "auto"): 0.063,
}

# Per-reference-image input cost charged by ``images.edit``. Approximated.
_OPENAI_EDIT_INPUT_COST_PER_REF_USD: float = 0.003

# Per-partial-image surcharge when ``stream=True`` is used with
# ``partial_images=N``. Each intermediate preview costs 100 output image
# tokens, billed at $30.00/1M for gpt-image-2 (2026-04 pricing) =
# $0.0030 per partial. The final image is included in the base cost.
_OPENAI_PARTIAL_IMAGE_COST_USD: float = 0.003


# ---------------------------------------------------------------------------
# Google Gemini Nano Banana 2 / Pro pricing (USD per image, Standard tier).
# ---------------------------------------------------------------------------
# Gemini bills per-resolution-tier, not per-size-quality. The tiers below
# cover 2026-04 published pricing.
_GEMINI_FLASH_IMAGE_COST_BY_RESOLUTION: dict[str, float] = {
    "0.5K": 0.045,
    "1K": 0.067,
    "2K": 0.101,
    "4K": 0.151,
}
_GEMINI_PRO_IMAGE_COST_BY_RESOLUTION: dict[str, float] = {
    # Pro's 1K and 2K are billed the same.
    "1K": 0.134,
    "2K": 0.134,
    "4K": 0.240,
}


# ---------------------------------------------------------------------------
# Z.AI GLM-image (flat) and Ollama (free) pricing.
# ---------------------------------------------------------------------------
# Z.AI bills a single rate per generated image regardless of size or quality
# (2026-04); Ollama is local inference and has no per-image cost.
_ZAI_IMAGE_COST_USD: float = 0.015
_OLLAMA_IMAGE_COST_USD: float = 0.0


def _gemini_tier_for_size(size: str) -> str:
    """Map a pixel size like ``"1024x1024"`` to a Gemini resolution tier label.

    Uses the larger of width/height so rectangular outputs (e.g. portrait
    1024x1536) still land on the correct tier. Unknown sizes fall back to
    ``"1K"`` — never raise; cost estimation must not break gameplay.
    """
    try:
        w_str, h_str = size.lower().split("x", 1)
        longest = max(int(w_str), int(h_str))
    except (ValueError, AttributeError):
        return "1K"
    if longest <= 512:
        return "0.5K"
    if longest <= 1536:
        # 1024 and 1536 both belong to the 1K tier on Gemini's published
        # Standard pricing; there is no dedicated 1.5K tier.
        return "1K"
    if longest <= 2048:
        return "2K"
    return "4K"


def openai_image_cost(
    size: str,
    quality: str = "auto",
    *,
    num_input_refs: int = 0,
    partial_images: int = 0,
) -> float:
    """Estimate the USD cost of one OpenAI image generation call.

    Args:
        size: Output size string, e.g. ``"1024x1024"``.
        quality: Quality tier — ``"low"`` / ``"medium"`` / ``"high"`` /
            ``"auto"``.
        num_input_refs: Reference portraits sent to ``images.edit``; 0 for
            plain ``images.generate``.
        partial_images: Number of intermediate preview images requested via
            ``stream=True, partial_images=N``. Each adds a flat surcharge
            (~$0.0030 at 2026-04 gpt-image-2 pricing). 0 for non-streaming.

    Returns:
        Estimated cost in USD. Returns ``0.0`` for unknown size/quality combos
        rather than raising — pricing must never break gameplay.
    """
    base = _OPENAI_IMAGE_COST_USD.get((size, quality), 0.0)
    return (
        base
        + _OPENAI_EDIT_INPUT_COST_PER_REF_USD * num_input_refs
        + _OPENAI_PARTIAL_IMAGE_COST_USD * partial_images
    )


def gemini_image_cost(model: str, size: str) -> float:
    """Estimate the USD cost of one Gemini image generation call.

    Args:
        model: Gemini model id. Anything containing ``"pro"`` (case-insensitive)
            is billed against the Pro table; otherwise the Flash (Nano Banana
            2) table.
        size: Pixel size string, e.g. ``"1024x1024"``. Used only to pick a
            resolution tier (``0.5K`` / ``1K`` / ``2K`` / ``4K``).

    Returns:
        Estimated cost in USD. Returns ``0.0`` for unknown tiers.
    """
    tier = _gemini_tier_for_size(size)
    if "pro" in model.lower():
        return _GEMINI_PRO_IMAGE_COST_BY_RESOLUTION.get(tier, 0.0)
    return _GEMINI_FLASH_IMAGE_COST_BY_RESOLUTION.get(tier, 0.0)


def zai_image_cost() -> float:
    """Return the flat per-image USD cost for Z.AI GLM-image."""
    return _ZAI_IMAGE_COST_USD


def ollama_image_cost() -> float:
    """Return the per-image USD cost for Ollama local inference (always 0)."""
    return _OLLAMA_IMAGE_COST_USD


def image_cost(
    provider: str,
    *,
    model: str,
    size: str,
    quality: str = "auto",
    num_input_refs: int = 0,
    partial_images: int = 0,
) -> float:
    """Single-dispatch cost helper — pick the right table for ``provider``.

    Args:
        provider: One of ``"openai"`` / ``"gemini"`` / ``"zai"`` / ``"ollama"``.
            Anything else yields ``0.0``.
        model: Provider-specific model id. Only consulted by providers whose
            pricing varies by model (currently: Gemini).
        size: Pixel size string; OpenAI / Gemini interpret this. Z.AI and
            Ollama ignore it — their rates are flat.
        quality: OpenAI-only quality tier; ignored by other providers.
        num_input_refs: OpenAI-only per-ref edit surcharge; ignored by others.
        partial_images: OpenAI-only streaming-preview surcharge; ignored by
            others (no other provider supports partial-image streaming).

    Returns:
        Estimated cost in USD. Always ``>= 0.0``.
    """
    if provider == "openai":
        return openai_image_cost(
            size,
            quality,
            num_input_refs=num_input_refs,
            partial_images=partial_images,
        )
    if provider == "gemini":
        return gemini_image_cost(model, size)
    if provider == "zai":
        return zai_image_cost()
    if provider == "ollama":
        return ollama_image_cost()
    return 0.0
