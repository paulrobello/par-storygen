"""Unit tests for the shared image-prompt builders in ``images/_prompts.py``.

These helpers back the OpenAI, Gemini, Z.AI, and Ollama providers; the
per-provider tests exercise the surrounding code path but we pin the prompt
shapes here directly so future providers reusing the helpers can lean on a
single authoritative test file.
"""

from __future__ import annotations

from storygen.images._prompts import build_cover_prompt, build_portrait_prompt, build_scene_prompt


def test_portrait_transparent_includes_transparent_png_phrase() -> None:
    """When transparent is requested, the explicit ``"Transparent PNG"``
    sentence must appear. OpenAI additionally sets
    ``background="transparent"`` via an API flag at the call site; the
    prompt sentence is harmless alongside the flag and is the only signal
    prompt-only providers (Gemini, Z.AI, Ollama) get."""
    out = build_portrait_prompt(
        "a tall rogue",
        transparent=True,
        art_style="watercolor",
    )
    assert "Transparent PNG" in out
    assert "transparent" in out.lower()


def test_portrait_opaque_uses_plain_neutral_background() -> None:
    """When ``transparent=False`` the prompt asks for a ``plain neutral
    background`` and does NOT mention transparency."""
    out = build_portrait_prompt("a cat", transparent=False, art_style="noir")
    assert "plain neutral background" in out
    assert "Transparent PNG" not in out


def test_portrait_includes_art_style_prefix() -> None:
    out = build_portrait_prompt(
        "a tall rogue",
        transparent=False,
        art_style="watercolor",
    )
    assert "watercolor" in out
    # Full-body framing directives must also be there.
    assert "full-length" in out.lower() or "full-body" in out.lower()
    assert "front-facing" in out.lower()
    assert "feet" in out.lower()
    # Description must be preserved verbatim.
    assert "a tall rogue" in out


def test_portrait_prop_ban_is_present() -> None:
    """Portraits are reference anchors — props must be explicitly banned."""
    # Default (model=None) uses classic format.
    out = build_portrait_prompt(
        "a tall rogue",
        transparent=False,
        art_style="watercolor",
    )
    assert "must NOT be holding" in out or "no props" in out.lower()


def test_scene_prompt_appends_art_style() -> None:
    # Default (model=None) uses classic format with appended style.
    out = build_scene_prompt("a wheat field at dusk", art_style="watercolor")
    assert "a wheat field at dusk" in out
    assert "Rendered in watercolor style." in out


def test_scene_prompt_default_style_respected_at_call_site() -> None:
    """Helper has no default; callers pass their own. Verifies caller contract."""
    out = build_scene_prompt("prompt", art_style="children's story book")
    assert "Rendered in children's story book style." in out


def test_scene_prompt_v2_format() -> None:
    """gpt-image-2 gets the structured format with style prepended."""
    out = build_scene_prompt("a wheat field at dusk", art_style="watercolor", model="gpt-image-2")
    assert "a wheat field at dusk" in out
    assert "Art style: watercolor illustration." in out


def test_scene_prompt_includes_character_facing_object_guidance() -> None:
    out = build_scene_prompt("Olivia reads from a tablet", art_style="comic book")
    assert "Spatial orientation:" in out
    assert "orient the visible surface toward that character" in out
    assert "not toward the viewer" in out
    assert "gaze and hands" in out


def test_scene_prompt_v2_includes_character_facing_object_guidance() -> None:
    out = build_scene_prompt(
        "Olivia reads from a tablet",
        art_style="comic book",
        model="gpt-image-2",
    )
    assert "Spatial orientation:" in out
    assert "orient the visible surface toward that character" in out


def test_scene_prompt_prevents_screens_on_device_backs() -> None:
    out = build_scene_prompt("Marcus holds a tablet", art_style="comic book")
    assert "only the front/display side contains screen content" in out
    assert "plain physical back/case" in out
    assert "no glowing UI" in out
    assert "Do not put a readable display on the back side" in out


def test_scene_prompt_defaults_idle_held_devices_to_non_display_side() -> None:
    out = build_scene_prompt(
        "Olivia holds a phone while looking across the crowd",
        art_style="comic book",
    )
    assert "holding or carrying a device" in out
    assert "not actively using it or deliberately showing its screen" in out
    assert "default to the blank back/case" in out
    assert "screen turned or tilted away" in out


def test_cover_prompt_includes_title() -> None:
    out = build_cover_prompt(
        theme_title="The Lost Kingdom",
        theme_description="A quest to reclaim a fallen realm",
        art_style="children's story book",
    )
    assert "The Lost Kingdom" in out


def test_cover_prompt_includes_art_style() -> None:
    # Default (model=None) uses classic format.
    out = build_cover_prompt(
        theme_title="Dark Tides",
        theme_description="Pirates on the open sea",
        art_style="watercolor noir",
    )
    assert "Rendered in watercolor noir style." in out


def test_cover_prompt_v2_format() -> None:
    """gpt-image-2 gets the structured format with text-rendering guidance."""
    out = build_cover_prompt(
        theme_title="Dark Tides",
        theme_description="Pirates on the open sea",
        art_style="watercolor noir",
        model="gpt-image-2",
    )
    assert "Art style: watercolor noir illustration." in out
    assert "Text to render:" in out


def test_cover_prompt_bans_characters_and_narrative() -> None:
    out = build_cover_prompt(
        theme_title="X",
        theme_description="Y",
        art_style="Z",
    )
    assert "No characters" in out
    assert "no narrative text" in out.lower()


def test_cover_prompt_includes_description() -> None:
    out = build_cover_prompt(
        theme_title="T",
        theme_description="A journey through time and space",
        art_style="A",
    )
    assert "A journey through time and space" in out
