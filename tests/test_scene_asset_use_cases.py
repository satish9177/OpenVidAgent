"""Scene table use-case tests (Slice 5)."""

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
    GetLatestSceneTable,
    ListSceneTables,
)
from backend.app.domain import AssetKind, Run, RunStatus, SceneSpec
from tests.fakes import (
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
    status: RunStatus,
    run_id: str = "run-1",
) -> Run:
    run = Run(run_id=run_id, prompt="prompt", status=status)
    runs.save(run)
    return run


def _create_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
) -> CreateSceneTable:
    ids = (f"scene-asset-{n}" for n in itertools.count(1))
    return CreateSceneTable(
        runs, assets, storage, asset_id_factory=lambda: next(ids)
    )


def _scenes() -> tuple[SceneSpec, ...]:
    return (
        SceneSpec(
            scene_id="scene-1",
            narration="Opening narration",
            visual_query="city skyline at dawn",
            duration_seconds=4.0,
        ),
        SceneSpec(
            scene_id="scene-2",
            narration="Closing narration",
            visual_query="quiet office desk",
            duration_seconds=3.5,
        ),
    )


def test_create_from_script_approved_transitions_to_scenes_ready() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.SCRIPT_APPROVED)

    table = _create_use_case(runs, assets, storage).execute("run-1", _scenes())

    assert table.kind is AssetKind.SCENE_TABLE
    assert table.version == 1
    assert table.uri  # populated by StoragePort
    assert table.metadata == {"source": "manual"}
    stored_run = runs.get("run-1")
    assert stored_run is not None
    assert stored_run.status is RunStatus.SCENES_READY


def test_second_create_increments_version_and_stays_scenes_ready() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.SCRIPT_APPROVED)
    create = _create_use_case(runs, assets, storage)

    first = create.execute("run-1", _scenes())
    run_after_first = runs.get("run-1")

    second = create.execute("run-1", _scenes())
    run_after_second = runs.get("run-1")

    assert first.version == 1
    assert second.version == 2
    # Same-status case: no self-transition attempted, run not mutated/re-saved.
    assert run_after_second is not None
    assert run_after_second.status is RunStatus.SCENES_READY
    assert run_after_second == run_after_first
    assert [
        asset.version
        for asset in assets.list_for_run("run-1", AssetKind.SCENE_TABLE)
    ] == [1, 2]


@pytest.mark.parametrize(
    "status",
    [
        RunStatus.CREATED,
        RunStatus.SCRIPT_READY,
        RunStatus.SCENES_APPROVED,
        RunStatus.RENDERED,
        RunStatus.FAILED,
    ],
)
def test_reject_when_status_not_allowed(status: RunStatus) -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, status)

    with pytest.raises(AssetCreationRejectedError) as exc_info:
        _create_use_case(runs, assets, storage).execute("run-1", _scenes())

    assert exc_info.value.status is status
    assert exc_info.value.kind is AssetKind.SCENE_TABLE
    # Rejection happens before any side effects.
    assert list(assets.list_for_run("run-1", AssetKind.SCENE_TABLE)) == []
    assert storage.saved == {}


def test_create_raises_run_not_found_when_run_missing() -> None:
    runs, assets, storage = _triple()

    with pytest.raises(RunNotFoundError, match="Run 'missing' was not found"):
        _create_use_case(runs, assets, storage).execute("missing", _scenes())


def test_get_latest_raises_asset_not_found_when_none_exists() -> None:
    _, assets, storage = _triple()

    with pytest.raises(AssetNotFoundError):
        GetLatestSceneTable(assets, storage).execute("run-1")


def test_list_returns_empty_when_no_scene_table() -> None:
    _, assets, _ = _triple()

    assert list(ListSceneTables(assets).execute("run-1")) == []


def test_scene_table_bytes_persisted_as_valid_json() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.SCRIPT_APPROVED)
    scenes = _scenes()

    stored = _create_use_case(runs, assets, storage).execute("run-1", scenes)

    payload = json.loads(storage.saved[stored.uri].decode("utf-8"))
    assert isinstance(payload, list)
    assert [item["scene_id"] for item in payload] == ["scene-1", "scene-2"]
    assert payload[0]["duration_seconds"] == 4.0


def test_round_trip_identity_of_scene_spec_tuple() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.SCRIPT_APPROVED)
    scenes = (
        SceneSpec(
            scene_id="s1",
            narration="café narration — 日本語",
            visual_query="emoji 🎬 query",
            duration_seconds=12.25,
        ),
        SceneSpec(
            scene_id="s2",
            narration="second",
            visual_query="q2",
            duration_seconds=0.5,
        ),
    )

    _create_use_case(runs, assets, storage).execute("run-1", scenes)

    result = GetLatestSceneTable(assets, storage).execute("run-1")
    assert result.scenes == scenes
    assert isinstance(result.scenes[0].duration_seconds, float)
    # NamedTuple destructuring works as a read model.
    asset, parsed = result
    assert asset.kind is AssetKind.SCENE_TABLE
    assert parsed == scenes


def test_get_latest_returns_newest_version() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.SCRIPT_APPROVED)
    create = _create_use_case(runs, assets, storage)

    create.execute("run-1", _scenes())
    create.execute("run-1", _scenes())

    result = GetLatestSceneTable(assets, storage).execute("run-1")
    assert result.asset.version == 2
