"""Unit tests for the extracted image-model option/select logic (ARC-012/QA-006).

Exercises the pure option-building + select-resolution that the image and
character-image sections share, without a Textual Screen. The screen-side
widget wiring is covered by ``test_settings_screen.py``.
"""

from __future__ import annotations

from storygen.screens.controllers.settings_image import (
    image_model_options,
    model_select_state,
)

CUSTOM = "__custom__"


def test_image_model_options_curated_plus_custom() -> None:
    options = image_model_options("openai", CUSTOM)
    # 3 curated openai models + the Custom entry.
    assert [v for _, v in options] == ["gpt-image-2", "gpt-image-1.5", "gpt-image-1", CUSTOM]
    assert options[-1] == ("Custom (type below)…", CUSTOM)


def test_image_model_options_unknown_provider_is_custom_only() -> None:
    options = image_model_options("never-heard-of-it", CUSTOM)
    assert options == [("Custom (type below)…", CUSTOM)]


def test_model_select_state_curated_model_selected_directly() -> None:
    options, target, show_input = model_select_state("openai", "gpt-image-1.5", CUSTOM)
    assert len(options) == 4
    assert target == "gpt-image-1.5"
    assert show_input is False


def test_model_select_state_non_curated_model_shows_custom_input() -> None:
    _options, target, show_input = model_select_state("openai", "dall-e-9000", CUSTOM)
    assert target == CUSTOM
    assert show_input is True


def test_model_select_state_single_model_provider() -> None:
    # zai has exactly one curated model.
    _options, target, show_input = model_select_state("zai", "glm-image", CUSTOM)
    assert target == "glm-image"
    assert show_input is False
