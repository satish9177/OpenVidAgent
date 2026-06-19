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
    GenerateSceneTable,
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
from backend.app.application.use_cases.stock_assets import (
    CreateStockPlan,
    GenerateStockPlan,
    GetLatestStockPlan,
    ListStockPlans,
    StockPlan,
)

__all__ = [
    "ApproveScenes",
    "ApproveScript",
    "CreateRun",
    "CreateSceneTable",
    "CreateScriptDraft",
    "CreateStockPlan",
    "GenerateSceneTable",
    "GenerateScriptDraft",
    "GenerateStockPlan",
    "GetLatestSceneTable",
    "GetLatestScriptDraft",
    "GetLatestStockPlan",
    "GetRun",
    "HealthCheck",
    "HealthStatus",
    "ListSceneTables",
    "ListScriptDrafts",
    "ListStockPlans",
    "MarkFailed",
    "MarkScenesReady",
    "MarkScriptReady",
    "SceneTable",
    "StockPlan",
]
