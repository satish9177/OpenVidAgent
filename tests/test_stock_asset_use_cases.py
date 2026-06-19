"""Stock plan asset use-case tests."""

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
    CreateStockPlan,
    GetLatestStockPlan,
    ListStockPlans,
)
from backend.app.domain import AssetKind, Run, RunStatus, StockQuerySpec
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
    status: RunStatus = RunStatus.SCENES_APPROVED,
    run_id: str = "run-1",
) -> Run:
    run = Run(run_id=run_id, prompt="prompt", status=status)
    runs.save(run)
    return run


def _create_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
) -> CreateStockPlan:
    ids = (f"stock-plan-{n}" for n in itertools.count(1))
    return CreateStockPlan(
        runs, assets, storage, asset_id_factory=lambda: next(ids)
    )


def _queries() -> tuple[StockQuerySpec, ...]:
    return (
        StockQuerySpec(
            scene_id="scene-1",
            query="city skyline sunrise",
            visual_intent="Open with an establishing city shot.",
            duration_seconds=4.0,
        ),
        StockQuerySpec(
            scene_id="scene-2",
            query="focused office work",
            visual_intent="Show the user solving the problem.",
            duration_seconds=5.25,
            provider_hint=None,
        ),
    )


def test_create_persists_stock_plan_tagged_manual_by_default() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)

    plan = _create_use_case(runs, assets, storage).execute("run-1", _queries())

    assert plan.kind is AssetKind.STOCK_PLAN
    assert plan.version == 1
    assert plan.uri
    assert plan.metadata == {"source": "manual"}
    assert list(assets.list_for_run("run-1", AssetKind.STOCK_PLAN)) == [plan]


def test_second_create_increments_version_and_keeps_scenes_approved() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    create = _create_use_case(runs, assets, storage)

    first = create.execute("run-1", _queries())
    run_after_first = runs.get("run-1")
    second = create.execute("run-1", _queries())
    run_after_second = runs.get("run-1")

    assert (first.version, second.version) == (1, 2)
    assert run_after_second is not None
    assert run_after_second.status is RunStatus.SCENES_APPROVED
    assert run_after_second == run_after_first
    assert [
        asset.version
        for asset in assets.list_for_run("run-1", AssetKind.STOCK_PLAN)
    ] == [1, 2]


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
def test_create_rejects_every_status_except_scenes_approved(
    status: RunStatus,
) -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, status)

    with pytest.raises(AssetCreationRejectedError) as exc_info:
        _create_use_case(runs, assets, storage).execute("run-1", _queries())

    assert exc_info.value.status is status
    assert exc_info.value.kind is AssetKind.STOCK_PLAN
    assert list(assets.list_for_run("run-1", AssetKind.STOCK_PLAN)) == []
    assert storage.saved == {}


def test_create_raises_run_not_found_when_run_missing() -> None:
    runs, assets, storage = _triple()

    with pytest.raises(RunNotFoundError, match="Run 'missing' was not found"):
        _create_use_case(runs, assets, storage).execute("missing", _queries())


def test_list_returns_ordered_stock_plan_versions() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    create = _create_use_case(runs, assets, storage)

    first = create.execute("run-1", _queries())
    second = create.execute("run-1", _queries())

    assert list(ListStockPlans(assets).execute("run-1")) == [first, second]


def test_get_latest_raises_asset_not_found_when_none_exists() -> None:
    _, assets, storage = _triple()

    with pytest.raises(AssetNotFoundError) as exc_info:
        GetLatestStockPlan(assets, storage).execute("run-1")

    assert exc_info.value.kind is AssetKind.STOCK_PLAN


def test_stock_plan_bytes_are_persisted_as_valid_json() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)

    stored = _create_use_case(runs, assets, storage).execute("run-1", _queries())

    payload = json.loads(storage.saved[stored.uri].decode("utf-8"))
    assert isinstance(payload, list)
    assert [item["scene_id"] for item in payload] == ["scene-1", "scene-2"]
    assert payload[0]["query"] == "city skyline sunrise"
    assert payload[1]["provider_hint"] is None


def test_round_trip_identity_of_stock_query_spec_tuple() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    queries = (
        StockQuerySpec(
            scene_id="s1",
            query="cafe counter closeup",
            visual_intent="Show the setup with warm practical lighting.",
            duration_seconds=12.25,
            provider_hint=None,
        ),
        StockQuerySpec(
            scene_id="s2",
            query="quiet product workflow",
            visual_intent="Show the workflow result on screen.",
            duration_seconds=0.5,
        ),
    )

    _create_use_case(runs, assets, storage).execute("run-1", queries)

    result = GetLatestStockPlan(assets, storage).execute("run-1")
    assert result.queries == queries
    assert isinstance(result.queries[0].duration_seconds, float)
    assert result.queries[0].provider_hint is None
    asset, parsed = result
    assert asset.kind is AssetKind.STOCK_PLAN
    assert parsed == queries


def test_get_latest_returns_newest_stock_plan_version() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    create = _create_use_case(runs, assets, storage)

    create.execute("run-1", _queries())
    create.execute(
        "run-1",
        (
            StockQuerySpec(
                scene_id="scene-new",
                query="new query",
                visual_intent="new intent",
                duration_seconds=1.5,
            ),
        ),
    )

    result = GetLatestStockPlan(assets, storage).execute("run-1")
    assert result.asset.version == 2
    assert result.queries[0].scene_id == "scene-new"
