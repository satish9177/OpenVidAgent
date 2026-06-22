"""Deterministic scheme-only render-readiness classifier."""

from __future__ import annotations

from collections.abc import Sequence

from backend.app.domain import (
    RenderInputReadiness,
    RenderOutputManifest,
    RenderPlanSegment,
    RenderReadinessReport,
)
from backend.app.ports import RenderReadinessChecker


class StubRenderReadinessChecker(RenderReadinessChecker):
    def check(
        self,
        render_plan_asset_id: str,
        render_plan_version: int,
        render_plan_segments: Sequence[RenderPlanSegment],
        render_output: RenderOutputManifest | None,
        ffmpeg_availability: str,
    ) -> RenderReadinessReport:
        inputs: list[RenderInputReadiness] = []
        blockers: list[str] = []
        warnings: list[str] = []

        for segment in render_plan_segments:
            clip = _classify_required(
                segment.order_index,
                segment.scene_id,
                "clip",
                segment.clip_uri,
            )
            voiceover = _classify_required(
                segment.order_index,
                segment.scene_id,
                "voiceover",
                segment.voiceover_uri,
            )
            subtitle = RenderInputReadiness(
                order_index=segment.order_index,
                scene_id=segment.scene_id,
                role="subtitle",
                uri=segment.subtitle_text,
                scheme="inline",
                required=False,
                status="placeholder",
                blocker_reason="subtitle_manifest_only",
            )
            inputs.extend((clip, voiceover, subtitle))
            for item in (clip, voiceover):
                if item.blocker_reason is not None:
                    _append_unique(blockers, item.blocker_reason)
            _append_unique(warnings, "subtitle_manifest_only")

        if render_output is None or render_output.output_uri is None:
            _append_unique(warnings, "render_output_not_available")
        if ffmpeg_availability == "missing":
            _append_unique(blockers, "ffmpeg_unavailable")

        required_inputs = tuple(item for item in inputs if item.required)
        materialized_required_count = sum(
            item.status == "materialized" for item in required_inputs
        )
        total_required_count = len(required_inputs)
        status = (
            "ready"
            if materialized_required_count == total_required_count
            and ffmpeg_availability != "missing"
            else "blocked"
        )
        return RenderReadinessReport(
            status=status,
            render_plan_asset_id=render_plan_asset_id,
            render_plan_version=render_plan_version,
            render_output_asset_id=None,
            render_output_version=None,
            ffmpeg_availability=ffmpeg_availability,
            segment_count=len(render_plan_segments),
            materialized_required_count=materialized_required_count,
            total_required_count=total_required_count,
            inputs=tuple(inputs),
            blocker_summary=tuple(blockers),
            warnings=tuple(warnings),
            generation_reason="scheme_classification_only",
        )


def _classify_required(
    order_index: int,
    scene_id: str,
    role: str,
    reference: str,
) -> RenderInputReadiness:
    normalized = reference.strip()
    if not normalized:
        return RenderInputReadiness(
            order_index=order_index,
            scene_id=scene_id,
            role=role,
            uri=reference,
            scheme="missing",
            required=True,
            status="missing",
            blocker_reason=f"{role}_missing",
        )

    scheme = _reference_scheme(normalized)
    if scheme in {"file", "relative"}:
        status = "materialized"
        blocker_reason = None
    else:
        status = "placeholder"
        blocker_reason = f"{role}_not_materialized"
    return RenderInputReadiness(
        order_index=order_index,
        scene_id=scene_id,
        role=role,
        uri=reference,
        scheme=scheme,
        required=True,
        status=status,
        blocker_reason=blocker_reason,
    )


def _reference_scheme(reference: str) -> str:
    lowered = reference.lower()
    if lowered.startswith("file:"):
        return "file"
    if "://" in lowered:
        return lowered.split("://", maxsplit=1)[0]
    if reference.startswith(("/", "\\")):
        return "file"
    if len(reference) >= 2 and reference[1] == ":":
        return "file"
    return "relative"


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)
