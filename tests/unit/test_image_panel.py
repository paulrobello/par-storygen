"""Unit tests for ImagePanel widget state transitions."""

from __future__ import annotations

from pathlib import Path

from storygen.widgets.image_panel import ImagePanel, ImagePanelState


def test_initial_state_is_empty() -> None:
    panel = ImagePanel()
    assert panel.panel_state == ImagePanelState.EMPTY


def test_set_generating_transitions_state() -> None:
    panel = ImagePanel()
    panel.show_generating()
    assert panel.panel_state == ImagePanelState.GENERATING


def test_set_failed_transitions_state() -> None:
    panel = ImagePanel()
    panel.show_failed()
    assert panel.panel_state == ImagePanelState.FAILED


def test_set_done_requires_path(tmp_path: Path) -> None:
    fake_png = tmp_path / "x.png"
    # Write a 1-pixel transparent PNG so Pillow can open it.
    fake_png.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    panel = ImagePanel()
    panel.show_image(fake_png)
    assert panel.panel_state == ImagePanelState.DONE
