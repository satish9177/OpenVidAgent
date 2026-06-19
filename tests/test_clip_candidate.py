from dataclasses import FrozenInstanceError

import pytest

from backend.app.domain import AssetKind, ClipCandidate


def test_clip_candidates_asset_kind_value() -> None:
    assert AssetKind.CLIP_CANDIDATES.value == "clip_candidates"


def test_clip_candidate_stores_all_fields() -> None:
    candidate = ClipCandidate(
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
    )

    assert candidate.scene_id == "scene-1"
    assert candidate.query_text == "modern office workspace"
    assert candidate.provider == "stub"
    assert candidate.provider_clip_id == "scene-1-1"
    assert candidate.title == "Modern office workspace"
    assert candidate.preview_url == "memory://clips/scene-1/1/preview.jpg"
    assert candidate.source_url == "memory://clips/scene-1/1"
    assert candidate.duration_seconds == 4.5
    assert candidate.width == 1920
    assert candidate.height == 1080


def test_clip_candidate_is_frozen() -> None:
    candidate = ClipCandidate(
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

    with pytest.raises(FrozenInstanceError):
        candidate.title = "New title"
