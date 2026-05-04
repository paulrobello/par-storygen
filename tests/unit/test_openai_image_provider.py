"""Unit tests for OpenAIImageProvider — mocks the AsyncOpenAI client."""

from __future__ import annotations

import base64
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import AsyncOpenAI

from storygen.images.base import ReferencePortrait
from storygen.images.openai_provider import OpenAIImageProvider


def _make_image_response(png_bytes: bytes) -> MagicMock:
    data_item = MagicMock()
    data_item.b64_json = base64.b64encode(png_bytes).decode()
    resp = MagicMock()
    resp.data = [data_item]
    return resp


@pytest.mark.asyncio
async def test_generate_portrait_transparent() -> None:
    client = MagicMock()
    client.images.generate = AsyncMock(return_value=_make_image_response(b"PNG-PORTRAIT"))
    provider = OpenAIImageProvider(model="gpt-image-2", client=cast(AsyncOpenAI, client))

    out = await provider.generate_portrait("a tall rogue in a black coat", transparent=True)

    assert out == b"PNG-PORTRAIT"
    assert client.images.generate.await_args is not None
    kwargs = client.images.generate.await_args.kwargs
    assert kwargs["model"] == "gpt-image-2"
    prompt = kwargs["prompt"]
    # User description must appear verbatim
    assert "a tall rogue in a black coat" in prompt
    # Framing guidance must be injected so the body isn't cropped
    assert "full-length" in prompt.lower() or "full-body" in prompt.lower()
    assert "front-facing" in prompt.lower()
    # Transparency sentence appears; gpt-image-2 does not support
    # background="transparent" so the API flag falls back to "opaque".
    assert "Transparent PNG" in prompt
    assert "feet" in prompt.lower()  # explicit guard against bottom crops
    # Reference image must be neutral: no props that would persist into scenes.
    assert "no props" in prompt.lower()
    assert "hands empty" in prompt.lower()
    assert kwargs["background"] == "opaque"
    assert kwargs["quality"] == "low"
    # Portrait orientation — the smallest size that fits a full standing figure.
    assert kwargs["size"] == "1024x1536"
    assert kwargs["output_format"] == "png"


@pytest.mark.asyncio
async def test_generate_scene_passes_reference_images() -> None:
    client = MagicMock()
    client.images.edit = AsyncMock(return_value=_make_image_response(b"PNG-SCENE"))
    provider = OpenAIImageProvider(model="gpt-image-2", client=cast(AsyncOpenAI, client))

    out = await provider.generate_scene(
        "rooftop chase at night, neon rain",
        reference_portraits=[
            ReferencePortrait("ref-1", b"ref-1"),
            ReferencePortrait("ref-2", b"ref-2"),
        ],
    )

    assert out == b"PNG-SCENE"
    assert client.images.edit.await_args is not None
    kwargs = client.images.edit.await_args.kwargs
    assert kwargs["model"] == "gpt-image-2"
    # gpt-image-2 always processes references at high fidelity —
    # input_fidelity is not passed as a param.
    assert "input_fidelity" not in kwargs
    # image param is a list of file-like tuples — one per reference
    assert len(kwargs["image"]) == 2


@pytest.mark.asyncio
async def test_generate_scene_without_references_falls_back_to_generate() -> None:
    client = MagicMock()
    client.images.generate = AsyncMock(return_value=_make_image_response(b"PNG-NOREFS"))
    provider = OpenAIImageProvider(model="gpt-image-2", client=cast(AsyncOpenAI, client))

    out = await provider.generate_scene("a lonely wheat field at dusk", reference_portraits=[])

    assert out == b"PNG-NOREFS"
    client.images.generate.assert_awaited()


@pytest.mark.asyncio
async def test_generate_portrait_default_art_style_appears_in_prompt() -> None:
    """Without an art_style override, the default 'children's story book' shows up."""
    client = MagicMock()
    client.images.generate = AsyncMock(return_value=_make_image_response(b"PNG"))
    provider = OpenAIImageProvider(model="gpt-image-2", client=cast(AsyncOpenAI, client))
    await provider.generate_portrait("a tall rogue", transparent=True)
    assert client.images.generate.await_args is not None
    prompt = client.images.generate.await_args.kwargs["prompt"]
    assert "children's story book" in prompt


@pytest.mark.asyncio
async def test_generate_portrait_custom_art_style_appears_in_prompt() -> None:
    """A user-supplied art_style replaces the default in the prompt."""
    client = MagicMock()
    client.images.generate = AsyncMock(return_value=_make_image_response(b"PNG"))
    provider = OpenAIImageProvider(model="gpt-image-2", client=cast(AsyncOpenAI, client))
    await provider.generate_portrait("a tall rogue", transparent=True, art_style="watercolor")
    assert client.images.generate.await_args is not None
    prompt = client.images.generate.await_args.kwargs["prompt"]
    assert "watercolor" in prompt
    assert "children's story book" not in prompt


@pytest.mark.asyncio
async def test_generate_scene_appends_art_style_to_prompt_no_refs() -> None:
    client = MagicMock()
    client.images.generate = AsyncMock(return_value=_make_image_response(b"PNG"))
    provider = OpenAIImageProvider(model="gpt-image-2", client=cast(AsyncOpenAI, client))
    await provider.generate_scene("a wheat field", reference_portraits=[], art_style="watercolor")
    assert client.images.generate.await_args is not None
    prompt = client.images.generate.await_args.kwargs["prompt"]
    assert "a wheat field" in prompt
    assert "Art style: watercolor illustration." in prompt


@pytest.mark.asyncio
async def test_generate_scene_appends_art_style_to_prompt_with_refs() -> None:
    client = MagicMock()
    client.images.edit = AsyncMock(return_value=_make_image_response(b"PNG"))
    provider = OpenAIImageProvider(model="gpt-image-2", client=cast(AsyncOpenAI, client))
    await provider.generate_scene(
        "a rooftop chase",
        reference_portraits=[ReferencePortrait("ref1", b"ref1")],
        art_style="noir comic",
    )
    assert client.images.edit.await_args is not None
    prompt = client.images.edit.await_args.kwargs["prompt"]
    assert "a rooftop chase" in prompt
    assert "Art style: noir comic illustration." in prompt


@pytest.mark.asyncio
async def test_generate_scene_default_art_style_appears_no_refs() -> None:
    client = MagicMock()
    client.images.generate = AsyncMock(return_value=_make_image_response(b"PNG"))
    provider = OpenAIImageProvider(model="gpt-image-2", client=cast(AsyncOpenAI, client))
    await provider.generate_scene("a wheat field", reference_portraits=[])
    assert client.images.generate.await_args is not None
    prompt = client.images.generate.await_args.kwargs["prompt"]
    assert "Art style: children's story book illustration." in prompt


# --- gpt-image-1.5 backward compatibility ---


@pytest.mark.asyncio
async def test_v15_portrait_supports_transparent_background() -> None:
    """gpt-image-1.5 should still pass background='transparent' when asked."""
    client = MagicMock()
    client.images.generate = AsyncMock(return_value=_make_image_response(b"PNG"))
    provider = OpenAIImageProvider(model="gpt-image-1.5", client=cast(AsyncOpenAI, client))
    await provider.generate_portrait("a tall rogue", transparent=True)
    assert client.images.generate.await_args is not None
    kwargs = client.images.generate.await_args.kwargs
    assert kwargs["background"] == "transparent"


@pytest.mark.asyncio
async def test_v15_edit_passes_input_fidelity() -> None:
    """gpt-image-1.5 should still pass input_fidelity='high' on edit calls."""
    client = MagicMock()
    client.images.edit = AsyncMock(return_value=_make_image_response(b"PNG"))
    provider = OpenAIImageProvider(model="gpt-image-1.5", client=cast(AsyncOpenAI, client))
    await provider.generate_scene(
        "a chase", reference_portraits=[ReferencePortrait("ref1", b"ref1")]
    )
    assert client.images.edit.await_args is not None
    kwargs = client.images.edit.await_args.kwargs
    assert kwargs["input_fidelity"] == "high"


class _StreamEvent:
    """Async-iterable event stub mimicking the OpenAI SDK shape.

    The SDK delivers ``ImageGenPartialImageEvent`` /
    ``ImageGenCompletedEvent`` (and the ``ImageEdit*`` siblings) — each has
    ``type``, ``b64_json``, plus other metadata. We only exercise the two
    fields the provider reads.
    """

    def __init__(self, event_type: str, b64_json: str) -> None:
        self.type = event_type
        self.b64_json = b64_json


class _AsyncEventStream:
    """async-iterator wrapper over a sequence of event objects."""

    def __init__(self, events: list[_StreamEvent]) -> None:
        self._events = events

    def __aiter__(self) -> _AsyncEventStream:
        return self

    async def __anext__(self) -> _StreamEvent:
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


@pytest.mark.asyncio
async def test_generate_scene_no_partial_callback_uses_non_streaming() -> None:
    """``on_partial=None`` must keep the legacy non-streaming code path —
    no ``stream=True`` kwarg, no partial events, single response shape."""
    client = MagicMock()
    client.images.edit = AsyncMock(return_value=_make_image_response(b"FINAL"))
    provider = OpenAIImageProvider(model="gpt-image-2", client=cast(AsyncOpenAI, client))

    out = await provider.generate_scene(
        "scene prompt", reference_portraits=[ReferencePortrait("ref", b"ref")], on_partial=None
    )

    assert out == b"FINAL"
    assert client.images.edit.await_args is not None
    kwargs = client.images.edit.await_args.kwargs
    assert "stream" not in kwargs
    assert "partial_images" not in kwargs


@pytest.mark.asyncio
async def test_generate_scene_with_refs_streams_when_callback_provided() -> None:
    """``on_partial=callback`` enables ``stream=True, partial_images=2`` and
    fires the callback for each partial event; the completed event yields
    the final bytes."""
    partial_bytes_1 = b"PARTIAL-1"
    partial_bytes_2 = b"PARTIAL-2"
    final_bytes = b"FINAL"
    events = [
        _StreamEvent("image_edit.partial_image", base64.b64encode(partial_bytes_1).decode()),
        _StreamEvent("image_edit.partial_image", base64.b64encode(partial_bytes_2).decode()),
        _StreamEvent("image_edit.completed", base64.b64encode(final_bytes).decode()),
    ]
    client = MagicMock()
    client.images.edit = AsyncMock(return_value=_AsyncEventStream(events))
    provider = OpenAIImageProvider(model="gpt-image-2", client=cast(AsyncOpenAI, client))

    seen: list[bytes] = []

    async def cb(payload: bytes) -> None:
        seen.append(payload)

    out = await provider.generate_scene(
        "scene prompt", reference_portraits=[ReferencePortrait("ref", b"ref")], on_partial=cb
    )

    assert out == final_bytes
    assert seen == [partial_bytes_1, partial_bytes_2]
    assert client.images.edit.await_args is not None
    kwargs = client.images.edit.await_args.kwargs
    assert kwargs["stream"] is True
    assert kwargs["partial_images"] == 2


@pytest.mark.asyncio
async def test_generate_scene_no_refs_streams_via_generate_endpoint() -> None:
    """When there are no reference portraits, streaming uses ``images.generate``
    (not ``images.edit``) — but still with ``stream=True, partial_images=2``."""
    final_bytes = b"FINAL-NOREFS"
    events = [
        _StreamEvent("image_generation.partial_image", base64.b64encode(b"P").decode()),
        _StreamEvent("image_generation.completed", base64.b64encode(final_bytes).decode()),
    ]
    client = MagicMock()
    client.images.generate = AsyncMock(return_value=_AsyncEventStream(events))
    # Pre-bind images.edit as a never-awaited AsyncMock so we can assert
    # zero awaits without confusing MagicMock auto-attribute creation.
    client.images.edit = AsyncMock()
    provider = OpenAIImageProvider(model="gpt-image-2", client=cast(AsyncOpenAI, client))

    seen: list[bytes] = []

    async def cb(payload: bytes) -> None:
        seen.append(payload)

    out = await provider.generate_scene("a wheat field", reference_portraits=[], on_partial=cb)

    assert out == final_bytes
    assert seen == [b"P"]
    assert client.images.generate.await_args is not None
    kwargs = client.images.generate.await_args.kwargs
    assert kwargs["stream"] is True
    assert kwargs["partial_images"] == 2
    # images.edit should NOT be called when there are no refs.
    client.images.edit.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_scene_stream_without_completed_event_raises() -> None:
    """A stream that ends without a ``*.completed`` event must raise so the
    pipeline marks the node failed rather than caching an empty image."""
    events = [
        _StreamEvent("image_edit.partial_image", base64.b64encode(b"P").decode()),
    ]
    client = MagicMock()
    client.images.edit = AsyncMock(return_value=_AsyncEventStream(events))
    provider = OpenAIImageProvider(model="gpt-image-2", client=cast(AsyncOpenAI, client))

    async def cb(payload: bytes) -> None:
        del payload

    with pytest.raises(RuntimeError, match="without a final image"):
        await provider.generate_scene(
            "p", reference_portraits=[ReferencePortrait("r", b"r")], on_partial=cb
        )


@pytest.mark.asyncio
async def test_generate_portrait_ignores_on_partial() -> None:
    """``on_partial`` is accepted on the portrait API for protocol symmetry
    but must be a no-op (portraits are too fast for streaming to help)."""
    client = MagicMock()
    client.images.generate = AsyncMock(return_value=_make_image_response(b"P"))
    provider = OpenAIImageProvider(model="gpt-image-2", client=cast(AsyncOpenAI, client))

    async def cb(payload: bytes) -> None:
        del payload
        raise RuntimeError("portrait callback must NOT be invoked")

    out = await provider.generate_portrait("a tall rogue", transparent=True, on_partial=cb)
    assert out == b"P"
    assert client.images.generate.await_args is not None
    kwargs = client.images.generate.await_args.kwargs
    assert "stream" not in kwargs
    assert "partial_images" not in kwargs


def test_api_key_priority_storygen_image_wins_over_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """STORYGEN_IMAGE_API_KEY must override OPENAI_API_KEY when no explicit arg is passed.

    Enables the split-provider workflow where text runs through a custom
    OpenAI-compatible endpoint (e.g. z.ai) via OPENAI_API_KEY, while images
    keep going to real OpenAI via STORYGEN_IMAGE_API_KEY.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "zai-key-not-for-images")
    monkeypatch.setenv("STORYGEN_IMAGE_API_KEY", "real-openai-key")
    captured: dict[str, object] = {}

    class _Stub:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("storygen.images.openai_provider.AsyncOpenAI", _Stub)
    OpenAIImageProvider(model="gpt-image-2")
    assert captured["api_key"] == "real-openai-key"


def test_api_key_priority_explicit_arg_wins_over_envs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit api_key arg (e.g. per-save pinned value) beats both env vars."""
    monkeypatch.setenv("OPENAI_API_KEY", "openai-env")
    monkeypatch.setenv("STORYGEN_IMAGE_API_KEY", "storygen-image-env")
    captured: dict[str, object] = {}

    class _Stub:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("storygen.images.openai_provider.AsyncOpenAI", _Stub)
    OpenAIImageProvider(model="gpt-image-2", api_key="per-save-pin")
    assert captured["api_key"] == "per-save-pin"


def test_api_key_falls_back_to_openai_when_storygen_image_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without STORYGEN_IMAGE_API_KEY, the provider still uses OPENAI_API_KEY."""
    monkeypatch.setenv("OPENAI_API_KEY", "openai-env")
    monkeypatch.delenv("STORYGEN_IMAGE_API_KEY", raising=False)
    captured: dict[str, object] = {}

    class _Stub:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("storygen.images.openai_provider.AsyncOpenAI", _Stub)
    OpenAIImageProvider(model="gpt-image-2")
    assert captured["api_key"] == "openai-env"


def test_api_key_falls_back_to_openai_when_storygen_image_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty STORYGEN_IMAGE_API_KEY is treated as unset for art config fallback."""
    monkeypatch.setenv("OPENAI_API_KEY", "openai-env")
    monkeypatch.setenv("STORYGEN_IMAGE_API_KEY", "")
    captured: dict[str, object] = {}

    class _Stub:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("storygen.images.openai_provider.AsyncOpenAI", _Stub)
    OpenAIImageProvider(model="gpt-image-2")
    assert captured["api_key"] == "openai-env"
