"""Render output manifest use-case tests."""

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
    CreateRenderOutput,
    CreateRenderPlan,
    GenerateRenderOutput,
    GetLatestRenderOutput,
    GetLatestRenderPlan,
    ListRenderOutputs,
)
from backend.app.domain import (
    AssetKind,
    RenderOutputManifest,
    RenderPlanSegment,
    Run,
    RunStatus,
)
from tests.fakes import (
    FakeRenderOutputGenerator,
    InMemoryRunRepository,
    InMemoryStorage,
    InMemoryVersionedAssetRepository,
)


PROFILE = {
    "render_intent": "cinematic_b_roll",
    "aspect_ratio": "9:16",
    "container": "mov",
    "resolution_width": "1080",
    "resolution_height": "1920",
    "fps": "24",
}


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
) -> None:
    runs.save(Run(run_id="run-1", prompt="prompt", status=status))


def _render_segment(index: int, visual_end: float) -> RenderPlanSegment:
    visual_start = max(0.0, visual_end - 4.0)
    return RenderPlanSegment(
        order_index=index,
        scene_id=f"scene-{index}",
        clip_uri=f"memory://downloads/{index}/clip.mp4",
        clip_provider="stub",
        clip_provider_id=f"clip-{index}",
        visual_start_seconds=visual_start,
        visual_end_seconds=visual_end,
        visual_duration_seconds=visual_end - visual_start,
        voiceover_uri=f"memory://voiceovers/{index}/voice.mp3",
        voiceover_start_seconds=visual_start,
        voiceover_end_seconds=visual_end,
        voiceover_duration_seconds=visual_end - visual_start,
        subtitle_text=f"Narration {index}",
        subtitle_start_seconds=visual_start,
        subtitle_end_seconds=visual_end,
        subtitle_language="en",
    )


def _manifest(
    *,
    asset_id: str = "render-plan-1",
    version: int = 1,
    segment_count: int = 2,
    duration: float = 8.0,
) -> RenderOutputManifest:
    return RenderOutputManifest(
        status="not_rendered",
        render_plan_asset_id=asset_id,
        render_plan_version=version,
        render_intent="cinematic_b_roll",
        aspect_ratio="9:16",
        container="mov",
        resolution_width=1080,
        resolution_height=1920,
        fps=24.0,
        segment_count=segment_count,
        estimated_duration_seconds=duration,
        output_uri=None,
        generation_reason="metadata_only_foundation",
    )


def _create_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
) -> CreateRenderOutput:
    ids = (f"render-output-{n}" for n in itertools.count(1))
    return CreateRenderOutput(
        runs, assets, storage, asset_id_factory=lambda: next(ids)
    )


def _seed_render_plan(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    *,
    segments: tuple[RenderPlanSegment, ...] = (
        _render_segment(0, 4.0),
        _render_segment(1, 8.0),
    ),
    metadata: dict[str, str] | None = None,
) -> None:
    CreateRenderPlan(
        runs,
        assets,
        storage,
        asset_id_factory=lambda: "render-plan-1",
    ).execute(
        "run-1",
        segments,
        source="generated",
        asset_metadata=metadata,
    )


def _generate_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    generator: FakeRenderOutputGenerator,
) -> GenerateRenderOutput:
    return GenerateRenderOutput(
        runs,
        generator,
        GetLatestRenderPlan(assets, storage),
        _create_use_case(runs, assets, storage),
    )


def test_create_versions_json_object_and_latest_round_trip() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    create = _create_use_case(runs, assets, storage)

    first = create.execute("run-1", _manifest())
    second = create.execute("run-1", _manifest(version=2))

    assert first.kind is AssetKind.RENDER_OUTPUT
    assert (first.version, second.version) == (1, 2)
    assert first.metadata == {"source": "manual"}
    assert [asset.version for asset in ListRenderOutputs(assets).execute(
        "run-1"
    )] == [1, 2]
    latest = GetLatestRenderOutput(assets, storage).execute("run-1")
    assert latest.asset == second
    assert latest.manifest == _manifest(version=2)
    payload = json.loads(storage.saved[first.uri].decode("utf-8"))
    assert isinstance(payload, dict)
    assert isinstance(payload["render_plan_version"], int)
    assert isinstance(payload["resolution_width"], int)
    assert isinstance(payload["fps"], float)
    assert isinstance(payload["segment_count"], int)
    assert isinstance(payload["estimated_duration_seconds"], float)
    assert payload["output_uri"] is None


def test_generate_uses_latest_plan_and_present_profile_values() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    _seed_render_plan(runs, assets, storage, metadata=PROFILE)
    generator = FakeRenderOutputGenerator(_manifest())

    asset = _generate_use_case(runs, assets, storage, generator).execute("run-1")

    segments = (_render_segment(0, 4.0), _render_segment(1, 8.0))
    assert generator.calls == [("render-plan-1", 1, segments, PROFILE)]
    assert asset.metadata == {
        "render_plan_asset_id": "render-plan-1",
        "render_plan_version": "1",
        "status": "not_rendered",
        **PROFILE,
        "source": "generated",
    }
    assert all(isinstance(value, str) for value in asset.metadata.values())
    assert runs.get("run-1").status is RunStatus.SCENES_APPROVED


def test_generate_resolves_missing_profile_defaults_and_allows_empty_plan() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    _seed_render_plan(runs, assets, storage, segments=(), metadata=None)
    generator = FakeRenderOutputGenerator(
        _manifest(segment_count=0, duration=0.0)
    )

    asset = _generate_use_case(runs, assets, storage, generator).execute("run-1")

    expected_profile = {
        "aspect_ratio": "16:9",
        "resolution_width": "1920",
        "resolution_height": "1080",
        "fps": "30",
        "container": "mp4",
        "render_intent": "voiceover_b_roll",
    }
    assert generator.calls == [("render-plan-1", 1, (), expected_profile)]
    assert asset.metadata["status"] == "not_rendered"


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
        _create_use_case(runs, assets, storage).execute("run-1", _manifest())

    assert exc_info.value.kind is AssetKind.RENDER_OUTPUT
    assert assets.list_for_run("run-1", AssetKind.RENDER_OUTPUT) == []
    assert storage.saved == {}


def test_generate_invalid_status_wins_over_missing_render_plan() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.CREATED)
    generator = FakeRenderOutputGenerator()

    with pytest.raises(AssetCreationRejectedError) as exc_info:
        _generate_use_case(runs, assets, storage, generator).execute("run-1")

    assert exc_info.value.kind is AssetKind.RENDER_OUTPUT
    assert generator.calls == []


def test_generate_missing_render_plan_raises_naturally() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    generator = FakeRenderOutputGenerator()

    with pytest.raises(AssetNotFoundError) as exc_info:
        _generate_use_case(runs, assets, storage, generator).execute("run-1")

    assert exc_info.value.kind is AssetKind.RENDER_PLAN
    assert generator.calls == []


def test_generate_missing_run_raises_before_render_plan_read() -> None:
    runs, assets, storage = _triple()
    generator = FakeRenderOutputGenerator()

    with pytest.raises(RunNotFoundError):
        _generate_use_case(runs, assets, storage, generator).execute("missing")

    assert generator.calls == []


def test_latest_raises_when_render_output_is_missing() -> None:
    _, assets, storage = _triple()

    with pytest.raises(AssetNotFoundError) as exc_info:
        GetLatestRenderOutput(assets, storage).execute("run-1")

    assert exc_info.value.kind is AssetKind.RENDER_OUTPUT
