"""Deterministic metadata-only render planner adapter."""

from __future__ import annotations

from collections.abc import Sequence

from backend.app.domain import (
    DownloadedClip,
    RenderPlanSegment,
    SubtitleSegment,
    VideoAssemblySegment,
    VoiceoverSegment,
)
from backend.app.ports import RenderPlanner


class StubRenderPlanner(RenderPlanner):
    def plan(
        self,
        assembly_segments: Sequence[VideoAssemblySegment],
        downloaded_clips: Sequence[DownloadedClip],
        voiceover_segments: Sequence[VoiceoverSegment],
        subtitle_segments: Sequence[SubtitleSegment],
    ) -> Sequence[RenderPlanSegment]:
        downloaded_by_order = {
            clip.order_index: clip for clip in downloaded_clips
        }
        voiceover_by_order = {
            segment.order_index: segment for segment in voiceover_segments
        }
        subtitles_by_order = {
            segment.order_index: segment for segment in subtitle_segments
        }

        # Two independent cursors: the visual timeline folds from assembly
        # target durations, the voiceover timeline folds from narration
        # durations. They coincide only when narration length matches the
        # visual slot; keeping them separate lets a divergent narration be
        # expressed without reshaping the manifest. Assembly segments are
        # defensively sorted by order_index so the folds stay correct even if
        # the spine arrives out of order (mirrors GenerateSubtitles).
        visual_start_seconds = 0.0
        voiceover_start_seconds = 0.0
        planned: list[RenderPlanSegment] = []
        for assembly_segment in sorted(
            assembly_segments, key=lambda segment: segment.order_index
        ):
            order_index = assembly_segment.order_index
            downloaded_clip = downloaded_by_order[order_index]
            voiceover_segment = voiceover_by_order[order_index]
            subtitle_segment = subtitles_by_order[order_index]
            visual_duration_seconds = assembly_segment.target_duration_seconds
            visual_end_seconds = visual_start_seconds + visual_duration_seconds
            voiceover_duration_seconds = voiceover_segment.duration_seconds
            voiceover_end_seconds = (
                voiceover_start_seconds + voiceover_duration_seconds
            )
            planned.append(
                RenderPlanSegment(
                    order_index=order_index,
                    scene_id=assembly_segment.scene_id,
                    clip_uri=downloaded_clip.local_uri,
                    clip_provider=downloaded_clip.provider,
                    clip_provider_id=downloaded_clip.provider_clip_id,
                    visual_start_seconds=visual_start_seconds,
                    visual_end_seconds=visual_end_seconds,
                    visual_duration_seconds=visual_duration_seconds,
                    voiceover_uri=voiceover_segment.audio_uri,
                    voiceover_start_seconds=voiceover_start_seconds,
                    voiceover_end_seconds=voiceover_end_seconds,
                    voiceover_duration_seconds=voiceover_duration_seconds,
                    subtitle_text=subtitle_segment.text,
                    subtitle_start_seconds=subtitle_segment.start_seconds,
                    subtitle_end_seconds=subtitle_segment.end_seconds,
                    subtitle_language=subtitle_segment.language,
                )
            )
            visual_start_seconds = visual_end_seconds
            voiceover_start_seconds = voiceover_end_seconds
        return tuple(planned)
