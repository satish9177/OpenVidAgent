"""Render plan API tests with injected in-memory dependencies."""

from __future__ import annotations

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from backend.app.application.use_cases import (
    CreateDownloadedClipSet,
    CreateSubtitles,
    CreateVideoAssemblyPlan,
    CreateVoiceover,
)
from backend.app.domain import (
    DownloadedClip,
    RenderPlanSegment,
    Run,
    RunStatus,
    SubtitleSegment,
    VideoAssemblySegment,
    VoiceoverSegment,
)
from backend.app.infrastructure.generation import StubRenderPlanner
from backend.app.main import create_app
from tests.fakes import (
    FakeRenderPlanner,
    InMemoryRunRepository,
    InMemoryStorage,
    InMemoryVersionedAssetRepository,
)


def _assembly(index: int) -> VideoAssemblySegment:
    return VideoAssemblySegment(
        scene_id=f"scene-{index}",
        query_text=f"query {index}",
        narration=f"Narration {index}",
        visual_query=f"Visual {index}",
        provider="stub",
        provider_clip_id=f"clip-{index}",
        title=f"Clip {index}",
        preview_url=f"memory://clips/{index}/preview.jpg",
        source_url=f"memory://clips/{index}",
        target_duration_seconds=4.0,
        source_duration_seconds=6.0,
        width=1920,
        height=1080,
        order_index=index,
        transition="cut",
        continuity_note="ordered_by_scene_table",
        selection_reason="first_candidate_for_scene_query",
    )


def _downloaded(index: int) -> DownloadedClip:
    return DownloadedClip(
        scene_id=f"scene-{index}",
        query_text=f"query {index}",
        provider="stub",
        provider_clip_id=f"clip-{index}",
        title=f"Clip {index}",
        source_url=f"memory://clips/{index}",
        local_uri=f"memory://downloads/run-1/{index:04d}/clip.mp4",
        content_type="video/mp4",
        duration_seconds=6.0,
        width=1920,
        height=1080,
        order_index=index,
        download_status="available",
        download_reason="deterministic_placeholder",
    )


def _voiceover(index: int) -> VoiceoverSegment:
    return VoiceoverSegment(
        scene_id=f"scene-{index}",
        order_index=index,
        narration_text=f"Narration {index}",
        language="en",
        voice_id="stub-narrator",
        provider="stub",
        audio_uri=f"memory://voiceovers/run-1/{index:04d}/scene.mp3",
        content_type="audio/mpeg",
        duration_seconds=4.0,
        status="available",
        generation_reason="deterministic_placeholder",
    )


def _subtitle(index: int) -> SubtitleSegment:
    start = 4.0 * index
    return SubtitleSegment(
        scene_id=f"scene-{index}",
        order_index=index,
        text=f"Narration {index}",
        language="en",
        start_seconds=start,
        end_seconds=start + 4.0,
        duration_seconds=4.0,
        format="manifest",
        status="available",
        generation_reason="deterministic_placeholder",
    )


def _render_segment(index: int) -> RenderPlanSegment:
    start = 4.0 * index
    return RenderPlanSegment(
        order_index=index,
        scene_id=f"scene-{index}",
        clip_uri=f"memory://downloads/run-1/{index:04d}/clip.mp4",
        clip_provider="stub",
        clip_provider_id=f"clip-{index}",
        visual_start_seconds=start,
        visual_end_seconds=start + 4.0,
        visual_duration_seconds=4.0,
        voiceover_uri=f"memory://voiceovers/run-1/{index:04d}/scene.mp3",
        voiceover_start_seconds=start,
        voiceover_end_seconds=start + 4.0,
        voiceover_duration_seconds=4.0,
        subtitle_text=f"Narration {index}",
        subtitle_start_seconds=start,
        subtitle_end_seconds=start + 4.0,
        subtitle_language="en",
    )


def _client(
    run_status: RunStatus = RunStatus.SCENES_APPROVED,
    *,
    render_planner: FakeRenderPlanner | None = None,
) -> TestClient:
    runs = InMemoryRunRepository()
    runs.save(Run(run_id="run-1", prompt="prompt", status=run_status))
    return TestClient(
        create_app(
            run_repository=runs,
            versioned_asset_repository=InMemoryVersionedAssetRepository(),
            storage=InMemoryStorage(),
            render_planner=render_planner,
        )
    )


def _seed_upstreams(
    client: TestClient,
    *,
    count: int = 4,
    downloaded_indexes: tuple[int, ...] = (0, 1),
) -> None:
    runs = client.app.state.run_repository
    assets = client.app.state.versioned_asset_repository
    storage = client.app.state.storage
    creators = (
        lambda: CreateVideoAssemblyPlan(
            runs, assets, storage, asset_id_factory=lambda: "assembly-1"
        ).execute("run-1", (_assembly(0), _assembly(1))),
        lambda: CreateDownloadedClipSet(
            runs, assets, storage, asset_id_factory=lambda: "downloads-1"
        ).execute(
            "run-1", tuple(_downloaded(i) for i in downloaded_indexes)
        ),
        lambda: CreateVoiceover(
            runs, assets, storage, asset_id_factory=lambda: "voiceover-1"
        ).execute("run-1", (_voiceover(0), _voiceover(1))),
        lambda: CreateSubtitles(
            runs, assets, storage, asset_id_factory=lambda: "subtitles-1"
        ).execute("run-1", (_subtitle(0), _subtitle(1))),
    )
    for creator in creators[:count]:
        creator()


def test_generate_render_plan_versions_and_uses_injected_fake() -> None:
    planner = FakeRenderPlanner((_render_segment(0), _render_segment(1)))
    client = _client(render_planner=planner)
    _seed_upstreams(client)

    first = client.post("/runs/run-1/render-plans/generate")
    second = client.post("/runs/run-1/render-plans/generate")

    assert first.status_code == status.HTTP_201_CREATED
    assert second.status_code == status.HTTP_201_CREATED
    assert first.json()["kind"] == "render_plan"
    assert (first.json()["version"], second.json()["version"]) == (1, 2)
    metadata = first.json()["metadata"]
    assert metadata["source"] == "generated"
    assert metadata["video_assembly_plan_asset_id"] == "assembly-1"
    assert metadata["downloaded_clips_asset_id"] == "downloads-1"
    assert metadata["voiceover_asset_id"] == "voiceover-1"
    assert metadata["subtitles_asset_id"] == "subtitles-1"
    assert metadata["aspect_ratio"] == "16:9"
    assert metadata["resolution_width"] == "1920"
    assert metadata["resolution_height"] == "1080"
    assert metadata["fps"] == "30"
    assert metadata["container"] == "mp4"
    assert metadata["render_intent"] == "voiceover_b_roll"
    assert len(planner.calls) == 2
    assert client.get("/runs/run-1").json()["status"] == "scenes_approved"


def test_list_and_latest_render_plans_return_parsed_segments() -> None:
    client = _client(
        render_planner=FakeRenderPlanner(
            (_render_segment(0), _render_segment(1))
        )
    )
    _seed_upstreams(client)
    client.post("/runs/run-1/render-plans/generate")
    client.post("/runs/run-1/render-plans/generate")

    listed = client.get("/runs/run-1/render-plans")
    latest = client.get("/runs/run-1/render-plans/latest")

    assert listed.status_code == status.HTTP_200_OK
    assert [asset["version"] for asset in listed.json()] == [1, 2]
    assert latest.status_code == status.HTTP_200_OK
    assert latest.json()["asset"]["version"] == 2
    assert latest.json()["segments"] == [
        _render_segment(0).__dict__,
        _render_segment(1).__dict__,
    ]


def test_generate_render_plan_missing_run_returns_404() -> None:
    planner = FakeRenderPlanner()
    client = _client(render_planner=planner)

    response = client.post("/runs/missing/render-plans/generate")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert planner.calls == []


@pytest.mark.parametrize(
    ("count", "kind"),
    [
        (0, "video_assembly_plan"),
        (1, "downloaded_clips"),
        (2, "voiceover"),
        (3, "subtitle_manifest"),
    ],
)
def test_generate_render_plan_missing_upstream_returns_404(
    count: int, kind: str
) -> None:
    planner = FakeRenderPlanner()
    client = _client(render_planner=planner)
    _seed_upstreams(client, count=count)

    response = client.post("/runs/run-1/render-plans/generate")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["kind"] == kind
    assert planner.calls == []


def test_generate_render_plan_invalid_status_wins_over_missing_inputs() -> None:
    planner = FakeRenderPlanner()
    client = _client(RunStatus.CREATED, render_planner=planner)

    response = client.post("/runs/run-1/render-plans/generate")

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["kind"] == "render_plan"
    assert planner.calls == []


def test_generate_render_plan_mismatch_maps_to_actionable_409() -> None:
    planner = FakeRenderPlanner()
    client = _client(render_planner=planner)
    _seed_upstreams(client, downloaded_indexes=(0,))

    response = client.post("/runs/run-1/render-plans/generate")

    assert response.status_code == status.HTTP_409_CONFLICT
    body = response.json()
    assert body["run_id"] == "run-1"
    assert body["source"] == "downloaded_clips"
    assert body["expected_order_indexes"] == [0, 1]
    assert body["actual_order_indexes"] == [0]
    assert body["missing_order_indexes"] == [1]
    assert body["extra_order_indexes"] == []
    assert planner.calls == []


def test_manual_output_file_and_ffmpeg_routes_are_absent() -> None:
    client = _client()

    assert client.post("/runs/run-1/render-plans").status_code == 405
    assert client.get("/runs/run-1/render-plans/output").status_code == 404
    assert client.post("/runs/run-1/render-plans/render").status_code == 404
    assert client.get("/runs/run-1/render-plans/ffmpeg").status_code == 404


def test_default_app_wires_stub_render_planner() -> None:
    app = create_app(
        run_repository=InMemoryRunRepository(),
        versioned_asset_repository=InMemoryVersionedAssetRepository(),
        storage=InMemoryStorage(),
    )

    assert isinstance(app.state.render_planner, StubRenderPlanner)
