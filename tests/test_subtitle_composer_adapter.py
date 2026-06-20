from __future__ import annotations

from backend.app.domain import SubtitleSegment, VoiceoverSegment
from backend.app.infrastructure.generation import StubSubtitleComposer
from backend.app.ports import SubtitleComposer
from tests.fakes import FakeSubtitleComposer


def _voiceover_segment() -> VoiceoverSegment:
    return VoiceoverSegment(
        scene_id="scene-2",
        order_index=1,
        narration_text="The finished roast is ready to brew.",
        language="en",
        voice_id="stub-narrator",
        provider="stub",
        audio_uri="memory://voiceovers/run-1/0001/scene-2.mp3",
        content_type="audio/mpeg",
        duration_seconds=3.75,
        status="available",
        generation_reason="deterministic_placeholder",
    )


def test_stub_composer_satisfies_port_and_is_repeatable() -> None:
    composer = StubSubtitleComposer()
    voiceover_segment = _voiceover_segment()

    assert isinstance(composer, SubtitleComposer)
    assert composer.compose(voiceover_segment, 4.25, "te") == composer.compose(
        voiceover_segment, 4.25, "te"
    )


def test_stub_composer_maps_text_timing_language_and_placeholder_fields() -> None:
    subtitle = StubSubtitleComposer().compose(
        _voiceover_segment(), 4.25, "te"
    )

    assert subtitle == SubtitleSegment(
        scene_id="scene-2",
        order_index=1,
        text="The finished roast is ready to brew.",
        language="te",
        start_seconds=4.25,
        end_seconds=8.0,
        duration_seconds=3.75,
        format="manifest",
        status="available",
        generation_reason="deterministic_placeholder",
    )
    assert not hasattr(subtitle, "subtitle_uri")


def test_fake_composer_records_call_and_returns_configured_segment() -> None:
    configured = StubSubtitleComposer().compose(
        _voiceover_segment(), 0.0, "en"
    )
    fake = FakeSubtitleComposer((configured,))

    assert fake.compose(_voiceover_segment(), 2.5, "te") == configured
    assert fake.calls == [(_voiceover_segment(), 2.5, "te")]
