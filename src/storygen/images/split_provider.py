"""Split image provider routing portraits and scenes to different backends."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from storygen.images.base import ImageProvider, ReferencePortrait


class SplitImageProvider:
    """Route portrait generation to character provider and scene art to art provider."""

    def __init__(self, *, character_provider: ImageProvider, art_provider: ImageProvider) -> None:
        self._character_provider = character_provider
        self._art_provider = art_provider
        # ARC-115: snapshot the art provider's capability. Scenes are the only
        # call site that consumes reference portraits, so this split provider
        # supports refs iff the art backend does. Capability is static (a class
        # attribute on concrete providers), so a construction-time snapshot is
        # correct and matches the ImageProvider protocol's plain-bool shape.
        self.supports_reference_images: bool = art_provider.supports_reference_images

    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
        reference_image: bytes | None = None,
    ) -> bytes:
        return await self._character_provider.generate_portrait(
            description,
            transparent=transparent,
            art_style=art_style,
            on_partial=on_partial,
            reference_image=reference_image,
        )

    async def generate_scene(
        self,
        prompt: str,
        *,
        reference_portraits: list[ReferencePortrait],
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
    ) -> bytes:
        return await self._art_provider.generate_scene(
            prompt,
            reference_portraits=reference_portraits,
            art_style=art_style,
            on_partial=on_partial,
        )
