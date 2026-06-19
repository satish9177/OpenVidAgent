from __future__ import annotations

import inspect
from collections.abc import Sequence
from typing import get_type_hints

from backend.app.domain import SceneSpec, SelectedClip, VideoAssemblySegment
from backend.app.ports import VideoAssemblyPlanner


class _FakeVideoAssemblyPlanner:
    def plan(
        self,
        scenes: Sequence[SceneSpec],
        selected_clips: Sequence[SelectedClip],
    ) -> Sequence[VideoAssemblySegment]:
        return ()


def test_fake_satisfies_video_assembly_planner_protocol() -> None:
    assert isinstance(_FakeVideoAssemblyPlanner(), VideoAssemblyPlanner)


def test_video_assembly_planner_resolves_from_provider_ports() -> None:
    assert inspect.getmodule(VideoAssemblyPlanner).__name__ == (
        "backend.app.ports.providers"
    )


def test_video_assembly_planner_contract_uses_safe_domain_sequences() -> None:
    hints = get_type_hints(VideoAssemblyPlanner.plan)

    assert hints["scenes"] == Sequence[SceneSpec]
    assert hints["selected_clips"] == Sequence[SelectedClip]
    assert hints["return"] == Sequence[VideoAssemblySegment]
