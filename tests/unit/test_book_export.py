"""Unit tests for storygen.export.book."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from storygen.core.models import (
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.export.book import (
    BookPage,
    export_book,
    sanitize_title,
    unique_output_dir,
)
from storygen.storage.save import GameSave

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_TEMPLATE = """\
<!DOCTYPE html>
<html><head><title>{{ title }}</title></head>
<body>
{% for p in pages %}
<div class="chapter" data-chapter="{{ p.chapter }}">
<h2>Chapter {{ p.chapter }}</h2>
<p class="narration">{{ p.narration }}</p>
{% if p.choice_text %}<p class="choice">{{ p.choice_text }}</p>{% endif %}
{% if p.image_url %}<img src="{{ p.image_url }}" />{% endif %}
{% if p.audio_url %}<audio src="{{ p.audio_url }}"></audio>{% endif %}
</div>
{% endfor %}
<footer>Total: {{ total }}</footer>
</body></html>
"""


def _node(
    node_id: str,
    parent: str | None,
    *,
    chose: str | None = None,
    narration: str | None = None,
    is_ending: bool = False,
    is_major: bool = False,
    image_path: str | None = None,
    image_status: str = "not_planned",
    tts_audio_path: str | None = None,
    choices: list[StoredChoice] | None = None,
) -> StoryNode:
    return StoryNode(
        id=node_id,
        parent_id=parent,
        chosen_choice_id=chose,
        chosen_at=datetime.now(UTC) if chose else None,
        narration=narration or f"beat-{node_id}",
        choices=choices if choices is not None else [StoredChoice(id="c1", text="next")],
        is_major=is_major,
        is_ending=is_ending,
        image_prompt=None,
        image_path=image_path,
        image_status=image_status,  # type: ignore[arg-type]
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        tts_audio_path=tts_audio_path,
        created_at=datetime.now(UTC),
    )


def _save(
    nodes: dict[str, StoryNode],
    *,
    title: str = "Test Story",
    root: str = "root",
    current: str | None = None,
) -> GameSave:
    return GameSave(
        version=1,
        id=uuid4(),
        theme=Theme(title=title, setting="s", premise="p", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        characters=[],
        nodes=nodes,
        root_node_id=root,
        current_node_id=current or list(nodes.keys())[-1],
        endings_reached=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture()
def template_dir(tmp_path: Path) -> Path:
    """Create a temp directory with a minimal template.html for testing."""
    td = tmp_path / "tpl"
    td.mkdir()
    (td / "template.html").write_text(_MINIMAL_TEMPLATE, encoding="utf-8")
    return td


@pytest.fixture()
def fake_file(template_dir: Path) -> str:
    """Return a fake __file__ path inside template_dir."""
    return str(template_dir / "book.py")


# ---------------------------------------------------------------------------
# BookPage dataclass
# ---------------------------------------------------------------------------


class TestBookPage:
    def test_fields(self) -> None:
        page = BookPage(
            chapter=1,
            narration="Once upon a time",
            choice_text=None,
            image_url=None,
            audio_url=None,
            is_ending=False,
            is_major=False,
        )
        assert page.chapter == 1
        assert page.narration == "Once upon a time"
        assert page.choice_text is None


# ---------------------------------------------------------------------------
# sanitize_title
# ---------------------------------------------------------------------------


class TestSanitizeTitle:
    def test_removes_special_characters(self) -> None:
        assert sanitize_title("Hello, World!") == "Hello_World"

    def test_keeps_alphanumeric_spaces_dashes(self) -> None:
        assert sanitize_title("My-Story_2 Go!") == "My-Story_2_Go"

    def test_strips_whitespace(self) -> None:
        assert sanitize_title("  spaced  ") == "spaced"


# ---------------------------------------------------------------------------
# unique_output_dir
# ---------------------------------------------------------------------------


class TestUniqueOutputDir:
    def test_returns_base_when_not_exists(self, tmp_path: Path) -> None:
        base = tmp_path / "novel"
        assert unique_output_dir(base) == base

    def test_appends_suffix_when_exists(self, tmp_path: Path) -> None:
        base = tmp_path / "novel"
        base.mkdir()
        result = unique_output_dir(base)
        assert result == Path(f"{base} (2)")

    def test_increments_until_free(self, tmp_path: Path) -> None:
        base = tmp_path / "novel"
        base.mkdir()
        (tmp_path / "novel (2)").mkdir()
        (tmp_path / "novel (3)").mkdir()
        result = unique_output_dir(base)
        assert result == Path(f"{base} (4)")


# ---------------------------------------------------------------------------
# export_book
# ---------------------------------------------------------------------------


class TestExportBook:
    def test_single_ending_node(self, tmp_path: Path, fake_file: str) -> None:
        """Export a single-node path (root is also the ending)."""
        node = _node("end1", None, narration="The end.", is_ending=True)
        save = _save({"end1": node}, root="end1")

        with (
            patch("storygen.export.book.__file__", fake_file),
            patch("storygen.export.book.paths.game_dir", return_value=tmp_path / "g"),
        ):
            out = export_book(save, "end1", output_dir=tmp_path / "book", open_browser=False)

        assert out.is_dir()
        index = out / "index.html"
        assert index.exists()
        html = index.read_text()
        assert "Test Story" in html
        assert "The end." in html
        assert "Chapter 1" in html

    def test_multi_node_path_with_choice_text(self, tmp_path: Path, fake_file: str) -> None:
        """Export a multi-node path and verify choice text appears."""
        root = _node("root", None)
        mid = _node(
            "mid",
            "root",
            chose="c1",
            narration="Middle beat.",
            choices=[StoredChoice(id="c2", text="fight")],
        )
        end = _node("end", "mid", chose="c2", narration="Finale.", is_ending=True)

        # Root has a choice c1 with text "next" (default)
        save = _save({"root": root, "mid": mid, "end": end})

        with (
            patch("storygen.export.book.__file__", fake_file),
            patch("storygen.export.book.paths.game_dir", return_value=tmp_path / "g"),
        ):
            out = export_book(save, "end", output_dir=tmp_path / "book", open_browser=False)

        html = (out / "index.html").read_text()
        assert "Middle beat." in html
        assert "Finale." in html
        # mid chose c1 from root, root.choices[0].text == "next"
        assert "next" in html

    def test_output_directory_creation(self, tmp_path: Path, fake_file: str) -> None:
        """Sub-directories images/ and audio/ are created."""
        node = _node("root", None, narration="Hi", is_ending=True)
        save = _save({"root": node}, root="root")

        with (
            patch("storygen.export.book.__file__", fake_file),
            patch("storygen.export.book.paths.game_dir", return_value=tmp_path / "g"),
        ):
            out = export_book(save, "root", output_dir=tmp_path / "mybook", open_browser=False)

        assert (out / "images").is_dir()
        assert (out / "audio").is_dir()
        assert (out / "index.html").exists()

    def test_existing_dir_suffix(self, tmp_path: Path, fake_file: str) -> None:
        """When output_dir is None and default exists, a (2) suffix is used."""
        node = _node("root", None, narration="Hi", is_ending=True)
        save = _save({"root": node}, root="root", title="SuffixTest")

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        desktop = fake_home / "Desktop"
        desktop.mkdir()

        # Pre-create the default directory
        default_dir = desktop / "SuffixTest_Book"
        default_dir.mkdir(parents=True, exist_ok=True)

        with (
            patch("storygen.export.book.__file__", fake_file),
            patch("storygen.export.book.paths.game_dir", return_value=tmp_path / "g"),
            patch("storygen.export.book.Path.home", return_value=fake_home),
        ):
            out = export_book(save, "root", open_browser=False)
        assert out.name == "SuffixTest_Book (2)"
        assert out.is_dir()

    def test_scene_image_copied(self, tmp_path: Path, fake_file: str) -> None:
        """A node with a completed image gets its file copied."""
        game_src = tmp_path / "game_src"
        game_src.mkdir()
        img_src = game_src / "images" / "nodes" / "n1.png"
        img_src.parent.mkdir(parents=True)
        img_src.write_bytes(b"\x89PNG_FAKE")

        node = _node(
            "n1",
            None,
            narration="Beat with image",
            image_path="images/nodes/n1.png",
            image_status="done",
            is_ending=True,
        )
        save = _save({"n1": node}, root="n1")

        with (
            patch("storygen.export.book.__file__", fake_file),
            patch("storygen.export.book.paths.game_dir", return_value=game_src),
        ):
            out = export_book(save, "n1", output_dir=tmp_path / "book", open_browser=False)

        copied = out / "images" / "n1.png"
        assert copied.exists()
        assert copied.read_bytes() == b"\x89PNG_FAKE"

    def test_scene_image_skipped_when_not_done(self, tmp_path: Path, fake_file: str) -> None:
        """A node whose image_status is not 'done' does not copy anything."""
        game_src = tmp_path / "game_src"
        game_src.mkdir()

        node = _node(
            "n1",
            None,
            narration="No image",
            image_path="images/nodes/n1.png",
            image_status="failed",
            is_ending=True,
        )
        save = _save({"n1": node}, root="n1")

        with (
            patch("storygen.export.book.__file__", fake_file),
            patch("storygen.export.book.paths.game_dir", return_value=game_src),
        ):
            out = export_book(save, "n1", output_dir=tmp_path / "book", open_browser=False)

        html = (out / "index.html").read_text()
        assert "<img" not in html

    def test_tts_audio_copied(self, tmp_path: Path, fake_file: str) -> None:
        """A node with a TTS audio file gets it copied to audio/."""
        game_src = tmp_path / "game_src"
        game_src.mkdir()
        audio_src = game_src / "audio" / "n1-openai-abc12345.mp3"
        audio_src.parent.mkdir(parents=True)
        audio_src.write_bytes(b"FAKE_MP3")

        node = _node(
            "n1",
            None,
            narration="Beat with audio",
            tts_audio_path="audio/n1-openai-abc12345.mp3",
            is_ending=True,
        )
        save = _save({"n1": node}, root="n1")

        with (
            patch("storygen.export.book.__file__", fake_file),
            patch("storygen.export.book.paths.game_dir", return_value=game_src),
        ):
            out = export_book(save, "n1", output_dir=tmp_path / "book", open_browser=False)

        copied = out / "audio" / "n1-openai-abc12345.mp3"
        assert copied.exists()
        assert copied.read_bytes() == b"FAKE_MP3"
        html = (out / "index.html").read_text()
        assert "audio/n1-openai-abc12345.mp3" in html

    def test_html_contains_title_and_chapters(self, tmp_path: Path, fake_file: str) -> None:
        """The rendered HTML contains the story title and chapter markers."""
        n1 = _node("root", None, narration="Chapter one.")
        n2 = _node("ch2", "root", chose="c1", narration="Chapter two.", is_ending=True)
        save = _save({"root": n1, "ch2": n2}, root="root")

        with (
            patch("storygen.export.book.__file__", fake_file),
            patch("storygen.export.book.paths.game_dir", return_value=tmp_path / "g"),
        ):
            out = export_book(save, "ch2", output_dir=tmp_path / "book", open_browser=False)

        html = (out / "index.html").read_text()
        assert "Test Story" in html
        assert "Chapter 1" in html
        assert "Chapter 2" in html
        assert "Total: 2" in html

    def test_default_output_dir_is_desktop(self, tmp_path: Path, fake_file: str) -> None:
        """When output_dir is None, the default is ~/Desktop/<title>_Book/."""
        node = _node("root", None, narration="Hi", is_ending=True)
        save = _save({"root": node}, root="root", title="DesktopTest")

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        desktop = fake_home / "Desktop"
        desktop.mkdir()

        expected_dir = desktop / "DesktopTest_Book"
        with (
            patch("storygen.export.book.__file__", fake_file),
            patch("storygen.export.book.paths.game_dir", return_value=tmp_path / "g"),
            patch("storygen.export.book.Path.home", return_value=fake_home),
        ):
            out = export_book(save, "root", open_browser=False)
        assert out == expected_dir

    def test_open_browser_called(self, tmp_path: Path, fake_file: str) -> None:
        """When open_browser=True, webbrowser.open is called."""
        node = _node("root", None, narration="Hi", is_ending=True)
        save = _save({"root": node}, root="root")

        with (
            patch("storygen.export.book.__file__", fake_file),
            patch("storygen.export.book.paths.game_dir", return_value=tmp_path / "g"),
            patch("storygen.export.book.webbrowser.open") as mock_open,
        ):
            out = export_book(save, "root", output_dir=tmp_path / "book", open_browser=True)

        mock_open.assert_called_once_with((out / "index.html").as_uri())

    def test_open_browser_not_called_when_false(self, tmp_path: Path, fake_file: str) -> None:
        """When open_browser=False, webbrowser.open is not called."""
        node = _node("root", None, narration="Hi", is_ending=True)
        save = _save({"root": node}, root="root")

        with (
            patch("storygen.export.book.__file__", fake_file),
            patch("storygen.export.book.paths.game_dir", return_value=tmp_path / "g"),
            patch("storygen.export.book.webbrowser.open") as mock_open,
        ):
            export_book(save, "root", output_dir=tmp_path / "book", open_browser=False)

        mock_open.assert_not_called()

    def test_root_node_has_no_choice_text(self, tmp_path: Path, fake_file: str) -> None:
        """The root node (no parent, no chosen_choice_id) has choice_text=None."""
        node = _node("root", None, narration="Start.", is_ending=True)
        save = _save({"root": node}, root="root")

        with (
            patch("storygen.export.book.__file__", fake_file),
            patch("storygen.export.book.paths.game_dir", return_value=tmp_path / "g"),
        ):
            out = export_book(save, "root", output_dir=tmp_path / "book", open_browser=False)

        html = (out / "index.html").read_text()
        assert "Start." in html
        assert 'class="choice"' not in html
