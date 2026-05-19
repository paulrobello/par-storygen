from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import typer
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS — allow localhost:3000 for local dev frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8100", "http://127.0.0.1:8100"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
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
    host: str = typer.Option("0.0.0.0", help="Bind host"),  # type: ignore[reportUnknownMemberType]
    port: int = typer.Option(8000, help="Bind port"),  # type: ignore[reportUnknownMemberType]
    reload: bool = typer.Option(False, help="Enable auto-reload"),  # type: ignore[reportUnknownMemberType]
) -> None:
    """Start the storygen API server."""
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
