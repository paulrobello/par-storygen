"""Bundled widget + refresh/sync logic for one image-provider section of SettingsScreen.

The image and character-image provider sections in :class:`SettingsScreen`
share identical refresh/sync logic — only the widget references differ. This
class removes that duplication: the screen constructs the widgets (with their
load-bearing CSS ids intact) and hands them to a section instance, which
owns the four shared operations (api-key status, suggested-models hint,
model-select sync, model-options).

The screen's text-provider section is structurally different (a plain
``Input`` instead of a ``Select + Input`` pair, ``api_key_env_var`` instead
of ``IMAGE_API_KEY_ENV``, ``SUGGESTED_MODELS`` instead of
``SUGGESTED_IMAGE_MODELS``) and exists only once, so it is intentionally
not folded in here — there is no duplication to remove (per repo §2).
"""

from __future__ import annotations

import os

from textual.widgets import Input, Select, Static

from storygen.screens.controllers.settings_image import (
    image_model_options,
    model_select_state,
)
from storygen.storage import app_state


class ImageProviderSection:
    """One image-provider section's widgets + the shared refresh/sync logic.

    The owning screen constructs the five widgets (preserving their CSS ids)
    and passes the ``custom_model`` sentinel shared with the screen. The four
    methods below were previously duplicated verbatim between the image and
    character-image sections. No widget ids are constructed or renamed here.
    """

    def __init__(
        self,
        *,
        model_select: Select[str],
        model_input: Input,
        api_key_input: Input,
        api_key_status: Static,
        suggested: Static,
        custom_model: str,
    ) -> None:
        self._model_select = model_select
        self._model_input = model_input
        self._api_key_input = api_key_input
        self._api_key_status = api_key_status
        self._suggested = suggested
        self._custom_model = custom_model

    def refresh_api_key_status(self, provider: str) -> None:
        env_name = app_state.IMAGE_API_KEY_ENV.get(provider)
        if env_name is None:
            self._api_key_status.update("No API key required (local)")
            return
        persisted = self._api_key_input.value.strip()
        present = bool(os.environ.get(env_name))
        if persisted:
            self._api_key_status.update(f"API key ({env_name}): set in settings")
        else:
            mark = "present" if present else "missing"
            self._api_key_status.update(f"API key ({env_name}): {mark}")

    def refresh_suggested(self, provider: str) -> None:
        models = app_state.SUGGESTED_IMAGE_MODELS.get(provider, ())
        if not models:
            self._suggested.update("")
            return
        self._suggested.update(f"Suggested: {', '.join(models)}")

    def model_options(self, provider: str) -> list[tuple[str, str]]:
        """Curated image-model choices for the Select widget, plus a Custom entry."""
        return image_model_options(provider, self._custom_model)

    def sync_model_select(self, provider: str, model: str) -> None:
        """Rebuild the model Select options for ``provider`` and pick ``model``.

        If ``model`` is in the curated list for ``provider``, the Select points
        at it; otherwise the Select shows the Custom sentinel (the Input keeps
        the real value). The Input is only shown when Custom is selected.
        """
        options, target_value, show_input = model_select_state(provider, model, self._custom_model)
        with self._model_select.prevent(Select.Changed):
            self._model_select.set_options(options)
            self._model_select.value = target_value
        self._model_input.display = show_input
