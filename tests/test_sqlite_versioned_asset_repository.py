"""SQLite VersionedAssetRepository tests (Slice 2)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.app.domain import AssetKind, VersionedAsset
from backend.app.infrastructure.db import (
    SQLiteVersionedAssetRepository,
    initialize_database,
)
from backend.app.ports import VersionedAssetRepository


def _repository(tmp_path: Path) -> SQLiteVersionedAssetRepository:
    database_path = tmp_path / "openvidagent.sqlite"
    initialize_database(database_path)
    return SQLiteVersionedAssetRepository(database_path)


def _asset(
    version: int,
    *,
    asset_id: str | None = None,
    kind: AssetKind = AssetKind.SCRIPT,
    metadata: dict[str, str] | None = None,
) -> VersionedAsset:
    return VersionedAsset(
        asset_id=asset_id or f"asset-{kind.value}-{version}",
        kind=kind,
        version=version,
        uri=f"{kind.value}/{version}",
        metadata=metadata or {},
    )


def test_satisfies_versioned_asset_repository_port(tmp_path: Path) -> None:
    assert isinstance(_repository(tmp_path), VersionedAssetRepository)


def test_get_latest_returns_highest_version(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    repository.save("run-1", _asset(1))
    repository.save("run-1", _asset(2))

    latest = repository.get_latest("run-1", AssetKind.SCRIPT)
    assert latest is not None
    assert latest.version == 2
    assert latest == _asset(2)


def test_list_for_run_is_ordered_by_version(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    repository.save("run-1", _asset(2))
    repository.save("run-1", _asset(1))
    repository.save("run-1", _asset(3))

    versions = [asset.version for asset in repository.list_for_run("run-1", AssetKind.SCRIPT)]
    assert versions == [1, 2, 3]


def test_metadata_round_trips(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    metadata = {"source": "user", "language": "en"}

    repository.save("run-1", _asset(1, metadata=metadata))

    stored = repository.get_latest("run-1", AssetKind.SCRIPT)
    assert stored is not None
    assert stored.metadata == metadata


def test_empty_repository_returns_none_and_empty_list(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    assert repository.get_latest("run-1", AssetKind.SCRIPT) is None
    assert list(repository.list_for_run("run-1", AssetKind.SCRIPT)) == []


def test_next_version_increments_per_run_and_kind(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    assert repository.next_version("run-1", AssetKind.SCRIPT) == 1

    repository.save("run-1", _asset(1))
    assert repository.next_version("run-1", AssetKind.SCRIPT) == 2

    repository.save("run-1", _asset(2))
    assert repository.next_version("run-1", AssetKind.SCRIPT) == 3


def test_rows_isolate_by_run_id(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    repository.save("run-1", _asset(1, asset_id="a1"))
    repository.save("run-2", _asset(1, asset_id="a2"))

    run_1_latest = repository.get_latest("run-1", AssetKind.SCRIPT)
    run_2_latest = repository.get_latest("run-2", AssetKind.SCRIPT)
    assert run_1_latest is not None and run_1_latest.asset_id == "a1"
    assert run_2_latest is not None and run_2_latest.asset_id == "a2"
    assert repository.next_version("run-1", AssetKind.SCRIPT) == 2
    assert repository.next_version("run-2", AssetKind.SCRIPT) == 2


def test_rows_isolate_by_kind(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    repository.save("run-1", _asset(1, asset_id="s1", kind=AssetKind.SCRIPT))

    assert repository.get_latest("run-1", AssetKind.SCENE_TABLE) is None
    assert repository.next_version("run-1", AssetKind.SCENE_TABLE) == 1


def test_duplicate_run_kind_version_is_rejected(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    repository.save("run-1", _asset(1, asset_id="a1"))

    with pytest.raises(sqlite3.IntegrityError):
        repository.save("run-1", _asset(1, asset_id="a2"))
