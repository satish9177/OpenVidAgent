from __future__ import annotations

import inspect
from typing import get_type_hints

from backend.app.domain import VideoAssemblySegment, VoiceoverSegment
from backend.app.ports import TTSProvider, VoiceoverGenerator


class _FakeVoiceoverGenerator:
    def generate(
        self,
        run_id: str,
        segment: VideoAssemblySegment,
        language: str,
    ) -> VoiceoverSegment:
        return VoiceoverSegment(
            scene_id=segment.scene_id,
            order_index=segment.order_index,
            narration_text=segment.narration,
            language=language,
            voice_id="fake-narrator",
            provider="fake",
            audio_uri=f"memory://voiceovers/{run_id}/voice.mp3",
            content_type="audio/mpeg",
            duration_seconds=segment.target_duration_seconds,
            status="available",
            generation_reason="fake",
        )


def test_fake_satisfies_voiceover_generator_protocol() -> None:
    assert isinstance(_FakeVoiceoverGenerator(), VoiceoverGenerator)


def test_voiceover_generator_resolves_from_provider_ports() -> None:
    assert inspect.getmodule(VoiceoverGenerator).__name__ == (
        "backend.app.ports.providers"
    )


def test_voiceover_generator_contract_uses_safe_domain_types() -> None:
    hints = get_type_hints(VoiceoverGenerator.generate)

    assert hints["run_id"] is str
    assert hints["segment"] is VideoAssemblySegment
    assert hints["language"] is str
    assert hints["return"] is VoiceoverSegment


def test_voiceover_generator_is_distinct_from_tts_provider() -> None:
    assert VoiceoverGenerator is not TTSProvider
    assert "generate" in VoiceoverGenerator.__dict__
    assert "synthesize" in TTSProvider.__dict__
