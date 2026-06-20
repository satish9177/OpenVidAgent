"""Deterministic metadata-only voiceover generator adapter."""

from __future__ import annotations

from backend.app.domain import VideoAssemblySegment, VoiceoverSegment
from backend.app.ports import VoiceoverGenerator


class StubVoiceoverGenerator(VoiceoverGenerator):
    def generate(
        self,
        run_id: str,
        segment: VideoAssemblySegment,
        language: str,
    ) -> VoiceoverSegment:
        safe_run_id = _safe_component(run_id, "run_id")
        safe_scene_id = _safe_component(segment.scene_id, "scene_id")
        resolved_language = language or "en"
        return VoiceoverSegment(
            scene_id=segment.scene_id,
            order_index=segment.order_index,
            narration_text=segment.narration,
            language=resolved_language,
            voice_id="stub-narrator",
            provider="stub",
            audio_uri=(
                f"memory://voiceovers/{safe_run_id}/{segment.order_index:04d}/"
                f"{safe_scene_id}.mp3"
            ),
            content_type="audio/mpeg",
            duration_seconds=segment.target_duration_seconds,
            status="available",
            generation_reason="deterministic_placeholder",
        )


def _safe_component(value: str, name: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or ":" in value
        or "\x00" in value
    ):
        raise ValueError(f"{name} must be a safe URI path component")
    return value
