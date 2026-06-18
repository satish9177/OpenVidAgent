"""Port contract tests for VersionedAssetRepository (Slice 1)."""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from dataclasses import fields

from backend.app.domain import AssetKind, VersionedAsset
from backend.app.ports import VersionedAssetRepository


class _FakeVersionedAssetRepository:
    """Minimal in-test fake exercising the port contract.

    Slice 4 introduces a shared ``InMemoryVersionedAssetRepository`` fake; this
    local fake only proves the Slice 1 port shape is satisfiable.
    """

    def __init__(self) -> None:
        self._assets: dict[tuple[str, AssetKind], list[VersionedAsset]] = {}

    def save(self, run_id: str, asset: VersionedAsset) -> None:
        self._assets.setdefault((run_id, asset.kind), []).append(asset)

    def get_latest(self, run_id: str, kind: AssetKind) -> VersionedAsset | None:
        versions = self._assets.get((run_id, kind))
        if not versions:
            return None
        return max(versions, key=lambda asset: asset.version)

    def list_for_run(
        self, run_id: str, kind: AssetKind
    ) -> Sequence[VersionedAsset]:
        versions = self._assets.get((run_id, kind), [])
        return sorted(versions, key=lambda asset: asset.version)

    def next_version(self, run_id: str, kind: AssetKind) -> int:
        return len(self._assets.get((run_id, kind), [])) + 1


def _asset(version: int, kind: AssetKind = AssetKind.SCRIPT) -> VersionedAsset:
    return VersionedAsset(
        asset_id=f"asset-{kind.value}-{version}",
        kind=kind,
        version=version,
        uri=f"{kind.value}/{version}",
    )


def test_fake_satisfies_versioned_asset_repository_protocol() -> None:
    assert isinstance(_FakeVersionedAssetRepository(), VersionedAssetRepository)


def test_port_is_runtime_checkable_and_rejects_incomplete_implementations() -> None:
    class _MissingMethods:
        def save(self, run_id: str, asset: VersionedAsset) -> None: ...

    assert not isinstance(_MissingMethods(), VersionedAssetRepository)


def test_run_id_is_a_method_parameter_not_an_asset_field() -> None:
    # D1: run_id is supplied per call, never stored on the domain asset.
    assert list(inspect.signature(VersionedAssetRepository.save).parameters) == [
        "self",
        "run_id",
        "asset",
    ]
    for method in ("get_latest", "list_for_run", "next_version"):
        params = list(
            inspect.signature(getattr(VersionedAssetRepository, method)).parameters
        )
        assert params == ["self", "run_id", "kind"], method

    assert "run_id" not in {field.name for field in fields(VersionedAsset)}


def test_fake_versioning_round_trips_through_the_port_contract() -> None:
    repo: VersionedAssetRepository = _FakeVersionedAssetRepository()
    run_id = "run-1"

    assert repo.get_latest(run_id, AssetKind.SCRIPT) is None
    assert list(repo.list_for_run(run_id, AssetKind.SCRIPT)) == []
    assert repo.next_version(run_id, AssetKind.SCRIPT) == 1

    v1 = _asset(1)
    repo.save(run_id, v1)
    assert repo.next_version(run_id, AssetKind.SCRIPT) == 2

    v2 = _asset(2)
    repo.save(run_id, v2)

    assert repo.get_latest(run_id, AssetKind.SCRIPT) == v2
    assert list(repo.list_for_run(run_id, AssetKind.SCRIPT)) == [v1, v2]


def test_fake_isolates_versions_by_run_and_kind() -> None:
    repo: VersionedAssetRepository = _FakeVersionedAssetRepository()

    repo.save("run-1", _asset(1, AssetKind.SCRIPT))

    assert repo.get_latest("run-2", AssetKind.SCRIPT) is None
    assert repo.get_latest("run-1", AssetKind.SCENE_TABLE) is None
    assert repo.next_version("run-1", AssetKind.SCENE_TABLE) == 1
