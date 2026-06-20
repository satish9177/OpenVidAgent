from __future__ import annotations

from dataclasses import replace

import pytest

from backend.app.domain import VideoAssemblySegment, VoiceoverSegment
from backend.app.infrastructure.generation import StubVoiceoverGenerator
from backend.app.ports import VoiceoverGenerator
from tests.fakes import FakeVoiceoverGenerator


def _segment() -> VideoAssemblySegment:
    return VideoAssemblySegment(
        scene_id="scene-1",
        query_text="coffee beans roasting",
        narration="Coffee beans develop flavor while roasting.",
        visual_query="close-up coffee roasting",
        provider="stub",
        provider_clip_id="scene-1-1",
        title="Coffee beans roasting",
        preview_url="memory://clips/scene-1/1/preview.jpg",
        source_url="memory://clips/scene-1/1",
        target_duration_seconds=4.25,
        source_duration_seconds=7.5,
        width=1920,
        height=1080,
        order_index=2,
        transition="cut",
        continuity_note="ordered_by_scene_table",
        selection_reason="first_candidate_for_scene_query",
    )


def test_stub_generator_satisfies_port_and_is_repeatable() -> None:
    generator = StubVoiceoverGenerator()
    segment = _segment()

    assert isinstance(generator, VoiceoverGenerator)
    assert generator.generate("run-1", segment, "te") == generator.generate(
        "run-1", segment, "te"
    )


def test_stub_generator_maps_segment_to_voiceover_metadata() -> None:
    voiceover = StubVoiceoverGenerator().generate("run-1", _segment(), "te")

    assert voiceover == VoiceoverSegment(
        scene_id="scene-1",
        order_index=2,
        narration_text="Coffee beans develop flavor while roasting.",
        language="te",
        voice_id="stub-narrator",
        provider="stub",
        audio_uri="memory://voiceovers/run-1/0002/scene-1.mp3",
        content_type="audio/mpeg",
        duration_seconds=4.25,
        status="available",
        generation_reason="deterministic_placeholder",
    )
    assert not hasattr(voiceover, "audio_path")


def test_stub_generator_empty_language_falls_back_to_english() -> None:
    voiceover = StubVoiceoverGenerator().generate("run-1", _segment(), "")

    assert voiceover.language == "en"


@pytest.mark.parametrize(
    "bad_value",
    ["", ".", "..", "nested/value", "nested\\value", "C:drive", "bad\x00id"],
)
@pytest.mark.parametrize("component", ["run_id", "scene_id"])
def test_stub_generator_rejects_unsafe_uri_components(
    component: str, bad_value: str
) -> None:
    segment = _segment()
    run_id = "run-1"
    if component == "run_id":
        run_id = bad_value
    else:
        segment = replace(segment, scene_id=bad_value)

    with pytest.raises(ValueError, match=component):
        StubVoiceoverGenerator().generate(run_id, segment, "en")


def test_fake_generator_records_calls_and_returns_configured_segment() -> None:
    configured = StubVoiceoverGenerator().generate("configured", _segment(), "en")
    fake = FakeVoiceoverGenerator((configured,))

    assert fake.generate("run-1", _segment(), "te") == configured
    assert fake.calls == [("run-1", _segment(), "te")]
