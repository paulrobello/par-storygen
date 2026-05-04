"""Unit tests for GeminiImageProvider — mocks the google-genai client chain."""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock

import google.genai as genai
import pytest

from storygen.images.base import ReferencePortrait
from storygen.images.gemini_provider import GeminiImageProvider


class _FakeInline:
    def __init__(self, data: bytes) -> None:
        self.data = data


class _FakePart:
    def __init__(self, inline_data: _FakeInline | None = None) -> None:
        self.inline_data = inline_data


def _fake_response(img_bytes: bytes, *, extra_text_parts: int = 0) -> MagicMock:
    """Build a response shaped like ``client.aio.models.generate_content``.

    ``extra_text_parts`` prepends text-only parts (``inline_data is None``) so
    tests can verify the provider skips them instead of picking the first
    part blindly.
    """
    parts: list[_FakePart] = [_FakePart(None) for _ in range(extra_text_parts)]
    parts.append(_FakePart(_FakeInline(img_bytes)))
    content = MagicMock()
    content.parts = parts
    candidate = MagicMock()
    candidate.content = content
    resp = MagicMock()
    resp.candidates = [candidate]
    return resp


def _make_client(response: MagicMock) -> MagicMock:
    """Stub the ``client.aio.models.generate_content`` await chain."""
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=response)
    return client


@pytest.mark.asyncio
async def test_generate_portrait_opaque_hits_generate_content_once() -> None:
    client = _make_client(_fake_response(b"PNG-PORTRAIT"))
    provider = GeminiImageProvider(
        model="gemini-3.1-flash-image-preview",
        client=cast(genai.Client, client),
    )

    out = await provider.generate_portrait("a tall rogue", transparent=False)

    assert out == b"PNG-PORTRAIT"
    call = client.aio.models.generate_content.await_args
    assert call is not None
    assert call.kwargs["model"] == "gemini-3.1-flash-image-preview"
    # portrait is a single-string ``contents`` payload
    prompt = call.kwargs["contents"]
    assert isinstance(prompt, str)
    assert "a tall rogue" in prompt
    assert "full-length" in prompt.lower() or "full-body" in prompt.lower()
    assert "front-facing" in prompt.lower()
    assert "feet" in prompt.lower()
    # config must request both TEXT and IMAGE modalities
    cfg = call.kwargs["config"]
    assert list(cfg.response_modalities or []) == ["TEXT", "IMAGE"]


@pytest.mark.asyncio
async def test_generate_portrait_transparent_adds_transparent_hint() -> None:
    client = _make_client(_fake_response(b"PNG-T"))
    provider = GeminiImageProvider(client=cast(genai.Client, client))

    await provider.generate_portrait("a cat", transparent=True)

    prompt = client.aio.models.generate_content.await_args.kwargs["contents"]
    assert "Transparent PNG" in prompt or "transparent" in prompt.lower()


@pytest.mark.asyncio
async def test_generate_scene_zero_refs_has_single_string_content() -> None:
    client = _make_client(_fake_response(b"PNG-SCENE"))
    provider = GeminiImageProvider(client=cast(genai.Client, client))

    out = await provider.generate_scene("a wheat field", reference_portraits=[])

    assert out == b"PNG-SCENE"
    contents = cast(list[object], client.aio.models.generate_content.await_args.kwargs["contents"])
    assert isinstance(contents, list)
    assert len(contents) == 1
    first = contents[0]
    assert isinstance(first, str)
    assert "a wheat field" in first
    assert "children's story book" in first
    # The no-refs path must delegate to build_scene_prompt verbatim so every
    # provider without a reference-image channel emits byte-identical output.
    from storygen.images._prompts import build_scene_prompt

    assert first == build_scene_prompt("a wheat field", art_style="children's story book")


@pytest.mark.asyncio
async def test_generate_scene_two_refs_builds_string_plus_parts() -> None:
    client = _make_client(_fake_response(b"PNG"))
    provider = GeminiImageProvider(client=cast(genai.Client, client))

    await provider.generate_scene(
        "a rooftop chase",
        reference_portraits=[
            ReferencePortrait("ref-a", b"ref-a"),
            ReferencePortrait("ref-b", b"ref-b"),
        ],
        art_style="noir comic",
    )

    contents = cast(list[object], client.aio.models.generate_content.await_args.kwargs["contents"])
    assert isinstance(contents, list)
    assert len(contents) == 3
    first = contents[0]
    assert isinstance(first, str)
    assert "a rooftop chase" in first
    assert "noir comic" in first
    # remaining entries are Part instances carrying the raw PNG bytes
    bodies: list[bytes] = []
    for part in contents[1:]:
        inline = getattr(part, "inline_data", None)
        assert inline is not None
        bodies.append(cast(bytes, inline.data))
    assert bodies == [b"ref-a", b"ref-b"]


@pytest.mark.asyncio
async def test_generate_scene_caps_references_at_14() -> None:
    client = _make_client(_fake_response(b"PNG"))
    provider = GeminiImageProvider(client=cast(genai.Client, client))

    refs = [ReferencePortrait(f"ref-{i}", f"ref-{i}".encode()) for i in range(20)]
    await provider.generate_scene("panorama", reference_portraits=refs)

    contents = cast(list[object], client.aio.models.generate_content.await_args.kwargs["contents"])
    # 1 string + 14 parts (cap), not 21
    assert len(contents) == 1 + 14


@pytest.mark.asyncio
async def test_extract_image_bytes_skips_text_parts() -> None:
    """Response with a text part before the image part still yields the image."""
    client = _make_client(_fake_response(b"PNG-AFTER-TEXT", extra_text_parts=2))
    provider = GeminiImageProvider(client=cast(genai.Client, client))

    out = await provider.generate_portrait("x", transparent=False)

    assert out == b"PNG-AFTER-TEXT"


@pytest.mark.asyncio
async def test_response_without_image_part_raises_runtime_error() -> None:
    """Text-only response → RuntimeError, not silent empty bytes."""
    content = MagicMock()
    content.parts = [_FakePart(None)]
    candidate = MagicMock()
    candidate.content = content
    resp = MagicMock()
    resp.candidates = [candidate]
    client = _make_client(resp)
    provider = GeminiImageProvider(client=cast(genai.Client, client))

    with pytest.raises(RuntimeError, match="no image part"):
        await provider.generate_portrait("x", transparent=False)


@pytest.mark.asyncio
async def test_response_without_candidates_raises_runtime_error() -> None:
    resp = MagicMock()
    resp.candidates = []
    client = _make_client(resp)
    provider = GeminiImageProvider(client=cast(genai.Client, client))

    with pytest.raises(RuntimeError, match="no candidates"):
        await provider.generate_portrait("x", transparent=False)


def test_api_key_is_threaded_into_client_constructor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit api_key must reach ``genai.Client(api_key=...)``."""
    captured: dict[str, object] = {}

    def _fake_client_ctor(*args: object, **kwargs: object) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr("storygen.images.gemini_provider.genai.Client", _fake_client_ctor)

    GeminiImageProvider(api_key="gem-secret-123")

    assert captured.get("api_key") == "gem-secret-123"


def test_no_api_key_lets_sdk_pick_up_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``api_key`` we call ``genai.Client()`` with no kwargs — SDK env fallback."""
    captured: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _fake_client_ctor(*args: object, **kwargs: object) -> MagicMock:
        captured.append((args, kwargs))
        return MagicMock()

    monkeypatch.setattr("storygen.images.gemini_provider.genai.Client", _fake_client_ctor)

    GeminiImageProvider()

    assert len(captured) == 1
    assert captured[0] == ((), {})
