from dataclasses import FrozenInstanceError, fields

import pytest

from backend.app.domain import AssetKind, RenderPlanSegment


EXPECTED_FIELDS = (
    "order_index",
    "scene_id",
    "clip_uri",
    "clip_provider",
    "clip_provider_id",
    "visual_start_seconds",
    "visual_end_seconds",
    "visual_duration_seconds",
    "voiceover_uri",
    "voiceover_start_seconds",
    "voiceover_end_seconds",
    "voiceover_duration_seconds",
    "subtitle_text",
    "subtitle_start_seconds",
    "subtitle_end_seconds",
    "subtitle_language",
)


def _render_plan_segment() -> RenderPlanSegment:
    return RenderPlanSegment(
        order_index=0,
        scene_id="scene-1",
        clip_uri="memory://downloads/run-1/0000/stub-scene-1-1.mp4",
        clip_provider="stub",
        clip_provider_id="scene-1-1",
        visual_start_seconds=0.0,
        visual_end_seconds=4.0,
        visual_duration_seconds=4.0,
        voiceover_uri="memory://voiceovers/run-1/0000/scene-1.mp3",
        voiceover_start_seconds=0.0,
        voiceover_end_seconds=4.0,
        voiceover_duration_seconds=4.0,
        subtitle_text="Coffee beans develop flavor while roasting.",
        subtitle_start_seconds=0.0,
        subtitle_end_seconds=4.0,
        subtitle_language="en",
    )


def test_render_plan_asset_kind_is_distinct() -> None:
    assert AssetKind.RENDER_PLAN.value == "render_plan"
    assert AssetKind.RENDER_PLAN not in {
        AssetKind.RENDER,
        AssetKind.SUBTITLE_MANIFEST,
        AssetKind.VOICEOVER,
        AssetKind.DOWNLOADED_CLIPS,
    }


def test_render_plan_segment_has_exact_metadata_fields() -> None:
    assert tuple(field.name for field in fields(RenderPlanSegment)) == (
        EXPECTED_FIELDS
    )
    assert "output_path" not in EXPECTED_FIELDS
    assert "output_video_uri" not in EXPECTED_FIELDS
    assert "ffmpeg_command" not in EXPECTED_FIELDS


def test_render_plan_segment_is_frozen() -> None:
    segment = _render_plan_segment()

    with pytest.raises(FrozenInstanceError):
        segment.visual_end_seconds = 5.0
