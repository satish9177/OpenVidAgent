"""Application use-cases."""

from backend.app.application.use_cases.health_check import HealthCheck, HealthStatus
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
    GetLatestSceneTable,
    ListSceneTables,
    SceneTable,
)
from backend.app.application.use_cases.script_assets import (
    CreateScriptDraft,
    GenerateScriptDraft,
    GetLatestScriptDraft,
    ListScriptDrafts,
)

__all__ = [
    "ApproveScenes",
    "ApproveScript",
    "CreateRun",
    "CreateSceneTable",
    "CreateScriptDraft",
    "GenerateScriptDraft",
    "GetLatestSceneTable",
    "GetLatestScriptDraft",
    "GetRun",
    "HealthCheck",
    "HealthStatus",
    "ListSceneTables",
    "ListScriptDrafts",
    "MarkFailed",
    "MarkScenesReady",
    "MarkScriptReady",
    "SceneTable",
]
