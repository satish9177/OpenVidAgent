from __future__ import annotations

from backend.app.domain import (
    DownloadedClip,
    RenderPlanSegment,
    SubtitleSegment,
    VideoAssemblySegment,
    VoiceoverSegment,
)
from backend.app.infrastructure.generation import StubRenderPlanner
from backend.app.ports import RenderPlanner
from tests.fakes import FakeRenderPlanner


def _assembly(order_index: int, duration: float) -> VideoAssemblySegment:
    return VideoAssemblySegment(
        scene_id=f"scene-{order_index}",
        query_text=f"query {order_index}",
        narration=f"Narration {order_index}",
        visual_query=f"Visual {order_index}",
        provider="stub",
        provider_clip_id=f"clip-{order_index}",
        title=f"Clip {order_index}",
        preview_url=f"memory://clips/{order_index}/preview.jpg",
        source_url=f"memory://clips/{order_index}",
        target_duration_seconds=duration,
        source_duration_seconds=duration + 2.0,
        width=1920,
        height=1080,
        order_index=order_index,
        transition="cut",
        continuity_note="ordered_by_scene_table",
        selection_reason="first_candidate_for_scene_query",
    )


def _downloaded(order_index: int) -> DownloadedClip:
    return DownloadedClip(
        scene_id=f"scene-{order_index}",
        query_text=f"query {order_index}",
        provider=f"provider-{order_index}",
        provider_clip_id=f"clip-{order_index}",
        title=f"Clip {order_index}",
        source_url=f"memory://clips/{order_index}",
        local_uri=f"memory://downloads/run-1/{order_index:04d}/clip.mp4",
        content_type="video/mp4",
        duration_seconds=8.0,
        width=1920,
        height=1080,
        order_index=order_index,
        download_status="available",
        download_reason="deterministic_placeholder",
    )


def _voiceover(order_index: int, duration: float) -> VoiceoverSegment:
    return VoiceoverSegment(
        scene_id=f"scene-{order_index}",
        order_index=order_index,
        narration_text=f"Narration {order_index}",
        language="en",
        voice_id="stub-narrator",
        provider="stub",
        audio_uri=f"memory://voiceovers/run-1/{order_index:04d}/scene.mp3",
        content_type="audio/mpeg",
        duration_seconds=duration,
        status="available",
        generation_reason="deterministic_placeholder",
    )


def _subtitle(
    order_index: int, start: float, duration: float
) -> SubtitleSegment:
    return SubtitleSegment(
        scene_id=f"scene-{order_index}",
        order_index=order_index,
        text=f"Narration {order_index}",
        language="en",
        start_seconds=start,
        end_seconds=start + duration,
        duration_seconds=duration,
        format="manifest",
        status="available",
        generation_reason="deterministic_placeholder",
    )


def test_stub_planner_satisfies_port_and_is_repeatable() -> None:
    planner = StubRenderPlanner()
    inputs = (
        (_assembly(0, 4.0),),
        (_downloaded(0),),
        (_voiceover(0, 4.0),),
        (_subtitle(0, 0.0, 4.0),),
    )

    assert isinstance(planner, RenderPlanner)
    assert planner.plan(*inputs) == planner.plan(*inputs)


def test_stub_planner_sorts_by_order_index_and_joins_by_index_not_position() -> None:
    planned = StubRenderPlanner().plan(
        (_assembly(1, 3.0), _assembly(0, 4.0)),
        (_downloaded(0), _downloaded(1)),
        (_voiceover(0, 4.0), _voiceover(1, 3.0)),
        (_subtitle(0, 0.0, 4.0), _subtitle(1, 4.0, 3.0)),
    )

    # Out-of-order assembly input is defensively sorted to ascending order_index.
    assert [segment.order_index for segment in planned] == [0, 1]
    assert planned[0] == RenderPlanSegment(
        order_index=0,
        scene_id="scene-0",
        clip_uri="memory://downloads/run-1/0000/clip.mp4",
        clip_provider="provider-0",
        clip_provider_id="clip-0",
        visual_start_seconds=0.0,
        visual_end_seconds=4.0,
        visual_duration_seconds=4.0,
        voiceover_uri="memory://voiceovers/run-1/0000/scene.mp3",
        voiceover_start_seconds=0.0,
        voiceover_end_seconds=4.0,
        voiceover_duration_seconds=4.0,
        subtitle_text="Narration 0",
        subtitle_start_seconds=0.0,
        subtitle_end_seconds=4.0,
        subtitle_language="en",
    )
    # Clips/voiceover/subtitles join by order_index, never by list position:
    # the order-1 row carries order-1 data though assembly supplied it first.
    assert planned[1].order_index == 1
    assert planned[1].scene_id == "scene-1"
    assert planned[1].clip_provider == "provider-1"
    assert planned[1].clip_provider_id == "clip-1"
    assert planned[1].clip_uri == "memory://downloads/run-1/0001/clip.mp4"
    assert planned[1].voiceover_uri == "memory://voiceovers/run-1/0001/scene.mp3"
    assert planned[1].visual_start_seconds == 4.0
    assert planned[1].visual_end_seconds == 7.0
    assert planned[1].subtitle_start_seconds == 4.0
    assert planned[1].subtitle_end_seconds == 7.0
    assert not hasattr(planned[0], "output_path")
    assert not hasattr(planned[0], "ffmpeg_command")


def test_stub_planner_folds_voiceover_window_independently_of_visual() -> None:
    # Narration durations (6.0, 1.0) diverge from the visual slots (4.0, 3.0).
    planned = StubRenderPlanner().plan(
        (_assembly(0, 4.0), _assembly(1, 3.0)),
        (_downloaded(0), _downloaded(1)),
        (_voiceover(0, 6.0), _voiceover(1, 1.0)),
        (_subtitle(0, 0.0, 6.0), _subtitle(1, 6.0, 1.0)),
    )

    assert [segment.order_index for segment in planned] == [0, 1]

    # Visual timeline folds from assembly target durations.
    assert (planned[0].visual_start_seconds, planned[0].visual_end_seconds) == (
        0.0,
        4.0,
    )
    assert (planned[1].visual_start_seconds, planned[1].visual_end_seconds) == (
        4.0,
        7.0,
    )

    # Voiceover timeline folds independently from narration durations.
    assert (
        planned[0].voiceover_start_seconds,
        planned[0].voiceover_end_seconds,
    ) == (0.0, 6.0)
    assert (
        planned[1].voiceover_start_seconds,
        planned[1].voiceover_end_seconds,
    ) == (6.0, 7.0)

    # Every segment's voiceover window is internally consistent, even when it
    # diverges from the visual slot.
    for segment in planned:
        assert (
            segment.voiceover_end_seconds - segment.voiceover_start_seconds
            == segment.voiceover_duration_seconds
        )

    # Subtitle timing is copied straight from the subtitle segment.
    assert (
        planned[0].subtitle_start_seconds,
        planned[0].subtitle_end_seconds,
    ) == (0.0, 6.0)
    assert (
        planned[1].subtitle_start_seconds,
        planned[1].subtitle_end_seconds,
    ) == (6.0, 7.0)


def test_fake_render_planner_records_all_four_inputs() -> None:
    configured = StubRenderPlanner().plan(
        (_assembly(0, 4.0),),
        (_downloaded(0),),
        (_voiceover(0, 4.0),),
        (_subtitle(0, 0.0, 4.0),),
    )
    fake = FakeRenderPlanner(configured)
    inputs = (
        (_assembly(0, 4.0),),
        (_downloaded(0),),
        (_voiceover(0, 4.0),),
        (_subtitle(0, 0.0, 4.0),),
    )

    assert fake.plan(*inputs) == configured
    assert fake.calls == [inputs]
