"""Tests for reference-image data model and storage paths."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path as _Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from storygen.images.openai_provider import OpenAIImageProvider
from storygen.llm.models import Character
from storygen.screens._ref_image_modals import ReferenceImageResult
from storygen.storage import paths
from storygen.storage.library import (
    LibraryCharacter,
    load_library_character,
    save_library_character,
)


class TestCharacterReferenceImage:
    def test_default_none(self) -> None:
        char = Character(
            id="abc",
            name="Test",
            backstory="",
            personality="",
            physical_description="tall",
            introduced_at_node_id="root",
        )
        assert char.reference_image_path is None

    def test_set_reference_image_path(self) -> None:
        char = Character(
            id="abc",
            name="Test",
            backstory="",
            personality="",
            physical_description="tall",
            introduced_at_node_id="root",
            reference_image_path="images/characters/abc-ref.png",
        )
        assert char.reference_image_path == "images/characters/abc-ref.png"


class TestReferencePaths:
    def test_relative_path(self) -> None:
        result = paths.relative_character_reference_path("abc123")
        assert result == "images/characters/abc123-ref.png"

    def test_absolute_path(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        result = paths.character_reference_path("game1", "char1")
        expected = paths.game_dir("game1") / "images" / "characters" / "char1-ref.png"
        assert result == expected


class TestOpenAIRefImagePortrait:
    async def test_generate_portrait_with_reference_image(self) -> None:
        """When reference_image is provided, uses images.edit instead of images.generate."""
        client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.data = [MagicMock(b64_json="aGVsbG8=")]
        client.images.edit.return_value = mock_resp

        provider = OpenAIImageProvider(client=client, model="gpt-image-2")
        result = await provider.generate_portrait(
            "a tall woman",
            transparent=True,
            art_style="watercolor",
            reference_image=b"\x89PNG fake bytes",
        )
        assert result == b"hello"
        client.images.edit.assert_called_once()
        client.images.generate.assert_not_called()

    async def test_generate_portrait_without_reference_image(self) -> None:
        """When reference_image is None, uses images.generate (existing path)."""
        client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.data = [MagicMock(b64_json="aGVsbG8=")]
        client.images.generate.return_value = mock_resp

        provider = OpenAIImageProvider(client=client, model="gpt-image-2")
        result = await provider.generate_portrait(
            "a tall woman",
            transparent=True,
        )
        assert result == b"hello"
        client.images.generate.assert_called_once()
        client.images.edit.assert_not_called()

    def test_sync_wrappers(self) -> None:
        """Run async tests synchronously for pytest."""
        asyncio.run(self.test_generate_portrait_with_reference_image())
        asyncio.run(self.test_generate_portrait_without_reference_image())


class TestLibraryReferenceImage:
    def test_library_character_default_none(self) -> None:
        lib = LibraryCharacter(
            id="a" * 32,
            name="Test",
            backstory="",
            personality="",
            physical_description="tall",
            portrait_prompt="tall",
            exported_at=datetime.now(UTC),
        )
        assert lib.reference_image_path is None

    def test_library_character_with_ref(self) -> None:
        lib = LibraryCharacter(
            id="a" * 32,
            name="Test",
            backstory="",
            personality="",
            physical_description="tall",
            portrait_prompt="tall",
            exported_at=datetime.now(UTC),
            reference_image_path="reference.png",
        )
        assert lib.reference_image_path == "reference.png"

    def test_export_with_reference(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        lib = LibraryCharacter(
            id="b" * 32,
            name="Test",
            backstory="",
            personality="",
            physical_description="tall",
            portrait_prompt="tall",
            exported_at=datetime.now(UTC),
        )
        ref_bytes = b"\x89PNG fake reference"
        save_library_character(
            lib, portrait_bytes=b"\x89PNG fake portrait", reference_bytes=ref_bytes
        )
        loaded = load_library_character(lib.id)
        assert loaded.reference_image_path == "reference.png"

    def test_export_without_reference(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        lib = LibraryCharacter(
            id="c" * 32,
            name="Test",
            backstory="",
            personality="",
            physical_description="tall",
            portrait_prompt="tall",
            exported_at=datetime.now(UTC),
        )
        save_library_character(lib, portrait_bytes=b"\x89PNG fake portrait")
        loaded = load_library_character(lib.id)
        assert loaded.reference_image_path is None


class TestReferenceImageResult:
    def test_creation(self) -> None:
        result = ReferenceImageResult(
            source_path=_Path("/tmp/test.png"),
            mode="use_as_is",
        )
        assert result.source_path == _Path("/tmp/test.png")
        assert result.mode == "use_as_is"
        assert result.style_prompt == ""

    def test_style_transfer_mode(self) -> None:
        result = ReferenceImageResult(
            source_path=_Path("/tmp/test.png"),
            mode="style_transfer",
        )
        assert result.mode == "style_transfer"

    def test_style_prompt(self) -> None:
        result = ReferenceImageResult(
            source_path=_Path("/tmp/test.png"),
            mode="style_transfer",
            style_prompt="anime",
        )
        assert result.style_prompt == "anime"


class TestBackwardCompat:
    def test_load_save_without_reference_image(self) -> None:
        """A save JSON with no reference_image_path field loads fine."""
        minimal_char: dict[str, object] = {
            "id": "abc",
            "name": "Test",
            "backstory": "",
            "personality": "",
            "physical_description": "tall",
            "portrait_path": None,
            "portrait_prompt": None,
            "introduced_at_node_id": "root",
            "outfits": [],
            "current_outfit_id": None,
            # NOTE: no reference_image_path key — legacy save
        }
        char = Character.model_validate(minimal_char)
        assert char.reference_image_path is None
