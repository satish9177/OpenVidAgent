from backend.app.domain import RenderOutputManifest, RenderPlanSegment
from backend.app.infrastructure.generation import (
    StubFfmpegAvailabilityProbe,
    StubRenderReadinessChecker,
)
from tests.fakes import (
    FakeFfmpegAvailabilityProbe,
    FakeRenderReadinessChecker,
)
from tests.test_render_readiness_report import _report


def _segment(
    order_index: int = 0,
    clip_uri: str = "memory://clips/clip.mp4",
    voiceover_uri: str = "memory://voiceovers/voice.mp3",
) -> RenderPlanSegment:
    return RenderPlanSegment(
        order_index=order_index,
        scene_id=f"scene-{order_index + 1}",
        clip_uri=clip_uri,
        clip_provider="stub",
        clip_provider_id=f"clip-{order_index + 1}",
        visual_start_seconds=float(order_index * 4),
        visual_end_seconds=float((order_index + 1) * 4),
        visual_duration_seconds=4.0,
        voiceover_uri=voiceover_uri,
        voiceover_start_seconds=float(order_index * 4),
        voiceover_end_seconds=float((order_index + 1) * 4),
        voiceover_duration_seconds=4.0,
        subtitle_text="Narration",
        subtitle_start_seconds=float(order_index * 4),
        subtitle_end_seconds=float((order_index + 1) * 4),
        subtitle_language="en",
    )


def _output(output_uri: str | None = None) -> RenderOutputManifest:
    return RenderOutputManifest(
        status="not_rendered",
        render_plan_asset_id="plan-1",
        render_plan_version=1,
        render_intent="voiceover_b_roll",
        aspect_ratio="16:9",
        container="mp4",
        resolution_width=1920,
        resolution_height=1080,
        fps=30.0,
        segment_count=1,
        estimated_duration_seconds=4.0,
        output_uri=output_uri,
        generation_reason="metadata_only_foundation",
    )


def test_memory_references_are_required_blockers_with_optional_warnings() -> None:
    checker = StubRenderReadinessChecker()
    segments = (_segment(0), _segment(1))

    report = checker.check("plan-1", 1, segments, _output(), "not_checked")

    assert report.status == "blocked"
    assert report.segment_count == 2
    assert report.materialized_required_count == 0
    assert report.total_required_count == 4
    assert report.ffmpeg_availability == "not_checked"
    assert report.blocker_summary == (
        "clip_not_materialized",
        "voiceover_not_materialized",
    )
    assert report.warnings == (
        "subtitle_manifest_only",
        "render_output_not_available",
    )
    assert [(item.role, item.required, item.status) for item in report.inputs] == [
        ("clip", True, "placeholder"),
        ("voiceover", True, "placeholder"),
        ("subtitle", False, "placeholder"),
        ("clip", True, "placeholder"),
        ("voiceover", True, "placeholder"),
        ("subtitle", False, "placeholder"),
    ]


def test_local_inputs_are_ready_without_probe_or_subtitle_file() -> None:
    checker = StubRenderReadinessChecker()
    segment = _segment(
        clip_uri="clips/clip.mp4",
        voiceover_uri="file:///audio/voice.mp3",
    )

    report = checker.check(
        "plan-1", 1, (segment,), _output("renders/video.mp4"), "not_checked"
    )

    assert report.status == "ready"
    assert report.materialized_required_count == 2
    assert report.total_required_count == 2
    assert report.blocker_summary == ()
    assert report.warnings == ("subtitle_manifest_only",)
    assert [item.scheme for item in report.inputs] == [
        "relative",
        "file",
        "inline",
    ]


def test_missing_inputs_and_explicit_missing_ffmpeg_block() -> None:
    report = StubRenderReadinessChecker().check(
        "plan-1", 1, (_segment(clip_uri="", voiceover_uri=" "),), None, "missing"
    )

    assert report.status == "blocked"
    assert report.blocker_summary == (
        "clip_missing",
        "voiceover_missing",
        "ffmpeg_unavailable",
    )
    assert [item.status for item in report.inputs[:2]] == ["missing", "missing"]


def test_checker_is_repeatable_and_stubs_do_not_fabricate_availability() -> None:
    checker = StubRenderReadinessChecker()
    arguments = ("plan-1", 1, (_segment(),), _output(), "not_checked")

    assert checker.check(*arguments) == checker.check(*arguments)
    assert StubFfmpegAvailabilityProbe().check() == "not_checked"


def test_recording_fakes_capture_calls() -> None:
    expected_report = _report()
    checker = FakeRenderReadinessChecker(expected_report)
    probe = FakeFfmpegAvailabilityProbe("available")
    segment = _segment()
    output = _output()

    assert checker.check("plan-1", 2, (segment,), output, probe.check()) is (
        expected_report
    )
    assert checker.calls == [("plan-1", 2, (segment,), output, "available")]
    assert probe.call_count == 1
