"""Scene table asset use-cases.

The caller supplies the ``SceneSpec`` sequence (no LLM scene generation in this
phase). These use-cases compose the ``RunRepository`` (lifecycle),
``StoragePort`` (durable bytes), and ``VersionedAssetRepository`` (version
index/metadata) ports and enforce the D7 scene-table rule in the application
layer, never in API routes. The scene table is stored as one versioned JSON
asset (D3); JSON (de)serialization stays in the application (D4), keeping the
domain ``SceneSpec`` serialization-free.
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
from backend.app.domain import AssetKind, Run, RunStatus, SceneSpec, VersionedAsset
from backend.app.ports import RunRepository, StoragePort, VersionedAssetRepository

AssetIdFactory = Callable[[], str]

# D7: a scene table requires an approved script and is only (re)created while
# scenes are still being drafted. Before approval the script must come first;
# at or past scene approval (or terminal) creation is rejected for now.
_SCENE_TABLE_ALLOWED = frozenset(
    {RunStatus.SCRIPT_APPROVED, RunStatus.SCENES_READY}
)


class SceneTable(NamedTuple):
    """Read model bundling the stored asset with its parsed scenes."""

    asset: VersionedAsset
    scenes: tuple[SceneSpec, ...]


class CreateSceneTable:
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
        self, run_id: str, scenes: Sequence[SceneSpec]
    ) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        if run.status not in _SCENE_TABLE_ALLOWED:
            raise AssetCreationRejectedError(
                run_id, AssetKind.SCENE_TABLE, run.status
            )

        version = self._asset_repository.next_version(
            run_id, AssetKind.SCENE_TABLE
        )
        table = VersionedAsset(
            asset_id=self._asset_id_factory(),
            kind=AssetKind.SCENE_TABLE,
            version=version,
            uri="",
            metadata={"source": "manual"},
        )
        stored = self._storage.save_asset(table, _scenes_to_bytes(scenes))
        self._asset_repository.save(run_id, stored)

        # Only advance the lifecycle when the status actually changes (D7): a
        # second scene table while already ``scenes_ready`` must NOT call a
        # self-transition, which the domain would reject.
        if run.status is RunStatus.SCRIPT_APPROVED:
            self._run_repository.save(run.mark_scenes_ready())

        return stored


class ListSceneTables:
    def __init__(self, asset_repository: VersionedAssetRepository) -> None:
        self._asset_repository = asset_repository

    def execute(self, run_id: str) -> Sequence[VersionedAsset]:
        return self._asset_repository.list_for_run(run_id, AssetKind.SCENE_TABLE)


class GetLatestSceneTable:
    def __init__(
        self,
        asset_repository: VersionedAssetRepository,
        storage: StoragePort,
    ) -> None:
        self._asset_repository = asset_repository
        self._storage = storage

    def execute(self, run_id: str) -> SceneTable:
        latest = self._asset_repository.get_latest(run_id, AssetKind.SCENE_TABLE)
        if latest is None:
            raise AssetNotFoundError(run_id, AssetKind.SCENE_TABLE)
        scenes = _scenes_from_bytes(self._storage.load_asset(latest))
        return SceneTable(asset=latest, scenes=scenes)


def _scenes_to_bytes(scenes: Sequence[SceneSpec]) -> bytes:
    """Serialize scenes to JSON bytes (domain stays serialization-free)."""
    payload = [
        {
            "scene_id": scene.scene_id,
            "narration": scene.narration,
            "visual_query": scene.visual_query,
            "duration_seconds": scene.duration_seconds,
        }
        for scene in scenes
    ]
    return json.dumps(payload).encode("utf-8")


def _scenes_from_bytes(data: bytes) -> tuple[SceneSpec, ...]:
    """Parse JSON bytes back into a ``SceneSpec`` tuple (validation in app)."""
    payload = json.loads(data.decode("utf-8"))
    return tuple(
        SceneSpec(
            scene_id=item["scene_id"],
            narration=item["narration"],
            visual_query=item["visual_query"],
            duration_seconds=item["duration_seconds"],
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
