"""Pure deterministic video assembly planning over metadata only."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from backend.app.domain import SceneSpec, SelectedClip, VideoAssemblySegment
from backend.app.ports import VideoAssemblyPlanner


class DeterministicVideoAssemblyPlanner(VideoAssemblyPlanner):
    def plan(
        self,
        scenes: Sequence[SceneSpec],
        selected_clips: Sequence[SelectedClip],
    ) -> Sequence[VideoAssemblySegment]:
        if not scenes or not selected_clips:
            return ()

        known_scene_ids = {scene.scene_id for scene in scenes}
        unknown_scene_ids = {
            clip.scene_id
            for clip in selected_clips
            if clip.scene_id not in known_scene_ids
        }
        if unknown_scene_ids:
            unknown = ", ".join(sorted(unknown_scene_ids))
            raise ValueError(
                f"Selected clips reference unknown scene IDs: {unknown}"
            )

        clips_by_scene_id: dict[str, list[SelectedClip]] = defaultdict(list)
        for selected_clip in selected_clips:
            clips_by_scene_id[selected_clip.scene_id].append(selected_clip)

        segments: list[VideoAssemblySegment] = []
        for scene in scenes:
            scene_clips = clips_by_scene_id.get(scene.scene_id, ())
            if not scene_clips:
                continue
            target_duration = scene.duration_seconds / len(scene_clips)
            for selected_clip in scene_clips:
                segments.append(
                    _to_segment(
                        scene,
                        selected_clip,
                        target_duration=target_duration,
                        order_index=len(segments),
                    )
                )
        return tuple(segments)


def _to_segment(
    scene: SceneSpec,
    selected_clip: SelectedClip,
    *,
    target_duration: float,
    order_index: int,
) -> VideoAssemblySegment:
    return VideoAssemblySegment(
        scene_id=scene.scene_id,
        query_text=selected_clip.query_text,
        narration=scene.narration,
        visual_query=scene.visual_query,
        provider=selected_clip.provider,
        provider_clip_id=selected_clip.provider_clip_id,
        title=selected_clip.title,
        preview_url=selected_clip.preview_url,
        source_url=selected_clip.source_url,
        target_duration_seconds=target_duration,
        source_duration_seconds=selected_clip.duration_seconds,
        width=selected_clip.width,
        height=selected_clip.height,
        order_index=order_index,
        transition="cut",
        continuity_note="ordered_by_scene_table",
        selection_reason=selected_clip.selection_reason,
    )
