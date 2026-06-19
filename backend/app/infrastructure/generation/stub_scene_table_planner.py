"""Deterministic local scene-table adapter.

A composition-root default that splits an approved script into a small, stable
set of scenes without any randomness, network, provider SDK, or subprocess. The
approved script and language are echoed into each ``SceneSpec`` so output is
reproducible and the inputs are observable. A real planner can replace it later
behind the same port.
"""

from __future__ import annotations

from collections.abc import Sequence

from backend.app.domain import SceneSpec
from backend.app.ports import SceneTablePlanner

# Keep the stub scene table small and deterministic.
_MAX_SCENES = 3


class StubSceneTablePlanner(SceneTablePlanner):
    def plan(self, approved_script: str, language: str) -> Sequence[SceneSpec]:
        return tuple(
            SceneSpec(
                scene_id=f"scene-{index}",
                narration=segment,
                visual_query=f"{language} stock footage for: {segment}",
                duration_seconds=float(max(1, len(segment.split()))),
            )
            for index, segment in enumerate(_segments(approved_script), start=1)
        )


def _segments(approved_script: str) -> tuple[str, ...]:
    """Split the script into a small, deterministic, non-empty set of segments."""
    lines = tuple(
        line.strip() for line in approved_script.splitlines() if line.strip()
    )
    if lines:
        return lines[:_MAX_SCENES]
    text = approved_script.strip()
    return (text,) if text else ("scene",)
