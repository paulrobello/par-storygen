"""Tests for SettingsScreen — editable wizard defaults + text provider + art toggle."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, Select, Static, Switch

from storygen.config import AppConfig
from storygen.llm.models import ImageProviderConfig, TextProviderConfig
from storygen.screens.settings import (
    ImageProviderChanged,
    SettingsScreen,
    TextProviderChanged,
)
from storygen.storage import app_state

_CFG = AppConfig(
    openai_api_key="k",
    text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
    image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
    character_image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
)


class _Harness(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self._cfg = _CFG
        self.received_messages: list[TextProviderChanged] = []
        self.received_image_messages: list[ImageProviderChanged] = []

    def on_mount(self) -> None:
        self.push_screen(SettingsScreen(self._cfg))

    def compose(self) -> ComposeResult:
        yield from []

    def on_text_provider_changed(self, event: TextProviderChanged) -> None:
        self.received_messages.append(event)

    def on_image_provider_changed(self, event: ImageProviderChanged) -> None:
        self.received_image_messages.append(event)


@pytest.mark.asyncio
async def test_settings_shows_current_image_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The editable image-provider widgets reflect the default on boot."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        assert (
            screen.query_one("#image-provider-model", Input).value == app_state.DEFAULT_IMAGE_MODEL
        )
        img_sel = screen.query_one("#image-provider-select", Select)  # pyright: ignore[reportUnknownVariableType]
        assert img_sel.value == app_state.DEFAULT_IMAGE_PROVIDER  # pyright: ignore[reportUnknownMemberType]


@pytest.mark.asyncio
async def test_text_provider_widgets_reflect_stored_prefs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.write_provider_prefs(
        app_state.ProviderPrefs(
            provider="openrouter",
            model="anthropic/claude-3.5-sonnet",
            base_url="https://openrouter.example.com/v1",
        )
    )
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        provider_select = screen.query_one("#provider-select", Select)  # pyright: ignore[reportUnknownVariableType]
        model_input = screen.query_one("#provider-model", Input)
        base_url_input = screen.query_one("#provider-base-url", Input)
        assert provider_select.value == "openrouter"  # pyright: ignore[reportUnknownMemberType]
        assert model_input.value == "anthropic/claude-3.5-sonnet"
        assert base_url_input.value == "https://openrouter.example.com/v1"


@pytest.mark.asyncio
async def test_changing_provider_updates_model_and_placeholder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        provider_select = screen.query_one("#provider-select", Select)  # pyright: ignore[reportUnknownVariableType]
        model_input = screen.query_one("#provider-model", Input)
        base_url_input = screen.query_one("#provider-base-url", Input)

        # Simulate user switching provider.
        provider_select.value = "ollama"
        await pilot.pause()

        # First suggested model for ollama.
        assert model_input.value == app_state.SUGGESTED_MODELS["ollama"][0]
        # base_url cleared so placeholder (factory default URL) becomes visible.
        assert base_url_input.value == ""
        assert "11434" in base_url_input.placeholder


@pytest.mark.asyncio
async def test_save_with_empty_model_does_not_persist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.write_provider_prefs(app_state.ProviderPrefs(provider="openai", model="gpt-4o-mini"))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        screen.query_one("#provider-model", Input).value = "   "
        screen.query_one("#btn-save", Button).press()
        await pilot.pause()

    # No message posted, prefs unchanged.
    assert app.received_messages == []
    prefs = app_state.read_provider_prefs()
    assert prefs.model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_save_with_invalid_base_url_does_not_persist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.write_provider_prefs(
        app_state.ProviderPrefs(provider="openai", model="gpt-4o-mini", base_url="")
    )
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        screen.query_one("#provider-base-url", Input).value = "not-a-url"
        screen.query_one("#btn-save", Button).press()
        await pilot.pause()

    assert app.received_messages == []
    assert app_state.read_provider_prefs().base_url == ""


@pytest.mark.asyncio
async def test_save_persists_provider_prefs_and_posts_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)

        provider_sel = screen.query_one(  # pyright: ignore[reportUnknownVariableType]
            "#provider-select", Select
        )
        provider_sel.value = "ollama"  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        # Set explicit values (override the auto-fill from the change handler).
        screen.query_one("#provider-model", Input).value = "qwen2.5:32b-instruct"
        screen.query_one("#provider-base-url", Input).value = "http://local:11434/v1"
        screen.query_one("#btn-save", Button).press()
        await pilot.pause()

    prefs = app_state.read_provider_prefs()
    assert prefs.provider == "ollama"
    assert prefs.model == "qwen2.5:32b-instruct"
    assert prefs.base_url == "http://local:11434/v1"
    assert len(app.received_messages) == 1
    assert app.received_messages[0].prefs == prefs


@pytest.mark.asyncio
async def test_save_with_empty_base_url_stores_empty_string(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Empty base_url means 'use factory default' — store "" explicitly."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        screen.query_one("#provider-model", Input).value = "gpt-4o"
        screen.query_one("#provider-base-url", Input).value = ""
        screen.query_one("#btn-save", Button).press()
        await pilot.pause()

    prefs = app_state.read_provider_prefs()
    assert prefs.base_url == ""
    assert prefs.model == "gpt-4o"


@pytest.mark.asyncio
async def test_reset_resets_provider_widgets_without_persisting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.write_provider_prefs(
        app_state.ProviderPrefs(
            provider="openrouter",
            model="anthropic/claude-3.5-sonnet",
            base_url="https://openrouter.example.com/v1",
        )
    )
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        screen.query_one("#btn-reset", Button).press()
        await pilot.pause()

        reset_sel = screen.query_one(  # pyright: ignore[reportUnknownVariableType]
            "#provider-select", Select
        )
        assert reset_sel.value == "openai"  # pyright: ignore[reportUnknownMemberType]
        assert screen.query_one("#provider-model", Input).value == app_state.DEFAULT_TEXT_MODEL
        assert screen.query_one("#provider-base-url", Input).value == ""

    # Persistence untouched.
    prefs = app_state.read_provider_prefs()
    assert prefs.provider == "openrouter"


@pytest.mark.asyncio
async def test_settings_populates_from_persisted_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.write_wizard_defaults(
        app_state.WizardDefaults(
            theme="A misted valley",
            tone_preset="dark",
            tone_descriptor="",
            narration_style="first_person",
            art_style="noir comic",
            characters="A wizard and a goblin",
        )
    )
    app_state.set_art_enabled(False)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        art_input = screen.query_one("#default-art-style", Input)
        assert art_input.value == "noir comic"
        switch = screen.query_one("#art-enabled-switch", Switch)
        assert switch.value is False


@pytest.mark.asyncio
async def test_settings_save_persists_wizard_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)

        art_input = screen.query_one("#default-art-style", Input)
        art_input.value = "watercolor"
        length_input = screen.query_one("#default-length", Input)
        length_input.value = "18"
        switch = screen.query_one("#art-enabled-switch", Switch)
        switch.value = False

        save_btn = screen.query_one("#btn-save", Button)
        save_btn.press()
        await pilot.pause()

    restored = app_state.read_wizard_defaults()
    assert restored.art_style == "watercolor"
    assert restored.target_major_beats == 18
    assert app_state.art_enabled() is False


@pytest.mark.asyncio
async def test_settings_reset_does_not_persist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reset clears widgets but doesn't write to disk until Save is pressed."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.write_wizard_defaults(app_state.WizardDefaults(art_style="noir comic"))
    app_state.set_art_enabled(False)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        reset_btn = screen.query_one("#btn-reset", Button)
        reset_btn.press()
        await pilot.pause()
        # Without Save, the persisted state must be unchanged.
        assert app_state.read_wizard_defaults().art_style == "noir comic"
        assert app_state.art_enabled() is False


@pytest.mark.asyncio
async def test_api_key_status_reflects_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        status = screen.query_one("#provider-api-key-status", Static)
        assert "present" in str(status.content).lower()

        key_status_sel = screen.query_one(  # pyright: ignore[reportUnknownVariableType]
            "#provider-select", Select
        )
        key_status_sel.value = "openrouter"  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert "missing" in str(status.content).lower()


# ------------------------------------------------------------------
# Image provider widgets (Phase 5)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_image_provider_widgets_reflect_stored_prefs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.write_image_provider_prefs(
        app_state.ImageProviderPrefs(
            provider="zai",
            model="glm-image",
            base_url="https://api.z.ai/api/paas/v4/",
            fallback_provider="openai",
            fallback_model="gpt-image-2",
        )
    )
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        img_sel = screen.query_one("#image-provider-select", Select)  # pyright: ignore[reportUnknownVariableType]
        fb_sel = screen.query_one("#image-fallback-select", Select)  # pyright: ignore[reportUnknownVariableType]
        assert img_sel.value == "zai"  # pyright: ignore[reportUnknownMemberType]
        assert screen.query_one("#image-provider-model", Input).value == "glm-image"
        assert (
            screen.query_one("#image-provider-base-url", Input).value
            == "https://api.z.ai/api/paas/v4/"
        )
        assert fb_sel.value == "openai"  # pyright: ignore[reportUnknownMemberType]
        fb_input = screen.query_one("#image-fallback-model", Input)
        assert fb_input.value == "gpt-image-2"
        assert fb_input.disabled is False


@pytest.mark.asyncio
async def test_image_provider_change_updates_model_and_placeholder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        img_sel = screen.query_one("#image-provider-select", Select)  # pyright: ignore[reportUnknownVariableType]
        img_sel.value = "gemini"  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        model_input = screen.query_one("#image-provider-model", Input)
        base_url_input = screen.query_one("#image-provider-base-url", Input)
        # First curated suggestion for Gemini wins.
        assert model_input.value == app_state.SUGGESTED_IMAGE_MODELS["gemini"][0]
        # Gemini doesn't use a base_url — Input cleared, placeholder explains.
        assert base_url_input.value == ""
        assert "Gemini" in base_url_input.placeholder


@pytest.mark.asyncio
async def test_fallback_select_none_disables_fallback_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.write_image_provider_prefs(
        app_state.ImageProviderPrefs(
            provider="openai",
            model="gpt-image-2",
            fallback_provider="gemini",
            fallback_model="gemini-3-pro-image-preview",
        )
    )
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        fb_sel = screen.query_one("#image-fallback-select", Select)  # pyright: ignore[reportUnknownVariableType]
        fb_input = screen.query_one("#image-fallback-model", Input)
        # Sanity: loaded state has a fallback enabled.
        assert fb_input.disabled is False

        fb_sel.value = SettingsScreen._FALLBACK_NONE  # pyright: ignore[reportUnknownMemberType,reportPrivateUsage]
        await pilot.pause()
        assert fb_input.disabled is True
        assert fb_input.value == ""


@pytest.mark.asyncio
async def test_fallback_select_enables_and_prefills_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        fb_sel = screen.query_one("#image-fallback-select", Select)  # pyright: ignore[reportUnknownVariableType]
        fb_input = screen.query_one("#image-fallback-model", Input)
        assert fb_input.disabled is True

        fb_sel.value = "zai"  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert fb_input.disabled is False
        assert fb_input.value == app_state.SUGGESTED_IMAGE_MODELS["zai"][0]


@pytest.mark.asyncio
async def test_ref_warning_visible_only_for_unsupported_providers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        ref = screen.query_one("#image-ref-warning", Static)
        # Default (openai) supports refs — hidden.
        assert ref.display is False

        img_sel = screen.query_one("#image-provider-select", Select)  # pyright: ignore[reportUnknownVariableType]
        img_sel.value = "zai"  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert ref.display is True

        img_sel.value = "gemini"  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        # Gemini supports refs — hidden again.
        assert ref.display is False


@pytest.mark.asyncio
async def test_ollama_warning_visible_when_primary_or_fallback_is_ollama(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        warn = screen.query_one("#image-ollama-warning", Static)
        assert warn.display is False

        # Primary = ollama.
        img_sel = screen.query_one("#image-provider-select", Select)  # pyright: ignore[reportUnknownVariableType]
        img_sel.value = "ollama"  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert warn.display is True

        # Flip primary back to openai, fallback = ollama: still visible.
        img_sel.value = "openai"  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert warn.display is False
        fb_sel = screen.query_one("#image-fallback-select", Select)  # pyright: ignore[reportUnknownVariableType]
        fb_sel.value = "ollama"  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert warn.display is True


@pytest.mark.asyncio
async def test_save_with_empty_image_model_does_not_persist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        screen.query_one("#image-provider-model", Input).value = "   "
        screen.query_one("#btn-save", Button).press()
        await pilot.pause()

    # Neither provider-changed message posted; image prefs still at defaults.
    assert app.received_image_messages == []
    assert app.received_messages == []
    prefs = app_state.read_image_provider_prefs()
    assert prefs == app_state.ImageProviderPrefs()


@pytest.mark.asyncio
async def test_save_with_invalid_image_base_url_does_not_persist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        screen.query_one("#image-provider-base-url", Input).value = "not-a-url"
        screen.query_one("#btn-save", Button).press()
        await pilot.pause()

    assert app.received_image_messages == []
    assert app_state.read_image_provider_prefs() == app_state.ImageProviderPrefs()


@pytest.mark.asyncio
async def test_save_persists_image_provider_prefs_and_posts_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)

        img_sel = screen.query_one("#image-provider-select", Select)  # pyright: ignore[reportUnknownVariableType]
        img_sel.value = "gemini"  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        fb_sel = screen.query_one("#image-fallback-select", Select)  # pyright: ignore[reportUnknownVariableType]
        fb_sel.value = "openai"  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        screen.query_one("#image-provider-model", Input).value = "gemini-3-pro-image-preview"
        screen.query_one("#image-fallback-model", Input).value = "gpt-image-2"
        screen.query_one("#btn-save", Button).press()
        await pilot.pause()

    prefs = app_state.read_image_provider_prefs()
    assert prefs.provider == "gemini"
    assert prefs.model == "gemini-3-pro-image-preview"
    assert prefs.fallback_provider == "openai"
    assert prefs.fallback_model == "gpt-image-2"
    assert len(app.received_image_messages) == 1
    assert app.received_image_messages[0].prefs == prefs


@pytest.mark.asyncio
async def test_reset_clears_image_widgets_without_persisting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.write_image_provider_prefs(
        app_state.ImageProviderPrefs(
            provider="zai",
            model="glm-image",
            fallback_provider="openai",
            fallback_model="gpt-image-2",
        )
    )
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        screen.query_one("#btn-reset", Button).press()
        await pilot.pause()

        img_sel = screen.query_one("#image-provider-select", Select)  # pyright: ignore[reportUnknownVariableType]
        fb_sel = screen.query_one("#image-fallback-select", Select)  # pyright: ignore[reportUnknownVariableType]
        assert img_sel.value == app_state.DEFAULT_IMAGE_PROVIDER  # pyright: ignore[reportUnknownMemberType]
        assert (
            screen.query_one("#image-provider-model", Input).value == app_state.DEFAULT_IMAGE_MODEL
        )
        assert screen.query_one("#image-provider-base-url", Input).value == ""
        assert fb_sel.value == SettingsScreen._FALLBACK_NONE  # pyright: ignore[reportUnknownMemberType,reportPrivateUsage]
        fb_input = screen.query_one("#image-fallback-model", Input)
        assert fb_input.value == ""
        assert fb_input.disabled is True
        assert screen.query_one("#image-ref-warning", Static).display is False
        assert screen.query_one("#image-ollama-warning", Static).display is False

    # Persistence untouched.
    restored = app_state.read_image_provider_prefs()
    assert restored.provider == "zai"
    assert restored.fallback_provider == "openai"


@pytest.mark.asyncio
async def test_save_with_fallback_matching_primary_warns_but_persists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """User can save a matching fallback; a warning fires but prefs still persist."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)

        calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        monkeypatch.setattr(
            screen,
            "notify",
            lambda *a, **k: calls.append((a, k)),  # type: ignore[no-untyped-call]
        )

        # Drive primary and fallback to the same provider (gemini).
        img_sel = screen.query_one("#image-provider-select", Select)  # pyright: ignore[reportUnknownVariableType]
        img_sel.value = "gemini"  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        fb_sel = screen.query_one("#image-fallback-select", Select)  # pyright: ignore[reportUnknownVariableType]
        fb_sel.value = "gemini"  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        # Ensure both model inputs are populated (fallback-model was prefilled
        # by _on_image_fallback_changed, but guard against future changes).
        screen.query_one("#image-provider-model", Input).value = "gemini-3.1-flash-image-preview"
        screen.query_one("#image-fallback-model", Input).value = "gemini-3-pro-image-preview"

        screen.query_one("#btn-save", Button).press()
        await pilot.pause()

    # A warning notification fired mentioning "Fallback".
    warnings = [
        (a, k)
        for (a, k) in calls
        if k.get("severity") == "warning" and a and "Fallback" in str(a[0])
    ]
    assert len(warnings) >= 1, f"Expected a warning about matching fallback, got: {calls}"

    # Despite the warning, prefs persisted with fallback == primary.
    prefs = app_state.read_image_provider_prefs()
    assert prefs.provider == "gemini"
    assert prefs.fallback_provider == "gemini"
    assert prefs.fallback_model == "gemini-3-pro-image-preview"
    # And the ImageProviderChanged message still posted (save completed).
    assert len(app.received_image_messages) == 1
    assert app.received_image_messages[0].prefs == prefs


# ------------------------------------------------------------------
# Character portrait provider widgets
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scene_cover_and_character_image_provider_sections_render(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        headings = [str(static.content) for static in screen.query(Static)]
        assert "Art generation provider (scenes + covers)" in headings
        assert "Character portrait provider" in headings
        assert "Image provider" not in headings


@pytest.mark.asyncio
async def test_character_image_provider_defaults_show_openai_v15(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        char_sel = screen.query_one("#character-image-provider-select", Select)  # pyright: ignore[reportUnknownVariableType]
        char_model_select = screen.query_one("#character-image-provider-model-select", Select)  # pyright: ignore[reportUnknownVariableType]
        char_model_input = screen.query_one("#character-image-provider-model", Input)
        assert char_sel.value == app_state.DEFAULT_CHARACTER_IMAGE_PROVIDER  # pyright: ignore[reportUnknownMemberType]
        assert char_model_select.value == app_state.DEFAULT_CHARACTER_IMAGE_MODEL  # pyright: ignore[reportUnknownMemberType]
        assert char_model_input.value == app_state.DEFAULT_CHARACTER_IMAGE_MODEL


@pytest.mark.asyncio
async def test_save_persists_character_image_provider_prefs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)

        char_sel = screen.query_one("#character-image-provider-select", Select)  # pyright: ignore[reportUnknownVariableType]
        char_sel.value = "gemini"  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        screen.query_one(
            "#character-image-provider-model", Input
        ).value = "gemini-3-pro-image-preview"
        screen.query_one(
            "#character-image-provider-base-url", Input
        ).value = "https://generativelanguage.googleapis.com/v1"
        screen.query_one("#btn-save", Button).press()
        await pilot.pause()

    prefs = app_state.read_character_image_provider_prefs()
    assert prefs.provider == "gemini"
    assert prefs.model == "gemini-3-pro-image-preview"
    assert prefs.base_url == "https://generativelanguage.googleapis.com/v1"
    assert len(app.received_image_messages) == 1


@pytest.mark.asyncio
async def test_reset_restores_character_image_provider_defaults_without_persisting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.write_character_image_provider_prefs(
        app_state.CharacterImageProviderPrefs(
            provider="zai",
            model="glm-image",
            base_url="https://api.z.ai/v1",
        )
    )
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        screen.query_one("#btn-reset", Button).press()
        await pilot.pause()

        char_sel = screen.query_one("#character-image-provider-select", Select)  # pyright: ignore[reportUnknownVariableType]
        char_model_select = screen.query_one("#character-image-provider-model-select", Select)  # pyright: ignore[reportUnknownVariableType]
        assert char_sel.value == app_state.DEFAULT_CHARACTER_IMAGE_PROVIDER  # pyright: ignore[reportUnknownMemberType]
        assert char_model_select.value == app_state.DEFAULT_CHARACTER_IMAGE_MODEL  # pyright: ignore[reportUnknownMemberType]
        assert (
            screen.query_one("#character-image-provider-model", Input).value
            == app_state.DEFAULT_CHARACTER_IMAGE_MODEL
        )
        assert screen.query_one("#character-image-provider-base-url", Input).value == ""

    restored = app_state.read_character_image_provider_prefs()
    assert restored.provider == "zai"
    assert restored.model == "glm-image"


# ------------------------------------------------------------------
# Branch prefetch (v2 Phase 1)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prefetch_section_renders_with_two_switches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        prefetch_sw = screen.query_one("#prefetch-enabled-switch", Switch)
        prefetch_img_sw = screen.query_one("#prefetch-images-switch", Switch)
        # Defaults: both off.
        assert prefetch_sw.value is False
        assert prefetch_img_sw.value is False
        # Images switch is gated off when prefetch is off.
        assert prefetch_img_sw.disabled is True


@pytest.mark.asyncio
async def test_prefetch_images_disabled_when_prefetch_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        prefetch_sw = screen.query_one("#prefetch-enabled-switch", Switch)
        prefetch_img_sw = screen.query_one("#prefetch-images-switch", Switch)
        # Toggle prefetch on then off — verify gating tracks.
        prefetch_sw.value = True
        await pilot.pause()
        assert prefetch_img_sw.disabled is False
        prefetch_sw.value = False
        await pilot.pause()
        assert prefetch_img_sw.disabled is True


@pytest.mark.asyncio
async def test_prefetch_images_disabled_when_art_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        art_sw = screen.query_one("#art-enabled-switch", Switch)
        prefetch_sw = screen.query_one("#prefetch-enabled-switch", Switch)
        prefetch_img_sw = screen.query_one("#prefetch-images-switch", Switch)
        # Art off, prefetch on → images switch still disabled.
        art_sw.value = False
        await pilot.pause()
        prefetch_sw.value = True
        await pilot.pause()
        assert prefetch_img_sw.disabled is True


@pytest.mark.asyncio
async def test_prefetch_images_enabled_when_both_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        art_sw = screen.query_one("#art-enabled-switch", Switch)
        prefetch_sw = screen.query_one("#prefetch-enabled-switch", Switch)
        prefetch_img_sw = screen.query_one("#prefetch-images-switch", Switch)
        art_sw.value = True
        await pilot.pause()
        prefetch_sw.value = True
        await pilot.pause()
        assert prefetch_img_sw.disabled is False


@pytest.mark.asyncio
async def test_save_persists_prefetch_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        prefetch_sw = screen.query_one("#prefetch-enabled-switch", Switch)
        prefetch_img_sw = screen.query_one("#prefetch-images-switch", Switch)
        prefetch_sw.value = True
        await pilot.pause()
        prefetch_img_sw.value = True
        await pilot.pause()
        screen.query_one("#btn-save", Button).press()
        await pilot.pause()

    assert app_state.prefetch_enabled() is True
    assert app_state.prefetch_images_enabled() is True


@pytest.mark.asyncio
async def test_reset_clears_prefetch_flags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # Persist truthy initial state so populate would otherwise show True.
    app_state.set_prefetch_enabled(True)
    app_state.set_prefetch_images_enabled(True)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        prefetch_sw = screen.query_one("#prefetch-enabled-switch", Switch)
        prefetch_img_sw = screen.query_one("#prefetch-images-switch", Switch)
        # Populate loaded the on-state.
        assert prefetch_sw.value is True
        assert prefetch_img_sw.value is True

        screen.query_one("#btn-reset", Button).press()
        await pilot.pause()

        assert prefetch_sw.value is False
        assert prefetch_img_sw.value is False

    # No persist on reset — disk values unchanged.
    assert app_state.prefetch_enabled() is True
    assert app_state.prefetch_images_enabled() is True


@pytest.mark.asyncio
async def test_streaming_switch_default_off_and_enabled_when_art_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The streaming switch defaults off but is interactable while art is on."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        streaming_sw = screen.query_one("#image-streaming-switch", Switch)
        assert streaming_sw.value is False
        # Art defaults on, so streaming switch must be enabled (interactable).
        assert streaming_sw.disabled is False


@pytest.mark.asyncio
async def test_streaming_switch_disabled_when_art_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When art generation is globally off, streaming has nothing to preview."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        art_sw = screen.query_one("#art-enabled-switch", Switch)
        streaming_sw = screen.query_one("#image-streaming-switch", Switch)
        art_sw.value = False
        await pilot.pause()
        assert streaming_sw.disabled is True
        # Toggling art back on re-enables it.
        art_sw.value = True
        await pilot.pause()
        assert streaming_sw.disabled is False


@pytest.mark.asyncio
async def test_save_persists_streaming_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Toggling the streaming switch and pressing Save updates app_state."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        streaming_sw = screen.query_one("#image-streaming-switch", Switch)
        streaming_sw.value = True
        await pilot.pause()
        screen.query_one("#btn-save", Button).press()
        await pilot.pause()

    assert app_state.image_streaming_enabled() is True


@pytest.mark.asyncio
async def test_reset_clears_streaming_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Reset clears the widget without persisting; on-disk value untouched."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.set_image_streaming_enabled(True)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        streaming_sw = screen.query_one("#image-streaming-switch", Switch)
        # Populate loaded the persisted on-state.
        assert streaming_sw.value is True

        screen.query_one("#btn-reset", Button).press()
        await pilot.pause()

        assert streaming_sw.value is False

    # Reset is widget-only — disk value persists until Save.
    assert app_state.image_streaming_enabled() is True


@pytest.mark.asyncio
async def test_llm_cache_switch_default_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The LLM cache switch defaults off and renders with the expected id."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        cache_sw = screen.query_one("#llm-cache-switch", Switch)
        assert cache_sw.value is False


@pytest.mark.asyncio
async def test_save_persists_llm_cache_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Toggling the LLM cache switch and pressing Save updates app_state."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        cache_sw = screen.query_one("#llm-cache-switch", Switch)
        cache_sw.value = True
        await pilot.pause()
        screen.query_one("#btn-save", Button).press()
        await pilot.pause()

    assert app_state.llm_cache_enabled() is True


@pytest.mark.asyncio
async def test_reset_clears_llm_cache_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Reset clears the widget without persisting; on-disk value untouched."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.set_llm_cache_enabled(True)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        cache_sw = screen.query_one("#llm-cache-switch", Switch)
        # Populate loaded the persisted on-state.
        assert cache_sw.value is True

        screen.query_one("#btn-reset", Button).press()
        await pilot.pause()

        assert cache_sw.value is False

    # Reset is widget-only — disk value persists until Save.
    assert app_state.llm_cache_enabled() is True
