"""Application use-cases."""

from backend.app.application.use_cases.health_check import HealthCheck, HealthStatus
from backend.app.application.use_cases.downloaded_clip_assets import (
    CreateDownloadedClipSet,
    DownloadClips,
    DownloadedClipSet,
    GetLatestDownloadedClipSet,
    ListDownloadedClipSets,
)
from backend.app.application.use_cases.clip_candidate_assets import (
    ClipCandidateSet,
    CreateClipCandidateSet,
    GetLatestClipCandidateSet,
    ListClipCandidateSets,
    RetrieveClipCandidates,
)
from backend.app.application.use_cases.run_lifecycle import (
    ApproveScenes,
    ApproveScript,
    CreateRun,
    GetRun,
    MarkFailed,
    MarkScenesReady,
    MarkScriptReady,
)
from backend.app.application.use_cases.scene_assets import (
    CreateSceneTable,
    GenerateSceneTable,
    GetLatestSceneTable,
    ListSceneTables,
    SceneTable,
)
from backend.app.application.use_cases.selected_clip_assets import (
    CreateSelectedClipSet,
    GetLatestSelectedClipSet,
    ListSelectedClipSets,
    SelectClips,
    SelectedClipSet,
)
from backend.app.application.use_cases.script_assets import (
    CreateScriptDraft,
    GenerateScriptDraft,
    GetLatestScriptDraft,
    ListScriptDrafts,
)
from backend.app.application.use_cases.stock_assets import (
    CreateStockPlan,
    GenerateStockPlan,
    GetLatestStockPlan,
    ListStockPlans,
    StockPlan,
)
from backend.app.application.use_cases.video_assembly_plan_assets import (
    CreateVideoAssemblyPlan,
    GenerateVideoAssemblyPlan,
    GetLatestVideoAssemblyPlan,
    ListVideoAssemblyPlans,
    VideoAssemblyPlan,
)
from backend.app.application.use_cases.voiceover_assets import (
    CreateVoiceover,
    GenerateVoiceover,
    GetLatestVoiceover,
    ListVoiceovers,
    Voiceover,
)

__all__ = [
    "ApproveScenes",
    "ApproveScript",
    "ClipCandidateSet",
    "CreateClipCandidateSet",
    "CreateDownloadedClipSet",
    "CreateRun",
    "CreateSceneTable",
    "CreateScriptDraft",
    "CreateSelectedClipSet",
    "CreateStockPlan",
    "CreateVideoAssemblyPlan",
    "CreateVoiceover",
    "DownloadClips",
    "DownloadedClipSet",
    "GenerateSceneTable",
    "GenerateScriptDraft",
    "GenerateStockPlan",
    "GenerateVideoAssemblyPlan",
    "GenerateVoiceover",
    "GetLatestClipCandidateSet",
    "GetLatestDownloadedClipSet",
    "GetLatestSceneTable",
    "GetLatestScriptDraft",
    "GetLatestSelectedClipSet",
    "GetLatestStockPlan",
    "GetLatestVideoAssemblyPlan",
    "GetLatestVoiceover",
    "GetRun",
    "HealthCheck",
    "HealthStatus",
    "ListSceneTables",
    "ListSelectedClipSets",
    "ListScriptDrafts",
    "ListClipCandidateSets",
    "ListDownloadedClipSets",
    "ListStockPlans",
    "ListVideoAssemblyPlans",
    "ListVoiceovers",
    "MarkFailed",
    "MarkScenesReady",
    "MarkScriptReady",
    "SceneTable",
    "SelectClips",
    "SelectedClipSet",
    "StockPlan",
    "RetrieveClipCandidates",
    "VideoAssemblyPlan",
    "Voiceover",
]
