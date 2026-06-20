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
    ClipCandidateSet,
    CreateClipCandidateSet,
    CreateDownloadedClipSet,
    CreateSceneTable,
    CreateSelectedClipSet,
    CreateScriptDraft,
    CreateStockPlan,
    CreateVideoAssemblyPlan,
    DownloadClips,
    DownloadedClipSet,
    GenerateSceneTable,
    GenerateScriptDraft,
    GenerateStockPlan,
    GenerateVideoAssemblyPlan,
    GetLatestClipCandidateSet,
    GetLatestDownloadedClipSet,
    GetLatestSceneTable,
    GetLatestSelectedClipSet,
    GetLatestScriptDraft,
    GetLatestStockPlan,
    GetLatestVideoAssemblyPlan,
    ListClipCandidateSets,
    ListDownloadedClipSets,
    ListSceneTables,
    ListSelectedClipSets,
    ListScriptDrafts,
    ListStockPlans,
    ListVideoAssemblyPlans,
    RetrieveClipCandidates,
    SceneTable,
    SelectClips,
    SelectedClipSet,
    StockPlan,
    VideoAssemblyPlan,
)
from backend.app.domain import (
    ClipCandidate,
    DownloadedClip,
    SceneSpec,
    SelectedClip,
    StockQuerySpec,
    VersionedAsset,
    VideoAssemblySegment,
)
from backend.app.ports import (
    ClipRetrievalProvider,
    ClipDownloader,
    ClipSelector,
    RunRepository,
    SceneTablePlanner,
    ScriptDraftGenerator,
    StockClipPlanner,
    StoragePort,
    VersionedAssetRepository,
    VideoAssemblyPlanner,
)

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


def get_script_generator(request: Request) -> ScriptDraftGenerator:
    """Resolve the script-draft generator wired at composition time."""
    return request.app.state.script_generator


def get_scene_planner(request: Request) -> SceneTablePlanner:
    """Resolve the scene-table planner wired at composition time."""
    return request.app.state.scene_planner


def get_stock_planner(request: Request) -> StockClipPlanner:
    """Resolve the stock-clip planner wired at composition time."""
    return request.app.state.stock_planner


def get_clip_retrieval_provider(request: Request) -> ClipRetrievalProvider:
    """Resolve the clip retrieval provider wired at composition time."""
    return request.app.state.clip_retrieval_provider


def get_clip_selector(request: Request) -> ClipSelector:
    """Resolve the clip selector wired at composition time."""
    return request.app.state.clip_selector


def get_video_assembly_planner(request: Request) -> VideoAssemblyPlanner:
    """Resolve the video assembly planner wired at composition time."""
    return request.app.state.video_assembly_planner


def get_clip_downloader(request: Request) -> ClipDownloader:
    """Resolve the clip downloader wired at composition time."""
    return request.app.state.clip_downloader


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


class StockQuerySpecModel(BaseModel):
    scene_id: str
    query: str
    visual_intent: str
    duration_seconds: float
    provider_hint: str | None = None

    def to_domain(self) -> StockQuerySpec:
        return StockQuerySpec(
            scene_id=self.scene_id,
            query=self.query,
            visual_intent=self.visual_intent,
            duration_seconds=self.duration_seconds,
            provider_hint=self.provider_hint,
        )

    @classmethod
    def from_domain(cls, query: StockQuerySpec) -> "StockQuerySpecModel":
        return cls(
            scene_id=query.scene_id,
            query=query.query,
            visual_intent=query.visual_intent,
            duration_seconds=query.duration_seconds,
            provider_hint=query.provider_hint,
        )


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


class StockPlanResponse(BaseModel):
    asset: AssetResponse
    queries: list[StockQuerySpecModel]

    @classmethod
    def from_stock_plan(cls, plan: StockPlan) -> "StockPlanResponse":
        return cls(
            asset=AssetResponse.from_asset(plan.asset),
            queries=[
                StockQuerySpecModel.from_domain(query)
                for query in plan.queries
            ],
        )


class ClipCandidateModel(BaseModel):
    scene_id: str
    query_text: str
    provider: str
    provider_clip_id: str
    title: str
    preview_url: str
    source_url: str
    duration_seconds: float
    width: int
    height: int

    @classmethod
    def from_domain(cls, candidate: ClipCandidate) -> "ClipCandidateModel":
        return cls(
            scene_id=candidate.scene_id,
            query_text=candidate.query_text,
            provider=candidate.provider,
            provider_clip_id=candidate.provider_clip_id,
            title=candidate.title,
            preview_url=candidate.preview_url,
            source_url=candidate.source_url,
            duration_seconds=candidate.duration_seconds,
            width=candidate.width,
            height=candidate.height,
        )


class ClipCandidateSetResponse(BaseModel):
    asset: AssetResponse
    candidates: list[ClipCandidateModel]

    @classmethod
    def from_clip_candidate_set(
        cls, candidate_set: ClipCandidateSet
    ) -> "ClipCandidateSetResponse":
        return cls(
            asset=AssetResponse.from_asset(candidate_set.asset),
            candidates=[
                ClipCandidateModel.from_domain(candidate)
                for candidate in candidate_set.candidates
            ],
        )


class SelectedClipModel(BaseModel):
    scene_id: str
    query_text: str
    provider: str
    provider_clip_id: str
    title: str
    preview_url: str
    source_url: str
    duration_seconds: float
    width: int
    height: int
    selection_reason: str

    @classmethod
    def from_domain(cls, selected_clip: SelectedClip) -> "SelectedClipModel":
        return cls(
            scene_id=selected_clip.scene_id,
            query_text=selected_clip.query_text,
            provider=selected_clip.provider,
            provider_clip_id=selected_clip.provider_clip_id,
            title=selected_clip.title,
            preview_url=selected_clip.preview_url,
            source_url=selected_clip.source_url,
            duration_seconds=selected_clip.duration_seconds,
            width=selected_clip.width,
            height=selected_clip.height,
            selection_reason=selected_clip.selection_reason,
        )


class SelectedClipSetResponse(BaseModel):
    asset: AssetResponse
    selected_clips: list[SelectedClipModel]

    @classmethod
    def from_selected_clip_set(
        cls, selected_clip_set: SelectedClipSet
    ) -> "SelectedClipSetResponse":
        return cls(
            asset=AssetResponse.from_asset(selected_clip_set.asset),
            selected_clips=[
                SelectedClipModel.from_domain(selected_clip)
                for selected_clip in selected_clip_set.selected_clips
            ],
        )


class VideoAssemblySegmentModel(BaseModel):
    scene_id: str
    query_text: str
    narration: str
    visual_query: str
    provider: str
    provider_clip_id: str
    title: str
    preview_url: str
    source_url: str
    target_duration_seconds: float
    source_duration_seconds: float
    width: int
    height: int
    order_index: int
    transition: str
    continuity_note: str
    selection_reason: str

    @classmethod
    def from_domain(
        cls, segment: VideoAssemblySegment
    ) -> "VideoAssemblySegmentModel":
        return cls(
            scene_id=segment.scene_id,
            query_text=segment.query_text,
            narration=segment.narration,
            visual_query=segment.visual_query,
            provider=segment.provider,
            provider_clip_id=segment.provider_clip_id,
            title=segment.title,
            preview_url=segment.preview_url,
            source_url=segment.source_url,
            target_duration_seconds=segment.target_duration_seconds,
            source_duration_seconds=segment.source_duration_seconds,
            width=segment.width,
            height=segment.height,
            order_index=segment.order_index,
            transition=segment.transition,
            continuity_note=segment.continuity_note,
            selection_reason=segment.selection_reason,
        )


class VideoAssemblyPlanResponse(BaseModel):
    asset: AssetResponse
    segments: list[VideoAssemblySegmentModel]

    @classmethod
    def from_video_assembly_plan(
        cls, plan: VideoAssemblyPlan
    ) -> "VideoAssemblyPlanResponse":
        return cls(
            asset=AssetResponse.from_asset(plan.asset),
            segments=[
                VideoAssemblySegmentModel.from_domain(segment)
                for segment in plan.segments
            ],
        )


class DownloadedClipModel(BaseModel):
    scene_id: str
    query_text: str
    provider: str
    provider_clip_id: str
    title: str
    source_url: str
    local_uri: str
    content_type: str
    duration_seconds: float
    width: int
    height: int
    order_index: int
    download_status: str
    download_reason: str

    @classmethod
    def from_domain(cls, clip: DownloadedClip) -> "DownloadedClipModel":
        return cls(
            scene_id=clip.scene_id,
            query_text=clip.query_text,
            provider=clip.provider,
            provider_clip_id=clip.provider_clip_id,
            title=clip.title,
            source_url=clip.source_url,
            local_uri=clip.local_uri,
            content_type=clip.content_type,
            duration_seconds=clip.duration_seconds,
            width=clip.width,
            height=clip.height,
            order_index=clip.order_index,
            download_status=clip.download_status,
            download_reason=clip.download_reason,
        )


class DownloadedClipSetResponse(BaseModel):
    asset: AssetResponse
    downloaded_clips: list[DownloadedClipModel]

    @classmethod
    def from_downloaded_clip_set(
        cls, downloaded_clip_set: DownloadedClipSet
    ) -> "DownloadedClipSetResponse":
        return cls(
            asset=AssetResponse.from_asset(downloaded_clip_set.asset),
            downloaded_clips=[
                DownloadedClipModel.from_domain(clip)
                for clip in downloaded_clip_set.downloaded_clips
            ],
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


@router.post(
    "/{run_id}/script-drafts/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetResponse,
)
def generate_script_draft(
    run_id: str,
    run_repository: RunRepository = Depends(get_run_repository),
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
    storage: StoragePort = Depends(get_storage),
    script_generator: ScriptDraftGenerator = Depends(get_script_generator),
) -> AssetResponse:
    create_script_draft = CreateScriptDraft(
        run_repository, asset_repository, storage
    )
    asset = GenerateScriptDraft(
        run_repository, script_generator, create_script_draft
    ).execute(run_id)
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


@router.post(
    "/{run_id}/scene-tables/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetResponse,
)
def generate_scene_table(
    run_id: str,
    run_repository: RunRepository = Depends(get_run_repository),
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
    storage: StoragePort = Depends(get_storage),
    scene_planner: SceneTablePlanner = Depends(get_scene_planner),
) -> AssetResponse:
    create_scene_table = CreateSceneTable(
        run_repository, asset_repository, storage
    )
    asset = GenerateSceneTable(
        run_repository, scene_planner, create_scene_table
    ).execute(run_id)
    return AssetResponse.from_asset(asset)


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


@router.post(
    "/{run_id}/stock-plans/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetResponse,
)
def generate_stock_plan(
    run_id: str,
    run_repository: RunRepository = Depends(get_run_repository),
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
    storage: StoragePort = Depends(get_storage),
    stock_planner: StockClipPlanner = Depends(get_stock_planner),
) -> AssetResponse:
    create_stock_plan = CreateStockPlan(
        run_repository, asset_repository, storage
    )
    get_latest_scene_table = GetLatestSceneTable(asset_repository, storage)
    asset = GenerateStockPlan(
        run_repository,
        stock_planner,
        get_latest_scene_table,
        create_stock_plan,
    ).execute(run_id)
    return AssetResponse.from_asset(asset)


@router.get("/{run_id}/stock-plans", response_model=list[AssetResponse])
def list_stock_plans(
    run_id: str,
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
) -> list[AssetResponse]:
    assets = ListStockPlans(asset_repository).execute(run_id)
    return [AssetResponse.from_asset(asset) for asset in assets]


@router.get("/{run_id}/stock-plans/latest", response_model=StockPlanResponse)
def get_latest_stock_plan(
    run_id: str,
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
    storage: StoragePort = Depends(get_storage),
) -> StockPlanResponse:
    plan = GetLatestStockPlan(asset_repository, storage).execute(run_id)
    return StockPlanResponse.from_stock_plan(plan)


@router.post(
    "/{run_id}/clip-candidates/retrieve",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetResponse,
)
def retrieve_clip_candidates(
    run_id: str,
    run_repository: RunRepository = Depends(get_run_repository),
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
    storage: StoragePort = Depends(get_storage),
    clip_retrieval_provider: ClipRetrievalProvider = Depends(
        get_clip_retrieval_provider
    ),
) -> AssetResponse:
    create_clip_candidate_set = CreateClipCandidateSet(
        run_repository, asset_repository, storage
    )
    get_latest_stock_plan = GetLatestStockPlan(asset_repository, storage)
    asset = RetrieveClipCandidates(
        run_repository,
        clip_retrieval_provider,
        get_latest_stock_plan,
        create_clip_candidate_set,
    ).execute(run_id)
    return AssetResponse.from_asset(asset)


@router.get("/{run_id}/clip-candidates", response_model=list[AssetResponse])
def list_clip_candidates(
    run_id: str,
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
) -> list[AssetResponse]:
    assets = ListClipCandidateSets(asset_repository).execute(run_id)
    return [AssetResponse.from_asset(asset) for asset in assets]


@router.get(
    "/{run_id}/clip-candidates/latest",
    response_model=ClipCandidateSetResponse,
)
def get_latest_clip_candidates(
    run_id: str,
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
    storage: StoragePort = Depends(get_storage),
) -> ClipCandidateSetResponse:
    candidate_set = GetLatestClipCandidateSet(
        asset_repository, storage
    ).execute(run_id)
    return ClipCandidateSetResponse.from_clip_candidate_set(candidate_set)


@router.post(
    "/{run_id}/selected-clips/select",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetResponse,
)
def select_clips(
    run_id: str,
    run_repository: RunRepository = Depends(get_run_repository),
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
    storage: StoragePort = Depends(get_storage),
    clip_selector: ClipSelector = Depends(get_clip_selector),
) -> AssetResponse:
    create_selected_clip_set = CreateSelectedClipSet(
        run_repository, asset_repository, storage
    )
    get_latest_clip_candidate_set = GetLatestClipCandidateSet(
        asset_repository, storage
    )
    asset = SelectClips(
        run_repository,
        clip_selector,
        get_latest_clip_candidate_set,
        create_selected_clip_set,
    ).execute(run_id)
    return AssetResponse.from_asset(asset)


@router.get("/{run_id}/selected-clips", response_model=list[AssetResponse])
def list_selected_clips(
    run_id: str,
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
) -> list[AssetResponse]:
    assets = ListSelectedClipSets(asset_repository).execute(run_id)
    return [AssetResponse.from_asset(asset) for asset in assets]


@router.get(
    "/{run_id}/selected-clips/latest",
    response_model=SelectedClipSetResponse,
)
def get_latest_selected_clips(
    run_id: str,
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
    storage: StoragePort = Depends(get_storage),
) -> SelectedClipSetResponse:
    selected_clip_set = GetLatestSelectedClipSet(
        asset_repository, storage
    ).execute(run_id)
    return SelectedClipSetResponse.from_selected_clip_set(selected_clip_set)


@router.post(
    "/{run_id}/video-assembly-plans/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetResponse,
)
def generate_video_assembly_plan(
    run_id: str,
    run_repository: RunRepository = Depends(get_run_repository),
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
    storage: StoragePort = Depends(get_storage),
    video_assembly_planner: VideoAssemblyPlanner = Depends(
        get_video_assembly_planner
    ),
) -> AssetResponse:
    create_video_assembly_plan = CreateVideoAssemblyPlan(
        run_repository, asset_repository, storage
    )
    get_latest_selected_clip_set = GetLatestSelectedClipSet(
        asset_repository, storage
    )
    get_latest_scene_table = GetLatestSceneTable(asset_repository, storage)
    asset = GenerateVideoAssemblyPlan(
        run_repository,
        video_assembly_planner,
        get_latest_selected_clip_set,
        get_latest_scene_table,
        create_video_assembly_plan,
    ).execute(run_id)
    return AssetResponse.from_asset(asset)


@router.get(
    "/{run_id}/video-assembly-plans",
    response_model=list[AssetResponse],
)
def list_video_assembly_plans(
    run_id: str,
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
) -> list[AssetResponse]:
    assets = ListVideoAssemblyPlans(asset_repository).execute(run_id)
    return [AssetResponse.from_asset(asset) for asset in assets]


@router.get(
    "/{run_id}/video-assembly-plans/latest",
    response_model=VideoAssemblyPlanResponse,
)
def get_latest_video_assembly_plan(
    run_id: str,
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
    storage: StoragePort = Depends(get_storage),
) -> VideoAssemblyPlanResponse:
    plan = GetLatestVideoAssemblyPlan(asset_repository, storage).execute(run_id)
    return VideoAssemblyPlanResponse.from_video_assembly_plan(plan)


@router.post(
    "/{run_id}/downloaded-clips/download",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetResponse,
)
def download_clips(
    run_id: str,
    run_repository: RunRepository = Depends(get_run_repository),
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
    storage: StoragePort = Depends(get_storage),
    clip_downloader: ClipDownloader = Depends(get_clip_downloader),
) -> AssetResponse:
    create_downloaded_clip_set = CreateDownloadedClipSet(
        run_repository, asset_repository, storage
    )
    get_latest_video_assembly_plan = GetLatestVideoAssemblyPlan(
        asset_repository, storage
    )
    asset = DownloadClips(
        run_repository,
        clip_downloader,
        get_latest_video_assembly_plan,
        create_downloaded_clip_set,
    ).execute(run_id)
    return AssetResponse.from_asset(asset)


@router.get(
    "/{run_id}/downloaded-clips",
    response_model=list[AssetResponse],
)
def list_downloaded_clips(
    run_id: str,
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
) -> list[AssetResponse]:
    assets = ListDownloadedClipSets(asset_repository).execute(run_id)
    return [AssetResponse.from_asset(asset) for asset in assets]


@router.get(
    "/{run_id}/downloaded-clips/latest",
    response_model=DownloadedClipSetResponse,
)
def get_latest_downloaded_clips(
    run_id: str,
    asset_repository: VersionedAssetRepository = Depends(
        get_versioned_asset_repository
    ),
    storage: StoragePort = Depends(get_storage),
) -> DownloadedClipSetResponse:
    downloaded_clip_set = GetLatestDownloadedClipSet(
        asset_repository, storage
    ).execute(run_id)
    return DownloadedClipSetResponse.from_downloaded_clip_set(
        downloaded_clip_set
    )
