"""Unit tests for RelationshipsScreen."""

from __future__ import annotations

from typing import cast

from textual.app import App, ComposeResult
from textual.content import Content

from storygen.core.models import Character, Relationship, RelationshipType
from storygen.screens.relationships import RelationshipsScreen


class _Harness(App[None]):
    CSS = "Screen { align: center middle; }"

    def compose(self) -> ComposeResult:
        yield RelationshipsScreen()

    def on_mount(self) -> None:
        screen = self.query_one(RelationshipsScreen)
        screen.set_data(
            characters=[
                Character(
                    id="a",
                    name="Aria",
                    backstory="",
                    personality="Bold.",
                    physical_description="Tall.",
                    introduced_at_node_id="root",
                ),
                Character(
                    id="b",
                    name="Kael",
                    backstory="",
                    personality="Swift.",
                    physical_description="Short.",
                    introduced_at_node_id="root",
                ),
                Character(
                    id="c",
                    name="Witch",
                    backstory="",
                    personality="Dark.",
                    physical_description="Green skin.",
                    introduced_at_node_id="root",
                ),
            ],
            relationships=[
                Relationship(
                    char_a_id="a",
                    char_b_id="b",
                    type=RelationshipType.ALLY,
                    strength=4,
                    context="bonded in ambush",
                    updated_at_node_id="n1",
                ),
                Relationship(
                    char_a_id="a",
                    char_b_id="c",
                    type=RelationshipType.RIVAL,
                    strength=3,
                    context="sworn enemies",
                    updated_at_node_id="n2",
                ),
            ],
        )


async def test_relationships_screen_renders() -> None:
    async with _Harness().run_test() as pilot:
        screen = pilot.app.query_one(RelationshipsScreen)
        content = screen.query_one("#rel-content")
        text = cast(Content, content.render()).plain
        assert "Aria" in text
        assert "Kael" in text
        assert "Witch" in text
        assert "ally" in text.lower()
        assert "rival" in text.lower()


async def test_relationships_screen_displays_no_relationships_message() -> None:
    """When no relationships exist, shows a message."""

    class _EmptyHarness(App[None]):
        CSS = "Screen { align: center middle; }"

        def compose(self) -> ComposeResult:
            yield RelationshipsScreen()

        def on_mount(self) -> None:
            screen = self.query_one(RelationshipsScreen)
            screen.set_data(
                characters=[
                    Character(
                        id="a",
                        name="Lone Wolf",
                        backstory="",
                        personality="Aloof.",
                        physical_description="Grey.",
                        introduced_at_node_id="root",
                    ),
                ],
                relationships=[],
            )

    async with _EmptyHarness().run_test() as pilot:
        screen = pilot.app.query_one(RelationshipsScreen)
        content = screen.query_one("#rel-content")
        text = cast(Content, content.render()).plain
        assert "No known relationships" in text
