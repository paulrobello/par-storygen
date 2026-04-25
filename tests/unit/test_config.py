"""Unit tests for config module — dotenv + env + defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

from storygen.config import AppConfig, load_config, reset_dotenv_cache_for_tests


def test_loads_defaults_when_no_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    # Isolate XDG_CONFIG_HOME so the dev's real state.json (provider_prefs,
    # image_provider_prefs, ...) can't influence the resolved config.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("STORYGEN_TEXT_MODEL", raising=False)
    monkeypatch.delenv("STORYGEN_TEXT_PROVIDER", raising=False)
    monkeypatch.delenv("STORYGEN_TEXT_BASE_URL", raising=False)
    monkeypatch.delenv("STORYGEN_IMAGE_PROVIDER", raising=False)
    monkeypatch.delenv("STORYGEN_IMAGE_MODEL", raising=False)
    monkeypatch.delenv("STORYGEN_IMAGE_BASE_URL", raising=False)
    reset_dotenv_cache_for_tests()

    cfg = load_config()

    assert cfg.text_config.provider == "openai"
    assert cfg.text_config.model == "gpt-4o-mini"
    assert cfg.image_config.provider == "openai"
    assert cfg.image_config.model == "gpt-image-2"
    assert cfg.openai_api_key == ""


def test_real_env_wins_over_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "from-real-env")
    reset_dotenv_cache_for_tests()

    cfg = load_config()

    assert cfg.openai_api_key == "from-real-env"


def test_dotenv_fills_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_dotenv_cache_for_tests()

    cfg = load_config()

    assert cfg.openai_api_key == "from-dotenv"


def test_text_model_override_honored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STORYGEN_TEXT_MODEL", "gpt-4o")
    reset_dotenv_cache_for_tests()

    cfg = load_config()

    assert cfg.text_config.model == "gpt-4o"


def test_image_provider_overrides_honored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STORYGEN_IMAGE_BASE_URL", "https://images.example.com/v1")
    monkeypatch.setenv("STORYGEN_IMAGE_API_KEY", "sk-image-only")
    reset_dotenv_cache_for_tests()

    cfg = load_config()

    assert cfg.image_config.base_url == "https://images.example.com/v1"
    assert cfg.image_config.api_key == "sk-image-only"


def test_provider_env_honored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STORYGEN_TEXT_PROVIDER", "openrouter")
    monkeypatch.setenv("STORYGEN_TEXT_MODEL", "anthropic/claude-3.5-sonnet")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    reset_dotenv_cache_for_tests()

    cfg = load_config()

    assert cfg.text_config.provider == "openrouter"
    assert cfg.text_config.model == "anthropic/claude-3.5-sonnet"


def test_prefs_used_when_no_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When no env vars set, ProviderPrefs from state.json win over hardcoded defaults."""
    from storygen.storage import app_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("STORYGEN_TEXT_PROVIDER", raising=False)
    monkeypatch.delenv("STORYGEN_TEXT_MODEL", raising=False)
    monkeypatch.delenv("STORYGEN_TEXT_BASE_URL", raising=False)
    reset_dotenv_cache_for_tests()

    app_state.write_provider_prefs(
        app_state.ProviderPrefs(
            provider="ollama",
            model="llama3.3:70b",
            base_url="http://remote-ollama:11434/v1",
        )
    )

    cfg = load_config()

    assert cfg.text_config.provider == "ollama"
    assert cfg.text_config.model == "llama3.3:70b"
    assert cfg.text_config.base_url == "http://remote-ollama:11434/v1"


def test_env_beats_prefs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Real env vars win over ProviderPrefs."""
    from storygen.storage import app_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("STORYGEN_TEXT_PROVIDER", "openai")
    monkeypatch.setenv("STORYGEN_TEXT_MODEL", "gpt-4o")
    reset_dotenv_cache_for_tests()

    app_state.write_provider_prefs(app_state.ProviderPrefs(provider="ollama", model="llama3.3:70b"))

    cfg = load_config()

    assert cfg.text_config.provider == "openai"
    assert cfg.text_config.model == "gpt-4o"


def test_prefs_partial_env_overlay(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Env vars overlay prefs at the field level (env model, prefs provider)."""
    from storygen.storage import app_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("STORYGEN_TEXT_PROVIDER", raising=False)
    monkeypatch.setenv("STORYGEN_TEXT_MODEL", "qwen2.5:32b-instruct")
    monkeypatch.delenv("STORYGEN_TEXT_BASE_URL", raising=False)
    reset_dotenv_cache_for_tests()

    app_state.write_provider_prefs(app_state.ProviderPrefs(provider="ollama", model="llama3.3:70b"))

    cfg = load_config()

    assert cfg.text_config.provider == "ollama"
    assert cfg.text_config.model == "qwen2.5:32b-instruct"


def test_invalid_env_provider_falls_through_to_prefs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Garbage STORYGEN_TEXT_PROVIDER value is ignored; prefs (or default) apply."""
    from storygen.storage import app_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("STORYGEN_TEXT_PROVIDER", "not-a-real-provider")
    monkeypatch.delenv("STORYGEN_TEXT_MODEL", raising=False)
    reset_dotenv_cache_for_tests()

    app_state.write_provider_prefs(
        app_state.ProviderPrefs(provider="openrouter", model="some/model")
    )

    cfg = load_config()

    # Bad env provider dropped; prefs provider wins.
    assert cfg.text_config.provider == "openrouter"
    assert cfg.text_config.model == "some/model"


def test_empty_env_strings_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Empty env values don't override prefs."""
    from storygen.storage import app_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("STORYGEN_TEXT_PROVIDER", "")
    monkeypatch.setenv("STORYGEN_TEXT_MODEL", "")
    monkeypatch.setenv("STORYGEN_TEXT_BASE_URL", "")
    reset_dotenv_cache_for_tests()

    app_state.write_provider_prefs(app_state.ProviderPrefs(provider="ollama", model="llama3.3:70b"))

    cfg = load_config()

    assert cfg.text_config.provider == "ollama"
    assert cfg.text_config.model == "llama3.3:70b"


def test_invalid_resolved_config_falls_back_to_hardcoded_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If everything resolves to an invalid config, fall back to safe default."""
    from storygen.storage import app_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("STORYGEN_TEXT_PROVIDER", raising=False)
    monkeypatch.delenv("STORYGEN_TEXT_MODEL", raising=False)
    monkeypatch.setenv("STORYGEN_TEXT_BASE_URL", "not-a-url")
    reset_dotenv_cache_for_tests()

    # Empty-string model in prefs (shouldn't happen via UI, but defend anyway).
    app_state.write_provider_prefs(app_state.ProviderPrefs(provider="openai", model="gpt-4o-mini"))

    cfg = load_config()

    # Malformed base_url triggered fallback to hardcoded default.
    assert cfg.text_config.provider == "openai"
    assert cfg.text_config.model == "gpt-4o-mini"
    assert cfg.text_config.base_url is None


def test_image_provider_env_honored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("STORYGEN_IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("STORYGEN_IMAGE_MODEL", "gemini-3.1-flash-image-preview")
    reset_dotenv_cache_for_tests()

    cfg = load_config()

    assert cfg.image_config.provider == "gemini"
    assert cfg.image_config.model == "gemini-3.1-flash-image-preview"


def test_image_prefs_used_when_no_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When no image env vars set, ImageProviderPrefs from state.json win over defaults."""
    from storygen.storage import app_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("STORYGEN_IMAGE_PROVIDER", raising=False)
    monkeypatch.delenv("STORYGEN_IMAGE_MODEL", raising=False)
    monkeypatch.delenv("STORYGEN_IMAGE_BASE_URL", raising=False)
    reset_dotenv_cache_for_tests()

    app_state.write_image_provider_prefs(
        app_state.ImageProviderPrefs(
            provider="zai",
            model="glm-image",
            base_url="https://api.z.ai/v1",
        )
    )

    cfg = load_config()

    assert cfg.image_config.provider == "zai"
    assert cfg.image_config.model == "glm-image"
    assert cfg.image_config.base_url == "https://api.z.ai/v1"


def test_image_env_beats_prefs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Real env vars win over ImageProviderPrefs."""
    from storygen.storage import app_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("STORYGEN_IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("STORYGEN_IMAGE_MODEL", "gpt-image-1")
    reset_dotenv_cache_for_tests()

    app_state.write_image_provider_prefs(
        app_state.ImageProviderPrefs(provider="gemini", model="gemini-3.1-flash-image-preview")
    )

    cfg = load_config()

    assert cfg.image_config.provider == "openai"
    assert cfg.image_config.model == "gpt-image-1"


def test_image_prefs_partial_env_overlay(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Env vars overlay prefs at the field level (env model, prefs provider)."""
    from storygen.storage import app_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("STORYGEN_IMAGE_PROVIDER", raising=False)
    monkeypatch.setenv("STORYGEN_IMAGE_MODEL", "x/flux2-klein:9b")
    monkeypatch.delenv("STORYGEN_IMAGE_BASE_URL", raising=False)
    reset_dotenv_cache_for_tests()

    app_state.write_image_provider_prefs(
        app_state.ImageProviderPrefs(provider="ollama", model="x/z-image-turbo")
    )

    cfg = load_config()

    assert cfg.image_config.provider == "ollama"
    assert cfg.image_config.model == "x/flux2-klein:9b"


def test_invalid_image_env_provider_falls_through_to_prefs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Garbage STORYGEN_IMAGE_PROVIDER is ignored; prefs (or default) apply."""
    from storygen.storage import app_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("STORYGEN_IMAGE_PROVIDER", "not-a-real-provider")
    monkeypatch.delenv("STORYGEN_IMAGE_MODEL", raising=False)
    reset_dotenv_cache_for_tests()

    app_state.write_image_provider_prefs(
        app_state.ImageProviderPrefs(provider="gemini", model="gemini-3.1-flash-image-preview")
    )

    cfg = load_config()

    assert cfg.image_config.provider == "gemini"
    assert cfg.image_config.model == "gemini-3.1-flash-image-preview"


def test_empty_image_env_strings_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Empty image env values don't override prefs."""
    from storygen.storage import app_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("STORYGEN_IMAGE_PROVIDER", "")
    monkeypatch.setenv("STORYGEN_IMAGE_MODEL", "")
    monkeypatch.setenv("STORYGEN_IMAGE_BASE_URL", "")
    reset_dotenv_cache_for_tests()

    app_state.write_image_provider_prefs(
        app_state.ImageProviderPrefs(provider="gemini", model="gemini-3.1-flash-image-preview")
    )

    cfg = load_config()

    assert cfg.image_config.provider == "gemini"
    assert cfg.image_config.model == "gemini-3.1-flash-image-preview"


def test_invalid_resolved_image_config_falls_back_to_hardcoded_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If everything resolves to an invalid image config, fall back to safe default."""
    from storygen.storage import app_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("STORYGEN_IMAGE_PROVIDER", raising=False)
    monkeypatch.delenv("STORYGEN_IMAGE_MODEL", raising=False)
    monkeypatch.setenv("STORYGEN_IMAGE_BASE_URL", "not-a-url")
    reset_dotenv_cache_for_tests()

    app_state.write_image_provider_prefs(
        app_state.ImageProviderPrefs(provider="openai", model="gpt-image-2")
    )

    cfg = load_config()

    # Malformed base_url triggered fallback to hardcoded default.
    assert cfg.image_config.provider == "openai"
    assert cfg.image_config.model == "gpt-image-2"
    assert cfg.image_config.base_url is None


def test_image_config_falls_back_fully_on_invalid_base_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When image config validation fails, DROP the api_key too — don't attach
    a provider-specific key to the fallback OpenAI config."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("STORYGEN_IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("STORYGEN_IMAGE_API_KEY", "gemini-specific-key")
    monkeypatch.setenv("STORYGEN_IMAGE_BASE_URL", "not a url")  # triggers validation failure
    monkeypatch.delenv("STORYGEN_IMAGE_MODEL", raising=False)
    # Isolate dotenv
    monkeypatch.chdir(tmp_path)
    reset_dotenv_cache_for_tests()
    cfg = load_config().image_config
    assert cfg.provider == "openai"
    assert cfg.model == "gpt-image-2"
    assert cfg.base_url is None
    assert cfg.api_key is None, (
        "api_key must be dropped on fallback to avoid cross-provider key leakage"
    )


def test_image_api_key_still_honored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """STORYGEN_IMAGE_API_KEY keeps flowing through regardless of prefs layer."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("STORYGEN_IMAGE_API_KEY", "sk-image-layered")
    reset_dotenv_cache_for_tests()

    cfg = load_config()

    assert cfg.image_config.api_key == "sk-image-layered"


def test_app_config_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    cfg = AppConfig(
        openai_api_key="k",
        text_config=...,  # type: ignore[arg-type]
        image_config=...,  # type: ignore[arg-type]
    )
    try:
        cfg.openai_api_key = "mutated"  # type: ignore[misc]
    except FrozenInstanceError:
        return
    raise AssertionError("AppConfig must be frozen")
