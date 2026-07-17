"""Unit tests for :class:`storygen.images.routed_provider.RoutedImageProvider`."""

from __future__ import annotations

from typing import Any

import pytest

from storygen.images.base import ImageProvider, ReferencePortrait
from storygen.images.routed_provider import RoutedImageProvider


class _FakeProvider:
    """Minimal ImageProvider stub with scripted outcomes."""

    supports_reference_images: bool = True

    def __init__(
        self,
        *,
        portrait_bytes: bytes = b"portrait",
        scene_bytes: bytes = b"scene",
        raise_exc: Exception | None = None,
    ) -> None:
        self._portrait_bytes = portrait_bytes
        self._scene_bytes = scene_bytes
        self._raise_exc = raise_exc
        self.portrait_calls = 0
        self.scene_calls = 0
        self.last_on_partial: Any = None

    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        on_partial: Any = None,
        reference_image: bytes | None = None,
    ) -> bytes:
        del on_partial, reference_image
        self.portrait_calls += 1
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._portrait_bytes

    async def generate_scene(
        self,
        prompt: str,
        *,
        reference_portraits: list[ReferencePortrait],
        art_style: str = "children's story book",
        on_partial: Any = None,
    ) -> bytes:
        self.last_on_partial = on_partial
        self.scene_calls += 1
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._scene_bytes


def test_routed_is_runtime_image_provider() -> None:
    """`isinstance(routed, ImageProvider)` must be True (Protocol check)."""
    routed = RoutedImageProvider(_FakeProvider())
    assert isinstance(routed, ImageProvider)


@pytest.mark.asyncio
async def test_primary_success_returns_primary_bytes() -> None:
    primary = _FakeProvider(portrait_bytes=b"P1", scene_bytes=b"S1")
    fallback = _FakeProvider(portrait_bytes=b"P2", scene_bytes=b"S2")
    calls: list[tuple[str, Exception]] = []
    routed = RoutedImageProvider(
        primary,
        fallback,
        primary_label="prim",
        fallback_label="back",
        on_fallback=lambda label, exc: calls.append((label, exc)),
    )
    assert await routed.generate_portrait("x", transparent=False) == b"P1"
    assert await routed.generate_scene("y", reference_portraits=[]) == b"S1"
    assert primary.portrait_calls == 1
    assert primary.scene_calls == 1
    assert fallback.portrait_calls == 0
    assert fallback.scene_calls == 0
    assert calls == []  # on_fallback never fires on success


@pytest.mark.asyncio
async def test_primary_fails_no_fallback_reraises() -> None:
    primary = _FakeProvider(raise_exc=RuntimeError("primary down"))
    routed = RoutedImageProvider(primary, None)
    with pytest.raises(RuntimeError, match="primary down"):
        await routed.generate_portrait("x", transparent=False)
    with pytest.raises(RuntimeError, match="primary down"):
        await routed.generate_scene("y", reference_portraits=[])


@pytest.mark.asyncio
async def test_primary_fails_fallback_succeeds_returns_fallback_bytes() -> None:
    primary = _FakeProvider(raise_exc=RuntimeError("primary down"))
    fallback = _FakeProvider(portrait_bytes=b"F-P", scene_bytes=b"F-S")
    calls: list[tuple[str, Exception]] = []
    routed = RoutedImageProvider(
        primary,
        fallback,
        primary_label="prim",
        fallback_label="back",
        on_fallback=lambda label, exc: calls.append((label, exc)),
    )
    assert await routed.generate_portrait("x", transparent=False) == b"F-P"
    assert await routed.generate_scene("y", reference_portraits=[]) == b"F-S"
    # on_fallback fires for each method call (portrait + scene = 2).
    assert len(calls) == 2
    assert all(label == "back" for label, _ in calls)
    assert all(isinstance(exc, RuntimeError) for _, exc in calls)


@pytest.mark.asyncio
async def test_both_fail_reraises_primary_exception() -> None:
    """When both providers fail, the PRIMARY's exception is surfaced."""
    primary_exc = RuntimeError("primary-ERR")
    fallback_exc = ValueError("fallback-ERR")
    primary = _FakeProvider(raise_exc=primary_exc)
    fallback = _FakeProvider(raise_exc=fallback_exc)
    routed = RoutedImageProvider(primary, fallback)
    with pytest.raises(RuntimeError, match="primary-ERR"):
        await routed.generate_portrait("x", transparent=False)
    with pytest.raises(RuntimeError, match="primary-ERR"):
        await routed.generate_scene("y", reference_portraits=[])


@pytest.mark.asyncio
async def test_both_fail_primary_exc_has_fallback_cause() -> None:
    """Primary's exception is raised with fallback's exception as __cause__."""
    primary = _FakeProvider(raise_exc=RuntimeError("primary down"))
    fallback = _FakeProvider(raise_exc=RuntimeError("fallback down too"))
    router = RoutedImageProvider(primary, fallback)
    with pytest.raises(RuntimeError, match="primary down") as excinfo:
        await router.generate_portrait("x", transparent=False, art_style="x")
    assert isinstance(excinfo.value.__cause__, RuntimeError)
    assert "fallback down too" in str(excinfo.value.__cause__)


@pytest.mark.asyncio
async def test_on_fallback_callback_exception_is_swallowed() -> None:
    """A misbehaving on_fallback callback must not crash the render."""
    primary = _FakeProvider(raise_exc=RuntimeError("boom"))
    fallback = _FakeProvider(portrait_bytes=b"OK")

    def _bad_cb(_label: str, _exc: Exception) -> None:
        raise RuntimeError("callback crashed")

    routed = RoutedImageProvider(primary, fallback, on_fallback=_bad_cb)
    assert await routed.generate_portrait("x", transparent=False) == b"OK"


@pytest.mark.asyncio
async def test_generate_scene_forwards_reference_portraits() -> None:
    """Reference portraits reach the selected provider unchanged."""
    captured: list[list[ReferencePortrait]] = []

    class _Capture:
        supports_reference_images: bool = True

        async def generate_portrait(
            self,
            description: str,
            *,
            transparent: bool,
            art_style: str = "children's story book",
            on_partial: Any = None,
            reference_image: bytes | None = None,
        ) -> bytes:
            del on_partial, reference_image
            return b""

        async def generate_scene(
            self,
            prompt: str,
            *,
            reference_portraits: list[ReferencePortrait],
            art_style: str = "children's story book",
            on_partial: Any = None,
        ) -> bytes:
            del on_partial
            captured.append(list(reference_portraits))
            return b"ok"

    routed = RoutedImageProvider(_Capture())
    await routed.generate_scene(
        "prompt",
        reference_portraits=[ReferencePortrait("a", b"a"), ReferencePortrait("b", b"b")],
    )
    assert len(captured) == 1
    assert len(captured[0]) == 2
    assert captured[0][0].name == "a"
    assert captured[0][0].data == b"a"
    assert captured[0][1].name == "b"
    assert captured[0][1].data == b"b"
