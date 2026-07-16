"""Pure image-model option + select-resolution logic for :class:`SettingsScreen`.

The image and character-image provider sections each pair a curated-model
``Select`` with a free-text ``Input`` (for models outside the curated list).
The logic that builds the Select's option list and resolves which entry a
given model string maps to is identical across both sections and has no
widget dependency — extracted here so it is unit-testable and not duplicated.
"""

from __future__ import annotations

from storygen.storage import app_state


def image_model_options(provider: str, custom_model: str) -> list[tuple[str, str]]:
    """Curated image-model choices for a Select, plus a Custom entry.

    Returns ``[(label, value), ...]``: each curated model becomes a
    ``(model, model)`` entry, then ``("Custom (type below)…", custom_model)``
    is appended so the user can type a non-listed model in the Input without
    losing Select state.
    """
    curated = app_state.SUGGESTED_IMAGE_MODELS.get(provider, ())
    options: list[tuple[str, str]] = [(m, m) for m in curated]
    options.append(("Custom (type below)…", custom_model))
    return options


def model_select_state(
    provider: str,
    model: str,
    custom_model: str,
) -> tuple[list[tuple[str, str]], str, bool]:
    """Build the Select options for ``provider`` and resolve ``model``.

    Returns ``(options, target_value, show_custom_input)`` in one pass: if
    ``model`` is in the curated list the Select points at it and the custom
    Input is hidden; otherwise the Select points at the Custom sentinel and
    the Input is shown.
    """
    options = image_model_options(provider, custom_model)
    curated_values = {v for _, v in options if v != custom_model}
    target_value = model if model in curated_values else custom_model
    return options, target_value, target_value == custom_model
