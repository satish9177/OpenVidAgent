from dataclasses import FrozenInstanceError, fields

import pytest

from backend.app.domain import AssetKind, DownloadedClip


EXPECTED_FIELDS = (
    "scene_id",
    "query_text",
    "provider",
    "provider_clip_id",
    "title",
    "source_url",
    "local_uri",
    "content_type",
    "duration_seconds",
    "width",
    "height",
    "order_index",
    "download_status",
    "download_reason",
)


def _downloaded_clip() -> DownloadedClip:
    return DownloadedClip(
        scene_id="scene-1",
        query_text="coffee beans roasting",
        provider="stub",
        provider_clip_id="scene-1-1",
        title="Coffee beans roasting",
        source_url="memory://clips/scene-1/1",
        local_uri="memory://downloads/run-1/0000/stub-scene-1-1.mp4",
        content_type="video/mp4",
        duration_seconds=4.5,
        width=1920,
        height=1080,
        order_index=0,
        download_status="available",
        download_reason="deterministic_placeholder",
    )


def test_downloaded_clips_asset_kind_is_distinct() -> None:
    assert AssetKind.DOWNLOADED_CLIPS.value == "downloaded_clips"
    assert AssetKind.DOWNLOADED_CLIPS not in {
        AssetKind.SELECTED_CLIPS,
        AssetKind.VIDEO_ASSEMBLY_PLAN,
        AssetKind.STOCK_CLIP,
        AssetKind.RENDER,
    }


def test_downloaded_clip_has_exact_expected_fields() -> None:
    assert tuple(field.name for field in fields(DownloadedClip)) == EXPECTED_FIELDS
    assert "local_path" not in EXPECTED_FIELDS


def test_downloaded_clip_is_frozen() -> None:
    downloaded_clip = _downloaded_clip()

    with pytest.raises(FrozenInstanceError):
        downloaded_clip.local_uri = "memory://downloads/other.mp4"
