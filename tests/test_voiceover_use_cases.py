"""Voiceover manifest use-case tests."""

from __future__ import annotations

import itertools
import json

import pytest

from backend.app.application.errors import (
    AssetCreationRejectedError,
    AssetNotFoundError,
    RunNotFoundError,
)
from backend.app.application.use_cases import (
    CreateVideoAssemblyPlan,
    CreateVoiceover,
    GenerateVoiceover,
    GetLatestVideoAssemblyPlan,
    GetLatestVoiceover,
    ListVoiceovers,
)
from backend.app.domain import (
    AssetKind,
    Run,
    RunStatus,
    VideoAssemblySegment,
    VoiceoverSegment,
)
from tests.fakes import (
    FakeVoiceoverGenerator,
    InMemoryRunRepository,
    InMemoryStorage,
    InMemoryVersionedAssetRepository,
)


def _triple() -> tuple[
    InMemoryRunRepository, InMemoryVersionedAssetRepository, InMemoryStorage
]:
    return (
        InMemoryRunRepository(),
        InMemoryVersionedAssetRepository(),
        InMemoryStorage(),
    )


def _seed_run(
    runs: InMemoryRunRepository,
    status: RunStatus = RunStatus.SCENES_APPROVED,
    language: str = "en",
) -> Run:
    run = Run(
        run_id="run-1",
        prompt="prompt",
        status=status,
        language=language,
    )
    runs.save(run)
    return run


def _create_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
) -> CreateVoiceover:
    ids = (f"voiceover-{n}" for n in itertools.count(1))
    return CreateVoiceover(
        runs, assets, storage, asset_id_factory=lambda: next(ids)
    )


def _segment(order_index: int = 0) -> VideoAssemblySegment:
    return VideoAssemblySegment(
        scene_id=f"scene-{order_index + 1}",
        query_text=f"query {order_index}",
        narration=f"Narration {order_index}",
        visual_query=f"Visual {order_index}",
        provider="stub",
        provider_clip_id=f"clip-{order_index}",
        title=f"Clip {order_index}",
        preview_url=f"memory://clips/{order_index}/preview.jpg",
        source_url=f"memory://clips/{order_index}",
        target_duration_seconds=4.0 + order_index,
        source_duration_seconds=7.5 + order_index,
        width=1920,
        height=1080,
        order_index=order_index,
        transition="cut",
        continuity_note="ordered_by_scene_table",
        selection_reason="first_candidate_for_scene_query",
    )


def _voiceover_segment(
    order_index: int = 0, language: str = "en"
) -> VoiceoverSegment:
    segment = _segment(order_index)
    return VoiceoverSegment(
        scene_id=segment.scene_id,
        order_index=order_index,
        narration_text=segment.narration,
        language=language,
        voice_id="fake-narrator",
        provider="fake",
        audio_uri=(
            f"memory://voiceovers/run-1/{order_index:04d}/"
            f"{segment.scene_id}.mp3"
        ),
        content_type="audio/mpeg",
        duration_seconds=segment.target_duration_seconds,
        status="available",
        generation_reason="fake_generation",
    )


def _seed_plan(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    segments: tuple[VideoAssemblySegment, ...] = (_segment(0), _segment(1)),
) -> None:
    CreateVideoAssemblyPlan(
        runs,
        assets,
        storage,
        asset_id_factory=lambda: "video-assembly-plan-1",
    ).execute("run-1", segments, source="generated")


def _generate_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    generator: FakeVoiceoverGenerator,
) -> GenerateVoiceover:
    return GenerateVoiceover(
        runs,
        generator,
        GetLatestVideoAssemblyPlan(assets, storage),
        _create_use_case(runs, assets, storage),
    )


def test_create_versions_json_manifest_and_latest_round_trip() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    create = _create_use_case(runs, assets, storage)

    first = create.execute("run-1", (_voiceover_segment(0),))
    second = create.execute("run-1", (_voiceover_segment(1),))

    assert first.kind is AssetKind.VOICEOVER
    assert (first.version, second.version) == (1, 2)
    assert first.metadata == {"source": "manual"}
    assert [asset.version for asset in ListVoiceovers(assets).execute(
        "run-1"
    )] == [1, 2]
    latest = GetLatestVoiceover(assets, storage).execute("run-1")
    assert latest.asset == second
    assert latest.segments == (_voiceover_segment(1),)
    payload = json.loads(storage.saved[first.uri].decode("utf-8"))
    assert isinstance(payload, list)
    assert isinstance(payload[0]["duration_seconds"], float)
    assert isinstance(payload[0]["order_index"], int)
    assert payload[0]["audio_uri"].startswith("memory://voiceovers/")
    assert runs.get("run-1").status is RunStatus.SCENES_APPROVED


@pytest.mark.parametrize(
    "status",
    [status for status in RunStatus if status is not RunStatus.SCENES_APPROVED],
)
def test_create_rejects_every_status_except_scenes_approved(
    status: RunStatus,
) -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, status)

    with pytest.raises(AssetCreationRejectedError) as exc_info:
        _create_use_case(runs, assets, storage).execute(
            "run-1", (_voiceover_segment(),)
        )

    assert exc_info.value.kind is AssetKind.VOICEOVER
    assert assets.list_for_run("run-1", AssetKind.VOICEOVER) == []
    assert storage.saved == {}


def test_create_raises_when_run_is_missing() -> None:
    runs, assets, storage = _triple()

    with pytest.raises(RunNotFoundError):
        _create_use_case(runs, assets, storage).execute(
            "missing", (_voiceover_segment(),)
        )


def test_generate_calls_generator_in_order_with_run_language() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, language="te")
    _seed_plan(runs, assets, storage)
    generator = FakeVoiceoverGenerator(
        (_voiceover_segment(0, "te"), _voiceover_segment(1, "te"))
    )

    asset = _generate_use_case(runs, assets, storage, generator).execute("run-1")

    assert generator.calls == [
        ("run-1", _segment(0), "te"),
        ("run-1", _segment(1), "te"),
    ]
    assert asset.metadata == {
        "video_assembly_plan_asset_id": "video-assembly-plan-1",
        "video_assembly_plan_version": "1",
        "language": "te",
        "source": "generated",
    }
    assert all(isinstance(value, str) for value in asset.metadata.values())
    voiceover = GetLatestVoiceover(assets, storage).execute("run-1")
    assert voiceover.segments == (
        _voiceover_segment(0, "te"),
        _voiceover_segment(1, "te"),
    )
    assert all(segment.language == "te" for segment in voiceover.segments)
    assert runs.get("run-1").status is RunStatus.SCENES_APPROVED


def test_generate_empty_plan_persists_empty_manifest_without_call() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    _seed_plan(runs, assets, storage, segments=())
    generator = FakeVoiceoverGenerator()

    asset = _generate_use_case(runs, assets, storage, generator).execute("run-1")

    assert asset.kind is AssetKind.VOICEOVER
    assert generator.calls == []
    assert GetLatestVoiceover(assets, storage).execute("run-1").segments == ()
    assert runs.get("run-1").status is RunStatus.SCENES_APPROVED


def test_generate_invalid_status_wins_over_missing_plan() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.CREATED)
    generator = FakeVoiceoverGenerator()

    with pytest.raises(AssetCreationRejectedError) as exc_info:
        _generate_use_case(runs, assets, storage, generator).execute("run-1")

    assert exc_info.value.kind is AssetKind.VOICEOVER
    assert generator.calls == []
    assert assets.list_for_run("run-1", AssetKind.VOICEOVER) == []


def test_generate_missing_plan_raises_naturally() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    generator = FakeVoiceoverGenerator()

    with pytest.raises(AssetNotFoundError) as exc_info:
        _generate_use_case(runs, assets, storage, generator).execute("run-1")

    assert exc_info.value.kind is AssetKind.VIDEO_ASSEMBLY_PLAN
    assert generator.calls == []
    assert assets.list_for_run("run-1", AssetKind.VOICEOVER) == []


def test_generate_missing_run_raises_before_plan_read() -> None:
    runs, assets, storage = _triple()
    generator = FakeVoiceoverGenerator()

    with pytest.raises(RunNotFoundError):
        _generate_use_case(runs, assets, storage, generator).execute("missing")

    assert generator.calls == []


def test_latest_raises_when_voiceover_is_missing() -> None:
    _, assets, storage = _triple()

    with pytest.raises(AssetNotFoundError) as exc_info:
        GetLatestVoiceover(assets, storage).execute("run-1")

    assert exc_info.value.kind is AssetKind.VOICEOVER
