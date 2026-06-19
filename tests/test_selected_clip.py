from dataclasses import FrozenInstanceError

import pytest

from backend.app.domain import AssetKind, SelectedClip


def test_selected_clips_asset_kind_value() -> None:
    assert AssetKind.SELECTED_CLIPS.value == "selected_clips"


def test_selected_clip_stores_all_fields() -> None:
    selected = SelectedClip(
        scene_id="scene-1",
        query_text="modern office workspace",
        provider="stub",
        provider_clip_id="scene-1-1",
        title="Modern office workspace",
        preview_url="memory://clips/scene-1/1/preview.jpg",
        source_url="memory://clips/scene-1/1",
        duration_seconds=4.5,
        width=1920,
        height=1080,
        selection_reason="first_candidate_for_scene_query",
    )

    assert selected.scene_id == "scene-1"
    assert selected.query_text == "modern office workspace"
    assert selected.provider == "stub"
    assert selected.provider_clip_id == "scene-1-1"
    assert selected.title == "Modern office workspace"
    assert selected.preview_url == "memory://clips/scene-1/1/preview.jpg"
    assert selected.source_url == "memory://clips/scene-1/1"
    assert selected.duration_seconds == 4.5
    assert selected.width == 1920
    assert selected.height == 1080
    assert selected.selection_reason == "first_candidate_for_scene_query"


def test_selected_clip_selection_reason_is_required() -> None:
    with pytest.raises(TypeError, match="selection_reason"):
        SelectedClip(
            scene_id="scene-1",
            query_text="hands typing on laptop",
            provider="stub",
            provider_clip_id="scene-1-1",
            title="Hands typing on laptop",
            preview_url="memory://clips/scene-1/1/preview.jpg",
            source_url="memory://clips/scene-1/1",
            duration_seconds=3.0,
            width=1920,
            height=1080,
        )


def test_selected_clip_is_frozen() -> None:
    selected = SelectedClip(
        scene_id="scene-1",
        query_text="hands typing on laptop",
        provider="stub",
        provider_clip_id="scene-1-1",
        title="Hands typing on laptop",
        preview_url="memory://clips/scene-1/1/preview.jpg",
        source_url="memory://clips/scene-1/1",
        duration_seconds=3.0,
        width=1920,
        height=1080,
        selection_reason="first_candidate_for_scene_query",
    )

    with pytest.raises(FrozenInstanceError):
        selected.selection_reason = "new reason"
