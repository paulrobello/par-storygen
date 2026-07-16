from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import typer
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from storygen import __version__
from storygen.storage import paths

from storygen_api.deps import get_app_config, get_session_manager
from storygen_api.routers import characters, games, images, presets, settings, tts, wizard
from storygen_api.routers import ws as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Startup: load config. Shutdown: cleanup all pipelines."""
    # Pre-load config at startup
    get_app_config()
    yield
    # Cleanup all active pipeline sessions
    mgr = get_session_manager()
    await mgr.cleanup_all()


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title="par-storygen API",
        version=__version__,
        lifespan=lifespan,
    )

    # CORS — allow the dev frontend origin (Makefile ``web-dev`` serves on
    # ``:8100``). SEC-008: methods and headers are pinned to the set the API
    # actually uses rather than the wildcard, and origins are configurable via
    # ``STORYGEN_API_ALLOWED_ORIGINS`` (comma-separated) for non-default deploys.
    default_origins = "http://localhost:8100,http://127.0.0.1:8100"
    raw_origins = os.environ.get("STORYGEN_API_ALLOWED_ORIGINS", default_origins)
    allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Include all routers
    app.include_router(games.router)
    app.include_router(wizard.router)
    app.include_router(settings.router)
    app.include_router(images.router)
    app.include_router(characters.router)
    app.include_router(presets.router)
    app.include_router(tts.router)
    app.include_router(ws_router.router, prefix="/api")

    # Mount game image directories as static files
    games_root = paths.games_root()
    if games_root.exists():
        app.mount(
            "/api/images",
            StaticFiles(directory=str(games_root)),
            name="game-images",
        )

    @app.get("/api/health")
    async def _health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    return app


# Typer CLI entry point
_cli_app = typer.Typer(name="storygen-api", help="par-storygen HTTP API server")


@_cli_app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host (loopback by default)"),  # type: ignore[reportUnknownMemberType]
    port: int = typer.Option(8000, help="Bind port"),  # type: ignore[reportUnknownMemberType]
    reload: bool = typer.Option(False, help="Enable auto-reload"),  # type: ignore[reportUnknownMemberType]
) -> None:
    """Start the storygen API server.

    Binds to ``127.0.0.1`` by default (SEC-006). To expose on a LAN, pass
    ``--host 0.0.0.0`` AND set ``STORYGEN_API_TOKEN`` so SEC-001 auth gates
    every state-changing route.
    """
    uvicorn.run(
        "storygen_api.main:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


def cli() -> None:
    """Entry point for the storygen-api command."""
    _cli_app()


# Module-level app instance for `uvicorn storygen_api.main:app`
app = create_app()
