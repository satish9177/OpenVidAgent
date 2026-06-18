"""SQLite implementation of the VersionedAssetRepository port."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from backend.app.domain import AssetKind, VersionedAsset
from backend.app.ports import VersionedAssetRepository


class SQLiteVersionedAssetRepository(VersionedAssetRepository):
    """Per-``(run_id, kind)`` version index for assets, backed by SQLite.

    Owns only metadata and the version index; asset bytes live behind
    ``StoragePort``. Metadata (de)serialization to JSON stays inside this
    adapter (D4); the domain ``VersionedAsset`` stays serialization-free.
    """

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    def save(self, run_id: str, asset: VersionedAsset) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO assets (
                    asset_id, run_id, kind, version, uri, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    asset.asset_id,
                    run_id,
                    asset.kind.value,
                    asset.version,
                    asset.uri,
                    json.dumps(dict(asset.metadata)),
                ),
            )
            connection.commit()

    def get_latest(self, run_id: str, kind: AssetKind) -> VersionedAsset | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT asset_id, kind, version, uri, metadata
                FROM assets
                WHERE run_id = ? AND kind = ?
                ORDER BY version DESC
                LIMIT 1
                """,
                (run_id, kind.value),
            ).fetchone()

        if row is None:
            return None
        return _row_to_asset(row)

    def list_for_run(
        self, run_id: str, kind: AssetKind
    ) -> Sequence[VersionedAsset]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT asset_id, kind, version, uri, metadata
                FROM assets
                WHERE run_id = ? AND kind = ?
                ORDER BY version ASC
                """,
                (run_id, kind.value),
            ).fetchall()

        return [_row_to_asset(row) for row in rows]

    def next_version(self, run_id: str, kind: AssetKind) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT MAX(version) AS max_version
                FROM assets
                WHERE run_id = ? AND kind = ?
                """,
                (run_id, kind.value),
            ).fetchone()

        return (row["max_version"] or 0) + 1

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _row_to_asset(row: sqlite3.Row) -> VersionedAsset:
    return VersionedAsset(
        asset_id=row["asset_id"],
        kind=AssetKind(row["kind"]),
        version=row["version"],
        uri=row["uri"],
        metadata=json.loads(row["metadata"]),
    )
