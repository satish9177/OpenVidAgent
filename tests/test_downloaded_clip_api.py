"""Downloaded clip manifest API tests with injected in-memory dependencies."""

from __future__ import annotations

from fastapi import status
from fastapi.testclient import TestClient

from backend.app.application.use_cases import CreateVideoAssemblyPlan
from backend.app.domain import Run, RunStatus, VideoAssemblySegment
from backend.app.infrastructure.generation import StubClipDownloader
from backend.app.main import create_app
from tests.fakes import (
    FakeClipDownloader,
    InMemoryRunRepository,
    InMemoryStorage,
    InMemoryVersionedAssetRepository,
)


def _segment() -> VideoAssemblySegment:
    return VideoAssemblySegment(
        scene_id="scene-1",
        query_text="coffee beans roasting",
        narration="Coffee beans develop flavor while roasting.",
        visual_query="close-up coffee roasting",
        provider="stub",
        provider_clip_id="scene-1-1",
        title="Coffee beans roasting",
        preview_url="memory://clips/scene-1/1/preview.jpg",
        source_url="memory://clips/scene-1/1",
        target_duration_seconds=4.0,
        source_duration_seconds=7.5,
        width=1920,
        height=1080,
        order_index=0,
        transition="cut",
        continuity_note="ordered_by_scene_table",
        selection_reason="first_candidate_for_scene_query",
    )


def _client(
    run_status: RunStatus = RunStatus.SCENES_APPROVED,
    *,
    clip_downloader: FakeClipDownloader | None = None,
) -> TestClient:
    runs = InMemoryRunRepository()
    runs.save(Run(run_id="run-1", prompt="prompt", status=run_status))
    return TestClient(
        create_app(
            run_repository=runs,
            versioned_asset_repository=InMemoryVersionedAssetRepository(),
            storage=InMemoryStorage(),
            clip_downloader=clip_downloader,
        )
    )


def _seed_plan(client: TestClient) -> None:
    CreateVideoAssemblyPlan(
        client.app.state.run_repository,
        client.app.state.versioned_asset_repository,
        client.app.state.storage,
        asset_id_factory=lambda: "video-assembly-plan-1",
    ).execute("run-1", (_segment(),), source="generated")


def test_download_endpoint_versions_manifest_and_uses_injected_fake() -> None:
    downloader = FakeClipDownloader()
    client = _client(clip_downloader=downloader)
    _seed_plan(client)

    first = client.post("/runs/run-1/downloaded-clips/download")
    second = client.post("/runs/run-1/downloaded-clips/download")

    assert first.status_code == status.HTTP_201_CREATED
    assert second.status_code == status.HTTP_201_CREATED
    assert first.json()["kind"] == "downloaded_clips"
    assert (first.json()["version"], second.json()["version"]) == (1, 2)
    assert first.json()["metadata"] == {
        "video_assembly_plan_asset_id": "video-assembly-plan-1",
        "video_assembly_plan_version": "1",
        "source": "downloaded",
    }
    assert downloader.calls == [
        ("run-1", _segment()),
        ("run-1", _segment()),
    ]
    assert client.get("/runs/run-1").json()["status"] == "scenes_approved"


def test_list_and_latest_downloaded_clips_return_parsed_records() -> None:
    client = _client(clip_downloader=FakeClipDownloader())
    _seed_plan(client)
    client.post("/runs/run-1/downloaded-clips/download")
    client.post("/runs/run-1/downloaded-clips/download")

    listed = client.get("/runs/run-1/downloaded-clips")
    latest = client.get("/runs/run-1/downloaded-clips/latest")

    assert listed.status_code == status.HTTP_200_OK
    assert [asset["version"] for asset in listed.json()] == [1, 2]
    assert latest.status_code == status.HTTP_200_OK
    body = latest.json()
    assert body["asset"]["version"] == 2
    assert body["downloaded_clips"] == [
        {
            "scene_id": "scene-1",
            "query_text": "coffee beans roasting",
            "provider": "stub",
            "provider_clip_id": "scene-1-1",
            "title": "Coffee beans roasting",
            "source_url": "memory://clips/scene-1/1",
            "local_uri": "memory://downloads/run-1/0000/stub-scene-1-1.mp4",
            "content_type": "video/mp4",
            "duration_seconds": 7.5,
            "width": 1920,
            "height": 1080,
            "order_index": 0,
            "download_status": "available",
            "download_reason": "fake_download",
        }
    ]


def test_download_missing_run_returns_404_without_downloader_call() -> None:
    downloader = FakeClipDownloader()
    client = _client(clip_downloader=downloader)

    response = client.post("/runs/missing/downloaded-clips/download")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert downloader.calls == []


def test_download_missing_assembly_plan_returns_404() -> None:
    downloader = FakeClipDownloader()
    client = _client(clip_downloader=downloader)

    response = client.post("/runs/run-1/downloaded-clips/download")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["kind"] == "video_assembly_plan"
    assert downloader.calls == []


def test_download_invalid_status_wins_over_missing_plan() -> None:
    downloader = FakeClipDownloader()
    client = _client(RunStatus.CREATED, clip_downloader=downloader)

    response = client.post("/runs/run-1/downloaded-clips/download")

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["kind"] == "downloaded_clips"
    assert response.json()["status"] == "created"
    assert downloader.calls == []


def test_manual_media_and_render_routes_are_absent() -> None:
    client = _client()

    assert client.post("/runs/run-1/downloaded-clips").status_code == 405
    assert client.get("/runs/run-1/downloaded-clips/media").status_code == 404
    assert client.post("/runs/run-1/downloaded-clips/render").status_code == 404


def test_default_app_wires_stub_clip_downloader() -> None:
    app = create_app(
        run_repository=InMemoryRunRepository(),
        versioned_asset_repository=InMemoryVersionedAssetRepository(),
        storage=InMemoryStorage(),
    )

    assert isinstance(app.state.clip_downloader, StubClipDownloader)
