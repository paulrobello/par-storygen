"""Typer CLI entry point — bound to the `storygen` console script in par-storygen."""

from __future__ import annotations

from typing import Annotated

import typer

import storygen
from storygen.app import StoryGenApp

app = typer.Typer(add_completion=False, help="AI-driven TUI choose-your-own-adventure.")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(storygen.__version__)
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = False,
) -> None:
    """AI-driven TUI choose-your-own-adventure."""
    _ = version
    if ctx.invoked_subcommand is None:
        run()


@app.command()
def run(
    resume: Annotated[
        bool,
        typer.Option(
            "--resume",
            "-r",
            help="Skip the menu and resume the most recently played story.",
        ),
    ] = False,
) -> None:
    """Launch the TUI."""
    StoryGenApp(resume_last=resume).run()


if __name__ == "__main__":
    app()
