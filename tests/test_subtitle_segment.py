from dataclasses import FrozenInstanceError, fields

import pytest

from backend.app.domain import AssetKind, SubtitleSegment


EXPECTED_FIELDS = (
    "scene_id",
    "order_index",
    "text",
    "language",
    "start_seconds",
    "end_seconds",
    "duration_seconds",
    "format",
    "status",
    "generation_reason",
)


def _subtitle_segment() -> SubtitleSegment:
    return SubtitleSegment(
        scene_id="scene-1",
        order_index=0,
        text="Coffee beans develop flavor while roasting.",
        language="en",
        start_seconds=0.0,
        end_seconds=4.0,
        duration_seconds=4.0,
        format="manifest",
        status="available",
        generation_reason="deterministic_placeholder",
    )


def test_subtitle_manifest_asset_kind_is_distinct() -> None:
    assert AssetKind.SUBTITLE_MANIFEST.value == "subtitle_manifest"
    assert AssetKind.SUBTITLE_MANIFEST not in {
        AssetKind.SUBTITLE,
        AssetKind.VOICEOVER,
        AssetKind.VOICE,
        AssetKind.RENDER,
    }


def test_subtitle_segment_has_exact_expected_fields_without_uri() -> None:
    assert tuple(field.name for field in fields(SubtitleSegment)) == (
        EXPECTED_FIELDS
    )
    assert "subtitle_uri" not in EXPECTED_FIELDS


def test_subtitle_segment_is_frozen() -> None:
    segment = _subtitle_segment()

    with pytest.raises(FrozenInstanceError):
        segment.end_seconds = 5.0
