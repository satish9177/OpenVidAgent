from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from typing import get_type_hints

from backend.app.domain import RenderOutputManifest, RenderPlanSegment
from backend.app.ports import Renderer, RenderOutputGenerator


class _FakeRenderOutputGenerator:
    def generate(
        self,
        render_plan_asset_id: str,
        render_plan_version: int,
        render_plan_segments: Sequence[RenderPlanSegment],
        render_profile: Mapping[str, str],
    ) -> RenderOutputManifest:
        return RenderOutputManifest(
            status="not_rendered",
            render_plan_asset_id=render_plan_asset_id,
            render_plan_version=render_plan_version,
            render_intent=render_profile["render_intent"],
            aspect_ratio=render_profile["aspect_ratio"],
            container=render_profile["container"],
            resolution_width=int(render_profile["resolution_width"]),
            resolution_height=int(render_profile["resolution_height"]),
            fps=float(render_profile["fps"]),
            segment_count=len(render_plan_segments),
            estimated_duration_seconds=0.0,
            output_uri=None,
            generation_reason="fake",
        )


def test_fake_satisfies_render_output_generator_protocol() -> None:
    assert isinstance(_FakeRenderOutputGenerator(), RenderOutputGenerator)


def test_render_output_generator_resolves_from_provider_ports() -> None:
    assert inspect.getmodule(RenderOutputGenerator).__name__ == (
        "backend.app.ports.providers"
    )


def test_render_output_generator_contract_uses_safe_types() -> None:
    hints = get_type_hints(RenderOutputGenerator.generate)

    assert hints["render_plan_asset_id"] is str
    assert hints["render_plan_version"] is int
    assert hints["render_plan_segments"] == Sequence[RenderPlanSegment]
    assert hints["render_profile"] == Mapping[str, str]
    assert hints["return"] is RenderOutputManifest


def test_render_output_generator_is_distinct_from_renderer() -> None:
    assert RenderOutputGenerator is not Renderer
    assert "generate" in RenderOutputGenerator.__dict__
    assert "render" in Renderer.__dict__
