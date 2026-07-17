"""FastAPI application factory for the ``storygen_api`` REST + WebSocket surface.

Wires lifespan (single-worker guard, ARC-004), CORS (SEC-008), and route
mounting. All game assets are served by token-gated router endpoints
(``routers/images.py``) — there is intentionally no static file mount over the
save-data directory (SEC-101: a ``StaticFiles`` mount there bypassed
``verify_token`` and exposed ``game.json`` / ``llm/`` unauthenticated).
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

import typer
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from storygen import __version__
from storygen_api.deps import get_app_config, get_session_manager
from storygen_api.routers import characters, games, images, presets, settings, tts, wizard
from storygen_api.routers import ws as ws_router

_logger = logging.getLogger(__name__)

# ARC-004: this server holds in-process state that does NOT survive a second
# uvicorn worker — ``SessionManager``'s pipeline registry, ``WebSocketManager``'s
# connection lists, and the TTS player all live in module-level singletons. A
# deploy that scales horizontally (``--workers N``, gunicorn ``-w N``, or a
# platform that sets ``WEB_CONCURRENCY``) silently desyncs game state: a WS
# handshake hit on worker A advances a pipeline on worker B, whose callbacks
# broadcast to a connection list that does not include the player. Until these
# singletons move to a shared store (Redis / DB), the server is single-worker.
# ``WEB_CONCURRENCY`` is the conventional signal from gunicorn, Heroku, Render,
# Fly.io, etc.; we fail-fast on it and warn loudly otherwise.


def _enforce_single_worker() -> None:
    """Fail-fast if the process manager signals more than one worker.

    Reads ``WEB_CONCURRENCY`` (the standard signal from gunicorn / Heroku /
    Render / Fly.io). A value > 1 raises at lifespan startup so uvicorn refuses
    to serve rather than silently desyncing in-process state. ``uvicorn
    --workers N`` run directly does NOT set this env var, so we additionally
    log a prominent startup warning documenting the single-worker constraint.
    """
    raw = os.environ.get("WEB_CONCURRENCY", "").strip()
    if raw:
        try:
            workers = int(raw)
        except ValueError:
            workers = 1  # malformed value; treat as single and warn below
        else:
            if workers > 1:
                raise RuntimeError(
                    "storygen_api must run with a single worker until "
                    "SessionManager / WebSocketManager / TTS state move to a "
                    f"shared store (WEB_CONCURRENCY={workers}). Re-launch with "
                    "WEB_CONCURRENCY=1, or `uvicorn storygen_api.main:app "
                    "--workers 1`."
                )
    _logger.warning(
        "storygen_api is single-worker only: SessionManager, "
        "WebSocketManager, and the TTS player hold in-process state. "
        "Scaling workers will desync game sessions."
    )


_EVICTION_INTERVAL_SECONDS = 300.0  # 5 minutes


async def _eviction_loop() -> None:
    """Background task that evicts idle pipeline sessions (ARC-106).

    Runs every :data:`_EVICTION_INTERVAL_SECONDS`. ``evict_idle`` skips games
    whose advance lock is held, so a mid-advance game is never disturbed.
    """
    while True:
        await asyncio.sleep(_EVICTION_INTERVAL_SECONDS)
        try:
            mgr = get_session_manager()
            await mgr.evict_idle()
        except Exception:
            # The loop must survive transient errors so eviction continues
            # across the process lifetime; log and carry on.
            _logger.exception("eviction loop iteration failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Startup: load config, assert single-worker. Shutdown: cleanup pipelines."""
    # ARC-004: refuse to serve if the process manager spun up >1 worker.
    _enforce_single_worker()
    # Pre-load config at startup
    get_app_config()
    # ARC-106: background eviction of idle pipeline sessions.
    eviction_task = asyncio.create_task(_eviction_loop())
    yield
    # Shutdown: stop the eviction loop and cleanup all active sessions.
    eviction_task.cancel()
    with suppress(asyncio.CancelledError):
        await eviction_task
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
        # SEC-107: auth rides the Authorization header / WS subprotocol, not
        # cookies, so credentialed CORS is unnecessary. Disabling it narrows
        # the cross-origin surface (no ``Set-Cookie`` / cookie echo on
        # preflight). ``Authorization`` stays in ``allow_headers`` so token-
        # bearing requests still pass preflight after SEC-102.
        allow_credentials=False,
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

    @app.get("/api/health")
    async def _health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction] - registered as a FastAPI route by the @app.get decorator above; pyright doesn't model the decorator's registration side-effect
        return {"status": "ok"}

    return app


# Typer CLI entry point
_cli_app = typer.Typer(name="storygen-api", help="par-storygen HTTP API server")


@_cli_app.command()
def serve(
    # typer.Option returns a dynamically-typed placeholder that typer resolves at
    # runtime; pyright sees the placeholder's type as unknown. This is typer's
    # documented pattern — see https://typer.tiangolo.com/tutorial/options/
    host: str = typer.Option("127.0.0.1", help="Bind host (loopback by default)"),  # type: ignore[reportUnknownMemberType]
    port: int = typer.Option(8101, help="Bind port"),  # type: ignore[reportUnknownMemberType]
    reload: bool = typer.Option(False, help="Enable auto-reload"),  # type: ignore[reportUnknownMemberType]
) -> None:
    """Start the storygen API server.

    Binds to ``127.0.0.1:8101`` by default (SEC-006; the port pairs with the
    Next.js dev server on :8100). To expose on a LAN, pass ``--host 0.0.0.0``
    AND set ``STORYGEN_API_TOKEN`` so SEC-001 auth gates every
    state-changing route.
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
