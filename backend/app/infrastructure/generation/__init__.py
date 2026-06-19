"""Deterministic local generation adapters (no external calls)."""

from backend.app.infrastructure.generation.echo_script_draft_generator import (
    EchoScriptDraftGenerator,
)
from backend.app.infrastructure.generation.stub_scene_table_planner import (
    StubSceneTablePlanner,
)
from backend.app.infrastructure.generation.stub_stock_clip_planner import (
    StubStockClipPlanner,
)

__all__ = [
    "EchoScriptDraftGenerator",
    "StubSceneTablePlanner",
    "StubStockClipPlanner",
]
