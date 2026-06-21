"""Deterministic metadata-only render output generator adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from backend.app.domain import RenderOutputManifest, RenderPlanSegment
from backend.app.ports import RenderOutputGenerator


class StubRenderOutputGenerator(RenderOutputGenerator):
    def generate(
        self,
        render_plan_asset_id: str,
        render_plan_version: int,
        render_plan_segments: Sequence[RenderPlanSegment],
        render_profile: Mapping[str, str],
    ) -> RenderOutputManifest:
        estimated_duration_seconds = max(
            (
                segment.visual_end_seconds
                for segment in render_plan_segments
            ),
            default=0.0,
        )
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
            estimated_duration_seconds=estimated_duration_seconds,
            output_uri=None,
            generation_reason="metadata_only_foundation",
        )
