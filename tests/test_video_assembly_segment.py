from dataclasses import FrozenInstanceError, fields

import pytest

from backend.app.domain import AssetKind, VideoAssemblySegment


EXPECTED_FIELDS = (
    "scene_id",
    "query_text",
    "narration",
    "visual_query",
    "provider",
    "provider_clip_id",
    "title",
    "preview_url",
    "source_url",
    "target_duration_seconds",
    "source_duration_seconds",
    "width",
    "height",
    "order_index",
    "transition",
    "continuity_note",
    "selection_reason",
)


def _segment() -> VideoAssemblySegment:
    return VideoAssemblySegment(
        scene_id="scene-1",
        query_text="hands typing on laptop",
        narration="A focused team turns an idea into a product.",
        visual_query="modern software team at work",
        provider="stub",
        provider_clip_id="scene-1-1",
        title="Hands typing on laptop",
        preview_url="memory://clips/scene-1/1/preview.jpg",
        source_url="memory://clips/scene-1/1",
        target_duration_seconds=4.0,
        source_duration_seconds=7.5,
        width=1920,
        height=1080,
        order_index=0,
        transition="cut",
        continuity_note="ordered_by_scene_table",
        selection_reason="first_candidate_for_scene_query",
    )


def test_video_assembly_plan_asset_kind_is_distinct() -> None:
    assert AssetKind.VIDEO_ASSEMBLY_PLAN.value == "video_assembly_plan"
    assert AssetKind.VIDEO_ASSEMBLY_PLAN not in {
        AssetKind.SELECTED_CLIPS,
        AssetKind.STOCK_CLIP,
        AssetKind.RENDER,
    }


def test_video_assembly_segment_has_exact_expected_fields() -> None:
    assert tuple(field.name for field in fields(VideoAssemblySegment)) == (
        EXPECTED_FIELDS
    )


def test_video_assembly_segment_is_frozen() -> None:
    segment = _segment()

    with pytest.raises(FrozenInstanceError):
        segment.order_index = 1
