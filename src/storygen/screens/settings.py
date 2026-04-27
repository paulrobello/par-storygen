"""SettingsScreen: editable text + image provider, wizard defaults, global art toggle."""

from __future__ import annotations

import os
from typing import ClassVar, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    Switch,
    TextArea,
)

from storygen.config import AppConfig
from storygen.images.provider_factory import resolve_image_base_url
from storygen.llm.provider_factory import Provider, api_key_env_var, resolve_base_url
from storygen.screens.wizard import (
    READER_LEVEL_OPTIONS,
    STYLE_OPTIONS,
    TONE_PRESETS,
    valid_narration_style_values,
    valid_reader_level_values,
    valid_tone_preset_values,
)
from storygen.storage import app_state
from storygen.storage.app_state import (
    CharacterImageProviderPrefs,
    ImageProviderPrefs,
    ProviderPrefs,
    TTSPrefs,
    coerce_reader_level,
)
from storygen.tts.player import TTSPlayer


class TextProviderChanged(Message):
    """Emitted by SettingsScreen after a successful text-provider save.

    The app-level handler rebuilds ``text_model`` from the freshly-persisted
    ``ProviderPrefs`` so subsequent games use the new config without requiring
    a restart.
    """

    def __init__(self, prefs: ProviderPrefs) -> None:
        super().__init__()
        self.prefs = prefs


class ImageProviderChanged(Message):
    """Emitted by SettingsScreen after a successful image-provider save.

    StoryGenApp rebuilds the routed image provider in response. Fires
    independently of :class:`TextProviderChanged` — a single Save click may
    post both.
    """

    def __init__(self, prefs: ImageProviderPrefs) -> None:
        super().__init__()
        self.prefs = prefs


class TTSPrefsChanged(Message):
    """Emitted by SettingsScreen after a successful TTS save.

    StoryGenApp rebuilds the TTS player in response.
    """

    def __init__(self, prefs: TTSPrefs) -> None:
        super().__init__()
        self.prefs = prefs


def _image_base_url_placeholder(provider: str) -> str:
    """Placeholder label for the image base-URL Input.

    Gemini's SDK doesn't accept OpenAI-style base URLs, so we surface an
    explicit "(not used by Gemini)" hint rather than leaving the field empty
    (which would look identical to a provider whose default URL is unknown).
    """
    if provider == "gemini":
        return "(not used by Gemini)"
    return resolve_image_base_url(provider)


class SettingsScreen(Screen[None]):
    """Editable text/image provider prefs, wizard defaults, and the global art toggle."""

    DEFAULT_CSS = """
    SettingsScreen #settings-body { padding: 1 2; }
    SettingsScreen Label { margin-top: 1; color: $accent; }
    SettingsScreen Static.section { text-style: bold; margin-top: 1; color: $text-muted; }
    SettingsScreen #provider-api-key-status,
    SettingsScreen #provider-suggested,
    SettingsScreen #image-provider-api-key-status,
    SettingsScreen #image-provider-suggested,
    SettingsScreen #character-image-provider-api-key-status,
    SettingsScreen #character-image-provider-suggested { color: $text-muted; }
    SettingsScreen #image-ref-warning {
        text-style: bold;
        color: $warning;
        margin-top: 1;
    }
    SettingsScreen #image-ollama-warning {
        color: $text-muted;
        margin-top: 1;
    }
    SettingsScreen #default-theme, SettingsScreen #default-characters {
        height: 4;
    }
    SettingsScreen .switch-row {
        height: auto;
        margin-top: 1;
    }
    SettingsScreen .switch-label {
        padding-top: 1;
        padding-left: 1;
    }
    SettingsScreen #settings-buttons {
        height: auto;
        margin-top: 2;
    }
    SettingsScreen #settings-buttons Button {
        margin-right: 2;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "app.pop_screen", "Back"),
    ]

    # Sentinel value used for the "(none)" entry in the fallback Select.
    # Textual's Select treats Select.BLANK specially; an explicit sentinel
    # avoids any ambiguity with the allow_blank=False contract.
    _FALLBACK_NONE: ClassVar[str] = "__none__"
    # Sentinel Select value meaning "the user typed a custom model in the Input".
    # Stays selected whenever the Input value is not in the provider's curated list.
    _CUSTOM_MODEL: ClassVar[str] = "__custom__"
    # Sentinel for the voice Select "(none)" entry.
    _VOICE_NONE: ClassVar[str] = "__voice_none__"

    def __init__(self, config: AppConfig, tts_player: TTSPlayer | None = None) -> None:
        super().__init__()
        self._config = config
        self._tts_player = tts_player
        # When True, Select.Changed / Input.Changed handlers are no-ops. Cleared
        # via call_after_refresh so the construction-time Changed messages
        # queued by allow_blank=False Selects drain harmlessly. See the long
        # comment block below for the full "why prevent() isn't enough" story.
        #
        # * ``self.prevent(Select.Changed)`` scoped to ``on_mount`` is
        #   insufficient because Textual's ``Select`` with ``allow_blank=False``
        #   auto-selects the first option at *construction* time and queues a
        #   ``Changed`` for it. That message pre-exists any ``prevent`` window
        #   we could open from ``on_mount``/``_populate_from_state``.
        # * ``self.is_mounted`` as a guard doesn't help: by the time the queued
        #   constructor-Changed dispatches, ``is_mounted`` is already ``True``,
        #   so the handler runs and overwrites the just-restored prefs. Verified
        #   empirically in tests.
        # * Constructing without ``value=`` doesn't help either:
        #   ``allow_blank=False`` still auto-selects the first option and queues
        #   the same ``Changed``. Verified with a minimal repro.
        #
        # Two flags (not one) so the fallback Change handler doesn't silently
        # no-op while only the primary provider Select is initializing.
        self._suppress_provider_handler: bool = False
        self._suppress_image_provider_handler: bool = False

        # --- Text provider widgets (editable) ---
        self._provider_select: Select[str] = Select(
            list(app_state.PROVIDER_CHOICES),
            value=app_state.DEFAULT_TEXT_PROVIDER,
            allow_blank=False,
            id="provider-select",
        )
        self._model_input = Input(
            value=app_state.DEFAULT_TEXT_MODEL,
            placeholder="e.g. gpt-4o-mini",
            id="provider-model",
        )
        self._base_url_input = Input(
            value="",
            placeholder=resolve_base_url(
                cast(Provider, app_state.DEFAULT_TEXT_PROVIDER), override=None
            ),
            id="provider-base-url",
        )
        self._api_key_status = Static("", id="provider-api-key-status")
        self._suggested = Static("", id="provider-suggested")

        # --- Image provider widgets (editable, new in Phase 5) ---
        self._image_provider_select: Select[str] = Select(
            list(app_state.IMAGE_PROVIDER_CHOICES),
            value=app_state.DEFAULT_IMAGE_PROVIDER,
            allow_blank=False,
            id="image-provider-select",
        )
        self._image_model_select: Select[str] = Select(
            self._image_model_options(app_state.DEFAULT_IMAGE_PROVIDER),
            value=app_state.DEFAULT_IMAGE_MODEL,
            allow_blank=False,
            id="image-provider-model-select",
        )
        self._image_model_input = Input(
            value=app_state.DEFAULT_IMAGE_MODEL,
            placeholder="e.g. gpt-image-2",
            id="image-provider-model",
        )
        self._image_base_url_input = Input(
            value="",
            placeholder=_image_base_url_placeholder(app_state.DEFAULT_IMAGE_PROVIDER),
            id="image-provider-base-url",
        )
        self._image_api_key_status = Static("", id="image-provider-api-key-status")
        self._image_suggested = Static("", id="image-provider-suggested")
        # Fallback Select prepends a "(none)" entry with a sentinel value.
        self._fallback_select: Select[str] = Select(
            [("(none)", self._FALLBACK_NONE), *app_state.IMAGE_PROVIDER_CHOICES],
            value=self._FALLBACK_NONE,
            allow_blank=False,
            id="image-fallback-select",
        )
        self._fallback_model_input = Input(
            value="",
            placeholder="e.g. gemini-3-pro-image-preview",
            id="image-fallback-model",
            disabled=True,
        )
        self._ref_warning = Static(
            "[!] Selected provider(s) don't support reference images. "
            "Character visual consistency will degrade across scenes.",
            id="image-ref-warning",
        )
        self._ref_warning.display = False
        self._ollama_warning = Static(
            "Ollama requires >=0.13.3 running locally. Image gen is macOS-only as of 2026-04.",
            id="image-ollama-warning",
        )
        self._ollama_warning.display = False

        # --- Character portrait image provider widgets ---
        self._character_image_provider_select: Select[str] = Select(
            list(app_state.IMAGE_PROVIDER_CHOICES),
            value=app_state.DEFAULT_CHARACTER_IMAGE_PROVIDER,
            allow_blank=False,
            id="character-image-provider-select",
        )
        self._character_image_model_select: Select[str] = Select(
            self._character_image_model_options(app_state.DEFAULT_CHARACTER_IMAGE_PROVIDER),
            value=app_state.DEFAULT_CHARACTER_IMAGE_MODEL,
            allow_blank=False,
            id="character-image-provider-model-select",
        )
        self._character_image_model_input = Input(
            value=app_state.DEFAULT_CHARACTER_IMAGE_MODEL,
            placeholder="e.g. gpt-image-1.5",
            id="character-image-provider-model",
        )
        self._character_image_base_url_input = Input(
            value="",
            placeholder=_image_base_url_placeholder(app_state.DEFAULT_CHARACTER_IMAGE_PROVIDER),
            id="character-image-provider-base-url",
        )
        self._character_image_api_key_status = Static(
            "", id="character-image-provider-api-key-status"
        )
        self._character_image_suggested = Static("", id="character-image-provider-suggested")

        # --- Wizard defaults ---
        self._theme_area = TextArea(id="default-theme")
        self._tone_select = Select(
            TONE_PRESETS,
            value=app_state.DEFAULT_TONE_PRESET,
            allow_blank=False,
            id="default-tone-preset",
        )
        self._tone_descriptor = Input(
            placeholder="Custom tone descriptor (e.g. melancholy comedy)",
            id="default-tone-descriptor",
        )
        self._style_select = Select(
            STYLE_OPTIONS,
            value=app_state.DEFAULT_NARRATION_STYLE,
            allow_blank=False,
            id="default-style",
        )
        self._art_style_input = Input(
            placeholder="e.g. children's story book, watercolor, noir comic",
            id="default-art-style",
        )
        self._length_input = Input(
            value=str(app_state.DEFAULT_TARGET_MAJOR_BEATS),
            placeholder=(f"{app_state.MIN_TARGET_MAJOR_BEATS}-{app_state.MAX_TARGET_MAJOR_BEATS}"),
            id="default-length",
            restrict=r"\d*",
        )
        self._reader_level_select = Select(
            READER_LEVEL_OPTIONS,
            value=app_state.DEFAULT_READER_LEVEL,
            allow_blank=False,
            id="default-reader-level",
        )
        self._char_area = TextArea(id="default-characters")
        self._art_switch = Switch(value=True, id="art-enabled-switch")
        self._streaming_switch = Switch(value=False, id="image-streaming-switch")
        self._prefetch_switch = Switch(value=False, id="prefetch-enabled-switch")
        self._prefetch_images_switch = Switch(value=False, id="prefetch-images-switch")
        self._llm_cache_switch = Switch(value=False, id="llm-cache-switch")
        self._auto_select_switch = Switch(value=False, id="auto-select-switch")
        self._auto_open_art_switch = Switch(value=False, id="auto-open-art-switch")

        # --- TTS widgets ---
        self._suppress_tts_handler: bool = False
        self._tts_provider_select: Select[str] = Select(
            list(app_state.TTS_PROVIDER_CHOICES),
            value=app_state.DEFAULT_TTS_PROVIDER,
            allow_blank=False,
            id="tts-provider-select",
        )
        self._tts_api_key_input = Input(
            value="",
            placeholder="Leave blank to use env var",
            id="tts-api-key",
            password=True,
        )
        self._tts_voice_select: Select[str] = Select(
            [],
            prompt="Select a voice",
            allow_blank=True,
            id="tts-voice-select",
        )
        self._tts_api_key_status = Static("", id="tts-api-key-status")
        self._tts_auto_read_switch = Switch(value=False, id="tts-auto-read-switch")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with VerticalScroll(id="settings-body"):
            yield Static("Text provider", classes="section")
            yield Label("Provider")
            yield self._provider_select
            yield Label("Model")
            yield self._model_input
            yield Label("Base URL (blank = use provider default)")
            yield self._base_url_input
            yield self._api_key_status
            yield self._suggested

            yield Static("Art generation provider (scenes + covers)", classes="section")
            yield Label("Provider")
            yield self._image_provider_select
            yield Label("Model")
            yield self._image_model_select
            yield self._image_model_input
            yield Label("Base URL (blank = use provider default)")
            yield self._image_base_url_input
            yield self._image_api_key_status
            yield self._image_suggested
            yield Label("Fallback provider (optional)")
            yield self._fallback_select
            yield Label("Fallback model")
            yield self._fallback_model_input
            yield self._ref_warning
            yield self._ollama_warning

            yield Static("Character portrait provider", classes="section")
            yield Label("Provider")
            yield self._character_image_provider_select
            yield Label("Model")
            yield self._character_image_model_select
            yield self._character_image_model_input
            yield Label("Base URL (blank = use provider default)")
            yield self._character_image_base_url_input
            yield self._character_image_api_key_status
            yield self._character_image_suggested

            yield Static("Wizard defaults", classes="section")
            yield Label("Default theme")
            yield self._theme_area
            yield Label("Default tone")
            yield self._tone_select
            yield self._tone_descriptor
            yield Label("Default narration style")
            yield self._style_select
            yield Label("Default art style")
            yield self._art_style_input
            yield Label("Default story length (major beats)")
            yield self._length_input
            yield Label("Default reader level")
            yield self._reader_level_select
            yield Label("Default character requirements")
            yield self._char_area

            yield Static("Image generation", classes="section")
            with Horizontal(classes="switch-row"):
                yield self._art_switch
                yield Static(
                    "Enable image generation (portraits + scenes)",
                    classes="switch-label",
                )
            with Horizontal(classes="switch-row"):
                yield self._streaming_switch
                yield Static(
                    "Stream partial scene previews (OpenAI only — adds ~5% cost)",
                    classes="switch-label",
                )
            with Horizontal(classes="switch-row"):
                yield self._auto_open_art_switch
                yield Static(
                    "Auto-open full-res images in system viewer when generated",
                    classes="switch-label",
                )

            yield Static("Branch prefetch", classes="section")
            with Horizontal(classes="switch-row"):
                yield self._prefetch_switch
                yield Static(
                    "Enable branch prefetch (generates next beats while you read — extra LLM cost)",
                    classes="switch-label",
                )
            with Horizontal(classes="switch-row"):
                yield self._prefetch_images_switch
                yield Static(
                    "Prefetch scene images too (extra image cost)",
                    classes="switch-label",
                )

            yield Static("Developer", classes="section")
            with Horizontal(classes="switch-row"):
                yield self._llm_cache_switch
                yield Static(
                    "Cache raw LLM exchanges for debugging (no gameplay effect)",
                    classes="switch-label",
                )
            with Horizontal(classes="switch-row"):
                yield self._auto_select_switch
                yield Static(
                    "Auto-select choices (random, waits for image + TTS)",
                    classes="switch-label",
                )

            yield Static("Text-to-speech", classes="section")
            yield Label("Provider")
            yield self._tts_provider_select
            yield Label("API key (blank = use provider env var)")
            yield self._tts_api_key_input
            yield self._tts_api_key_status
            yield Label("Voice")
            with Horizontal(classes="switch-row"):
                yield self._tts_voice_select
                yield Button("Refresh", id="btn-refresh-tts-voices", variant="default")
            with Horizontal(classes="switch-row"):
                yield self._tts_auto_read_switch
                yield Static(
                    "Auto-read story beats aloud when generated",
                    classes="switch-label",
                )

            with Horizontal(id="settings-buttons"):
                yield Button("Save", id="btn-save", variant="primary")
                yield Button("Reset to defaults", id="btn-reset")
        yield Footer()

    def on_mount(self) -> None:
        self._suppress_provider_handler = True
        self._suppress_image_provider_handler = True
        self._suppress_tts_handler = True
        self._populate_from_state()
        self.call_after_refresh(self._clear_suppress_flag)
        # Auto-fetch TTS voices in the background so the saved voice is pre-selected.
        self.run_worker(self._auto_fetch_tts_voices(), exclusive=False, name="tts-voice-prefetch")

    def _clear_suppress_flag(self) -> None:
        self._suppress_provider_handler = False
        self._suppress_image_provider_handler = False
        self._suppress_tts_handler = False

    # ------------------------------------------------------------------
    # Populate / refresh helpers
    # ------------------------------------------------------------------

    def _refresh_api_key_status(self, provider: str) -> None:
        env_name = api_key_env_var(cast(Provider, provider))
        if env_name is None:
            self._api_key_status.update("API key: not required (local)")
            return
        present = bool(os.environ.get(env_name))
        mark = "present" if present else "missing"
        self._api_key_status.update(f"API key ({env_name}): {mark}")

    def _refresh_suggested(self, provider: str) -> None:
        models = app_state.SUGGESTED_MODELS.get(provider, [])
        if not models:
            self._suggested.update("")
            return
        self._suggested.update(f"Suggested: {', '.join(models)}")

    def _refresh_image_api_key_status(self, provider: str) -> None:
        env_name = app_state.IMAGE_API_KEY_ENV.get(provider)
        if env_name is None:
            self._image_api_key_status.update("No API key required (local)")
            return
        present = bool(os.environ.get(env_name))
        mark = "present" if present else "missing"
        self._image_api_key_status.update(f"API key ({env_name}): {mark}")

    def _image_model_options(self, provider: str) -> list[tuple[str, str]]:
        """Curated image-model choices for the Select widget, plus a Custom entry.

        Returns ``[(label, value), ...]``. Each curated model becomes a
        ``(model, model)`` entry; ``_CUSTOM_MODEL`` is appended so the user can
        type a non-listed model in the Input without losing Select state.
        """
        curated = app_state.SUGGESTED_IMAGE_MODELS.get(provider, ())
        options: list[tuple[str, str]] = [(m, m) for m in curated]
        options.append(("Custom (type below)…", self._CUSTOM_MODEL))
        return options

    def _sync_image_model_select(self, provider: str, model: str) -> None:
        """Rebuild the image-model Select options for ``provider`` and pick ``model``.

        If ``model`` is in the curated list for ``provider``, the Select points
        at it; otherwise the Select shows the Custom sentinel (the Input keeps
        the real value). The Input is only shown when Custom is selected.
        """
        options = self._image_model_options(provider)
        curated_values = {v for _, v in options if v != self._CUSTOM_MODEL}
        target_value = model if model in curated_values else self._CUSTOM_MODEL
        with self._image_model_select.prevent(Select.Changed):
            self._image_model_select.set_options(options)
            self._image_model_select.value = target_value
        self._image_model_input.display = target_value == self._CUSTOM_MODEL

    def _refresh_image_suggested(self, provider: str) -> None:
        models = app_state.SUGGESTED_IMAGE_MODELS.get(provider, ())
        if not models:
            self._image_suggested.update("")
            return
        self._image_suggested.update(f"Suggested: {', '.join(models)}")

    def _refresh_character_image_api_key_status(self, provider: str) -> None:
        env_name = app_state.IMAGE_API_KEY_ENV.get(provider)
        if env_name is None:
            self._character_image_api_key_status.update("No API key required (local)")
            return
        present = bool(os.environ.get(env_name))
        mark = "present" if present else "missing"
        self._character_image_api_key_status.update(f"API key ({env_name}): {mark}")

    def _character_image_model_options(self, provider: str) -> list[tuple[str, str]]:
        return self._image_model_options(provider)

    def _sync_character_image_model_select(self, provider: str, model: str) -> None:
        options = self._character_image_model_options(provider)
        curated_values = {v for _, v in options if v != self._CUSTOM_MODEL}
        target_value = model if model in curated_values else self._CUSTOM_MODEL
        with self._character_image_model_select.prevent(Select.Changed):
            self._character_image_model_select.set_options(options)
            self._character_image_model_select.value = target_value
        self._character_image_model_input.display = target_value == self._CUSTOM_MODEL

    def _refresh_character_image_suggested(self, provider: str) -> None:
        models = app_state.SUGGESTED_IMAGE_MODELS.get(provider, ())
        if not models:
            self._character_image_suggested.update("")
            return
        self._character_image_suggested.update(f"Suggested: {', '.join(models)}")

    def _current_character_image_provider(self) -> str:
        return cast(str, self._character_image_provider_select.value)

    def _current_primary_image_provider(self) -> str:
        return cast(str, self._image_provider_select.value)

    def _current_fallback_image_provider(self) -> str:
        """The sentinel ``_FALLBACK_NONE`` is translated to ``""`` for consumers."""
        raw = cast(str, self._fallback_select.value)
        return "" if raw == self._FALLBACK_NONE else raw

    def _refresh_ref_warning(self) -> None:
        primary = self._current_primary_image_provider()
        fallback = self._current_fallback_image_provider()
        unsupported: list[str] = []
        if primary not in app_state.PROVIDER_SUPPORTS_REFS:
            unsupported.append(primary)
        if fallback and fallback not in app_state.PROVIDER_SUPPORTS_REFS:
            unsupported.append(fallback)
        self._ref_warning.display = bool(unsupported)

    def _refresh_ollama_warning(self) -> None:
        primary = self._current_primary_image_provider()
        fallback = self._current_fallback_image_provider()
        self._ollama_warning.display = primary == "ollama" or fallback == "ollama"

    def _populate_from_state(self) -> None:
        """Load persisted defaults + prefs into the widgets.

        The prevent context must be on the *posting widget* (e.g. the Select),
        not the screen — reactive watchers read ``_prevent_message_types_stack``
        from the widget they fire on, not from the enclosing screen.
        """
        # Text provider
        prefs = app_state.read_provider_prefs()
        with (
            self._provider_select.prevent(Select.Changed),
            self._model_input.prevent(Input.Changed),
            self._base_url_input.prevent(Input.Changed),
        ):
            self._provider_select.value = prefs.provider
            self._model_input.value = prefs.model
            self._base_url_input.value = prefs.base_url
            self._base_url_input.placeholder = resolve_base_url(
                cast(Provider, prefs.provider), override=None
            )
        self._refresh_api_key_status(prefs.provider)
        self._refresh_suggested(prefs.provider)

        # Image provider
        img_prefs = app_state.read_image_provider_prefs()
        fallback_value = (
            img_prefs.fallback_provider if img_prefs.fallback_provider else self._FALLBACK_NONE
        )
        with (
            self._image_provider_select.prevent(Select.Changed),
            self._image_model_input.prevent(Input.Changed),
            self._image_base_url_input.prevent(Input.Changed),
            self._fallback_select.prevent(Select.Changed),
            self._fallback_model_input.prevent(Input.Changed),
        ):
            self._image_provider_select.value = img_prefs.provider
            self._image_model_input.value = img_prefs.model
            self._image_base_url_input.value = img_prefs.base_url
            self._image_base_url_input.placeholder = _image_base_url_placeholder(img_prefs.provider)
            self._fallback_select.value = fallback_value
            self._fallback_model_input.value = img_prefs.fallback_model
            self._fallback_model_input.disabled = not img_prefs.fallback_provider
        self._sync_image_model_select(img_prefs.provider, img_prefs.model)
        self._refresh_image_api_key_status(img_prefs.provider)
        self._refresh_image_suggested(img_prefs.provider)
        self._refresh_ref_warning()
        self._refresh_ollama_warning()

        # Character portrait image provider
        character_img_prefs = app_state.read_character_image_provider_prefs()
        with (
            self._character_image_provider_select.prevent(Select.Changed),
            self._character_image_model_input.prevent(Input.Changed),
            self._character_image_base_url_input.prevent(Input.Changed),
        ):
            self._character_image_provider_select.value = character_img_prefs.provider
            self._character_image_model_input.value = character_img_prefs.model
            self._character_image_base_url_input.value = character_img_prefs.base_url
            self._character_image_base_url_input.placeholder = _image_base_url_placeholder(
                character_img_prefs.provider
            )
        self._sync_character_image_model_select(
            character_img_prefs.provider, character_img_prefs.model
        )
        self._refresh_character_image_api_key_status(character_img_prefs.provider)
        self._refresh_character_image_suggested(character_img_prefs.provider)

        # Wizard defaults
        defaults = app_state.read_wizard_defaults()
        tone_preset = (
            defaults.tone_preset
            if defaults.tone_preset in valid_tone_preset_values()
            else app_state.DEFAULT_TONE_PRESET
        )
        narration_style = (
            defaults.narration_style
            if defaults.narration_style in valid_narration_style_values()
            else app_state.DEFAULT_NARRATION_STYLE
        )
        reader_level = (
            defaults.reader_level
            if defaults.reader_level in valid_reader_level_values()
            else app_state.DEFAULT_READER_LEVEL
        )
        with (
            self._tone_select.prevent(Select.Changed),
            self._style_select.prevent(Select.Changed),
            self._reader_level_select.prevent(Select.Changed),
            self._art_switch.prevent(Switch.Changed),
            self._streaming_switch.prevent(Switch.Changed),
            self._prefetch_switch.prevent(Switch.Changed),
            self._prefetch_images_switch.prevent(Switch.Changed),
            self._llm_cache_switch.prevent(Switch.Changed),
            self._auto_select_switch.prevent(Switch.Changed),
            self._auto_open_art_switch.prevent(Switch.Changed),
        ):
            self._theme_area.text = defaults.theme
            self._tone_select.value = tone_preset
            self._tone_descriptor.value = defaults.tone_descriptor
            self._style_select.value = narration_style
            self._art_style_input.value = defaults.art_style
            self._length_input.value = str(defaults.target_major_beats)
            self._reader_level_select.value = reader_level
            self._char_area.text = defaults.characters
            self._art_switch.value = app_state.art_enabled()
            self._streaming_switch.value = app_state.image_streaming_enabled()
            self._prefetch_switch.value = app_state.prefetch_enabled()
            self._prefetch_images_switch.value = app_state.prefetch_images_enabled()
            self._llm_cache_switch.value = app_state.llm_cache_enabled()
            self._auto_select_switch.value = app_state.auto_select_enabled()
            self._auto_open_art_switch.value = app_state.auto_open_art_enabled()
            self._refresh_image_gating()

        # TTS
        tts_prefs = app_state.read_tts_prefs()
        with (
            self._tts_provider_select.prevent(Select.Changed),
            self._tts_api_key_input.prevent(Input.Changed),
            self._tts_auto_read_switch.prevent(Switch.Changed),
        ):
            self._tts_provider_select.value = tts_prefs.provider
            self._tts_api_key_input.value = tts_prefs.api_key
            self._tts_auto_read_switch.value = tts_prefs.auto_read
        self._refresh_tts_api_key_status(tts_prefs.provider)
        self._populate_tts_voices(tts_prefs.voice)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    @on(Select.Changed, "#provider-select")
    def _on_provider_changed(self, event: Select.Changed) -> None:
        """Handle user-initiated provider switch — refresh dependent widgets."""
        if self._suppress_provider_handler:
            return
        value_obj = event.value
        if not isinstance(value_obj, str):
            return
        provider = value_obj
        suggested = app_state.SUGGESTED_MODELS.get(provider, [])
        first_model = suggested[0] if suggested else app_state.DEFAULT_TEXT_MODEL
        with (
            self._model_input.prevent(Input.Changed),
            self._base_url_input.prevent(Input.Changed),
        ):
            self._model_input.value = first_model
            self._base_url_input.value = ""
            self._base_url_input.placeholder = resolve_base_url(
                cast(Provider, provider), override=None
            )
        self._refresh_api_key_status(provider)
        self._refresh_suggested(provider)

    @on(Select.Changed, "#image-provider-select")
    def _on_image_provider_changed(self, event: Select.Changed) -> None:
        """Mirror of the text handler for the image-provider Select."""
        if self._suppress_image_provider_handler:
            return
        value_obj = event.value
        if not isinstance(value_obj, str):
            return
        provider = value_obj
        suggested = app_state.SUGGESTED_IMAGE_MODELS.get(provider, ())
        first_model = suggested[0] if suggested else app_state.DEFAULT_IMAGE_MODEL
        with (
            self._image_model_input.prevent(Input.Changed),
            self._image_base_url_input.prevent(Input.Changed),
        ):
            self._image_model_input.value = first_model
            self._image_base_url_input.value = ""
            self._image_base_url_input.placeholder = _image_base_url_placeholder(provider)
        self._sync_image_model_select(provider, first_model)
        self._refresh_image_api_key_status(provider)
        self._refresh_image_suggested(provider)
        self._refresh_ref_warning()
        self._refresh_ollama_warning()

    @on(Select.Changed, "#image-provider-model-select")
    def _on_image_model_selected(self, event: Select.Changed) -> None:
        """Copy the chosen curated model into the model Input and toggle visibility.

        The sentinel ``_CUSTOM_MODEL`` reveals the Input so the user can type
        freely. Selecting any curated model hides the Input and overwrites its
        value so Save still reads the correct string.
        """
        if self._suppress_image_provider_handler:
            return
        value_obj = event.value
        if not isinstance(value_obj, str):
            return
        if value_obj == self._CUSTOM_MODEL:
            self._image_model_input.display = True
            return
        with self._image_model_input.prevent(Input.Changed):
            self._image_model_input.value = value_obj
        self._image_model_input.display = False

    @on(Input.Changed, "#image-provider-model")
    def _on_image_model_input_changed(self, event: Input.Changed) -> None:
        """Re-sync the Select when the user types a custom model in the Input."""
        if self._suppress_image_provider_handler:
            return
        provider = self._current_primary_image_provider()
        self._sync_image_model_select(provider, event.value.strip())

    @on(Select.Changed, "#character-image-provider-select")
    def _on_character_image_provider_changed(self, event: Select.Changed) -> None:
        """Mirror of image provider switching for character-portrait generation."""
        if self._suppress_image_provider_handler:
            return
        value_obj = event.value
        if not isinstance(value_obj, str):
            return
        provider = value_obj
        suggested = app_state.SUGGESTED_IMAGE_MODELS.get(provider, ())
        first_model = suggested[0] if suggested else app_state.DEFAULT_CHARACTER_IMAGE_MODEL
        with (
            self._character_image_model_input.prevent(Input.Changed),
            self._character_image_base_url_input.prevent(Input.Changed),
        ):
            self._character_image_model_input.value = first_model
            self._character_image_base_url_input.value = ""
            self._character_image_base_url_input.placeholder = _image_base_url_placeholder(provider)
        self._sync_character_image_model_select(provider, first_model)
        self._refresh_character_image_api_key_status(provider)
        self._refresh_character_image_suggested(provider)

    @on(Select.Changed, "#character-image-provider-model-select")
    def _on_character_image_model_selected(self, event: Select.Changed) -> None:
        if self._suppress_image_provider_handler:
            return
        value_obj = event.value
        if not isinstance(value_obj, str):
            return
        if value_obj == self._CUSTOM_MODEL:
            self._character_image_model_input.display = True
            return
        with self._character_image_model_input.prevent(Input.Changed):
            self._character_image_model_input.value = value_obj
        self._character_image_model_input.display = False

    @on(Input.Changed, "#character-image-provider-model")
    def _on_character_image_model_input_changed(self, event: Input.Changed) -> None:
        if self._suppress_image_provider_handler:
            return
        provider = self._current_character_image_provider()
        self._sync_character_image_model_select(provider, event.value.strip())

    @on(Select.Changed, "#image-fallback-select")
    def _on_image_fallback_changed(self, event: Select.Changed) -> None:
        """Enable/disable the fallback-model Input based on the fallback provider."""
        if self._suppress_image_provider_handler:
            return
        value_obj = event.value
        if not isinstance(value_obj, str):
            return
        fallback = "" if value_obj == self._FALLBACK_NONE else value_obj
        with self._fallback_model_input.prevent(Input.Changed):
            if not fallback:
                self._fallback_model_input.value = ""
                self._fallback_model_input.disabled = True
            else:
                self._fallback_model_input.disabled = False
                suggested = app_state.SUGGESTED_IMAGE_MODELS.get(fallback, ())
                self._fallback_model_input.value = suggested[0] if suggested else ""
        self._refresh_ref_warning()
        self._refresh_ollama_warning()

    def _refresh_image_gating(self) -> None:
        """Update gating for all art-dependent switches.

        - Streaming switch: disabled whenever art is globally off (no images
          at all). Provider-agnostic: streaming is a runtime no-op for
          non-OpenAI providers anyway, and the user might switch providers
          later.
        - Prefetch-images switch: disabled when prefetch is off OR art is off.
        """
        art_on = self._art_switch.value
        prefetch_on = self._prefetch_switch.value
        self._streaming_switch.disabled = not art_on
        self._auto_open_art_switch.disabled = not art_on
        self._prefetch_images_switch.disabled = not (art_on and prefetch_on)

    @on(Switch.Changed, "#art-enabled-switch")
    def _on_art_switch_changed(self, event: Switch.Changed) -> None:
        """Re-evaluate art-dependent switch gating when the art toggle flips."""
        del event
        self._refresh_image_gating()

    # ------------------------------------------------------------------
    # TTS helpers and handlers
    # ------------------------------------------------------------------

    def _refresh_tts_api_key_status(self, provider: str) -> None:
        env_name = app_state.TTS_API_KEY_ENV.get(provider)
        if env_name is None:
            self._tts_api_key_status.update("API key: not required (local)")
            return
        present = bool(os.environ.get(env_name))
        mark = "present" if present else "missing"
        self._tts_api_key_status.update(f"API key ({env_name}): {mark}")

    def _populate_tts_voices(self, current_voice: str = "") -> None:
        """Populate the voice Select from the TTSPlayer's cached voices."""
        if self._tts_player is None:
            return
        voices = self._tts_player.voices
        if not voices:
            return
        options = [(v.name, v.id) for v in voices]
        with self._tts_voice_select.prevent(Select.Changed):
            self._tts_voice_select.set_options(options)
            # Select current voice if it's in the list, otherwise leave blank.
            if current_voice:
                voice_ids = {v.id for v in voices}
                if current_voice in voice_ids:
                    self._tts_voice_select.value = current_voice  # type: ignore[assignment]

    @on(Select.Changed, "#tts-provider-select")
    def _on_tts_provider_changed(self, event: Select.Changed) -> None:
        if self._suppress_tts_handler:
            return
        value_obj = event.value
        if not isinstance(value_obj, str):
            return
        provider = value_obj
        self._refresh_tts_api_key_status(provider)
        # Clear voices — user must refresh for new provider.
        with self._tts_api_key_input.prevent(Input.Changed):
            self._tts_api_key_input.value = ""
        self._populate_tts_voices("")

    async def _auto_fetch_tts_voices(self) -> None:
        """Fetch voices on mount so the saved voice can be pre-selected."""
        if self._tts_player is None:
            return
        tts_prefs = app_state.read_tts_prefs()
        if not tts_prefs.voice and not self._tts_player.voices:
            return
        # Configure the player with current settings so it can fetch voices.
        self._tts_player.configure(
            tts_prefs.provider,
            api_key=tts_prefs.api_key,
            voice=tts_prefs.voice,
        )
        if not self._tts_player.voices:
            await self._tts_player.refresh_voices()
        if self._tts_player.voices:
            self._populate_tts_voices(tts_prefs.voice)

    @on(Button.Pressed, "#btn-refresh-tts-voices")
    async def _on_refresh_tts_voices(self, event: Button.Pressed) -> None:
        del event
        if self._tts_player is None:
            self.notify("TTS player not available.", severity="warning", timeout=3)
            return
        provider = cast(str, self._tts_provider_select.value)
        api_key = self._tts_api_key_input.value.strip()
        self._tts_player.configure(provider, api_key=api_key)
        voices = await self._tts_player.refresh_voices()
        if voices:
            self._populate_tts_voices()
            self.notify(f"Loaded {len(voices)} voices.", timeout=3)
        else:
            self._populate_tts_voices()
            self.notify("No voices found.", severity="warning", timeout=3)

    @on(Switch.Changed, "#prefetch-enabled-switch")
    def _on_prefetch_switch_changed(self, event: Switch.Changed) -> None:
        """Re-evaluate prefetch-images gating when prefetch is toggled."""
        del event
        self._refresh_image_gating()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-save":
            self._save_settings()
        elif bid == "btn-reset":
            self._reset_widgets()

    # ------------------------------------------------------------------
    # Save / reset
    # ------------------------------------------------------------------

    def _save_settings(self) -> None:
        """Persist image prefs + text prefs + wizard defaults + art toggle.

        Validates everything up front; if any validation fails we bail without
        writing anything so the screen stays consistent with on-disk state.
        """
        # --- Image provider validation ---
        image_provider = self._current_primary_image_provider()
        image_model = self._image_model_input.value.strip()
        image_base_url = self._image_base_url_input.value.strip()
        fallback_provider = self._current_fallback_image_provider()
        fallback_model = self._fallback_model_input.value.strip()

        if not image_model:
            self.notify(
                "Image model cannot be empty — settings not saved.",
                severity="error",
                timeout=5,
            )
            return
        if image_base_url and not (
            image_base_url.startswith("http://") or image_base_url.startswith("https://")
        ):
            self.notify(
                "Image base URL must start with http:// or https:// — settings not saved.",
                severity="error",
                timeout=5,
            )
            return
        if fallback_provider:
            if not fallback_model:
                self.notify(
                    "Fallback model cannot be empty — settings not saved.",
                    severity="error",
                    timeout=5,
                )
                return
            if fallback_provider == image_provider:
                self.notify(
                    "Fallback provider matches primary — it won't be used.",
                    severity="warning",
                    timeout=5,
                )

        # --- Character image provider validation ---
        character_image_provider = self._current_character_image_provider()
        character_image_model = self._character_image_model_input.value.strip()
        character_image_base_url = self._character_image_base_url_input.value.strip()

        if not character_image_model:
            self.notify(
                "Character image model cannot be empty — settings not saved.",
                severity="error",
                timeout=5,
            )
            return
        if character_image_base_url and not (
            character_image_base_url.startswith("http://")
            or character_image_base_url.startswith("https://")
        ):
            self.notify(
                "Character image base URL must start with http:// or https:// — settings not saved.",
                severity="error",
                timeout=5,
            )
            return

        # --- Text provider validation ---
        provider = cast(str, self._provider_select.value)
        model = self._model_input.value.strip()
        base_url = self._base_url_input.value.strip()

        if not model:
            self.notify(
                "Model name cannot be empty — settings not saved.",
                severity="error",
                timeout=5,
            )
            return
        if base_url and not (base_url.startswith("http://") or base_url.startswith("https://")):
            self.notify(
                "Base URL must start with http:// or https:// — settings not saved.",
                severity="error",
                timeout=5,
            )
            return

        # Validation passed — build the frozen pref records.
        image_prefs = ImageProviderPrefs(
            provider=image_provider,
            model=image_model,
            base_url=image_base_url,
            fallback_provider=fallback_provider,
            fallback_model=fallback_model if fallback_provider else "",
        )
        character_image_prefs = CharacterImageProviderPrefs(
            provider=character_image_provider,
            model=character_image_model,
            base_url=character_image_base_url,
        )
        prefs = ProviderPrefs(provider=provider, model=model, base_url=base_url)

        # --- Wizard defaults ---
        raw_length = self._length_input.value.strip()
        try:
            length_n = int(raw_length) if raw_length else app_state.DEFAULT_TARGET_MAJOR_BEATS
        except ValueError:
            length_n = app_state.DEFAULT_TARGET_MAJOR_BEATS
        clamped_length = max(
            app_state.MIN_TARGET_MAJOR_BEATS,
            min(app_state.MAX_TARGET_MAJOR_BEATS, length_n),
        )
        defaults = app_state.WizardDefaults(
            theme=self._theme_area.text,
            tone_preset=cast(str, self._tone_select.value),
            tone_descriptor=self._tone_descriptor.value,
            narration_style=cast(str, self._style_select.value),
            art_style=self._art_style_input.value.strip() or app_state.DEFAULT_ART_STYLE,
            target_major_beats=clamped_length,
            reader_level=coerce_reader_level(self._reader_level_select.value),
            characters=self._char_area.text,
        )

        # --- TTS prefs ---
        tts_provider = cast(str, self._tts_provider_select.value)
        tts_api_key = self._tts_api_key_input.value.strip()
        tts_voice_raw = self._tts_voice_select.value
        tts_voice = tts_voice_raw if isinstance(tts_voice_raw, str) else ""
        tts_auto_read = self._tts_auto_read_switch.value
        tts_prefs = TTSPrefs(
            provider=tts_provider,
            api_key=tts_api_key,
            voice=tts_voice,
            auto_read=tts_auto_read,
        )

        # Single atomic write so a crash mid-save can't leave partial persistence.
        # Both provider Changed messages fire afterwards; each app-level handler
        # rebuilds only its own provider so the double-fire is harmless.
        app_state.write_all_settings(
            image_prefs=image_prefs,
            character_image_prefs=character_image_prefs,
            text_prefs=prefs,
            wizard_defaults=defaults,
            tts_prefs=tts_prefs,
            art_enabled_value=self._art_switch.value,
            prefetch_enabled_value=self._prefetch_switch.value,
            prefetch_images_enabled_value=self._prefetch_images_switch.value,
            image_streaming_enabled_value=self._streaming_switch.value,
            llm_cache_enabled_value=self._llm_cache_switch.value,
            auto_select_value=self._auto_select_switch.value,
            auto_open_art_value=self._auto_open_art_switch.value,
        )
        self.post_message(ImageProviderChanged(image_prefs))
        self.post_message(TextProviderChanged(prefs))
        self.post_message(TTSPrefsChanged(tts_prefs))
        self.notify("Settings saved.", timeout=3)

    def _reset_widgets(self) -> None:
        """Reset widgets to constants without persisting (user must press Save)."""
        self._suppress_provider_handler = True
        self._suppress_image_provider_handler = True
        self._suppress_tts_handler = True
        with (
            self._provider_select.prevent(Select.Changed),
            self._tone_select.prevent(Select.Changed),
            self._style_select.prevent(Select.Changed),
            self._reader_level_select.prevent(Select.Changed),
            self._image_provider_select.prevent(Select.Changed),
            self._character_image_provider_select.prevent(Select.Changed),
            self._fallback_select.prevent(Select.Changed),
            self._tts_provider_select.prevent(Select.Changed),
            self._tts_auto_read_switch.prevent(Switch.Changed),
        ):
            # Text-provider section.
            self._provider_select.value = app_state.DEFAULT_TEXT_PROVIDER
            self._model_input.value = app_state.DEFAULT_TEXT_MODEL
            self._base_url_input.value = ""
            self._base_url_input.placeholder = resolve_base_url(
                cast(Provider, app_state.DEFAULT_TEXT_PROVIDER), override=None
            )
            # Image-provider section.
            self._image_provider_select.value = app_state.DEFAULT_IMAGE_PROVIDER
            self._image_model_input.value = app_state.DEFAULT_IMAGE_MODEL
            self._image_base_url_input.value = ""
            self._image_base_url_input.placeholder = _image_base_url_placeholder(
                app_state.DEFAULT_IMAGE_PROVIDER
            )
            self._fallback_select.value = self._FALLBACK_NONE
            self._fallback_model_input.value = ""
            self._fallback_model_input.disabled = True
            # Character portrait image-provider section.
            self._character_image_provider_select.value = app_state.DEFAULT_CHARACTER_IMAGE_PROVIDER
            self._character_image_model_input.value = app_state.DEFAULT_CHARACTER_IMAGE_MODEL
            self._character_image_base_url_input.value = ""
            self._character_image_base_url_input.placeholder = _image_base_url_placeholder(
                app_state.DEFAULT_CHARACTER_IMAGE_PROVIDER
            )
            # Wizard defaults.
            self._theme_area.text = ""
            self._tone_select.value = app_state.DEFAULT_TONE_PRESET
            self._tone_descriptor.value = ""
            self._style_select.value = app_state.DEFAULT_NARRATION_STYLE
            self._art_style_input.value = app_state.DEFAULT_ART_STYLE
            self._length_input.value = str(app_state.DEFAULT_TARGET_MAJOR_BEATS)
            self._reader_level_select.value = app_state.DEFAULT_READER_LEVEL
            self._char_area.text = ""
            self._art_switch.value = True
            self._streaming_switch.value = False
            self._prefetch_switch.value = False
            self._prefetch_images_switch.value = False
            self._llm_cache_switch.value = False
            self._auto_select_switch.value = False
            self._auto_open_art_switch.value = False
            self._refresh_image_gating()
            # TTS section.
            self._tts_provider_select.value = app_state.DEFAULT_TTS_PROVIDER
            self._tts_api_key_input.value = ""
            self._tts_auto_read_switch.value = False
        self._refresh_api_key_status(app_state.DEFAULT_TEXT_PROVIDER)
        self._refresh_suggested(app_state.DEFAULT_TEXT_PROVIDER)
        self._refresh_image_api_key_status(app_state.DEFAULT_IMAGE_PROVIDER)
        self._refresh_image_suggested(app_state.DEFAULT_IMAGE_PROVIDER)
        self._sync_image_model_select(
            app_state.DEFAULT_IMAGE_PROVIDER, app_state.DEFAULT_IMAGE_MODEL
        )
        self._refresh_character_image_api_key_status(app_state.DEFAULT_CHARACTER_IMAGE_PROVIDER)
        self._refresh_character_image_suggested(app_state.DEFAULT_CHARACTER_IMAGE_PROVIDER)
        self._sync_character_image_model_select(
            app_state.DEFAULT_CHARACTER_IMAGE_PROVIDER, app_state.DEFAULT_CHARACTER_IMAGE_MODEL
        )
        self._ref_warning.display = False
        self._ollama_warning.display = False
        self._refresh_tts_api_key_status(app_state.DEFAULT_TTS_PROVIDER)
        self._populate_tts_voices("")
        self.call_after_refresh(self._clear_suppress_flag)
        self.notify("Reset to defaults — press Save to persist.", timeout=3)
