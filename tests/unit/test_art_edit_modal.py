"""Unit tests for ArtEditModal."""

from __future__ import annotations

from storygen.screens._art_edit_modal import ArtEditMode, ArtEditResult


def test_art_edit_result_edit_mode() -> None:
    result = ArtEditResult(mode=ArtEditMode.EDIT, text="make it darker")
    assert result.mode == ArtEditMode.EDIT
    assert result.text == "make it darker"
    assert result.use_current_as_ref is True


def test_art_edit_result_full_mode() -> None:
    result = ArtEditResult(
        mode=ArtEditMode.FULL,
        text="a sunlit meadow with wildflowers",
        use_current_as_ref=False,
    )
    assert result.mode == ArtEditMode.FULL
    assert result.text == "a sunlit meadow with wildflowers"
    assert result.use_current_as_ref is False
