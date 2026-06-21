"""Render output manifest API tests with in-memory dependencies."""

from __future__ import annotations

from fastapi import status
from fastapi.testclient import TestClient

from backend.app.application.use_cases import CreateRenderPlan
from backend.app.domain import (
    RenderOutputManifest,
    RenderPlanSegment,
    Run,
    RunStatus,
)
from backend.app.infrastructure.generation import StubRenderOutputGenerator
from backend.app.main import create_app
from tests.fakes import (
    FakeRenderOutputGenerator,
    InMemoryRunRepository,
    InMemoryStorage,
    InMemoryVersionedAssetRepository,
)


PROFILE = {
    "aspect_ratio": "16:9",
    "resolution_width": "1920",
    "resolution_height": "1080",
    "fps": "30",
    "container": "mp4",
    "render_intent": "voiceover_b_roll",
}


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
        voiceover_uri="memory://voiceovers/run-1/0000/scene.mp3",
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


def _client(
    run_status: RunStatus = RunStatus.SCENES_APPROVED,
    *,
    generator: FakeRenderOutputGenerator | None = None,
) -> TestClient:
    runs = InMemoryRunRepository()
    runs.save(Run(run_id="run-1", prompt="prompt", status=run_status))
    return TestClient(
        create_app(
            run_repository=runs,
            versioned_asset_repository=InMemoryVersionedAssetRepository(),
            storage=InMemoryStorage(),
            render_output_generator=generator,
        )
    )


def _seed_render_plan(client: TestClient) -> None:
    CreateRenderPlan(
        client.app.state.run_repository,
        client.app.state.versioned_asset_repository,
        client.app.state.storage,
        asset_id_factory=lambda: "render-plan-1",
    ).execute(
        "run-1",
        (_segment(),),
        source="generated",
        asset_metadata=PROFILE,
    )


def test_generate_render_output_versions_and_uses_injected_fake() -> None:
    generator = FakeRenderOutputGenerator(_manifest())
    client = _client(generator=generator)
    _seed_render_plan(client)

    first = client.post("/runs/run-1/render-outputs/generate")
    second = client.post("/runs/run-1/render-outputs/generate")

    assert first.status_code == status.HTTP_201_CREATED
    assert second.status_code == status.HTTP_201_CREATED
    assert first.json()["kind"] == "render_output"
    assert (first.json()["version"], second.json()["version"]) == (1, 2)
    assert first.json()["metadata"] == {
        "render_plan_asset_id": "render-plan-1",
        "render_plan_version": "1",
        "status": "not_rendered",
        **PROFILE,
        "source": "generated",
    }
    assert generator.calls == [
        ("render-plan-1", 1, (_segment(),), PROFILE),
        ("render-plan-1", 1, (_segment(),), PROFILE),
    ]
    assert client.get("/runs/run-1").json()["status"] == "scenes_approved"


def test_list_and_latest_render_outputs_return_null_uri_manifest() -> None:
    client = _client(generator=FakeRenderOutputGenerator(_manifest()))
    _seed_render_plan(client)
    client.post("/runs/run-1/render-outputs/generate")
    client.post("/runs/run-1/render-outputs/generate")

    listed = client.get("/runs/run-1/render-outputs")
    latest = client.get("/runs/run-1/render-outputs/latest")

    assert listed.status_code == status.HTTP_200_OK
    assert [asset["version"] for asset in listed.json()] == [1, 2]
    assert latest.status_code == status.HTTP_200_OK
    body = latest.json()
    assert body["asset"]["version"] == 2
    assert body["manifest"] == _manifest().__dict__
    assert body["manifest"]["status"] == "not_rendered"
    assert body["manifest"]["output_uri"] is None


def test_generate_render_output_missing_run_returns_404() -> None:
    generator = FakeRenderOutputGenerator()
    client = _client(generator=generator)

    response = client.post("/runs/missing/render-outputs/generate")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert generator.calls == []


def test_generate_render_output_missing_render_plan_returns_404() -> None:
    generator = FakeRenderOutputGenerator()
    client = _client(generator=generator)

    response = client.post("/runs/run-1/render-outputs/generate")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["kind"] == "render_plan"
    assert generator.calls == []


def test_generate_render_output_invalid_status_wins_over_missing_plan() -> None:
    generator = FakeRenderOutputGenerator()
    client = _client(RunStatus.CREATED, generator=generator)

    response = client.post("/runs/run-1/render-outputs/generate")

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["kind"] == "render_output"
    assert generator.calls == []


def test_manual_real_render_file_and_ffmpeg_routes_are_absent() -> None:
    client = _client()

    assert client.post("/runs/run-1/render-outputs").status_code == 405
    assert client.post("/runs/run-1/render-outputs/render").status_code == 404
    assert client.get("/runs/run-1/render-outputs/file").status_code == 404
    assert client.get("/runs/run-1/render-outputs/ffmpeg").status_code == 404


def test_default_app_wires_stub_render_output_generator() -> None:
    app = create_app(
        run_repository=InMemoryRunRepository(),
        versioned_asset_repository=InMemoryVersionedAssetRepository(),
        storage=InMemoryStorage(),
    )

    assert isinstance(
        app.state.render_output_generator,
        StubRenderOutputGenerator,
    )
