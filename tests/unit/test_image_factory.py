"""Unit tests for image provider factory."""

from __future__ import annotations

import pytest

from storygen.core.models import ImageProviderConfig
from storygen.images.base import ImageProvider, ReferencePortrait
from storygen.images.gemini_provider import GeminiImageProvider
from storygen.images.ollama_provider import OllamaImageProvider
from storygen.images.provider_factory import (
    _build,  # type: ignore[reportPrivateUsage]
    build_image_provider,
    build_routed_image_provider,
    validate_image_config,
)
from storygen.images.routed_provider import RoutedImageProvider
from storygen.images.zai_provider import ZaiImageProvider


def test_factory_returns_openai_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = ImageProviderConfig(provider="openai", model="gpt-image-2")
    provider = build_image_provider(cfg)
    assert isinstance(provider, ImageProvider)


def test_factory_rejects_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    # Direct bypass — Pydantic's Literal would catch this at config layer.
    with pytest.raises(ValueError, match="unsupported"):
        _build("nebula", "foo")


def test_factory_returns_zai_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 3: zai goes through a real backend adapter."""
    monkeypatch.setenv("ZAI_API_KEY", "zai-test")
    cfg = ImageProviderConfig(provider="zai", model="glm-image")
    provider = build_image_provider(cfg)
    assert isinstance(provider, ZaiImageProvider)
    assert isinstance(provider, ImageProvider)


def test_factory_returns_ollama_provider() -> None:
    """Phase 3: ollama goes through a real backend adapter."""
    cfg = ImageProviderConfig(provider="ollama", model="x/z-image-turbo")
    provider = build_image_provider(cfg)
    assert isinstance(provider, OllamaImageProvider)
    assert isinstance(provider, ImageProvider)


def test_factory_zai_threads_api_key_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-save ``api_key`` on the config reaches the Z.AI provider."""
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    captured: dict[str, object] = {}

    def _fake_ctor(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)

        class _C:
            pass

        return _C()

    monkeypatch.setattr("storygen.images.zai_provider.AsyncOpenAI", _fake_ctor)
    cfg = ImageProviderConfig(
        provider="zai",
        model="glm-image",
        api_key="zai-from-save",
    )
    build_image_provider(cfg)
    assert captured.get("api_key") == "zai-from-save"


def test_factory_ollama_honors_base_url_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-save ``base_url`` on the config reaches the Ollama provider."""
    captured: dict[str, object] = {}

    def _fake_ctor(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)

        class _C:
            pass

        return _C()

    monkeypatch.setattr("storygen.images.ollama_provider.AsyncOpenAI", _fake_ctor)
    cfg = ImageProviderConfig(
        provider="ollama",
        model="x/z-image-turbo",
        base_url="http://ollama.internal:11434/v1/",
    )
    build_image_provider(cfg)
    assert captured.get("base_url") == "http://ollama.internal:11434/v1/"


def test_factory_returns_gemini_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 2: gemini goes through a real backend adapter."""
    monkeypatch.setenv("GEMINI_API_KEY", "gem-test")
    cfg = ImageProviderConfig(provider="gemini", model="gemini-3.1-flash-image-preview")
    provider = build_image_provider(cfg)
    assert isinstance(provider, GeminiImageProvider)
    assert isinstance(provider, ImageProvider)


def test_factory_gemini_threads_api_key_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-save ``api_key`` on the config reaches the Gemini provider."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    captured: dict[str, object] = {}

    def _fake_client_ctor(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)

        class _C:
            pass

        return _C()

    monkeypatch.setattr("storygen.images.gemini_provider.genai.Client", _fake_client_ctor)
    cfg = ImageProviderConfig(
        provider="gemini",
        model="gemini-3.1-flash-image-preview",
        api_key="gem-from-save",
    )
    build_image_provider(cfg)
    assert captured.get("api_key") == "gem-from-save"


def test_validate_image_config_accepts_defaults() -> None:
    ok, err = validate_image_config(ImageProviderConfig())
    assert ok is True
    assert err == ""


def test_validate_image_config_accepts_http_base_url() -> None:
    ok, err = validate_image_config(
        ImageProviderConfig(
            provider="ollama", model="x/z-image-turbo", base_url="http://localhost:11434/v1"
        )
    )
    assert ok is True
    assert err == ""


def test_validate_image_config_accepts_https_base_url() -> None:
    ok, err = validate_image_config(
        ImageProviderConfig(
            provider="gemini",
            model="gemini-3.1-flash-image-preview",
            base_url="https://generativelanguage.googleapis.com/v1",
        )
    )
    assert ok is True
    assert err == ""


def test_validate_image_config_rejects_unknown_provider() -> None:
    ok, err = validate_image_config(
        ImageProviderConfig.model_construct(provider="mystery", model="gpt-image-2")
    )
    assert ok is False
    assert "provider" in err.lower()


def test_validate_image_config_rejects_empty_model() -> None:
    ok, err = validate_image_config(ImageProviderConfig(provider="openai", model=""))
    assert ok is False
    assert "model" in err.lower()


def test_validate_image_config_rejects_whitespace_model() -> None:
    ok, err = validate_image_config(ImageProviderConfig(provider="openai", model="   "))
    assert ok is False
    assert "model" in err.lower()


def test_validate_image_config_rejects_malformed_base_url() -> None:
    ok, err = validate_image_config(
        ImageProviderConfig(provider="openai", model="gpt-image-2", base_url="not a url")
    )
    assert ok is False
    assert "base_url" in err.lower() or "url" in err.lower()


def test_validate_image_config_treats_none_base_url_as_empty() -> None:
    ok, err = validate_image_config(
        ImageProviderConfig(provider="openai", model="gpt-image-2", base_url=None)
    )
    assert ok is True
    assert err == ""


def test_validate_image_config_treats_empty_base_url_as_unset() -> None:
    ok, err = validate_image_config(
        ImageProviderConfig(provider="openai", model="gpt-image-2", base_url="")
    )
    assert ok is True
    assert err == ""


# ----- Phase 4: build_routed_image_provider + on_ref_loss wiring -------------


def test_routed_returns_router_with_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Omitting ``fallback_cfg`` yields a router with a None fallback."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    primary_cfg = ImageProviderConfig(provider="openai", model="gpt-image-2")
    router = build_routed_image_provider(primary_cfg, fallback_cfg=None)
    assert isinstance(router, RoutedImageProvider)
    assert router._fallback is None  # pyright: ignore[reportPrivateUsage]


def test_routed_builds_primary_and_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ZAI_API_KEY", "zai-test")
    router = build_routed_image_provider(
        ImageProviderConfig(provider="openai", model="gpt-image-2"),
        fallback_cfg=ImageProviderConfig(provider="zai", model="glm-image"),
    )
    assert isinstance(router._primary, ImageProvider)  # pyright: ignore[reportPrivateUsage]
    assert isinstance(router._fallback, ImageProvider)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_routed_threads_ref_loss_to_nonref_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``on_ref_loss("zai")`` fires when a Z.AI primary drops refs on generate_scene."""
    monkeypatch.setenv("ZAI_API_KEY", "zai-test")
    # Stub AsyncOpenAI so no real network call happens.

    class _Resp:
        def __init__(self) -> None:
            class _D:
                url = "http://img/x.png"

            self.data = [_D()]

    class _Images:
        async def generate(self, **_kwargs: object) -> _Resp:
            return _Resp()

    class _Client:
        images = _Images()

    def _fake_ctor(*_args: object, **_kwargs: object) -> _Client:
        return _Client()

    monkeypatch.setattr("storygen.images.zai_provider.AsyncOpenAI", _fake_ctor)

    # Stub the URL download too.
    class _HttpResp:
        status_code = 200
        content = b"png"

    class _Http:
        async def get(self, _url: str) -> _HttpResp:
            return _HttpResp()

        async def __aenter__(self) -> _Http:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    def _http_factory(**_kwargs: object) -> _Http:
        return _Http()

    monkeypatch.setattr("storygen.images.zai_provider.httpx.AsyncClient", _http_factory)

    fired: list[str] = []
    router = build_routed_image_provider(
        ImageProviderConfig(provider="zai", model="glm-image"),
        fallback_cfg=None,
        on_ref_loss=fired.append,
    )
    await router.generate_scene("p", reference_portraits=[ReferencePortrait("ref", b"ref")])
    assert fired == ["zai"]


def test_routed_does_not_pass_ref_loss_to_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ref-supporting providers (openai) never receive ``on_ref_loss``.

    Verified indirectly: OpenAIImageProvider's constructor does NOT accept
    ``on_ref_loss``; if the factory forwarded it, construction would crash.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    # Should not raise.
    build_routed_image_provider(
        ImageProviderConfig(provider="openai", model="gpt-image-2"),
        fallback_cfg=None,
        on_ref_loss=lambda _label: None,
    )


def test_build_image_provider_accepts_on_ref_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``build_image_provider`` accepts ``on_ref_loss`` and threads to non-ref providers."""
    monkeypatch.setenv("ZAI_API_KEY", "zai-test")
    captured: list[object] = []

    def _fake_ctor(**kwargs: object) -> object:
        captured.append(kwargs.get("on_ref_loss"))

        class _C:
            pass

        return _C()

    monkeypatch.setattr("storygen.images.zai_provider.ZaiImageProvider", _fake_ctor)
    # Re-import via factory path so the patch applies.
    import storygen.images.provider_factory as pf

    monkeypatch.setattr(pf, "ZaiImageProvider", _fake_ctor)
    cb = lambda: None  # noqa: E731 — test-local
    pf.build_image_provider(
        ImageProviderConfig(provider="zai", model="glm-image"),
        on_ref_loss=cb,
    )
    assert captured == [cb]


def test_build_image_provider_openai_ignores_on_ref_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAI's constructor must NOT receive ``on_ref_loss`` (narrow surface)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured: list[dict[str, object]] = []

    def _fake_ctor(**kwargs: object) -> object:
        captured.append(dict(kwargs))

        class _C:
            pass

        return _C()

    import storygen.images.provider_factory as pf

    monkeypatch.setattr(pf, "OpenAIImageProvider", _fake_ctor)
    pf.build_image_provider(
        ImageProviderConfig(provider="openai", model="gpt-image-2"),
        on_ref_loss=lambda: None,
    )
    assert captured, "OpenAIImageProvider not constructed"
    assert "on_ref_loss" not in captured[0]
