from dataclasses import FrozenInstanceError, fields

import pytest

from backend.app.domain import AssetKind, RenderOutputManifest, RunStatus


EXPECTED_FIELDS = (
    "status",
    "render_plan_asset_id",
    "render_plan_version",
    "render_intent",
    "aspect_ratio",
    "container",
    "resolution_width",
    "resolution_height",
    "fps",
    "segment_count",
    "estimated_duration_seconds",
    "output_uri",
    "generation_reason",
)


def _manifest() -> RenderOutputManifest:
    return RenderOutputManifest(
        status="not_rendered",
        render_plan_asset_id="render-plan-1",
        render_plan_version=1,
        render_intent="voiceover_b_roll",
        aspect_ratio="16:9",
        container="mp4",
        resolution_width=1920,
        resolution_height=1080,
        fps=30.0,
        segment_count=2,
        estimated_duration_seconds=8.0,
        output_uri=None,
        generation_reason="metadata_only_foundation",
    )


def test_render_output_asset_kind_is_distinct() -> None:
    assert AssetKind.RENDER_OUTPUT.value == "render_output"
    assert AssetKind.RENDER_OUTPUT not in {
        AssetKind.RENDER_PLAN,
        AssetKind.RENDER,
    }
    assert RunStatus.RENDERED.value == "rendered"


def test_render_output_manifest_has_exact_metadata_fields() -> None:
    assert tuple(field.name for field in fields(RenderOutputManifest)) == (
        EXPECTED_FIELDS
    )
    for forbidden in (
        "output_path",
        "ffmpeg_command",
        "checksum",
        "file_size",
        "media_bytes",
    ):
        assert forbidden not in EXPECTED_FIELDS


def test_render_output_manifest_is_frozen_and_uri_can_be_none() -> None:
    manifest = _manifest()

    assert manifest.output_uri is None
    with pytest.raises(FrozenInstanceError):
        manifest.status = "available"
