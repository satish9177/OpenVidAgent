"""Stock plan asset use-cases.

``CreateStockPlan`` persists caller-supplied ``StockQuerySpec`` entries;
``GenerateStockPlan`` first obtains those entries from the ``StockClipPlanner``
port and then composes ``CreateStockPlan``. These use-cases enforce the D9
asset-only rule in the application layer: stock plans may be created only when
scenes are approved, and creating one never transitions the run.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import NamedTuple
from uuid import uuid4

from backend.app.application.errors import (
    AssetCreationRejectedError,
    AssetNotFoundError,
    RunNotFoundError,
)
from backend.app.application.use_cases.scene_assets import GetLatestSceneTable
from backend.app.domain import (
    AssetKind,
    Run,
    RunStatus,
    StockQuerySpec,
    VersionedAsset,
)
from backend.app.ports import (
    RunRepository,
    StockClipPlanner,
    StoragePort,
    VersionedAssetRepository,
)

AssetIdFactory = Callable[[], str]

# D9: stock planning is asset-only and allowed only after scene approval.
_STOCK_PLAN_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})


class StockPlan(NamedTuple):
    """Read model bundling the stored asset with its parsed stock queries."""

    asset: VersionedAsset
    queries: tuple[StockQuerySpec, ...]


class CreateStockPlan:
    def __init__(
        self,
        run_repository: RunRepository,
        asset_repository: VersionedAssetRepository,
        storage: StoragePort,
        asset_id_factory: AssetIdFactory | None = None,
    ) -> None:
        self._run_repository = run_repository
        self._asset_repository = asset_repository
        self._storage = storage
        self._asset_id_factory = asset_id_factory or _new_asset_id

    def execute(
        self,
        run_id: str,
        queries: Sequence[StockQuerySpec],
        source: str = "manual",
    ) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        if run.status not in _STOCK_PLAN_ALLOWED:
            raise AssetCreationRejectedError(
                run_id, AssetKind.STOCK_PLAN, run.status
            )

        version = self._asset_repository.next_version(
            run_id, AssetKind.STOCK_PLAN
        )
        plan = VersionedAsset(
            asset_id=self._asset_id_factory(),
            kind=AssetKind.STOCK_PLAN,
            version=version,
            uri="",
            metadata={"source": source},
        )
        stored = self._storage.save_asset(plan, _queries_to_bytes(queries))
        self._asset_repository.save(run_id, stored)
        return stored


class GenerateStockPlan:
    """Plan stock search queries from the latest approved scene table."""

    def __init__(
        self,
        run_repository: RunRepository,
        stock_planner: StockClipPlanner,
        get_latest_scene_table: GetLatestSceneTable,
        create_stock_plan: CreateStockPlan,
    ) -> None:
        self._run_repository = run_repository
        self._stock_planner = stock_planner
        self._get_latest_scene_table = get_latest_scene_table
        self._create_stock_plan = create_stock_plan

    def execute(self, run_id: str) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        if run.status not in _STOCK_PLAN_ALLOWED:
            raise AssetCreationRejectedError(
                run_id, AssetKind.STOCK_PLAN, run.status
            )

        scene_table = self._get_latest_scene_table.execute(run_id)
        queries = self._stock_planner.plan_stock_clips(
            scene_table.scenes, run.language
        )
        return self._create_stock_plan.execute(
            run_id, queries, source="generated"
        )


class ListStockPlans:
    def __init__(self, asset_repository: VersionedAssetRepository) -> None:
        self._asset_repository = asset_repository

    def execute(self, run_id: str) -> Sequence[VersionedAsset]:
        return self._asset_repository.list_for_run(run_id, AssetKind.STOCK_PLAN)


class GetLatestStockPlan:
    def __init__(
        self,
        asset_repository: VersionedAssetRepository,
        storage: StoragePort,
    ) -> None:
        self._asset_repository = asset_repository
        self._storage = storage

    def execute(self, run_id: str) -> StockPlan:
        latest = self._asset_repository.get_latest(run_id, AssetKind.STOCK_PLAN)
        if latest is None:
            raise AssetNotFoundError(run_id, AssetKind.STOCK_PLAN)
        queries = _queries_from_bytes(self._storage.load_asset(latest))
        return StockPlan(asset=latest, queries=queries)


def _queries_to_bytes(queries: Sequence[StockQuerySpec]) -> bytes:
    """Serialize stock query specs to JSON bytes."""
    payload = [
        {
            "scene_id": query.scene_id,
            "query": query.query,
            "visual_intent": query.visual_intent,
            "duration_seconds": query.duration_seconds,
            "provider_hint": query.provider_hint,
        }
        for query in queries
    ]
    return json.dumps(payload).encode("utf-8")


def _queries_from_bytes(data: bytes) -> tuple[StockQuerySpec, ...]:
    """Parse JSON bytes back into a ``StockQuerySpec`` tuple."""
    payload = json.loads(data.decode("utf-8"))
    return tuple(
        StockQuerySpec(
            scene_id=item["scene_id"],
            query=item["query"],
            visual_intent=item["visual_intent"],
            duration_seconds=float(item["duration_seconds"]),
            provider_hint=item.get("provider_hint"),
        )
        for item in payload
    )


def _require_run(repository: RunRepository, run_id: str) -> Run:
    run = repository.get(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    return run


def _new_asset_id() -> str:
    return str(uuid4())
