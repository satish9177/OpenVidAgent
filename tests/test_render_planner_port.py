from __future__ import annotations

import inspect
from collections.abc import Sequence
from typing import get_type_hints

from backend.app.domain import (
    DownloadedClip,
    RenderPlanSegment,
    SubtitleSegment,
    VideoAssemblySegment,
    VoiceoverSegment,
)
from backend.app.ports import Renderer, RenderPlanner


class _FakeRenderPlanner:
    def plan(
        self,
        assembly_segments: Sequence[VideoAssemblySegment],
        downloaded_clips: Sequence[DownloadedClip],
        voiceover_segments: Sequence[VoiceoverSegment],
        subtitle_segments: Sequence[SubtitleSegment],
    ) -> Sequence[RenderPlanSegment]:
        return ()


def test_fake_satisfies_render_planner_protocol() -> None:
    assert isinstance(_FakeRenderPlanner(), RenderPlanner)


def test_render_planner_resolves_from_provider_ports() -> None:
    assert inspect.getmodule(RenderPlanner).__name__ == (
        "backend.app.ports.providers"
    )


def test_render_planner_contract_uses_metadata_sequences() -> None:
    hints = get_type_hints(RenderPlanner.plan)

    assert hints["assembly_segments"] == Sequence[VideoAssemblySegment]
    assert hints["downloaded_clips"] == Sequence[DownloadedClip]
    assert hints["voiceover_segments"] == Sequence[VoiceoverSegment]
    assert hints["subtitle_segments"] == Sequence[SubtitleSegment]
    assert hints["return"] == Sequence[RenderPlanSegment]


def test_render_planner_is_distinct_from_renderer() -> None:
    assert RenderPlanner is not Renderer
    assert "plan" in RenderPlanner.__dict__
    assert "render" in Renderer.__dict__
