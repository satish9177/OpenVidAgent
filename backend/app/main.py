"""FastAPI application entrypoint and composition root.

As the composition root this module is allowed to import infrastructure to wire
concrete adapters onto the application's ports. Routes themselves stay free of
infrastructure.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.api.errors import register_exception_handlers
from backend.app.api.health import router as health_router
from backend.app.api.runs import router as runs_router
from backend.app.config.settings import Settings, get_settings
from backend.app.infrastructure.db import SQLiteRunRepository, initialize_database
from backend.app.ports import RunRepository


def create_app(
    settings: Settings | None = None,
    *,
    run_repository: RunRepository | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()

    lifespan = None
    if run_repository is None:
        run_repository = SQLiteRunRepository(resolved_settings.database_path)

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            initialize_database(resolved_settings.database_path)
            yield

    app = FastAPI(
        title=resolved_settings.app_name,
        debug=resolved_settings.debug,
        lifespan=lifespan,
    )
    app.state.run_repository = run_repository
    app.include_router(health_router)
    app.include_router(runs_router)
    register_exception_handlers(app)
    return app


app = create_app()
