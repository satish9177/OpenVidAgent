"""Subtitle manifest API tests with injected in-memory dependencies."""

from __future__ import annotations

from fastapi import status
from fastapi.testclient import TestClient

from backend.app.application.use_cases import CreateVoiceover
from backend.app.domain import Run, RunStatus, VoiceoverSegment
from backend.app.infrastructure.generation import StubSubtitleComposer
from backend.app.main import create_app
from tests.fakes import (
    FakeSubtitleComposer,
    InMemoryRunRepository,
    InMemoryStorage,
    InMemoryVersionedAssetRepository,
)


def _voiceover_segment(order_index: int = 0) -> VoiceoverSegment:
    return VoiceoverSegment(
        scene_id=f"scene-{order_index + 1}",
        order_index=order_index,
        narration_text=f"Narration {order_index}",
        language="te",
        voice_id="stub-narrator",
        provider="stub",
        audio_uri=f"memory://voiceovers/run-1/{order_index:04d}/scene.mp3",
        content_type="audio/mpeg",
        duration_seconds=4.0 + order_index,
        status="available",
        generation_reason="deterministic_placeholder",
    )


def _client(
    run_status: RunStatus = RunStatus.SCENES_APPROVED,
    *,
    subtitle_composer: FakeSubtitleComposer | None = None,
) -> TestClient:
    runs = InMemoryRunRepository()
    runs.save(Run(run_id="run-1", prompt="prompt", status=run_status))
    return TestClient(
        create_app(
            run_repository=runs,
            versioned_asset_repository=InMemoryVersionedAssetRepository(),
            storage=InMemoryStorage(),
            subtitle_composer=subtitle_composer,
        )
    )


def _seed_voiceover(client: TestClient) -> None:
    CreateVoiceover(
        client.app.state.run_repository,
        client.app.state.versioned_asset_repository,
        client.app.state.storage,
        asset_id_factory=lambda: "voiceover-1",
    ).execute(
        "run-1",
        (_voiceover_segment(1), _voiceover_segment(0)),
        source="generated",
        asset_metadata={"language": "te"},
    )


def test_generate_subtitles_versions_manifest_and_uses_injected_fake() -> None:
    composer = FakeSubtitleComposer()
    client = _client(subtitle_composer=composer)
    _seed_voiceover(client)

    first = client.post("/runs/run-1/subtitles/generate")
    second = client.post("/runs/run-1/subtitles/generate")

    assert first.status_code == status.HTTP_201_CREATED
    assert second.status_code == status.HTTP_201_CREATED
    assert first.json()["kind"] == "subtitle_manifest"
    assert (first.json()["version"], second.json()["version"]) == (1, 2)
    assert first.json()["metadata"] == {
        "voiceover_asset_id": "voiceover-1",
        "voiceover_version": "1",
        "language": "te",
        "source": "generated",
    }
    assert composer.calls == [
        (_voiceover_segment(0), 0.0, "te"),
        (_voiceover_segment(1), 4.0, "te"),
        (_voiceover_segment(0), 0.0, "te"),
        (_voiceover_segment(1), 4.0, "te"),
    ]
    assert client.get("/runs/run-1").json()["status"] == "scenes_approved"


def test_list_and_latest_subtitles_return_ordered_non_english_segments() -> None:
    client = _client(subtitle_composer=FakeSubtitleComposer())
    _seed_voiceover(client)
    client.post("/runs/run-1/subtitles/generate")
    client.post("/runs/run-1/subtitles/generate")

    listed = client.get("/runs/run-1/subtitles")
    latest = client.get("/runs/run-1/subtitles/latest")

    assert listed.status_code == status.HTTP_200_OK
    assert [asset["version"] for asset in listed.json()] == [1, 2]
    assert latest.status_code == status.HTTP_200_OK
    body = latest.json()
    assert body["asset"]["version"] == 2
    assert body["asset"]["metadata"]["language"] == "te"
    assert [segment["order_index"] for segment in body["segments"]] == [0, 1]
    assert body["segments"][0]["start_seconds"] == 0.0
    assert body["segments"][0]["end_seconds"] == 4.0
    assert body["segments"][1]["start_seconds"] == 4.0
    assert body["segments"][1]["end_seconds"] == 9.0
    assert all(segment["language"] == "te" for segment in body["segments"])
    assert all("subtitle_uri" not in segment for segment in body["segments"])


def test_generate_subtitles_missing_run_returns_404_without_composer_call() -> None:
    composer = FakeSubtitleComposer()
    client = _client(subtitle_composer=composer)

    response = client.post("/runs/missing/subtitles/generate")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert composer.calls == []


def test_generate_subtitles_missing_voiceover_returns_404() -> None:
    composer = FakeSubtitleComposer()
    client = _client(subtitle_composer=composer)

    response = client.post("/runs/run-1/subtitles/generate")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["kind"] == "voiceover"
    assert composer.calls == []


def test_generate_subtitles_invalid_status_wins_over_missing_voiceover() -> None:
    composer = FakeSubtitleComposer()
    client = _client(RunStatus.CREATED, subtitle_composer=composer)

    response = client.post("/runs/run-1/subtitles/generate")

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["kind"] == "subtitle_manifest"
    assert response.json()["status"] == "created"
    assert composer.calls == []


def test_manual_file_render_and_audio_routes_are_absent() -> None:
    client = _client()

    assert client.post("/runs/run-1/subtitles").status_code == 405
    assert client.get("/runs/run-1/subtitles/file").status_code == 404
    assert client.post("/runs/run-1/subtitles/render").status_code == 404
    assert client.get("/runs/run-1/subtitles/audio").status_code == 404


def test_default_app_wires_stub_subtitle_composer() -> None:
    app = create_app(
        run_repository=InMemoryRunRepository(),
        versioned_asset_repository=InMemoryVersionedAssetRepository(),
        storage=InMemoryStorage(),
    )

    assert isinstance(app.state.subtitle_composer, StubSubtitleComposer)
