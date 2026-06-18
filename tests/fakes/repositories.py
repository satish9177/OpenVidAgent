"""Fake repositories for application tests."""

from __future__ import annotations

from collections.abc import Sequence

from backend.app.domain import AssetKind, Run, VersionedAsset
from backend.app.ports import RunRepository, VersionedAssetRepository


class InMemoryRunRepository(RunRepository):
    def __init__(self) -> None:
        self.saved: dict[str, Run] = {}

    def get(self, run_id: str) -> Run | None:
        return self.saved.get(run_id)

    def save(self, run: Run) -> None:
        self.saved[run.run_id] = run


class InMemoryVersionedAssetRepository(VersionedAssetRepository):
    def __init__(self) -> None:
        self.saved: dict[tuple[str, AssetKind], list[VersionedAsset]] = {}

    def save(self, run_id: str, asset: VersionedAsset) -> None:
        self.saved.setdefault((run_id, asset.kind), []).append(asset)

    def get_latest(self, run_id: str, kind: AssetKind) -> VersionedAsset | None:
        versions = self.saved.get((run_id, kind))
        if not versions:
            return None
        return max(versions, key=lambda asset: asset.version)

    def list_for_run(
        self, run_id: str, kind: AssetKind
    ) -> Sequence[VersionedAsset]:
        return sorted(
            self.saved.get((run_id, kind), []), key=lambda asset: asset.version
        )

    def next_version(self, run_id: str, kind: AssetKind) -> int:
        versions = self.saved.get((run_id, kind), [])
        return max((asset.version for asset in versions), default=0) + 1
