from __future__ import annotations

from backend.app.domain import RenderOutputManifest, RenderPlanSegment
from backend.app.infrastructure.generation import StubRenderOutputGenerator
from backend.app.ports import RenderOutputGenerator
from tests.fakes import FakeRenderOutputGenerator


PROFILE = {
    "render_intent": "voiceover_b_roll",
    "aspect_ratio": "16:9",
    "container": "mp4",
    "resolution_width": "1920",
    "resolution_height": "1080",
    "fps": "30",
}


def _segment(order_index: int, visual_end: float) -> RenderPlanSegment:
    visual_start = max(0.0, visual_end - 4.0)
    return RenderPlanSegment(
        order_index=order_index,
        scene_id=f"scene-{order_index}",
        clip_uri=f"memory://downloads/{order_index}/clip.mp4",
        clip_provider="stub",
        clip_provider_id=f"clip-{order_index}",
        visual_start_seconds=visual_start,
        visual_end_seconds=visual_end,
        visual_duration_seconds=visual_end - visual_start,
        voiceover_uri=f"memory://voiceovers/{order_index}/voice.mp3",
        voiceover_start_seconds=visual_start,
        voiceover_end_seconds=visual_end,
        voiceover_duration_seconds=visual_end - visual_start,
        subtitle_text=f"Narration {order_index}",
        subtitle_start_seconds=visual_start,
        subtitle_end_seconds=visual_end,
        subtitle_language="en",
    )


def test_stub_generator_satisfies_port_and_is_repeatable() -> None:
    generator = StubRenderOutputGenerator()
    segments = (_segment(0, 4.0), _segment(1, 8.0))

    assert isinstance(generator, RenderOutputGenerator)
    assert generator.generate("plan-1", 2, segments, PROFILE) == (
        generator.generate("plan-1", 2, segments, PROFILE)
    )


def test_stub_generator_returns_truthful_typed_manifest() -> None:
    manifest = StubRenderOutputGenerator().generate(
        "plan-1",
        2,
        (_segment(1, 8.0), _segment(0, 4.0)),
        PROFILE,
    )

    assert manifest == RenderOutputManifest(
        status="not_rendered",
        render_plan_asset_id="plan-1",
        render_plan_version=2,
        render_intent="voiceover_b_roll",
        aspect_ratio="16:9",
        container="mp4",
        resolution_width=1920,
        resolution_height=1080,
        fps=30.0,
        segment_count=2,
        estimated_duration_seconds=8.0,
        output_uri=None,
        generation_reason="metadata_only_foundation",
    )
    assert not hasattr(manifest, "output_path")
    assert not hasattr(manifest, "ffmpeg_command")
    assert not hasattr(manifest, "checksum")
    assert not hasattr(manifest, "file_size")


def test_stub_generator_empty_plan_has_zero_estimate_and_no_uri() -> None:
    manifest = StubRenderOutputGenerator().generate("plan-1", 1, (), PROFILE)

    assert manifest.segment_count == 0
    assert manifest.estimated_duration_seconds == 0.0
    assert manifest.status == "not_rendered"
    assert manifest.output_uri is None


def test_fake_generator_records_inputs_and_returns_configured_manifest() -> None:
    configured = StubRenderOutputGenerator().generate(
        "configured", 4, (), PROFILE
    )
    fake = FakeRenderOutputGenerator(configured)
    segments = (_segment(0, 4.0),)

    assert fake.generate("plan-1", 2, segments, PROFILE) == configured
    assert fake.calls == [("plan-1", 2, segments, PROFILE)]
