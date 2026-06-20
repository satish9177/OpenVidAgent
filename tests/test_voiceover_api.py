"""Voiceover manifest API tests with injected in-memory dependencies."""

from __future__ import annotations

from fastapi import status
from fastapi.testclient import TestClient

from backend.app.application.use_cases import CreateVideoAssemblyPlan
from backend.app.domain import Run, RunStatus, VideoAssemblySegment
from backend.app.infrastructure.generation import StubVoiceoverGenerator
from backend.app.main import create_app
from tests.fakes import (
    FakeVoiceoverGenerator,
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
        target_duration_seconds=4.25,
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
    language: str = "te",
    voiceover_generator: FakeVoiceoverGenerator | None = None,
) -> TestClient:
    runs = InMemoryRunRepository()
    runs.save(
        Run(
            run_id="run-1",
            prompt="prompt",
            status=run_status,
            language=language,
        )
    )
    return TestClient(
        create_app(
            run_repository=runs,
            versioned_asset_repository=InMemoryVersionedAssetRepository(),
            storage=InMemoryStorage(),
            voiceover_generator=voiceover_generator,
        )
    )


def _seed_plan(client: TestClient) -> None:
    CreateVideoAssemblyPlan(
        client.app.state.run_repository,
        client.app.state.versioned_asset_repository,
        client.app.state.storage,
        asset_id_factory=lambda: "video-assembly-plan-1",
    ).execute("run-1", (_segment(),), source="generated")


def test_generate_voiceover_versions_manifest_and_uses_injected_fake() -> None:
    generator = FakeVoiceoverGenerator()
    client = _client(voiceover_generator=generator)
    _seed_plan(client)

    first = client.post("/runs/run-1/voiceovers/generate")
    second = client.post("/runs/run-1/voiceovers/generate")

    assert first.status_code == status.HTTP_201_CREATED
    assert second.status_code == status.HTTP_201_CREATED
    assert first.json()["kind"] == "voiceover"
    assert (first.json()["version"], second.json()["version"]) == (1, 2)
    assert first.json()["metadata"] == {
        "video_assembly_plan_asset_id": "video-assembly-plan-1",
        "video_assembly_plan_version": "1",
        "language": "te",
        "source": "generated",
    }
    assert generator.calls == [
        ("run-1", _segment(), "te"),
        ("run-1", _segment(), "te"),
    ]
    assert client.get("/runs/run-1").json()["status"] == "scenes_approved"


def test_list_and_latest_voiceovers_return_non_english_segments() -> None:
    client = _client(voiceover_generator=FakeVoiceoverGenerator())
    _seed_plan(client)
    client.post("/runs/run-1/voiceovers/generate")
    client.post("/runs/run-1/voiceovers/generate")

    listed = client.get("/runs/run-1/voiceovers")
    latest = client.get("/runs/run-1/voiceovers/latest")

    assert listed.status_code == status.HTTP_200_OK
    assert [asset["version"] for asset in listed.json()] == [1, 2]
    assert latest.status_code == status.HTTP_200_OK
    body = latest.json()
    assert body["asset"]["version"] == 2
    assert body["asset"]["metadata"]["language"] == "te"
    assert body["segments"] == [
        {
            "scene_id": "scene-1",
            "order_index": 0,
            "narration_text": "Coffee beans develop flavor while roasting.",
            "language": "te",
            "voice_id": "fake-narrator",
            "provider": "fake",
            "audio_uri": "memory://voiceovers/run-1/0000/scene-1.mp3",
            "content_type": "audio/mpeg",
            "duration_seconds": 4.25,
            "status": "available",
            "generation_reason": "fake_generation",
        }
    ]


def test_generate_voiceover_missing_run_returns_404_without_generator_call() -> None:
    generator = FakeVoiceoverGenerator()
    client = _client(voiceover_generator=generator)

    response = client.post("/runs/missing/voiceovers/generate")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert generator.calls == []


def test_generate_voiceover_missing_assembly_plan_returns_404() -> None:
    generator = FakeVoiceoverGenerator()
    client = _client(voiceover_generator=generator)

    response = client.post("/runs/run-1/voiceovers/generate")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["kind"] == "video_assembly_plan"
    assert generator.calls == []


def test_generate_voiceover_invalid_status_wins_over_missing_plan() -> None:
    generator = FakeVoiceoverGenerator()
    client = _client(
        RunStatus.CREATED,
        voiceover_generator=generator,
    )

    response = client.post("/runs/run-1/voiceovers/generate")

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["kind"] == "voiceover"
    assert response.json()["status"] == "created"
    assert generator.calls == []


def test_manual_audio_download_and_render_routes_are_absent() -> None:
    client = _client()

    assert client.post("/runs/run-1/voiceovers").status_code == 405
    assert client.get("/runs/run-1/voiceovers/audio").status_code == 404
    assert client.get("/runs/run-1/voiceovers/download").status_code == 404
    assert client.post("/runs/run-1/voiceovers/render").status_code == 404


def test_default_app_wires_stub_voiceover_generator() -> None:
    app = create_app(
        run_repository=InMemoryRunRepository(),
        versioned_asset_repository=InMemoryVersionedAssetRepository(),
        storage=InMemoryStorage(),
    )

    assert isinstance(app.state.voiceover_generator, StubVoiceoverGenerator)
