"""Unit tests for split portrait/scene image provider routing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from storygen.images.base import ImageProvider, ReferencePortrait
from storygen.images.split_provider import SplitImageProvider


class _FakeProvider:
    supports_reference_images: bool = True

    def __init__(self, *, portrait_bytes: bytes, scene_bytes: bytes) -> None:
        self._portrait_bytes = portrait_bytes
        self._scene_bytes = scene_bytes
        self.portrait_calls: list[tuple[str, bool, str, bytes | None]] = []
        self.scene_calls: list[tuple[str, list[ReferencePortrait], str]] = []

    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
        reference_image: bytes | None = None,
    ) -> bytes:
        del on_partial
        self.portrait_calls.append((description, transparent, art_style, reference_image))
        return self._portrait_bytes

    async def generate_scene(
        self,
        prompt: str,
        *,
        reference_portraits: list[ReferencePortrait],
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
    ) -> bytes:
        del on_partial
        self.scene_calls.append((prompt, list(reference_portraits), art_style))
        return self._scene_bytes


def test_split_provider_is_runtime_image_provider() -> None:
    provider = SplitImageProvider(
        character_provider=_FakeProvider(portrait_bytes=b"character", scene_bytes=b"unused"),
        art_provider=_FakeProvider(portrait_bytes=b"unused", scene_bytes=b"art"),
    )
    assert isinstance(provider, ImageProvider)


@pytest.mark.asyncio
async def test_generate_portrait_delegates_to_character_provider() -> None:
    character = _FakeProvider(portrait_bytes=b"CHARACTER", scene_bytes=b"wrong-scene")
    art = _FakeProvider(portrait_bytes=b"wrong-portrait", scene_bytes=b"ART")
    provider = SplitImageProvider(character_provider=character, art_provider=art)

    result = await provider.generate_portrait(
        "hero portrait",
        transparent=True,
        art_style="ink",
        reference_image=b"ref",
    )

    assert result == b"CHARACTER"
    assert character.portrait_calls == [("hero portrait", True, "ink", b"ref")]
    assert art.portrait_calls == []


@pytest.mark.asyncio
async def test_generate_scene_delegates_to_art_provider() -> None:
    character = _FakeProvider(portrait_bytes=b"CHARACTER", scene_bytes=b"wrong-scene")
    art = _FakeProvider(portrait_bytes=b"wrong-portrait", scene_bytes=b"ART")
    provider = SplitImageProvider(character_provider=character, art_provider=art)

    result = await provider.generate_scene(
        "castle at dawn",
        reference_portraits=[ReferencePortrait("p1", b"p1"), ReferencePortrait("p2", b"p2")],
        art_style="watercolor",
    )

    assert result == b"ART"
    assert art.scene_calls == [
        (
            "castle at dawn",
            [ReferencePortrait("p1", b"p1"), ReferencePortrait("p2", b"p2")],
            "watercolor",
        )
    ]
    assert character.scene_calls == []
