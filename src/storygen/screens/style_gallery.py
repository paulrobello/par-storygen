from __future__ import annotations

import os
import time
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, Static

from storygen.images.pricing import image_cost

_DEFAULT_CHARACTER = (
    "A warrior princess with flowing red hair and emerald green eyes, "
    "wearing ornate silver armor, standing in a confident pose"
)

_PROVIDER_OPTIONS: list[tuple[str, str, str]] = [
    ("openai", "OpenAI", "gpt-image-2"),
    ("gemini", "Gemini", "gemini-3.1-flash-image-preview"),
    ("zai", "Z.AI", "glm-image"),
    ("ollama", "Ollama", "x/z-image-turbo"),
]

_API_KEY_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "zai": "ZAI_API_KEY",
}


class StyleGalleryScreen(Screen[None]):
    """Compare image providers side-by-side with the same character portrait."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "back", "Back"),
    ]

    def __init__(self, config: object, image_provider: object) -> None:
        super().__init__()
        self._config = config
        self._image_provider = image_provider
        self._cache: dict[tuple[str, str, str], bytes] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="gallery-body"):
            yield Label("Image Style Gallery", id="gallery-title")
            yield Label(
                "Compare how different providers render the same character portrait.",
                id="gallery-desc",
            )

            with Vertical(id="gallery-config"):
                yield Label("Character description:")
                yield Input(value=_DEFAULT_CHARACTER, id="gallery-char-desc")

                yield Label("Providers to compare:")
                for pid, pname, default_model in _PROVIDER_OPTIONS:
                    has_key = (
                        pid == "ollama"
                        or bool(os.environ.get(_API_KEY_ENV.get(pid, ""), ""))
                    )
                    label = f"{pname} ({default_model})"
                    if not has_key:
                        label += " — no API key"
                    yield Checkbox(label, id=f"gallery-cb-{pid}", value=False)

                yield Button("Generate Comparison", id="gallery-gen", variant="primary")

            with Vertical(id="gallery-results"):
                pass

            yield Button("Back to Settings", id="gallery-back")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "gallery-back":
            self.app.pop_screen()  # pyright: ignore[reportUnknownMemberType]
        elif event.button.id == "gallery-gen":
            self.run_worker(self._generate(), name="gallery-gen")

    def action_back(self) -> None:
        self.app.pop_screen()  # pyright: ignore[reportUnknownMemberType]

    async def _generate(self) -> None:
        from storygen.images.provider_factory import build_image_provider
        from storygen.llm.models import ImageProviderConfig

        desc = self.query_one("#gallery-char-desc", Input).value.strip()
        if not desc:
            self.notify("Enter a character description", severity="warning", timeout=3)
            return

        selected: list[tuple[str, str, str]] = []
        for pid, pname, default_model in _PROVIDER_OPTIONS:
            cb = self.query_one(f"#gallery-cb-{pid}", Checkbox)
            if cb.value:
                selected.append((pid, pname, default_model))

        if not selected:
            self.notify("Select at least one provider", severity="warning", timeout=3)
            return

        results = self.query_one("#gallery-results", Vertical)
        for child in list(results.children):
            await child.remove()

        self.notify(f"Generating {len(selected)} portrait(s)…", timeout=120)

        art_style = getattr(
            getattr(self._config, "image_config", None), "art_style", "children's story book"
        )

        for pid, pname, default_model in selected:
            card = Static(f"[dim]{pname}: generating…[/]", classes="gallery-card")
            await results.mount(card)

            start = time.monotonic()
            try:
                api_key = self._get_api_key(pid)
                cfg = ImageProviderConfig(
                    provider=pid,  # type: ignore[arg-type]
                    model=default_model,
                    api_key=api_key,
                )
                provider = build_image_provider(cfg)
                img_bytes = await provider.generate_portrait(
                    desc,
                    transparent=False,
                    art_style=art_style,
                )
                elapsed = time.monotonic() - start
                cost = image_cost(pid, model=default_model, size="1024x1536")
                card.update(
                    f"[bold]{pname}[/bold] ({default_model})\n"
                    f"Time: {elapsed:.1f}s  |  Est. cost: ${cost:.4f}\n"
                    f"[dim]({len(img_bytes)} bytes)[/]"
                )
                self._cache[(pid, default_model, desc)] = img_bytes
            except Exception as exc:
                elapsed = time.monotonic() - start
                card.update(
                    f"[bold]{pname}[/bold] ({default_model})\n"
                    f"[red]Error: {exc}[/] ({elapsed:.1f}s)"
                )

    def _get_api_key(self, provider: str) -> str | None:
        if provider == "ollama":
            return None
        return os.environ.get(_API_KEY_ENV.get(provider, ""), "") or None

    CSS = """
    #gallery-body {
        padding: 1 2;
    }
    #gallery-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 0;
    }
    #gallery-desc {
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
    }
    #gallery-config {
        margin-bottom: 1;
        padding: 1;
        border: solid $panel;
    }
    #gallery-results {
        margin-top: 1;
    }
    .gallery-card {
        padding: 1;
        margin-bottom: 1;
        border: solid $panel;
        background: $surface-lighten-1;
    }
    """
