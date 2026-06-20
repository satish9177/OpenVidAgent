from __future__ import annotations

import inspect
from typing import get_type_hints

from backend.app.domain import SubtitleSegment, VoiceoverSegment
from backend.app.ports import SubtitleBuilder, SubtitleComposer


class _FakeSubtitleComposer:
    def compose(
        self,
        voiceover_segment: VoiceoverSegment,
        start_seconds: float,
        language: str,
    ) -> SubtitleSegment:
        return SubtitleSegment(
            scene_id=voiceover_segment.scene_id,
            order_index=voiceover_segment.order_index,
            text=voiceover_segment.narration_text,
            language=language,
            start_seconds=start_seconds,
            end_seconds=start_seconds + voiceover_segment.duration_seconds,
            duration_seconds=voiceover_segment.duration_seconds,
            format="manifest",
            status="available",
            generation_reason="fake",
        )


def test_fake_satisfies_subtitle_composer_protocol() -> None:
    assert isinstance(_FakeSubtitleComposer(), SubtitleComposer)


def test_subtitle_composer_resolves_from_provider_ports() -> None:
    assert inspect.getmodule(SubtitleComposer).__name__ == (
        "backend.app.ports.providers"
    )


def test_subtitle_composer_contract_uses_safe_domain_types() -> None:
    hints = get_type_hints(SubtitleComposer.compose)

    assert hints["voiceover_segment"] is VoiceoverSegment
    assert hints["start_seconds"] is float
    assert hints["language"] is str
    assert hints["return"] is SubtitleSegment


def test_subtitle_composer_is_distinct_from_subtitle_builder() -> None:
    assert SubtitleComposer is not SubtitleBuilder
    assert "compose" in SubtitleComposer.__dict__
    assert "build" in SubtitleBuilder.__dict__
