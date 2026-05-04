"""Unit tests for OllamaImageProvider — mocks AsyncOpenAI against localhost."""

from __future__ import annotations

import base64
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import AsyncOpenAI

from storygen.images.base import ReferencePortrait
from storygen.images.ollama_provider import IMAGE_SIZE, OllamaImageProvider


def _make_b64_response(png_bytes: bytes) -> MagicMock:
    item = MagicMock()
    item.b64_json = base64.b64encode(png_bytes).decode()
    resp = MagicMock()
    resp.data = [item]
    return resp


def _make_provider(
    *,
    response: MagicMock | None = None,
    on_ref_loss: object | None = None,
) -> tuple[OllamaImageProvider, MagicMock]:
    client = MagicMock()
    client.images.generate = AsyncMock(
        return_value=response if response is not None else _make_b64_response(b"PNG-BYTES")
    )
    provider = OllamaImageProvider(
        model="x/z-image-turbo",
        client=cast(AsyncOpenAI, client),
        on_ref_loss=cast(object, on_ref_loss),  # type: ignore[arg-type]
    )
    return provider, client


@pytest.mark.asyncio
async def test_generate_portrait_calls_generate_with_b64_response_format() -> None:
    provider, client = _make_provider()

    out = await provider.generate_portrait("a tall rogue", transparent=False)

    assert out == b"PNG-BYTES"
    kwargs = client.images.generate.await_args.kwargs
    assert kwargs["model"] == "x/z-image-turbo"
    assert kwargs["size"] == IMAGE_SIZE == "1024x1024"
    assert kwargs["response_format"] == "b64_json"
    prompt = kwargs["prompt"]
    assert "a tall rogue" in prompt
    assert "full-length" in prompt.lower() or "full-body" in prompt.lower()


@pytest.mark.asyncio
async def test_generate_portrait_transparent_adds_transparent_png_phrase() -> None:
    provider, client = _make_provider()

    await provider.generate_portrait("a fox", transparent=True)

    prompt = client.images.generate.await_args.kwargs["prompt"]
    # Ollama is prompt-only transparency — the English phrase must appear.
    assert "Transparent PNG" in prompt


@pytest.mark.asyncio
async def test_generate_scene_with_refs_fires_ref_loss_once() -> None:
    on_ref_loss = MagicMock()
    provider, _client = _make_provider(on_ref_loss=on_ref_loss)

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

    on_ref_loss.assert_called_once()


@pytest.mark.asyncio
async def test_generate_scene_no_refs_does_not_fire_ref_loss() -> None:
    on_ref_loss = MagicMock()
    provider, client = _make_provider(on_ref_loss=on_ref_loss)

    await provider.generate_scene("scene", reference_portraits=[])

    on_ref_loss.assert_not_called()
    kwargs = client.images.generate.await_args.kwargs
    assert kwargs["response_format"] == "b64_json"


@pytest.mark.asyncio
async def test_missing_b64_json_raises_runtime_error() -> None:
    item = MagicMock()
    item.b64_json = None
    resp = MagicMock()
    resp.data = [item]
    provider, _client = _make_provider(response=resp)

    with pytest.raises(RuntimeError, match="no image data"):
        await provider.generate_portrait("x", transparent=False)


@pytest.mark.asyncio
async def test_empty_data_array_raises_runtime_error() -> None:
    resp = MagicMock()
    resp.data = []
    provider, _client = _make_provider(response=resp)

    with pytest.raises(RuntimeError, match="no image data"):
        await provider.generate_portrait("x", transparent=False)


def test_client_uses_localhost_base_url_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_ctor(*args: object, **kwargs: object) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr("storygen.images.ollama_provider.AsyncOpenAI", _fake_ctor)

    OllamaImageProvider()

    assert captured.get("base_url") == "http://localhost:11434/v1/"
    # Sentinel api_key; server ignores it, but the SDK requires non-empty.
    assert captured.get("api_key") == "ollama"


def test_custom_base_url_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_ctor(*args: object, **kwargs: object) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr("storygen.images.ollama_provider.AsyncOpenAI", _fake_ctor)

    OllamaImageProvider(base_url="http://ollama.internal:11434/v1/")

    assert captured.get("base_url") == "http://ollama.internal:11434/v1/"
