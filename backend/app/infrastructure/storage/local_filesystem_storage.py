"""Local filesystem implementation of the StoragePort."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from backend.app.domain import VersionedAsset
from backend.app.ports import StoragePort


class LocalFilesystemStorage(StoragePort):
    """Persist asset bytes under an injected local storage root.

    The storage root is injected through the constructor (no global state) so
    tests can use a temporary directory (D5). The stored ``uri`` is a
    ``/``-relative path derived deterministically from the asset's own fields.
    The run id is intentionally not part of the layout: run association lives in
    ``VersionedAssetRepository`` (D1), keeping ``VersionedAsset`` reusable.

    Path-traversal is prevented two ways: ``asset_id``/``kind`` are validated as
    single safe path components on save, and every resolved path (on save and
    load) is confirmed to stay within the storage root.
    """

    def __init__(self, storage_root: str | Path) -> None:
        self._root = Path(storage_root).resolve()

    def save_asset(self, asset: VersionedAsset, data: bytes) -> VersionedAsset:
        relative_uri = self._relative_uri(asset)
        destination = self._resolve_within_root(relative_uri)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return replace(asset, uri=relative_uri)

    def load_asset(self, asset: VersionedAsset) -> bytes:
        source = self._resolve_within_root(asset.uri)
        return source.read_bytes()

    def _relative_uri(self, asset: VersionedAsset) -> str:
        kind = _safe_component(asset.kind.value, "kind")
        asset_id = _safe_component(asset.asset_id, "asset_id")
        return f"{kind}/{asset_id}/v{asset.version}"

    def _resolve_within_root(self, relative_uri: str) -> Path:
        if not relative_uri:
            raise ValueError("asset uri must not be empty")
        candidate = (self._root / relative_uri).resolve()
        if not candidate.is_relative_to(self._root):
            raise ValueError(
                f"resolved path escapes storage root: {relative_uri!r}"
            )
        return candidate


def _safe_component(value: str, field_name: str) -> str:
    if not value or value in {".", ".."}:
        raise ValueError(f"{field_name} is not a safe path component: {value!r}")
    if any(token in value for token in ("/", "\\", ":", "\x00")):
        raise ValueError(f"{field_name} is not a safe path component: {value!r}")
    return value
