"""Video assembly plan asset use-case tests."""

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
    CreateSceneTable,
    CreateSelectedClipSet,
    CreateVideoAssemblyPlan,
    GenerateVideoAssemblyPlan,
    GetLatestSceneTable,
    GetLatestSelectedClipSet,
    GetLatestVideoAssemblyPlan,
    ListVideoAssemblyPlans,
)
from backend.app.domain import (
    AssetKind,
    Run,
    RunStatus,
    SceneSpec,
    SelectedClip,
    VideoAssemblySegment,
)
from tests.fakes import (
    FakeVideoAssemblyPlanner,
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
) -> Run:
    run = Run(run_id="run-1", prompt="prompt", status=status)
    runs.save(run)
    return run


def _create_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
) -> CreateVideoAssemblyPlan:
    ids = (f"video-assembly-plan-{n}" for n in itertools.count(1))
    return CreateVideoAssemblyPlan(
        runs, assets, storage, asset_id_factory=lambda: next(ids)
    )


def _scene() -> SceneSpec:
    return SceneSpec(
        scene_id="scene-1",
        narration="A local-first video workflow takes shape.",
        visual_query="editor arranging video clips",
        duration_seconds=4.0,
    )


def _selected_clip() -> SelectedClip:
    return SelectedClip(
        scene_id="scene-1",
        query_text="editor arranging video clips",
        provider="fake",
        provider_clip_id="scene-1-fake-1",
        title="Editor arranging video clips",
        preview_url="memory://clips/scene-1/preview.jpg",
        source_url="memory://clips/scene-1",
        duration_seconds=8.5,
        width=1920,
        height=1080,
        selection_reason="first_candidate_for_scene_query",
    )


def _segment(order_index: int = 0) -> VideoAssemblySegment:
    return VideoAssemblySegment(
        scene_id="scene-1",
        query_text="editor arranging video clips",
        narration="A local-first video workflow takes shape.",
        visual_query="editor arranging video clips",
        provider="fake",
        provider_clip_id="scene-1-fake-1",
        title="Editor arranging video clips",
        preview_url="memory://clips/scene-1/preview.jpg",
        source_url="memory://clips/scene-1",
        target_duration_seconds=4.0,
        source_duration_seconds=8.5,
        width=1920,
        height=1080,
        order_index=order_index,
        transition="cut",
        continuity_note="ordered_by_scene_table",
        selection_reason="first_candidate_for_scene_query",
    )


def _seed_dependencies(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
) -> tuple[str, str]:
    runs.save(Run(run_id="run-1", prompt="prompt", status=RunStatus.SCENES_READY))
    scene_asset = CreateSceneTable(
        runs,
        assets,
        storage,
        asset_id_factory=lambda: "scene-table-1",
    ).execute("run-1", (_scene(),))
    runs.save(
        Run(run_id="run-1", prompt="prompt", status=RunStatus.SCENES_APPROVED)
    )
    selected_asset = CreateSelectedClipSet(
        runs,
        assets,
        storage,
        asset_id_factory=lambda: "selected-clips-1",
    ).execute("run-1", (_selected_clip(),))
    return scene_asset.asset_id, selected_asset.asset_id


def _generate_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    planner: FakeVideoAssemblyPlanner,
) -> GenerateVideoAssemblyPlan:
    return GenerateVideoAssemblyPlan(
        runs,
        planner,
        GetLatestSelectedClipSet(assets, storage),
        GetLatestSceneTable(assets, storage),
        _create_use_case(runs, assets, storage),
    )


def test_create_versions_json_metadata_and_latest_round_trip() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    create = _create_use_case(runs, assets, storage)

    first = create.execute("run-1", (_segment(),))
    second = create.execute("run-1", (_segment(order_index=1),))

    assert first.kind is AssetKind.VIDEO_ASSEMBLY_PLAN
    assert (first.version, second.version) == (1, 2)
    assert first.metadata == {
        "source": "manual",
        "aspect_ratio": "16:9",
        "render_intent": "voiceover_b_roll",
    }
    assert [asset.version for asset in ListVideoAssemblyPlans(assets).execute(
        "run-1"
    )] == [1, 2]
    latest = GetLatestVideoAssemblyPlan(assets, storage).execute("run-1")
    assert latest.asset == second
    assert latest.segments == (_segment(order_index=1),)
    payload = json.loads(storage.saved[first.uri].decode("utf-8"))
    assert isinstance(payload, list)
    assert isinstance(payload[0]["target_duration_seconds"], float)
    assert isinstance(payload[0]["source_duration_seconds"], float)
    assert isinstance(payload[0]["width"], int)
    assert isinstance(payload[0]["order_index"], int)
    assert runs.get("run-1").status is RunStatus.SCENES_APPROVED


def test_create_merges_extra_metadata_but_keeps_fixed_values() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)

    asset = _create_use_case(runs, assets, storage).execute(
        "run-1",
        (_segment(),),
        source="generated",
        asset_metadata={
            "scene_table_version": "7",
            "source": "overridden",
            "aspect_ratio": "1:1",
        },
    )

    assert asset.metadata == {
        "scene_table_version": "7",
        "source": "generated",
        "aspect_ratio": "16:9",
        "render_intent": "voiceover_b_roll",
    }


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
        _create_use_case(runs, assets, storage).execute("run-1", (_segment(),))

    assert exc_info.value.kind is AssetKind.VIDEO_ASSEMBLY_PLAN
    assert assets.list_for_run("run-1", AssetKind.VIDEO_ASSEMBLY_PLAN) == []
    assert storage.saved == {}


def test_create_raises_when_run_is_missing() -> None:
    runs, assets, storage = _triple()

    with pytest.raises(RunNotFoundError):
        _create_use_case(runs, assets, storage).execute("missing", (_segment(),))


def test_generate_reads_latest_inputs_once_and_stores_string_provenance() -> None:
    runs, assets, storage = _triple()
    scene_asset_id, selected_asset_id = _seed_dependencies(runs, assets, storage)
    planner = FakeVideoAssemblyPlanner((_segment(),))

    asset = _generate_use_case(runs, assets, storage, planner).execute("run-1")

    assert len(planner.calls) == 1
    scenes, selected_clips = planner.calls[0]
    assert scenes == (_scene(),)
    assert selected_clips == (_selected_clip(),)
    assert asset.metadata == {
        "scene_table_asset_id": scene_asset_id,
        "scene_table_version": "1",
        "selected_clips_asset_id": selected_asset_id,
        "selected_clips_version": "1",
        "source": "generated",
        "aspect_ratio": "16:9",
        "render_intent": "voiceover_b_roll",
    }
    assert all(isinstance(value, str) for value in asset.metadata.values())
    assert runs.get("run-1").status is RunStatus.SCENES_APPROVED


def test_generate_rejects_invalid_status_before_dependency_reads() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.CREATED)
    planner = FakeVideoAssemblyPlanner((_segment(),))

    with pytest.raises(AssetCreationRejectedError):
        _generate_use_case(runs, assets, storage, planner).execute("run-1")

    assert planner.calls == []
    assert assets.list_for_run("run-1", AssetKind.VIDEO_ASSEMBLY_PLAN) == []
    assert storage.saved == {}


def test_generate_raises_when_run_is_missing_before_dependencies() -> None:
    runs, assets, storage = _triple()
    planner = FakeVideoAssemblyPlanner((_segment(),))

    with pytest.raises(RunNotFoundError):
        _generate_use_case(runs, assets, storage, planner).execute("missing")

    assert planner.calls == []


def test_generate_naturally_raises_when_selected_clips_are_missing() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    planner = FakeVideoAssemblyPlanner((_segment(),))

    with pytest.raises(AssetNotFoundError) as exc_info:
        _generate_use_case(runs, assets, storage, planner).execute("run-1")

    assert exc_info.value.kind is AssetKind.SELECTED_CLIPS
    assert planner.calls == []
    assert assets.list_for_run("run-1", AssetKind.VIDEO_ASSEMBLY_PLAN) == []


def test_generate_raises_for_missing_scene_table_after_selected_clips() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    CreateSelectedClipSet(
        runs,
        assets,
        storage,
        asset_id_factory=lambda: "selected-clips-1",
    ).execute("run-1", (_selected_clip(),))
    planner = FakeVideoAssemblyPlanner((_segment(),))

    with pytest.raises(AssetNotFoundError) as exc_info:
        _generate_use_case(runs, assets, storage, planner).execute("run-1")

    assert exc_info.value.kind is AssetKind.SCENE_TABLE
    assert planner.calls == []
    assert assets.list_for_run("run-1", AssetKind.VIDEO_ASSEMBLY_PLAN) == []


def test_latest_raises_when_video_assembly_plan_is_missing() -> None:
    _, assets, storage = _triple()

    with pytest.raises(AssetNotFoundError) as exc_info:
        GetLatestVideoAssemblyPlan(assets, storage).execute("run-1")

    assert exc_info.value.kind is AssetKind.VIDEO_ASSEMBLY_PLAN
