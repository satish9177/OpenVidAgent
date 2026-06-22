"""Render-readiness API tests with in-memory dependencies."""

from __future__ import annotations

from fastapi import status
from fastapi.testclient import TestClient

from backend.app.application.use_cases import CreateRenderOutput, CreateRenderPlan
from backend.app.domain import (
    RenderInputReadiness,
    RenderOutputManifest,
    RenderPlanSegment,
    RenderReadinessReport,
    Run,
    RunStatus,
)
from backend.app.infrastructure.generation import (
    StubFfmpegAvailabilityProbe,
    StubRenderReadinessChecker,
)
from backend.app.main import create_app
from tests.fakes import (
    FakeFfmpegAvailabilityProbe,
    FakeRenderReadinessChecker,
    InMemoryRunRepository,
    InMemoryStorage,
    InMemoryVersionedAssetRepository,
)


def _segment() -> RenderPlanSegment:
    return RenderPlanSegment(
        order_index=0,
        scene_id="scene-1",
        clip_uri="memory://downloads/run-1/0000/clip.mp4",
        clip_provider="stub",
        clip_provider_id="clip-1",
        visual_start_seconds=0.0,
        visual_end_seconds=4.0,
        visual_duration_seconds=4.0,
        voiceover_uri="memory://voiceovers/run-1/0000/voice.mp3",
        voiceover_start_seconds=0.0,
        voiceover_end_seconds=4.0,
        voiceover_duration_seconds=4.0,
        subtitle_text="Narration",
        subtitle_start_seconds=0.0,
        subtitle_end_seconds=4.0,
        subtitle_language="en",
    )


def _manifest() -> RenderOutputManifest:
    return RenderOutputManifest(
        status="not_rendered",
        render_plan_asset_id="render-plan-1",
        render_plan_version=1,
        render_intent="voiceover_b_roll",
        aspect_ratio="16:9",
        container="mp4",
        resolution_width=1920,
        resolution_height=1080,
        fps=30.0,
        segment_count=1,
        estimated_duration_seconds=4.0,
        output_uri=None,
        generation_reason="metadata_only_foundation",
    )


def _input(role: str, required: bool, reason: str) -> RenderInputReadiness:
    return RenderInputReadiness(
        order_index=0,
        scene_id="scene-1",
        role=role,
        uri=(
            "Narration"
            if role == "subtitle"
            else f"memory://{role}/{role}.bin"
        ),
        scheme="inline" if role == "subtitle" else "memory",
        required=required,
        status="placeholder",
        blocker_reason=reason,
    )


def _report() -> RenderReadinessReport:
    return RenderReadinessReport(
        status="blocked",
        render_plan_asset_id="render-plan-1",
        render_plan_version=1,
        render_output_asset_id=None,
        render_output_version=None,
        ffmpeg_availability="not_checked",
        segment_count=1,
        materialized_required_count=0,
        total_required_count=2,
        inputs=(
            _input("clip", True, "clip_not_materialized"),
            _input("voiceover", True, "voiceover_not_materialized"),
            _input("subtitle", False, "subtitle_manifest_only"),
        ),
        blocker_summary=(
            "clip_not_materialized",
            "voiceover_not_materialized",
        ),
        warnings=(
            "subtitle_manifest_only",
            "render_output_not_available",
        ),
        generation_reason="fake_check",
    )


def _client(
    run_status: RunStatus = RunStatus.SCENES_APPROVED,
    *,
    checker: FakeRenderReadinessChecker | None = None,
    probe: FakeFfmpegAvailabilityProbe | None = None,
) -> TestClient:
    runs = InMemoryRunRepository()
    runs.save(Run(run_id="run-1", prompt="prompt", status=run_status))
    return TestClient(
        create_app(
            run_repository=runs,
            versioned_asset_repository=InMemoryVersionedAssetRepository(),
            storage=InMemoryStorage(),
            render_readiness_checker=checker,
            ffmpeg_availability_probe=probe,
        )
    )


def _seed_dependencies(client: TestClient, *, output: bool = True) -> None:
    CreateRenderPlan(
        client.app.state.run_repository,
        client.app.state.versioned_asset_repository,
        client.app.state.storage,
        asset_id_factory=lambda: "render-plan-1",
    ).execute("run-1", (_segment(),), source="generated")
    if output:
        CreateRenderOutput(
            client.app.state.run_repository,
            client.app.state.versioned_asset_repository,
            client.app.state.storage,
            asset_id_factory=lambda: "render-output-1",
        ).execute("run-1", _manifest(), source="generated")


def test_generate_blocked_readiness_returns_201_and_versions() -> None:
    checker = FakeRenderReadinessChecker(_report())
    probe = FakeFfmpegAvailabilityProbe()
    client = _client(checker=checker, probe=probe)
    _seed_dependencies(client)

    first = client.post("/runs/run-1/render-readiness/generate")
    second = client.post("/runs/run-1/render-readiness/generate")

    assert first.status_code == status.HTTP_201_CREATED
    assert second.status_code == status.HTTP_201_CREATED
    assert first.json()["kind"] == "render_readiness"
    assert (first.json()["version"], second.json()["version"]) == (1, 2)
    assert first.json()["metadata"] == {
        "render_plan_asset_id": "render-plan-1",
        "render_plan_version": "1",
        "render_output_asset_id": "render-output-1",
        "render_output_version": "1",
        "status": "blocked",
        "ffmpeg_availability": "not_checked",
        "source": "generated",
    }
    assert len(checker.calls) == 2
    assert checker.calls[0] == (
        "render-plan-1",
        1,
        (_segment(),),
        _manifest(),
        "not_checked",
    )
    assert probe.call_count == 2
    assert client.get("/runs/run-1").json()["status"] == "scenes_approved"


def test_list_and_latest_return_parsed_report_details() -> None:
    client = _client(
        checker=FakeRenderReadinessChecker(_report()),
        probe=FakeFfmpegAvailabilityProbe(),
    )
    _seed_dependencies(client)
    client.post("/runs/run-1/render-readiness/generate")
    client.post("/runs/run-1/render-readiness/generate")

    listed = client.get("/runs/run-1/render-readiness")
    latest = client.get("/runs/run-1/render-readiness/latest")

    assert listed.status_code == status.HTTP_200_OK
    assert [asset["version"] for asset in listed.json()] == [1, 2]
    assert latest.status_code == status.HTTP_200_OK
    body = latest.json()
    assert body["asset"]["version"] == 2
    assert body["report"]["status"] == "blocked"
    assert body["report"]["render_output_asset_id"] == "render-output-1"
    assert body["report"]["ffmpeg_availability"] == "not_checked"
    assert body["report"]["materialized_required_count"] == 0
    assert body["report"]["total_required_count"] == 2
    assert [item["role"] for item in body["report"]["inputs"]] == [
        "clip",
        "voiceover",
        "subtitle",
    ]
    assert body["report"]["blocker_summary"] == [
        "clip_not_materialized",
        "voiceover_not_materialized",
    ]


def test_generate_missing_run_returns_404() -> None:
    checker = FakeRenderReadinessChecker(_report())
    client = _client(checker=checker, probe=FakeFfmpegAvailabilityProbe())

    response = client.post("/runs/missing/render-readiness/generate")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert checker.calls == []


def test_generate_missing_render_plan_returns_404() -> None:
    checker = FakeRenderReadinessChecker(_report())
    client = _client(checker=checker, probe=FakeFfmpegAvailabilityProbe())

    response = client.post("/runs/run-1/render-readiness/generate")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["kind"] == "render_plan"
    assert checker.calls == []


def test_generate_tolerates_missing_render_output() -> None:
    checker = FakeRenderReadinessChecker(_report())
    client = _client(checker=checker, probe=FakeFfmpegAvailabilityProbe())
    _seed_dependencies(client, output=False)

    response = client.post("/runs/run-1/render-readiness/generate")

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["metadata"]["render_output_asset_id"] == ""
    assert checker.calls[0][3] is None
    latest = client.get("/runs/run-1/render-readiness/latest").json()
    assert latest["report"]["render_output_asset_id"] is None


def test_invalid_status_wins_over_missing_dependencies() -> None:
    checker = FakeRenderReadinessChecker(_report())
    probe = FakeFfmpegAvailabilityProbe()
    client = _client(RunStatus.CREATED, checker=checker, probe=probe)

    response = client.post("/runs/run-1/render-readiness/generate")

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["kind"] == "render_readiness"
    assert checker.calls == []
    assert probe.call_count == 0


def test_manual_render_probe_file_and_ffmpeg_routes_are_absent() -> None:
    client = _client()

    assert client.post("/runs/run-1/render-readiness").status_code == 405
    assert client.post("/runs/run-1/renders/generate").status_code == 404
    assert client.get("/runs/run-1/render-readiness/file").status_code == 404
    assert client.get("/runs/run-1/render-readiness/probe").status_code == 404
    assert client.get("/runs/run-1/render-readiness/ffmpeg").status_code == 404


def test_default_app_wires_readiness_and_availability_stubs() -> None:
    app = create_app(
        run_repository=InMemoryRunRepository(),
        versioned_asset_repository=InMemoryVersionedAssetRepository(),
        storage=InMemoryStorage(),
    )

    assert isinstance(
        app.state.render_readiness_checker, StubRenderReadinessChecker
    )
    assert isinstance(
        app.state.ffmpeg_availability_probe, StubFfmpegAvailabilityProbe
    )
