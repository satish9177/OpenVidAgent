from dataclasses import FrozenInstanceError, fields

import pytest

from backend.app.domain import (
    AssetKind,
    RenderInputReadiness,
    RenderReadinessReport,
)


INPUT_FIELDS = (
    "order_index",
    "scene_id",
    "role",
    "uri",
    "scheme",
    "required",
    "status",
    "blocker_reason",
)
REPORT_FIELDS = (
    "status",
    "render_plan_asset_id",
    "render_plan_version",
    "render_output_asset_id",
    "render_output_version",
    "ffmpeg_availability",
    "segment_count",
    "materialized_required_count",
    "total_required_count",
    "inputs",
    "blocker_summary",
    "warnings",
    "generation_reason",
)


def _input() -> RenderInputReadiness:
    return RenderInputReadiness(
        order_index=0,
        scene_id="scene-1",
        role="clip",
        uri="memory://clips/clip-1.mp4",
        scheme="memory",
        required=True,
        status="placeholder",
        blocker_reason="clip_not_materialized",
    )


def _report() -> RenderReadinessReport:
    return RenderReadinessReport(
        status="blocked",
        render_plan_asset_id="render-plan-1",
        render_plan_version=1,
        render_output_asset_id=None,
        render_output_version=None,
        ffmpeg_availability="not_checked",
        segment_count=1,
        materialized_required_count=0,
        total_required_count=2,
        inputs=(_input(),),
        blocker_summary=("clip_not_materialized",),
        warnings=("subtitle_manifest_only",),
        generation_reason="scheme_classification_only",
    )


def test_render_readiness_asset_kind_is_distinct() -> None:
    assert AssetKind.RENDER_READINESS.value == "render_readiness"
    assert AssetKind.RENDER_READINESS not in {
        AssetKind.RENDER_PLAN,
        AssetKind.RENDER_OUTPUT,
        AssetKind.RENDER,
    }


def test_render_readiness_models_have_exact_fields() -> None:
    assert tuple(field.name for field in fields(RenderInputReadiness)) == (
        INPUT_FIELDS
    )
    assert tuple(field.name for field in fields(RenderReadinessReport)) == (
        REPORT_FIELDS
    )
    for forbidden in (
        "output_path",
        "video_file",
        "ffmpeg_command",
        "probe_result_path",
        "run_status",
        "status_transition",
    ):
        assert forbidden not in INPUT_FIELDS
        assert forbidden not in REPORT_FIELDS


def test_render_readiness_models_are_frozen_with_string_statuses() -> None:
    readiness_input = _input()
    report = _report()

    assert isinstance(readiness_input.status, str)
    assert readiness_input.required is True
    assert isinstance(report.status, str)
    assert report.render_output_asset_id is None
    assert report.render_output_version is None
    with pytest.raises(FrozenInstanceError):
        readiness_input.status = "materialized"
    with pytest.raises(FrozenInstanceError):
        report.status = "ready"
