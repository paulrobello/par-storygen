"""Shared prompt builders for image providers.

Consolidates portrait/scene prompt construction so every backend (OpenAI,
Gemini, Z.AI, Ollama) emits consistent framing / art-style / anti-prop
language.  Builders accept an optional ``model`` parameter; when a
gpt-image-2 model is detected the prompt uses a structured 5-part format
(Scene / Composition / Constraints) with the art style placed first.
Older models (gpt-image-1 / 1.5) and non-OpenAI providers use the classic
paragraph format with ``Rendered in {style} style.`` appended.

Transparency handling: when ``transparent=True`` we always emit the explicit
"Transparent PNG background" sentence. OpenAI (gpt-image-1 / 1.5) additionally
enforces transparency via the ``background="transparent"`` API flag on
``images.generate`` (set at the call site, not here); the prompt hint is
harmless alongside the flag. gpt-image-2 does NOT support the transparent
background flag — the ``openai_provider`` detects this and falls back to
``background="opaque"``, relying solely on the prompt text. Gemini / Z.AI /
Ollama have no such flag, so the prompt sentence is the only signal they get.
"""

from __future__ import annotations

from storygen.images.base import ReferencePortrait


def _is_v2_model(model: str | None) -> bool:
    """Return True if the model is gpt-image-2 (or a snapshot thereof).

    ``None`` returns False (non-OpenAI providers or callers that don't
    specify a model — they get the classic paragraph format).
    """
    return model is not None and model.startswith("gpt-image-2")


def build_portrait_prompt(
    description: str,
    *,
    transparent: bool,
    art_style: str,
    model: str | None = None,
) -> str:
    """Wrap a raw character description with full-body portrait framing.

    When ``model`` starts with ``"gpt-image-2"`` the prompt uses a structured
    format with labeled sections and art style placed first (recommended for
    gpt-image-2).  For all other models the classic paragraph format is used
    with ``Rendered in {art_style} style.`` appended.

    Args:
        description: Raw character appearance text.
        transparent: Whether the caller asked for a transparent background.
        art_style: Visual style guidance (e.g. ``"children's story book"``).
        model: Optional model id to select the prompt format. When ``None``,
            defaults to the structured (v2) format.

    Returns:
        The full user-facing portrait prompt.
    """
    if transparent:
        background_rule = (
            "Transparent PNG background, subject only, no background, no scenery, "
            "no shadow on the ground"
        )
    else:
        background_rule = "plain neutral background"

    if _is_v2_model(model):
        return (
            f"Art style: {art_style} illustration.\n"
            "Scene: Full-length wide shot of a single character standing on the "
            "ground, shown from the very top of the head to the soles of the feet.\n"
            "Composition: The figure occupies roughly the central two-thirds of "
            "the vertical frame. Leave clear empty space above the head and clear "
            "empty space below the feet. Do NOT crop the head, hair, hands, or "
            "feet. Front-facing, relaxed neutral pose with arms at the sides and "
            "hands empty and open, looking directly at the viewer. Even soft "
            f"lighting, sharp focus. {background_rule}.\n"
            "Constraints: No props, no weapons, no tools, no bags, no instruments, "
            "no food, no accessories beyond the clothing described. This is a "
            "neutral reference portrait — anything held or carried here would "
            "incorrectly persist across every scene.\n\n"
            f"Character: {description}"
        )

    # Classic paragraph format for gpt-image-1 / 1.5 and non-OpenAI providers.
    return (
        "Full-length wide shot of a single character standing on the ground, "
        "shown from the very top of the head to the soles of the feet. "
        "Compose the figure so it occupies roughly the central two-thirds of "
        "the vertical frame: leave clear empty space above the head and "
        "clear empty space below the feet — do NOT crop the head, hair, "
        "hands, or feet. The character is front-facing, standing in a "
        "relaxed neutral pose with arms at the sides and hands empty and "
        "open, looking directly at the viewer. The character must NOT be "
        "holding, carrying, or wearing any props, weapons, tools, bags, "
        "instruments, food, or accessories beyond the clothing described — "
        "this image is a neutral reference used to compose other scenes, so "
        "anything held here would incorrectly persist across every scene. "
        "Show the entire body in a single uncropped figure. "
        f"{background_rule}. Even soft lighting, sharp focus. "
        f"Rendered in {art_style} style.\n\n"
        f"Character: {description}"
    )


def build_scene_ref_guidance(reference_portraits: list[ReferencePortrait]) -> str:
    """Build reference image identification text for scene prompts."""
    if not reference_portraits:
        return ""
    lines = [f"  Image {i + 1}: {rp.name}" for i, rp in enumerate(reference_portraits)]
    return "\n\nReference images provided:\n" + "\n".join(lines)


def build_scene_prompt(
    prompt: str,
    *,
    art_style: str,
    model: str | None = None,
    reference_portraits: list[ReferencePortrait] | None = None,
) -> str:
    """Wrap a raw scene prompt with art-style framing.

    gpt-image-2: style is prepended (``Art style: …``) so the model anchors
    on it early. Older models: ``Rendered in {art_style} style.`` is appended.

    Args:
        prompt: The raw scene description.
        art_style: Visual style guidance so renders match portraits.
        model: Optional model id to select the prompt format.
        reference_portraits: Optional reference portraits with names to identify
            in the prompt so the image model can match characters.

    Returns:
        The styled scene prompt.
    """
    if _is_v2_model(model):
        result = f"Art style: {art_style} illustration.\n\n{prompt}"
    else:
        result = f"{prompt}\n\nRendered in {art_style} style."

    if reference_portraits:
        result += build_scene_ref_guidance(reference_portraits)

    return result


def build_cover_prompt(
    *,
    theme_title: str,
    theme_description: str,
    art_style: str,
    model: str | None = None,
) -> str:
    """Build a decorative book-cover illustration prompt.

    gpt-image-2: structured format with explicit text-rendering guidance
    (leveraging its ~99% text accuracy). Older models: paragraph format.

    Args:
        theme_title: The story's title (displayed prominently in the art).
        theme_description: Short theme blurb for mood/setting cues.
        art_style: Visual style guidance (e.g. ``"children's story book"``).
        model: Optional model id to select the prompt format.

    Returns:
        The cover illustration prompt.
    """
    if _is_v2_model(model):
        return (
            f"Art style: {art_style} illustration.\n"
            f"Scene: Decorative book cover for a story. "
            f"The story's theme: {theme_description}.\n"
            f'Text to render: The title "{theme_title}" must appear prominently '
            "in the artwork, rendered as clean readable text.\n"
            "Constraints: No characters, no people, no dialogue, no narrative "
            "text other than the title — only the title text and decorative "
            "imagery that evokes the theme."
        )

    # Classic format for older models and non-OpenAI providers.
    return (
        f'Decorative book cover illustration for a story titled "{theme_title}". '
        f"The story's theme: {theme_description}. "
        f'The title "{theme_title}" must be prominently featured in the artwork. '
        "No characters, no people, no dialogue, no narrative text — "
        "only the title and decorative imagery. "
        f"Rendered in {art_style} style."
    )
