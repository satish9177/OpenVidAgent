"""Script draft and scene table asset API routes.

These routes translate HTTP requests into application use-case calls and
serialize the resulting assets. They hold no lifecycle/transition or versioning
rules and never mutate a ``Run`` or compute asset versions directly -- those
responsibilities live in the domain/application, reached through use-cases. HTTP
error mapping lives in ``backend.app.api.errors``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from backend.app.application.use_cases import (
    CreateSceneTable,
    CreateScriptDraft,
    GetLatestSceneTable,
    GetLatestScriptDraft,
    ListSceneTables,
    ListScriptDrafts,
    SceneTable,
)
from backend.app.domain import SceneSpec, VersionedAsset
from backend.app.ports import RunRepository, StoragePort, VersionedAssetRepository

router = APIRouter(prefix="/runs", tags=["assets"])


def get_run_repository(request: Request) -> RunRepository:
    """Resolve the run repository wired onto the app at composition time."""
    return request.app.state.run_repository


def get_versioned_asset_repository(
    request: Request,
) -> VersionedAssetRepository:
    """Resolve the versioned asset repository wired at composition time."""
    return request.app.state.versioned_asset_repository


def get_storage(request: Request) -> StoragePort:
    """Resolve the storage adapter wired at composition time."""
    return request.app.state.storage


class CreateScriptDraftRequest(BaseModel):
    text: str


class SceneSpecModel(BaseModel):
    scene_id: str
    narration: str
    visual_query: str
    duration_seconds: float

    def to_domain(self) -> SceneSpec:
        return SceneSpec(
            scene_id=self.scene_id,
            narration=self.narration,
            visual_query=self.visual_query,
            duration_seconds=self.duration_seconds,
        )

    @classmethod
    def from_domain(cls, scene: SceneSpec) -> "SceneSpecModel":
        return cls(
            scene_id=scene.scene_id,
            narration=scene.narration,
            visual_query=scene.visual_query,
            duration_seconds=scene.duration_seconds,
        )


class CreateSceneTableRequest(BaseModel):
    scenes: list[SceneSpecModel]


class AssetResponse(BaseModel):
    asset_id: str
    kind: str
    version: int
    uri: str
    metadata: dict[str, str]

    @classmethod
    def from_asset(cls, asset: VersionedAsset) -> "AssetResponse":
        return cls(
            asset_id=asset.asset_id,
            kind=asset.kind.value,
            version=asset.version,
            uri=asset.uri,
            metadata=dict(asset.metadata),
        )


class SceneTableResponse(BaseModel):
    asset: AssetResponse
    scenes: list[SceneSpecModel]

    @classmethod
    def from_scene_table(cls, table: SceneTable) -> "SceneTableResponse":
        return cls(
            asset=AssetResponse.from_asset(table.asset),
            scenes=[SceneSpecModel.from_domain(scene) for scene in table.scenes],
        )


@router.post(
    "/{run_id}/script-drafts",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetResponse,
)
def create_script_draft(
    run_id: str,
    body: CreateScriptDraftRequest,
    run_repository: RunRepository = Depends(get_run_repository),
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
    storage: StoragePort = Depends(get_storage),
) -> AssetResponse:
    asset = CreateScriptDraft(run_repository, asset_repository, storage).execute(
        run_id, body.text
    )
    return AssetResponse.from_asset(asset)


@router.get("/{run_id}/script-drafts", response_model=list[AssetResponse])
def list_script_drafts(
    run_id: str,
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
) -> list[AssetResponse]:
    assets = ListScriptDrafts(asset_repository).execute(run_id)
    return [AssetResponse.from_asset(asset) for asset in assets]


@router.get("/{run_id}/script-drafts/latest", response_model=AssetResponse)
def get_latest_script_draft(
    run_id: str,
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
) -> AssetResponse:
    asset = GetLatestScriptDraft(asset_repository).execute(run_id)
    return AssetResponse.from_asset(asset)


@router.post(
    "/{run_id}/scene-tables",
    status_code=status.HTTP_201_CREATED,
    response_model=SceneTableResponse,
)
def create_scene_table(
    run_id: str,
    body: CreateSceneTableRequest,
    run_repository: RunRepository = Depends(get_run_repository),
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
    storage: StoragePort = Depends(get_storage),
) -> SceneTableResponse:
    scenes = tuple(scene.to_domain() for scene in body.scenes)
    asset = CreateSceneTable(run_repository, asset_repository, storage).execute(
        run_id, scenes
    )
    return SceneTableResponse(
        asset=AssetResponse.from_asset(asset),
        scenes=[SceneSpecModel.from_domain(scene) for scene in scenes],
    )


@router.get("/{run_id}/scene-tables", response_model=list[AssetResponse])
def list_scene_tables(
    run_id: str,
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
) -> list[AssetResponse]:
    assets = ListSceneTables(asset_repository).execute(run_id)
    return [AssetResponse.from_asset(asset) for asset in assets]


@router.get("/{run_id}/scene-tables/latest", response_model=SceneTableResponse)
def get_latest_scene_table(
    run_id: str,
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
    storage: StoragePort = Depends(get_storage),
) -> SceneTableResponse:
    table = GetLatestSceneTable(asset_repository, storage).execute(run_id)
    return SceneTableResponse.from_scene_table(table)
