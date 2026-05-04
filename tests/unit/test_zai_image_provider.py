"""Unit tests for ZaiImageProvider — mocks AsyncOpenAI + httpx client."""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import AsyncOpenAI

from storygen.images.base import ReferencePortrait
from storygen.images.zai_provider import IMAGE_SIZE, ZaiImageProvider


def _make_image_response(url: str) -> MagicMock:
    item = MagicMock()
    item.url = url
    resp = MagicMock()
    resp.data = [item]
    return resp


def _make_http_client(*, status: int = 200, content: bytes = b"fake-png") -> MagicMock:
    http = MagicMock(spec=httpx.AsyncClient)
    response = MagicMock()
    response.status_code = status
    response.content = content
    http.get = AsyncMock(return_value=response)
    return http


def _make_provider(
    *,
    http_client: MagicMock | None = None,
    on_ref_loss: object | None = None,
    response: MagicMock | None = None,
) -> tuple[ZaiImageProvider, MagicMock, MagicMock]:
    client = MagicMock()
    client.images.generate = AsyncMock(
        return_value=response
        if response is not None
        else _make_image_response("https://cdn.example/image.png")
    )
    http = http_client if http_client is not None else _make_http_client()
    provider = ZaiImageProvider(
        model="glm-image",
        client=cast(AsyncOpenAI, client),
        http_client=cast(httpx.AsyncClient, http),
        on_ref_loss=cast(object, on_ref_loss),  # type: ignore[arg-type]
    )
    return provider, client, http


@pytest.mark.asyncio
async def test_generate_portrait_calls_images_generate_with_fixed_size() -> None:
    provider, client, http = _make_provider()

    out = await provider.generate_portrait("a tall rogue", transparent=False)

    assert out == b"fake-png"
    kwargs = client.images.generate.await_args.kwargs
    assert kwargs["model"] == "glm-image"
    assert kwargs["size"] == IMAGE_SIZE == "1280x1280"
    prompt = kwargs["prompt"]
    assert "a tall rogue" in prompt
    assert "children's story book" in prompt  # default art style
    assert "full-length" in prompt.lower() or "full-body" in prompt.lower()
    # URL fetch happened exactly once.
    http.get.assert_awaited_once_with("https://cdn.example/image.png")


@pytest.mark.asyncio
async def test_generate_portrait_transparent_includes_transparent_png_phrase() -> None:
    provider, client, _http = _make_provider()

    await provider.generate_portrait("a cat", transparent=True, art_style="noir comic")

    prompt = client.images.generate.await_args.kwargs["prompt"]
    # Z.AI is prompt-only transparency, so the English phrase must be present.
    assert "Transparent PNG" in prompt
    assert "noir comic" in prompt


@pytest.mark.asyncio
async def test_generate_scene_no_refs_does_not_fire_ref_loss() -> None:
    on_ref_loss = MagicMock()
    provider, client, _http = _make_provider(on_ref_loss=on_ref_loss)

    await provider.generate_scene("a wheat field", reference_portraits=[])

    on_ref_loss.assert_not_called()
    prompt = client.images.generate.await_args.kwargs["prompt"]
    assert "a wheat field" in prompt
    assert "Rendered in children's story book style." in prompt


@pytest.mark.asyncio
async def test_generate_scene_with_refs_fires_ref_loss_once() -> None:
    on_ref_loss = MagicMock()
    provider, _client, _http = _make_provider(on_ref_loss=on_ref_loss)

    await provider.generate_scene(
        "scene 1",
        reference_portraits=[
            ReferencePortrait("ref-a", b"ref-a"),
            ReferencePortrait("ref-b", b"ref-b"),
        ],
    )
    await provider.generate_scene(
        "scene 2", reference_portraits=[ReferencePortrait("ref-c", b"ref-c")]
    )
    await provider.generate_scene(
        "scene 3",
        reference_portraits=[
            ReferencePortrait("ref-d", b"ref-d"),
            ReferencePortrait("ref-e", b"ref-e"),
        ],
    )

    # Fires exactly once per provider instance, even across multiple calls.
    on_ref_loss.assert_called_once()


@pytest.mark.asyncio
async def test_generate_scene_without_on_ref_loss_callback_still_drops_refs() -> None:
    """A provider constructed without ``on_ref_loss`` must not raise when refs
    are supplied — it silently drops them."""
    provider, client, _http = _make_provider(on_ref_loss=None)

    out = await provider.generate_scene(
        "scene", reference_portraits=[ReferencePortrait("ref", b"ref")]
    )

    assert out == b"fake-png"
    # No reference data was forwarded to the API.
    kwargs = client.images.generate.await_args.kwargs
    assert "image" not in kwargs  # generate() does not take an ``image`` kwarg


@pytest.mark.asyncio
async def test_url_fetch_non_2xx_raises_runtime_error() -> None:
    http = _make_http_client(status=404, content=b"")
    provider, _client, _http = _make_provider(http_client=http)

    with pytest.raises(RuntimeError, match="404"):
        await provider.generate_portrait("x", transparent=False)


@pytest.mark.asyncio
async def test_response_with_no_data_raises_runtime_error() -> None:
    empty_resp = MagicMock()
    empty_resp.data = []
    provider, _client, _http = _make_provider(response=empty_resp)

    with pytest.raises(RuntimeError, match="no data"):
        await provider.generate_portrait("x", transparent=False)


@pytest.mark.asyncio
async def test_response_with_missing_url_raises_runtime_error() -> None:
    item = MagicMock()
    item.url = None
    resp = MagicMock()
    resp.data = [item]
    provider, _client, _http = _make_provider(response=resp)

    with pytest.raises(RuntimeError, match="url"):
        await provider.generate_portrait("x", transparent=False)


def test_missing_api_key_does_not_raise_at_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AsyncOpenAI requires non-empty api_key; provider uses a sentinel so
    construction succeeds even without ZAI_API_KEY set — auth errors
    surface at call time as a descriptive RuntimeError (not a misleading
    401 referencing the internal sentinel)."""
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    # Should not raise.
    provider = ZaiImageProvider()
    assert provider is not None


@pytest.mark.asyncio
async def test_missing_api_key_raises_descriptive_error_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calling a generate method without ZAI_API_KEY must raise a clear
    error before any HTTP traffic, instead of letting the sentinel leak
    into a 401 from Z.AI."""
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    provider = ZaiImageProvider()

    with pytest.raises(RuntimeError, match="ZAI_API_KEY"):
        await provider.generate_portrait("a cat", transparent=False)
    with pytest.raises(RuntimeError, match="ZAI_API_KEY"):
        await provider.generate_scene("a field", reference_portraits=[])


def test_api_key_threads_through_to_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit ``api_key`` reaches ``AsyncOpenAI(api_key=...)``."""
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    captured: dict[str, object] = {}

    def _fake_ctor(*args: object, **kwargs: object) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr("storygen.images.zai_provider.AsyncOpenAI", _fake_ctor)

    ZaiImageProvider(api_key="zai-secret-xyz")

    assert captured.get("api_key") == "zai-secret-xyz"
    # Default base_url must be preserved (trailing slash matters per Z.AI docs).
    assert captured.get("base_url") == "https://api.z.ai/api/paas/v4/"


def test_env_api_key_is_used_when_explicit_arg_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "env-zai-key")
    captured: dict[str, object] = {}

    def _fake_ctor(*args: object, **kwargs: object) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr("storygen.images.zai_provider.AsyncOpenAI", _fake_ctor)

    ZaiImageProvider()

    assert captured.get("api_key") == "env-zai-key"
