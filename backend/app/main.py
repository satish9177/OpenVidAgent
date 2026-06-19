"""FastAPI application entrypoint and composition root.

As the composition root this module is allowed to import infrastructure to wire
concrete adapters onto the application's ports. Routes themselves stay free of
infrastructure.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from backend.app.api.assets import router as assets_router
from backend.app.api.errors import register_exception_handlers
from backend.app.api.health import router as health_router
from backend.app.api.runs import router as runs_router
from backend.app.config.settings import Settings, get_settings
from backend.app.infrastructure.db import (
    SQLiteRunRepository,
    SQLiteVersionedAssetRepository,
    initialize_database,
)
from backend.app.infrastructure.generation import (
    DeterministicClipSelector,
    DeterministicVideoAssemblyPlanner,
    EchoScriptDraftGenerator,
    StubClipRetrievalProvider,
    StubSceneTablePlanner,
    StubStockClipPlanner,
)
from backend.app.infrastructure.storage import LocalFilesystemStorage
from backend.app.ports import (
    ClipRetrievalProvider,
    ClipSelector,
    RunRepository,
    SceneTablePlanner,
    ScriptDraftGenerator,
    StockClipPlanner,
    StoragePort,
    VersionedAssetRepository,
    VideoAssemblyPlanner,
)


def create_app(
    settings: Settings | None = None,
    *,
    run_repository: RunRepository | None = None,
    versioned_asset_repository: VersionedAssetRepository | None = None,
    storage: StoragePort | None = None,
    script_generator: ScriptDraftGenerator | None = None,
    scene_planner: SceneTablePlanner | None = None,
    stock_planner: StockClipPlanner | None = None,
    clip_retrieval_provider: ClipRetrievalProvider | None = None,
    clip_selector: ClipSelector | None = None,
    video_assembly_planner: VideoAssemblyPlanner | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()

    # Default to concrete infrastructure for anything the caller did not inject;
    # tests inject fakes for all three to avoid touching disk.
    needs_database = (
        run_repository is None or versioned_asset_repository is None
    )
    needs_storage_root = storage is None

    if run_repository is None:
        run_repository = SQLiteRunRepository(resolved_settings.database_path)
    if versioned_asset_repository is None:
        versioned_asset_repository = SQLiteVersionedAssetRepository(
            resolved_settings.database_path
        )
    if storage is None:
        storage = LocalFilesystemStorage(resolved_settings.storage_root)

    # Generation adapters are pure/deterministic (no disk, network, or SDK), so
    # defaulting them never affects the database/storage lifespan decision above.
    if script_generator is None:
        script_generator = EchoScriptDraftGenerator()
    if scene_planner is None:
        scene_planner = StubSceneTablePlanner()
    if stock_planner is None:
        stock_planner = StubStockClipPlanner()
    if clip_retrieval_provider is None:
        clip_retrieval_provider = StubClipRetrievalProvider()
    if clip_selector is None:
        clip_selector = DeterministicClipSelector()
    if video_assembly_planner is None:
        video_assembly_planner = DeterministicVideoAssemblyPlanner()

    lifespan = None
    if needs_database or needs_storage_root:

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            if needs_database:
                initialize_database(resolved_settings.database_path)
            if needs_storage_root:
                Path(resolved_settings.storage_root).mkdir(
                    parents=True, exist_ok=True
                )
            yield

    app = FastAPI(
        title=resolved_settings.app_name,
        debug=resolved_settings.debug,
        lifespan=lifespan,
    )
    app.state.run_repository = run_repository
    app.state.versioned_asset_repository = versioned_asset_repository
    app.state.storage = storage
    app.state.script_generator = script_generator
    app.state.scene_planner = scene_planner
    app.state.stock_planner = stock_planner
    app.state.clip_retrieval_provider = clip_retrieval_provider
    app.state.clip_selector = clip_selector
    app.state.video_assembly_planner = video_assembly_planner
    app.include_router(health_router)
    app.include_router(runs_router)
    app.include_router(assets_router)
    register_exception_handlers(app)
    return app


app = create_app()
