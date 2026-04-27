"""Smoke test: StoryGenApp boots and lands on MenuScreen."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from storygen.app import StoryGenApp
from storygen.llm.models import (
    Character,
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.llm.provider_factory import build_text_model
from storygen.screens.intro import IntroScreen
from storygen.screens.settings import ImageProviderChanged, TextProviderChanged
from storygen.storage import app_state
from storygen.storage.save import GameSave


@pytest.mark.asyncio
async def test_app_starts_on_menu(xdg_tmp, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    app = StoryGenApp()
    async with app.run_test() as pilot:
        assert isinstance(app.screen, IntroScreen)
        await pilot.pause()


@pytest.mark.asyncio
async def test_text_provider_changed_rebuilds_clients(
    xdg_tmp,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The on_text_provider_changed handler reloads config and rebuilds clients."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    # Work from the tmp dir so the repo's .env doesn't silently re-inject
    # STORYGEN_TEXT_* vars into os.environ via python-dotenv.
    monkeypatch.chdir(str(xdg_tmp))  # type: ignore[no-untyped-call]  # pyright: ignore[reportUnknownArgumentType]
    monkeypatch.delenv("STORYGEN_TEXT_PROVIDER", raising=False)
    monkeypatch.delenv("STORYGEN_TEXT_MODEL", raising=False)
    monkeypatch.delenv("STORYGEN_TEXT_BASE_URL", raising=False)
    from storygen.config import reset_dotenv_cache_for_tests

    reset_dotenv_cache_for_tests()

    app = StoryGenApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        original_text_model = app._text_model  # pyright: ignore[reportPrivateUsage]
        original_image_provider = app._image_provider  # pyright: ignore[reportPrivateUsage]

        # Persist a new provider pref (simulating what SettingsScreen._save_settings does).
        new_prefs = app_state.ProviderPrefs(
            provider="openrouter",
            model="anthropic/claude-3.5-sonnet",
            base_url="",
        )
        app_state.write_provider_prefs(new_prefs)

        app.on_text_provider_changed(TextProviderChanged(new_prefs))
        await pilot.pause()

        # Config reloaded with the new prefs.
        cfg = app._config  # pyright: ignore[reportPrivateUsage]
        assert cfg.text_config.provider == "openrouter"
        assert cfg.text_config.model == "anthropic/claude-3.5-sonnet"
        # Fresh client instances.
        assert app._text_model is not original_text_model  # pyright: ignore[reportPrivateUsage]
        assert app._image_provider is not original_image_provider  # pyright: ignore[reportPrivateUsage]


def _make_pinned_save(provider: str, model: str) -> GameSave:
    """Build a minimal GameSave whose text_config pins a specific provider/model."""
    node = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        # Non-empty narration so _backfill_blurb_if_missing early-returns
        # and doesn't attempt an LLM call during the test.
        narration="You open your eyes.",
        choices=[StoredChoice(id="c1", text="Sit up")],
        is_major=True,
        is_ending=False,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    return GameSave(
        version=1,
        id=uuid4(),
        theme=Theme(title="T", setting="S", premise="P", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider=provider, model=model),  # type: ignore[arg-type]
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        characters=[
            Character(
                id="alyx",
                name="Alyx",
                backstory="b",
                personality="p",
                physical_description="d",
                portrait_path=None,
                portrait_prompt=None,
                introduced_at_node_id="root",
            )
        ],
        nodes={"root": node},
        root_node_id="root",
        current_node_id="root",
        endings_reached=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_start_game_uses_save_text_config_not_app_model(
    xdg_tmp,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resumed save must use its pinned text_config, not whatever Settings last selected.

    Without the fix, ``_start_game`` built agents from ``self._text_model`` —
    the app-level model — so flipping Settings to a different provider would
    silently reroute an existing save's LLM traffic to the new provider while
    ``save.text_config`` still advertised the original one.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.chdir(str(xdg_tmp))  # type: ignore[no-untyped-call]  # pyright: ignore[reportUnknownArgumentType]
    monkeypatch.delenv("STORYGEN_TEXT_PROVIDER", raising=False)
    monkeypatch.delenv("STORYGEN_TEXT_MODEL", raising=False)
    monkeypatch.delenv("STORYGEN_TEXT_BASE_URL", raising=False)
    from storygen.config import reset_dotenv_cache_for_tests

    reset_dotenv_cache_for_tests()

    # Spy on build_text_model so we can see each call and its config.
    calls: list[TextProviderConfig] = []

    def spy(cfg: TextProviderConfig):  # type: ignore[no-untyped-def]
        calls.append(cfg)
        return build_text_model(cfg)

    monkeypatch.setattr("storygen.app.build_text_model", spy)

    # Disable art so _backfill_cover_if_missing is a no-op (this test focuses on text config).
    monkeypatch.setattr(app_state, "art_enabled", lambda: False)

    # App config defaults to openai; save pins ollama — they must differ.
    app = StoryGenApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        # Don't actually mount PlayScreen; we only care about text-model construction.
        def _no_switch(*_args: object, **_kwargs: object) -> None:
            return None

        monkeypatch.setattr(app, "switch_screen", _no_switch)
        save = _make_pinned_save(provider="ollama", model="llama3.3:70b")
        await app._start_game(save)  # pyright: ignore[reportPrivateUsage]

    pinned_calls = [c for c in calls if c.provider == "ollama"]
    assert pinned_calls, (
        "start_game must build a text model from save.text_config (ollama), "
        "not reuse self._text_model (openai)"
    )
    assert pinned_calls[0].model == "llama3.3:70b"


class _FakeStartImageProvider:
    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        on_partial: Any = None,
        reference_image: bytes | None = None,
    ) -> bytes:
        del description, transparent, art_style, on_partial, reference_image
        return b"portrait"

    async def generate_scene(
        self,
        prompt: str,
        *,
        reference_portraits: list[bytes],
        art_style: str = "children's story book",
        on_partial: Any = None,
    ) -> bytes:
        del prompt, reference_portraits, art_style, on_partial
        return b"scene"


@pytest.mark.asyncio
async def test_start_game_builds_art_and_character_routers_from_save_configs(
    xdg_tmp,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.chdir(str(xdg_tmp))  # type: ignore[no-untyped-call]  # pyright: ignore[reportUnknownArgumentType]
    from storygen.config import reset_dotenv_cache_for_tests

    reset_dotenv_cache_for_tests()

    calls: list[ImageProviderConfig] = []

    def spy_build_routed_image_provider(
        primary_cfg: ImageProviderConfig,
        *,
        fallback_cfg: ImageProviderConfig | None = None,
        on_ref_loss: object = None,
        on_fallback: object = None,
    ) -> _FakeStartImageProvider:
        del fallback_cfg, on_ref_loss, on_fallback
        calls.append(primary_cfg)
        return _FakeStartImageProvider()

    monkeypatch.setattr(
        "storygen.app.build_routed_image_provider",
        spy_build_routed_image_provider,
    )
    monkeypatch.setattr(app_state, "art_enabled", lambda: False)

    app = StoryGenApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        calls.clear()

        def _no_switch(*_args: object, **_kwargs: object) -> None:
            return None

        monkeypatch.setattr(app, "switch_screen", _no_switch)
        save = _make_pinned_save(provider="ollama", model="llama3.3:70b")
        art_cfg = ImageProviderConfig(provider="gemini", model="gemini-3.1-flash-image-preview")
        character_cfg = ImageProviderConfig(provider="zai", model="glm-image")
        save.image_config = art_cfg
        save.character_image_config = character_cfg

        await app._start_game(save)  # pyright: ignore[reportPrivateUsage]

    assert calls == [art_cfg, character_cfg]


# ----- Phase 4: ref-loss + fallback wiring -----------------------------------


@pytest.mark.asyncio
async def test_handle_ref_loss_is_idempotent_per_label(
    xdg_tmp,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_handle_ref_loss("zai")`` called twice surfaces exactly one toast."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    app = StoryGenApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        calls: list[tuple[object, ...]] = []

        def _spy(*args: object, **kwargs: object) -> None:
            calls.append((args, kwargs))

        monkeypatch.setattr(app, "notify", _spy)
        app._handle_ref_loss("zai")  # pyright: ignore[reportPrivateUsage]
        app._handle_ref_loss("zai")  # pyright: ignore[reportPrivateUsage]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_handle_ref_loss_surfaces_each_distinct_label(
    xdg_tmp,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two different labels = two distinct toasts."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    app = StoryGenApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(
            app,
            "notify",
            lambda *a, **k: calls.append((a, k)),  # type: ignore[no-untyped-call]
        )
        app._handle_ref_loss("zai")  # pyright: ignore[reportPrivateUsage]
        app._handle_ref_loss("ollama")  # pyright: ignore[reportPrivateUsage]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_handle_fallback_emits_warning_toast(
    xdg_tmp,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    app = StoryGenApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        monkeypatch.setattr(
            app,
            "notify",
            lambda *a, **k: calls.append((a, k)),  # type: ignore[no-untyped-call]
        )
        app._handle_fallback("gemini", RuntimeError("boom"))  # pyright: ignore[reportPrivateUsage]
    assert len(calls) == 1
    _args, kwargs = calls[0]
    assert kwargs.get("severity") == "warning"


@pytest.mark.asyncio
async def test_resolve_fallback_cfg_returns_none_when_no_fallback(
    xdg_tmp,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty fallback_provider pref → no fallback config."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    app_state.write_image_provider_prefs(
        app_state.ImageProviderPrefs(
            provider="openai",
            model="gpt-image-2",
            fallback_provider="",
            fallback_model="",
        )
    )
    app = StoryGenApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        primary = ImageProviderConfig(provider="openai", model="gpt-image-2")
        result = app._resolve_fallback_cfg(primary)  # pyright: ignore[reportPrivateUsage]
    assert result is None


@pytest.mark.asyncio
async def test_resolve_fallback_cfg_returns_none_when_matches_primary(
    xdg_tmp,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallback provider == primary provider → no fallback (degenerate)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    app_state.write_image_provider_prefs(
        app_state.ImageProviderPrefs(
            provider="openai",
            model="gpt-image-2",
            fallback_provider="openai",
            fallback_model="gpt-image-1",
        )
    )
    app = StoryGenApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        primary = ImageProviderConfig(provider="openai", model="gpt-image-2")
        result = app._resolve_fallback_cfg(primary)  # pyright: ignore[reportPrivateUsage]
    assert result is None


@pytest.mark.asyncio
async def test_resolve_fallback_cfg_builds_config_for_distinct_fallback(
    xdg_tmp,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Distinct fallback provider → ImageProviderConfig with matching provider."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("GEMINI_API_KEY", "gem-test")
    app_state.write_image_provider_prefs(
        app_state.ImageProviderPrefs(
            provider="openai",
            model="gpt-image-2",
            fallback_provider="gemini",
            fallback_model="gemini-3-pro-image-preview",
        )
    )
    app = StoryGenApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        primary = ImageProviderConfig(provider="openai", model="gpt-image-2")
        result = app._resolve_fallback_cfg(primary)  # pyright: ignore[reportPrivateUsage]
    assert result is not None
    assert result.provider == "gemini"
    assert result.model == "gemini-3-pro-image-preview"
    # api_key / base_url are NOT pinned for fallback — env resolution only.
    assert result.api_key is None
    assert result.base_url is None


@pytest.mark.asyncio
async def test_resolve_fallback_cfg_fills_default_model_when_blank(
    xdg_tmp,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty fallback_model falls back to SUGGESTED_IMAGE_MODELS[0]."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ZAI_API_KEY", "zai-test")
    app_state.write_image_provider_prefs(
        app_state.ImageProviderPrefs(
            provider="openai",
            model="gpt-image-2",
            fallback_provider="zai",
            fallback_model="",
        )
    )
    app = StoryGenApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        primary = ImageProviderConfig(provider="openai", model="gpt-image-2")
        result = app._resolve_fallback_cfg(primary)  # pyright: ignore[reportPrivateUsage]
    assert result is not None
    assert result.provider == "zai"
    # SUGGESTED_IMAGE_MODELS["zai"][0] == "glm-image"
    assert result.model == "glm-image"


@pytest.mark.asyncio
async def test_start_game_builds_per_save_routed_provider(
    xdg_tmp,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_start_game` builds a routed provider from ``save.image_config``."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.chdir(str(xdg_tmp))  # type: ignore[no-untyped-call]  # pyright: ignore[reportUnknownArgumentType]
    from storygen.config import reset_dotenv_cache_for_tests

    reset_dotenv_cache_for_tests()

    primary_cfgs: list[ImageProviderConfig] = []
    real = __import__("storygen.app", fromlist=["build_routed_image_provider"])
    real_fn = real.build_routed_image_provider

    def _spy(primary_cfg: ImageProviderConfig, **kwargs: object) -> object:
        primary_cfgs.append(primary_cfg)
        return real_fn(primary_cfg, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("storygen.app.build_routed_image_provider", _spy)

    # Disable art so _backfill_cover_if_missing is a no-op (this test focuses on provider routing).
    monkeypatch.setattr(app_state, "art_enabled", lambda: False)

    app = StoryGenApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        def _no_switch(*_args: object, **_kwargs: object) -> None:
            return None

        monkeypatch.setattr(app, "switch_screen", _no_switch)
        save = _make_pinned_save(provider="openai", model="gpt-4o-mini")
        # Verify save's image_config is the openai default, then override
        # to something distinct so we can tell app vs save sources apart.
        save.image_config = ImageProviderConfig(provider="openai", model="gpt-image-1")
        primary_cfgs.clear()  # discard the app-level __init__ call
        await app._start_game(save)  # pyright: ignore[reportPrivateUsage]

    assert primary_cfgs, "_start_game must call build_routed_image_provider"
    per_save_art = primary_cfgs[0]
    assert per_save_art.provider == "openai"
    assert per_save_art.model == "gpt-image-1"


# ----- Phase 5: image-provider Settings handler ------------------------------


@pytest.mark.asyncio
async def test_image_provider_changed_rebuilds_provider_and_clears_warn_set(
    xdg_tmp,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``on_image_provider_changed`` reloads config, rebuilds the image provider,
    and resets the session-scoped ref-loss warning set."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.chdir(str(xdg_tmp))  # type: ignore[no-untyped-call]  # pyright: ignore[reportUnknownArgumentType]
    from storygen.config import reset_dotenv_cache_for_tests

    reset_dotenv_cache_for_tests()

    app = StoryGenApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        original_image_provider = app._image_provider  # pyright: ignore[reportPrivateUsage]
        # Seed the warn set to verify it's cleared.
        app._ref_loss_warned.add("zai")  # pyright: ignore[reportPrivateUsage]

        new_prefs = app_state.ImageProviderPrefs(
            provider="openai",
            model="gpt-image-1",
        )
        app_state.write_image_provider_prefs(new_prefs)

        notifications: list[tuple[tuple[object, ...], dict[str, object]]] = []
        monkeypatch.setattr(
            app,
            "notify",
            lambda *a, **k: notifications.append((a, k)),  # type: ignore[no-untyped-call]
        )

        app.on_image_provider_changed(ImageProviderChanged(new_prefs))
        await pilot.pause()

        assert app._image_provider is not original_image_provider  # pyright: ignore[reportPrivateUsage]
        assert app._ref_loss_warned == set()  # pyright: ignore[reportPrivateUsage]
    # Notify fired with the new prefs.
    assert notifications
    body = str(notifications[-1][0][0])
    assert "openai/gpt-image-1" in body
