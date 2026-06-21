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
from backend.app.application.use_cases.render_plan_assets import (
    CreateRenderPlan,
    GenerateRenderPlan,
    GetLatestRenderPlan,
    ListRenderPlans,
    RenderPlan,
)
from backend.app.application.use_cases.render_output_assets import (
    CreateRenderOutput,
    GenerateRenderOutput,
    GetLatestRenderOutput,
    ListRenderOutputs,
    RenderOutput,
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
from backend.app.application.use_cases.subtitle_assets import (
    CreateSubtitles,
    GenerateSubtitles,
    GetLatestSubtitles,
    ListSubtitles,
    Subtitles,
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
    "CreateRenderPlan",
    "CreateRenderOutput",
    "CreateSceneTable",
    "CreateScriptDraft",
    "CreateSelectedClipSet",
    "CreateStockPlan",
    "CreateSubtitles",
    "CreateVideoAssemblyPlan",
    "CreateVoiceover",
    "DownloadClips",
    "DownloadedClipSet",
    "GenerateSceneTable",
    "GenerateRenderPlan",
    "GenerateRenderOutput",
    "GenerateScriptDraft",
    "GenerateStockPlan",
    "GenerateSubtitles",
    "GenerateVideoAssemblyPlan",
    "GenerateVoiceover",
    "GetLatestClipCandidateSet",
    "GetLatestDownloadedClipSet",
    "GetLatestSceneTable",
    "GetLatestRenderPlan",
    "GetLatestRenderOutput",
    "GetLatestScriptDraft",
    "GetLatestSelectedClipSet",
    "GetLatestStockPlan",
    "GetLatestSubtitles",
    "GetLatestVideoAssemblyPlan",
    "GetLatestVoiceover",
    "GetRun",
    "HealthCheck",
    "HealthStatus",
    "ListSceneTables",
    "ListRenderPlans",
    "ListRenderOutputs",
    "ListSelectedClipSets",
    "ListScriptDrafts",
    "ListClipCandidateSets",
    "ListDownloadedClipSets",
    "ListStockPlans",
    "ListSubtitles",
    "ListVideoAssemblyPlans",
    "ListVoiceovers",
    "MarkFailed",
    "MarkScenesReady",
    "MarkScriptReady",
    "SceneTable",
    "SelectClips",
    "SelectedClipSet",
    "StockPlan",
    "Subtitles",
    "RetrieveClipCandidates",
    "RenderPlan",
    "RenderOutput",
    "VideoAssemblyPlan",
    "Voiceover",
]
