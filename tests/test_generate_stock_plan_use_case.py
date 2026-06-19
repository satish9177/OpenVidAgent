"""GenerateStockPlan use-case tests."""

from __future__ import annotations

import itertools
from collections.abc import Sequence

import pytest

from backend.app.application.errors import (
    AssetCreationRejectedError,
    RunNotFoundError,
)
from backend.app.application.use_cases import (
    CreateSceneTable,
    CreateStockPlan,
    GenerateStockPlan,
    GetLatestSceneTable,
    GetLatestStockPlan,
)
from backend.app.domain import (
    AssetKind,
    Run,
    RunStatus,
    SceneSpec,
    StockQuerySpec,
)
from backend.app.ports import StockClipPlanner
from tests.fakes import (
    InMemoryRunRepository,
    InMemoryStorage,
    InMemoryVersionedAssetRepository,
)


class _RecordingStockClipPlanner(StockClipPlanner):
    def __init__(self, queries: Sequence[StockQuerySpec] | None = None) -> None:
        self._queries: tuple[StockQuerySpec, ...] = (
            tuple(queries)
            if queries is not None
            else (
                StockQuerySpec(
                    scene_id="scene-1",
                    query="generated stock query",
                    visual_intent="generated visual intent",
                    duration_seconds=4.0,
                ),
            )
        )
        self.calls: list[tuple[tuple[SceneSpec, ...], str]] = []

    def plan_stock_clips(
        self, scenes: Sequence[SceneSpec], language: str
    ) -> Sequence[StockQuerySpec]:
        self.calls.append((tuple(scenes), language))
        return self._queries


class _RecordingSceneTableReader:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, run_id: str) -> object:
        self.calls.append(run_id)
        raise AssertionError("scene-table reader should not be called")


def _triple() -> tuple[
    InMemoryRunRepository, InMemoryVersionedAssetRepository, InMemoryStorage
]:
    return (
        InMemoryRunRepository(),
        InMemoryVersionedAssetRepository(),
        InMemoryStorage(),
    )


def _scenes() -> tuple[SceneSpec, ...]:
    return (
        SceneSpec(
            scene_id="scene-1",
            narration="Show the city waking up.",
            visual_query="city sunrise timelapse",
            duration_seconds=4.5,
        ),
        SceneSpec(
            scene_id="scene-2",
            narration="Show focused work on a laptop.",
            visual_query="person working on laptop",
            duration_seconds=3.25,
        ),
    )


def _seed_scenes_approved_run_with_scene_table(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    *,
    scenes: Sequence[SceneSpec] | None = None,
    language: str = "en",
    run_id: str = "run-1",
) -> Run:
    run = Run(
        run_id=run_id,
        prompt="prompt",
        language=language,
        status=RunStatus.SCRIPT_APPROVED,
        approved_script="approved script",
    )
    runs.save(run)
    CreateSceneTable(
        runs,
        assets,
        storage,
        asset_id_factory=lambda: f"{run_id}-scene-table",
    ).execute(run_id, tuple(scenes) if scenes is not None else _scenes())
    scenes_ready = runs.get(run_id)
    assert scenes_ready is not None
    scenes_approved = scenes_ready.approve_scenes()
    runs.save(scenes_approved)
    return scenes_approved


def _generate_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    planner: StockClipPlanner,
) -> GenerateStockPlan:
    ids = (f"stock-plan-{n}" for n in itertools.count(1))
    create = CreateStockPlan(
        runs, assets, storage, asset_id_factory=lambda: next(ids)
    )
    return GenerateStockPlan(
        runs, planner, GetLatestSceneTable(assets, storage), create
    )


def test_generate_forwards_latest_scene_table_scenes_and_language_to_planner() -> None:
    runs, assets, storage = _triple()
    scenes = _scenes()
    _seed_scenes_approved_run_with_scene_table(
        runs, assets, storage, scenes=scenes, language="fr"
    )
    planner = _RecordingStockClipPlanner()

    _generate_use_case(runs, assets, storage, planner).execute("run-1")

    assert planner.calls == [(scenes, "fr")]


def test_generate_persists_stock_plan_tagged_generated() -> None:
    runs, assets, storage = _triple()
    _seed_scenes_approved_run_with_scene_table(runs, assets, storage)
    planned_queries = (
        StockQuerySpec(
            scene_id="scene-1",
            query="generated skyline search",
            visual_intent="generated skyline intent",
            duration_seconds=4.5,
            provider_hint=None,
        ),
        StockQuerySpec(
            scene_id="scene-2",
            query="generated laptop search",
            visual_intent="generated laptop intent",
            duration_seconds=3.25,
        ),
    )
    planner = _RecordingStockClipPlanner(planned_queries)

    asset = _generate_use_case(runs, assets, storage, planner).execute("run-1")

    assert asset.kind is AssetKind.STOCK_PLAN
    assert asset.version == 1
    assert asset.metadata == {"source": "generated"}
    assert list(assets.list_for_run("run-1", AssetKind.STOCK_PLAN)) == [asset]
    assert GetLatestStockPlan(assets, storage).execute("run-1").queries == (
        planned_queries
    )


def test_generate_second_plan_increments_version_and_keeps_scenes_approved() -> None:
    runs, assets, storage = _triple()
    _seed_scenes_approved_run_with_scene_table(runs, assets, storage)
    use_case = _generate_use_case(
        runs, assets, storage, _RecordingStockClipPlanner()
    )

    first = use_case.execute("run-1")
    run_after_first = runs.get("run-1")
    second = use_case.execute("run-1")
    run_after_second = runs.get("run-1")

    assert (first.version, second.version) == (1, 2)
    assert second.metadata == {"source": "generated"}
    assert run_after_second is not None
    assert run_after_second.status is RunStatus.SCENES_APPROVED
    assert run_after_second == run_after_first
    assert [
        asset.version
        for asset in assets.list_for_run("run-1", AssetKind.STOCK_PLAN)
    ] == [1, 2]


def test_generate_raises_run_not_found_when_run_missing() -> None:
    runs, assets, storage = _triple()
    planner = _RecordingStockClipPlanner()
    reader = _RecordingSceneTableReader()
    create = CreateStockPlan(runs, assets, storage)
    use_case = GenerateStockPlan(runs, planner, reader, create)

    with pytest.raises(RunNotFoundError, match="Run 'missing' was not found"):
        use_case.execute("missing")

    assert reader.calls == []
    assert planner.calls == []
    assert list(assets.list_for_run("missing", AssetKind.STOCK_PLAN)) == []
    assert storage.saved == {}


@pytest.mark.parametrize(
    "status",
    [
        RunStatus.CREATED,
        RunStatus.SCRIPT_READY,
        RunStatus.SCRIPT_APPROVED,
        RunStatus.SCENES_READY,
        RunStatus.RENDERED,
        RunStatus.FAILED,
    ],
)
def test_generate_rejects_invalid_status_before_read_planning_or_persistence(
    status: RunStatus,
) -> None:
    runs, assets, storage = _triple()
    runs.save(Run(run_id="run-1", prompt="prompt", status=status))
    planner = _RecordingStockClipPlanner()
    reader = _RecordingSceneTableReader()
    create = CreateStockPlan(runs, assets, storage)
    use_case = GenerateStockPlan(runs, planner, reader, create)

    with pytest.raises(AssetCreationRejectedError) as exc_info:
        use_case.execute("run-1")

    assert exc_info.value.status is status
    assert exc_info.value.kind is AssetKind.STOCK_PLAN
    assert reader.calls == []
    assert planner.calls == []
    assert list(assets.list_for_run("run-1", AssetKind.STOCK_PLAN)) == []
    assert storage.saved == {}
