"""Unit tests for app_state — last-played story persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from storygen.storage import app_state


def test_last_story_id_empty_when_no_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert app_state.last_story_id() is None


def test_remember_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.remember_last_story("abc-123")
    assert app_state.last_story_id() == "abc-123"


def test_remember_overwrites_previous(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.remember_last_story("first")
    app_state.remember_last_story("second")
    assert app_state.last_story_id() == "second"


def test_corrupt_state_returns_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "storygen"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "state.json").write_text("not json {", encoding="utf-8")
    assert app_state.last_story_id() is None


def test_wizard_defaults_empty_state_returns_constants(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    defaults = app_state.read_wizard_defaults()
    assert defaults.theme == ""
    assert defaults.tone_preset == app_state.DEFAULT_TONE_PRESET
    assert defaults.tone_descriptor == ""
    assert defaults.narration_style == app_state.DEFAULT_NARRATION_STYLE
    assert defaults.art_style == app_state.DEFAULT_ART_STYLE
    assert defaults.target_major_beats == app_state.DEFAULT_TARGET_MAJOR_BEATS
    assert defaults.target_major_beats == 5
    assert defaults.characters == ""


def test_wizard_defaults_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    defaults = app_state.WizardDefaults(
        theme="A swamp planet",
        tone_preset="custom",
        tone_descriptor="melancholy comedy",
        narration_style="first_person",
        art_style="watercolor",
        target_major_beats=15,
        characters="A wizard and a goblin",
    )
    app_state.write_wizard_defaults(defaults)
    restored = app_state.read_wizard_defaults()
    assert restored == defaults
    assert restored.target_major_beats == 15


def test_wizard_defaults_target_beats_clamps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pathological persisted target values are clamped/coerced on read."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "storygen"
    cfg_dir.mkdir(parents=True)

    state_file = cfg_dir / "state.json"

    state_file.write_text(
        json.dumps({"wizard_defaults": {"target_major_beats": 0}}),
        encoding="utf-8",
    )
    assert app_state.read_wizard_defaults().target_major_beats == app_state.MIN_TARGET_MAJOR_BEATS

    state_file.write_text(
        json.dumps({"wizard_defaults": {"target_major_beats": 999}}),
        encoding="utf-8",
    )
    assert app_state.read_wizard_defaults().target_major_beats == app_state.MAX_TARGET_MAJOR_BEATS

    state_file.write_text(
        json.dumps({"wizard_defaults": {"target_major_beats": "not-a-number"}}),
        encoding="utf-8",
    )
    assert (
        app_state.read_wizard_defaults().target_major_beats == app_state.DEFAULT_TARGET_MAJOR_BEATS
    )

    # Missing key falls back to default.
    state_file.write_text(
        json.dumps({"wizard_defaults": {}}),
        encoding="utf-8",
    )
    assert (
        app_state.read_wizard_defaults().target_major_beats == app_state.DEFAULT_TARGET_MAJOR_BEATS
    )


def test_wizard_defaults_partial_state_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If only some keys are present, missing ones use the constants."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "storygen"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "state.json").write_text(
        json.dumps({"wizard_defaults": {"art_style": "noir comic"}}),
        encoding="utf-8",
    )
    defaults = app_state.read_wizard_defaults()
    assert defaults.art_style == "noir comic"
    assert defaults.theme == ""
    assert defaults.tone_preset == app_state.DEFAULT_TONE_PRESET
    assert defaults.narration_style == app_state.DEFAULT_NARRATION_STYLE


def test_art_enabled_defaults_true(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert app_state.art_enabled() is True


def test_set_art_enabled_round_trips(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.set_art_enabled(False)
    assert app_state.art_enabled() is False
    app_state.set_art_enabled(True)
    assert app_state.art_enabled() is True


def test_provider_prefs_empty_state_returns_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    prefs = app_state.read_provider_prefs()
    assert prefs.provider == "openai"
    assert prefs.model == "gpt-4o-mini"
    assert prefs.base_url == ""


def test_provider_prefs_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    prefs = app_state.ProviderPrefs(
        provider="openrouter",
        model="anthropic/claude-3.5-sonnet",
        base_url="https://openrouter.ai/api/v1",
    )
    app_state.write_provider_prefs(prefs)
    restored = app_state.read_provider_prefs()
    assert restored == prefs


def test_provider_prefs_unknown_provider_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Unknown provider strings in state.json fall through to defaults."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "storygen"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "state.json").write_text(
        json.dumps(
            {
                "provider_prefs": {
                    "provider": "bogus-provider",
                    "model": "some-model",
                    "base_url": "",
                }
            }
        ),
        encoding="utf-8",
    )
    prefs = app_state.read_provider_prefs()
    # Falls back to defaults when provider isn't in allowlist.
    assert prefs.provider == "openai"
    assert prefs.model == "gpt-4o-mini"


def test_provider_prefs_corrupt_state_returns_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "storygen"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "state.json").write_text("not json {", encoding="utf-8")
    prefs = app_state.read_provider_prefs()
    assert prefs == app_state.ProviderPrefs()


def test_provider_prefs_partial_state_fills_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "storygen"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "state.json").write_text(
        json.dumps({"provider_prefs": {"provider": "ollama"}}),
        encoding="utf-8",
    )
    prefs = app_state.read_provider_prefs()
    assert prefs.provider == "ollama"
    assert prefs.model == "gpt-4o-mini"
    assert prefs.base_url == ""


def test_provider_prefs_missing_key_returns_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "storygen"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "state.json").write_text(
        json.dumps({"last_story_id": "x"}),
        encoding="utf-8",
    )
    prefs = app_state.read_provider_prefs()
    assert prefs == app_state.ProviderPrefs()


def test_provider_prefs_does_not_clobber_other_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.remember_last_story("game-xyz")
    app_state.set_art_enabled(False)
    app_state.write_provider_prefs(app_state.ProviderPrefs(provider="ollama", model="llama3.3:70b"))
    assert app_state.last_story_id() == "game-xyz"
    assert app_state.art_enabled() is False
    assert app_state.read_provider_prefs().provider == "ollama"


def test_provider_choices_and_suggested_models_shape() -> None:
    """Sanity-check the UI-facing constants stay consistent."""
    provider_ids = {pid for _, pid in app_state.PROVIDER_CHOICES}
    assert provider_ids == {"openai", "openrouter", "ollama"}
    assert set(app_state.SUGGESTED_MODELS.keys()) == provider_ids
    for models in app_state.SUGGESTED_MODELS.values():
        assert len(models) >= 1
        assert all(isinstance(m, str) and m for m in models)


def test_image_provider_prefs_empty_state_returns_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    prefs = app_state.read_image_provider_prefs()
    assert prefs.provider == "openai"
    assert prefs.model == "gpt-image-2"
    assert prefs.base_url == ""
    assert prefs.fallback_provider == ""
    assert prefs.fallback_model == ""


def test_image_provider_prefs_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    prefs = app_state.ImageProviderPrefs(
        provider="gemini",
        model="gemini-3.1-flash-image-preview",
        base_url="https://generativelanguage.googleapis.com/v1",
        fallback_provider="openai",
        fallback_model="gpt-image-2",
    )
    app_state.write_image_provider_prefs(prefs)
    restored = app_state.read_image_provider_prefs()
    assert restored == prefs


def test_image_provider_prefs_unknown_provider_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Unknown provider strings in state.json fall through to defaults."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "storygen"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "state.json").write_text(
        json.dumps(
            {
                "image_provider_prefs": {
                    "provider": "mystery-provider",
                    "model": "anything",
                    "base_url": "",
                    "fallback_provider": "",
                    "fallback_model": "",
                }
            }
        ),
        encoding="utf-8",
    )
    prefs = app_state.read_image_provider_prefs()
    assert prefs == app_state.ImageProviderPrefs()


def test_image_provider_prefs_unknown_fallback_provider_resets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Unknown fallback_provider strings are reset to "", and fallback_model follows."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "storygen"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "state.json").write_text(
        json.dumps(
            {
                "image_provider_prefs": {
                    "provider": "openai",
                    "model": "gpt-image-2",
                    "base_url": "",
                    "fallback_provider": "not-a-provider",
                    "fallback_model": "some-ghost-model",
                }
            }
        ),
        encoding="utf-8",
    )
    prefs = app_state.read_image_provider_prefs()
    # fallback_provider bad → reset, fallback_model force-cleared.
    assert prefs.provider == "openai"
    assert prefs.model == "gpt-image-2"
    assert prefs.fallback_provider == ""
    assert prefs.fallback_model == ""


def test_image_provider_prefs_empty_fallback_clears_fallback_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """fallback_provider == "" implies fallback_model must be "" (no ghost model)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "storygen"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "state.json").write_text(
        json.dumps(
            {
                "image_provider_prefs": {
                    "provider": "openai",
                    "model": "gpt-image-2",
                    "base_url": "",
                    "fallback_provider": "",
                    "fallback_model": "leftover-model",
                }
            }
        ),
        encoding="utf-8",
    )
    prefs = app_state.read_image_provider_prefs()
    assert prefs.fallback_provider == ""
    assert prefs.fallback_model == ""


def test_image_provider_prefs_corrupt_state_returns_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "storygen"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "state.json").write_text("not json {", encoding="utf-8")
    prefs = app_state.read_image_provider_prefs()
    assert prefs == app_state.ImageProviderPrefs()


def test_image_provider_prefs_missing_key_returns_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "storygen"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "state.json").write_text(
        json.dumps({"last_story_id": "x"}),
        encoding="utf-8",
    )
    prefs = app_state.read_image_provider_prefs()
    assert prefs == app_state.ImageProviderPrefs()


def test_image_provider_prefs_does_not_clobber_other_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.remember_last_story("game-abc")
    app_state.set_art_enabled(False)
    app_state.write_provider_prefs(app_state.ProviderPrefs(provider="ollama", model="llama3.3:70b"))
    app_state.write_image_provider_prefs(
        app_state.ImageProviderPrefs(provider="gemini", model="gemini-3.1-flash-image-preview")
    )
    assert app_state.last_story_id() == "game-abc"
    assert app_state.art_enabled() is False
    assert app_state.read_provider_prefs().provider == "ollama"
    assert app_state.read_image_provider_prefs().provider == "gemini"


def test_image_provider_choices_and_suggested_models_shape() -> None:
    """Sanity-check the UI-facing image constants stay consistent."""
    provider_ids = {pid for _, pid in app_state.IMAGE_PROVIDER_CHOICES}
    assert provider_ids == {"openai", "gemini", "zai", "ollama"}
    assert set(app_state.SUGGESTED_IMAGE_MODELS.keys()) == provider_ids
    for models in app_state.SUGGESTED_IMAGE_MODELS.values():
        assert len(models) >= 1
        assert all(isinstance(m, str) and m for m in models)
    # PROVIDER_SUPPORTS_REFS must be a subset of known providers.
    assert provider_ids >= app_state.PROVIDER_SUPPORTS_REFS
    # Key env map covers every provider id.
    assert set(app_state.IMAGE_API_KEY_ENV.keys()) == provider_ids


def test_character_image_provider_prefs_empty_state_returns_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    prefs = app_state.read_character_image_provider_prefs()
    assert prefs.provider == "openai"
    assert prefs.model == "gpt-image-1.5"
    assert prefs.base_url == ""


def test_character_image_provider_prefs_round_trip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    prefs = app_state.CharacterImageProviderPrefs(
        provider="gemini",
        model="gemini-3-pro-image-preview",
        base_url="https://generativelanguage.googleapis.com/v1",
    )
    app_state.write_character_image_provider_prefs(prefs)
    restored = app_state.read_character_image_provider_prefs()
    assert restored == prefs


def test_character_image_provider_prefs_invalid_provider_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "storygen"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "state.json").write_text(
        json.dumps(
            {
                "character_image_provider_prefs": {
                    "provider": "mystery-provider",
                    "model": "anything",
                    "base_url": "https://example.invalid",
                }
            }
        ),
        encoding="utf-8",
    )
    prefs = app_state.read_character_image_provider_prefs()
    assert prefs == app_state.CharacterImageProviderPrefs()


def test_write_all_settings_persists_character_image_provider_prefs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    prefs = app_state.CharacterImageProviderPrefs(
        provider="zai",
        model="glm-image",
        base_url="https://api.z.ai/v1",
    )
    app_state.write_all_settings(
        image_prefs=app_state.ImageProviderPrefs(),
        character_image_prefs=prefs,
        text_prefs=app_state.ProviderPrefs(),
        wizard_defaults=app_state.WizardDefaults(),
        art_enabled_value=True,
        prefetch_enabled_value=False,
        prefetch_images_enabled_value=False,
        image_streaming_enabled_value=False,
    )
    assert app_state.read_character_image_provider_prefs() == prefs


def test_wizard_defaults_does_not_clobber_other_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """write_wizard_defaults preserves last_story_id and art_enabled."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.remember_last_story("game-xyz")
    app_state.set_art_enabled(False)
    app_state.write_wizard_defaults(app_state.WizardDefaults(art_style="noir"))
    assert app_state.last_story_id() == "game-xyz"
    assert app_state.art_enabled() is False
    assert app_state.read_wizard_defaults().art_style == "noir"


def test_write_all_settings_persists_atomically(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """All four Settings-screen-owned sections persist in one write, and
    unrelated top-level keys (e.g. ``last_story_id``) are preserved."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # Seed an unrelated key in state.json to verify preservation.
    app_state.write_app_state({"last_story_id": "foo"})

    image_prefs = app_state.ImageProviderPrefs(
        provider="gemini",
        model="gemini-3.1-flash-image-preview",
        base_url="",
        fallback_provider="openai",
        fallback_model="gpt-image-2",
    )
    text_prefs = app_state.ProviderPrefs(
        provider="openai",
        model="gpt-4o-mini",
        base_url="",
    )
    wizard_defaults = app_state.WizardDefaults(
        theme="A swamp planet",
        tone_preset="custom",
        tone_descriptor="melancholy comedy",
        narration_style="first_person",
        art_style="watercolor",
        target_major_beats=15,
        characters="A wizard and a goblin",
    )

    app_state.write_all_settings(
        image_prefs=image_prefs,
        text_prefs=text_prefs,
        wizard_defaults=wizard_defaults,
        art_enabled_value=False,
        prefetch_enabled_value=True,
        prefetch_images_enabled_value=True,
        image_streaming_enabled_value=True,
    )

    # Unrelated key preserved.
    raw = app_state.read_app_state()
    assert raw["last_story_id"] == "foo"
    # All sections readable via their typed helpers.
    assert app_state.read_image_provider_prefs() == image_prefs
    assert app_state.read_provider_prefs() == text_prefs
    assert app_state.read_wizard_defaults() == wizard_defaults
    assert app_state.art_enabled() is False
    assert app_state.prefetch_enabled() is True
    assert app_state.prefetch_images_enabled() is True
    assert app_state.image_streaming_enabled() is True


def test_write_all_settings_matches_individual_writers_byte_for_byte(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Atomic writer must produce identical on-disk JSON vs the 4-call path."""
    image_prefs = app_state.ImageProviderPrefs(
        provider="zai",
        model="glm-image",
        base_url="https://api.z.ai/v1",
        fallback_provider="openai",
        fallback_model="gpt-image-2",
    )
    text_prefs = app_state.ProviderPrefs(
        provider="ollama",
        model="llama3.3:70b",
        base_url="http://localhost:11434/v1",
    )
    wizard_defaults = app_state.WizardDefaults(
        theme="Underwater ruins",
        tone_preset="serious",
        tone_descriptor="",
        narration_style="third_person",
        art_style="noir comic",
        target_major_beats=12,
        characters="A diver and a shark",
    )

    # Path A: sequential writes (mirrors what write_all_settings does in one shot).
    path_a = tmp_path / "a"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(path_a))
    app_state.write_image_provider_prefs(image_prefs)
    app_state.write_provider_prefs(text_prefs)
    app_state.write_wizard_defaults(wizard_defaults)
    app_state.set_art_enabled(False)
    app_state.set_prefetch_enabled(True)
    app_state.set_prefetch_images_enabled(False)
    app_state.set_image_streaming_enabled(True)
    app_state.set_llm_cache_enabled(False)
    app_state.set_auto_select_enabled(False)
    app_state.set_auto_open_art_enabled(False)
    bytes_a = (path_a / "storygen" / "state.json").read_bytes()

    # Path B: single atomic write.
    path_b = tmp_path / "b"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(path_b))
    app_state.write_all_settings(
        image_prefs=image_prefs,
        text_prefs=text_prefs,
        wizard_defaults=wizard_defaults,
        art_enabled_value=False,
        prefetch_enabled_value=True,
        prefetch_images_enabled_value=False,
        image_streaming_enabled_value=True,
        llm_cache_enabled_value=False,
        auto_select_value=False,
        auto_open_art_value=False,
    )
    bytes_b = (path_b / "storygen" / "state.json").read_bytes()

    assert bytes_a == bytes_b


def test_prefetch_enabled_defaults_to_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert app_state.prefetch_enabled() is False


def test_prefetch_images_enabled_defaults_to_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert app_state.prefetch_images_enabled() is False


def test_set_prefetch_enabled_persists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.set_prefetch_enabled(True)
    assert app_state.prefetch_enabled() is True
    app_state.set_prefetch_enabled(False)
    assert app_state.prefetch_enabled() is False


def test_set_prefetch_images_enabled_persists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.set_prefetch_images_enabled(True)
    assert app_state.prefetch_images_enabled() is True
    app_state.set_prefetch_images_enabled(False)
    assert app_state.prefetch_images_enabled() is False


def test_write_all_settings_persists_prefetch_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The atomic writer round-trips both new prefetch flags."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.write_all_settings(
        image_prefs=app_state.ImageProviderPrefs(),
        text_prefs=app_state.ProviderPrefs(),
        wizard_defaults=app_state.WizardDefaults(),
        art_enabled_value=True,
        prefetch_enabled_value=True,
        prefetch_images_enabled_value=True,
        image_streaming_enabled_value=False,
    )
    assert app_state.prefetch_enabled() is True
    assert app_state.prefetch_images_enabled() is True

    app_state.write_all_settings(
        image_prefs=app_state.ImageProviderPrefs(),
        text_prefs=app_state.ProviderPrefs(),
        wizard_defaults=app_state.WizardDefaults(),
        art_enabled_value=True,
        prefetch_enabled_value=False,
        prefetch_images_enabled_value=False,
        image_streaming_enabled_value=False,
    )
    assert app_state.prefetch_enabled() is False
    assert app_state.prefetch_images_enabled() is False


def test_image_streaming_enabled_defaults_to_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert app_state.image_streaming_enabled() is False


def test_set_image_streaming_enabled_persists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.set_image_streaming_enabled(True)
    assert app_state.image_streaming_enabled() is True
    app_state.set_image_streaming_enabled(False)
    assert app_state.image_streaming_enabled() is False


def test_llm_cache_enabled_defaults_to_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert app_state.llm_cache_enabled() is False


def test_set_llm_cache_enabled_persists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.set_llm_cache_enabled(True)
    assert app_state.llm_cache_enabled() is True
    app_state.set_llm_cache_enabled(False)
    assert app_state.llm_cache_enabled() is False


def test_write_all_settings_persists_llm_cache_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The atomic writer round-trips the llm_cache flag."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.write_all_settings(
        image_prefs=app_state.ImageProviderPrefs(),
        text_prefs=app_state.ProviderPrefs(),
        wizard_defaults=app_state.WizardDefaults(),
        art_enabled_value=True,
        prefetch_enabled_value=False,
        prefetch_images_enabled_value=False,
        image_streaming_enabled_value=False,
        llm_cache_enabled_value=True,
    )
    assert app_state.llm_cache_enabled() is True

    app_state.write_all_settings(
        image_prefs=app_state.ImageProviderPrefs(),
        text_prefs=app_state.ProviderPrefs(),
        wizard_defaults=app_state.WizardDefaults(),
        art_enabled_value=True,
        prefetch_enabled_value=False,
        prefetch_images_enabled_value=False,
        image_streaming_enabled_value=False,
        llm_cache_enabled_value=False,
    )
    assert app_state.llm_cache_enabled() is False


def test_write_all_settings_persists_image_streaming_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The atomic writer round-trips the image_streaming flag."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.write_all_settings(
        image_prefs=app_state.ImageProviderPrefs(),
        text_prefs=app_state.ProviderPrefs(),
        wizard_defaults=app_state.WizardDefaults(),
        art_enabled_value=True,
        prefetch_enabled_value=False,
        prefetch_images_enabled_value=False,
        image_streaming_enabled_value=True,
    )
    assert app_state.image_streaming_enabled() is True

    app_state.write_all_settings(
        image_prefs=app_state.ImageProviderPrefs(),
        text_prefs=app_state.ProviderPrefs(),
        wizard_defaults=app_state.WizardDefaults(),
        art_enabled_value=True,
        prefetch_enabled_value=False,
        prefetch_images_enabled_value=False,
        image_streaming_enabled_value=False,
    )
    assert app_state.image_streaming_enabled() is False


def test_wizard_defaults_save_to_catalog_default_true() -> None:
    """save_to_catalog defaults to True on a fresh WizardDefaults."""
    defaults = app_state.WizardDefaults()
    assert defaults.save_to_catalog is True


def test_read_wizard_defaults_includes_save_to_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reading state.json with save_to_catalog=False preserves it."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "storygen"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "state.json").write_text(
        json.dumps({"wizard_defaults": {"save_to_catalog": False}}),
        encoding="utf-8",
    )
    defaults = app_state.read_wizard_defaults()
    assert defaults.save_to_catalog is False


def test_write_wizard_defaults_roundtrips_save_to_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Writing save_to_catalog=False and reading it back preserves the value."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    defaults = app_state.WizardDefaults(save_to_catalog=False)
    app_state.write_wizard_defaults(defaults)
    restored = app_state.read_wizard_defaults()
    assert restored.save_to_catalog is False
