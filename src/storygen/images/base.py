"""Protocol describing what any image provider must expose."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import NamedTuple, Protocol, runtime_checkable


class ReferencePortrait(NamedTuple):
    """A named reference image for scene generation.

    Providers that support reference images use the ``name`` field to build
    prompt guidance telling the LLM which character each image depicts (e.g.
    "Image 1: Alice", "Image 2: current scene artwork").  The ``data`` field
    holds the raw PNG bytes.
    """

    name: str
    data: bytes


@runtime_checkable
class ImageProvider(Protocol):
    """Uniform surface for text-to-image backends."""

    # ARC-115: static capability declaration. ``True`` means the provider
    # accepts reference portraits/images (OpenAI ``images.edit``, Gemini
    # inline ``Part.from_bytes``). ``False`` means references are silently
    # dropped — the ``on_ref_loss`` toast still fires at runtime so users
    # know the effective provider changed.
    supports_reference_images: bool

    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
        reference_image: bytes | None = None,
    ) -> bytes:
        """Generate a single character portrait.

        Args:
            description: Physical description used as the portrait prompt base.
            transparent: Request a transparent background. Providers/models
                that cannot honor this (e.g. OpenAI ``gpt-image-2``) render an
                opaque neutral background instead.
            art_style: Art-style string threaded into the prompt.
            on_partial: Optional partial-image callback (OpenAI streaming only);
                invoked with each preview chunk as it arrives; other providers
                ignore it.
            reference_image: Optional single reference image bytes for
                providers that anchor a portrait to an existing look
                (OpenAI only today); silently dropped by non-ref providers.

        Returns:
            The generated PNG bytes.
        """
        ...

    async def generate_scene(
        self,
        prompt: str,
        *,
        reference_portraits: list[ReferencePortrait],
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
    ) -> bytes:
        """Generate a scene illustration.

        Args:
            prompt: Scene description (illustration-plan ``image_prompt``).
            reference_portraits: Named reference portraits for featured
                characters; ref-aware providers fold them into the call
                (OpenAI via ``images.edit``, Gemini inline) so faces stay
                consistent. Non-ref providers silently drop them.
            art_style: Art-style string threaded into the prompt.
            on_partial: Optional partial-image callback (OpenAI streaming only).

        Returns:
            The generated PNG bytes.
        """
        ...
