"""In-memory StoragePort fake for application tests."""

from __future__ import annotations

from dataclasses import replace

from backend.app.domain import VersionedAsset
from backend.app.ports import StoragePort


class InMemoryStorage(StoragePort):
    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}

    def save_asset(self, asset: VersionedAsset, data: bytes) -> VersionedAsset:
        uri = f"memory://{asset.kind.value}/{asset.asset_id}/v{asset.version}"
        self.saved[uri] = data
        return replace(asset, uri=uri)

    def load_asset(self, asset: VersionedAsset) -> bytes:
        try:
            return self.saved[asset.uri]
        except KeyError:
            raise FileNotFoundError(asset.uri) from None
