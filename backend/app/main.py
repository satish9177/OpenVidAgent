"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI

from backend.app.api.health import router as health_router
from backend.app.config.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    app = FastAPI(
        title=resolved_settings.app_name,
        debug=resolved_settings.debug,
    )
    app.include_router(health_router)
    return app


app = create_app()
