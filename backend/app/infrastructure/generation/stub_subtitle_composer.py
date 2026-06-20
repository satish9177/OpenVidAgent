"""Deterministic metadata-only subtitle composer adapter."""

from __future__ import annotations

from backend.app.domain import SubtitleSegment, VoiceoverSegment
from backend.app.ports import SubtitleComposer


class StubSubtitleComposer(SubtitleComposer):
    def compose(
        self,
        voiceover_segment: VoiceoverSegment,
        start_seconds: float,
        language: str,
    ) -> SubtitleSegment:
        duration_seconds = voiceover_segment.duration_seconds
        return SubtitleSegment(
            scene_id=voiceover_segment.scene_id,
            order_index=voiceover_segment.order_index,
            text=voiceover_segment.narration_text,
            language=language,
            start_seconds=start_seconds,
            end_seconds=start_seconds + duration_seconds,
            duration_seconds=duration_seconds,
            format="manifest",
            status="available",
            generation_reason="deterministic_placeholder",
        )
