"""Deterministic local generation adapters (no external calls)."""

from backend.app.infrastructure.generation.echo_script_draft_generator import (
    EchoScriptDraftGenerator,
)
from backend.app.infrastructure.generation.stub_scene_table_planner import (
    StubSceneTablePlanner,
)

__all__ = [
    "EchoScriptDraftGenerator",
    "StubSceneTablePlanner",
]
