from dataclasses import FrozenInstanceError, fields

import pytest

from backend.app.domain import AssetKind, VoiceoverSegment


EXPECTED_FIELDS = (
    "scene_id",
    "order_index",
    "narration_text",
    "language",
    "voice_id",
    "provider",
    "audio_uri",
    "content_type",
    "duration_seconds",
    "status",
    "generation_reason",
)


def _voiceover_segment() -> VoiceoverSegment:
    return VoiceoverSegment(
        scene_id="scene-1",
        order_index=0,
        narration_text="Coffee beans develop flavor while roasting.",
        language="en",
        voice_id="stub-narrator",
        provider="stub",
        audio_uri="memory://voiceovers/run-1/0000/scene-1.mp3",
        content_type="audio/mpeg",
        duration_seconds=4.0,
        status="available",
        generation_reason="deterministic_placeholder",
    )


def test_voiceover_asset_kind_is_distinct() -> None:
    assert AssetKind.VOICEOVER.value == "voiceover"
    assert AssetKind.VOICEOVER not in {
        AssetKind.VOICE,
        AssetKind.DOWNLOADED_CLIPS,
        AssetKind.VIDEO_ASSEMBLY_PLAN,
        AssetKind.SUBTITLE,
        AssetKind.RENDER,
    }


def test_voiceover_segment_has_exact_expected_fields() -> None:
    assert tuple(field.name for field in fields(VoiceoverSegment)) == (
        EXPECTED_FIELDS
    )
    assert "audio_path" not in EXPECTED_FIELDS


def test_voiceover_segment_is_frozen() -> None:
    segment = _voiceover_segment()

    with pytest.raises(FrozenInstanceError):
        segment.audio_uri = "memory://voiceovers/other.mp3"
