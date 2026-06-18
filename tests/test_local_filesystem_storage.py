"""LocalFilesystemStorage tests (Slice 3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.domain import AssetKind, VersionedAsset
from backend.app.infrastructure.storage import LocalFilesystemStorage
from backend.app.ports import StoragePort


def _asset(
    *,
    asset_id: str = "asset-1",
    kind: AssetKind = AssetKind.SCRIPT,
    version: int = 1,
    uri: str = "",
) -> VersionedAsset:
    return VersionedAsset(
        asset_id=asset_id, kind=kind, version=version, uri=uri
    )


def test_satisfies_storage_port(tmp_path: Path) -> None:
    assert isinstance(LocalFilesystemStorage(tmp_path), StoragePort)


def test_save_then_load_round_trips_bytes(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)

    stored = storage.save_asset(_asset(), b"hello world")

    assert storage.load_asset(stored) == b"hello world"


def test_save_populates_relative_deterministic_uri(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)

    stored = storage.save_asset(_asset(asset_id="a1", version=2), b"data")

    assert stored.uri == "script/a1/v2"
    assert not Path(stored.uri).is_absolute()
    # Bytes land under the storage root at the deterministic path.
    assert (tmp_path / "script" / "a1" / "v2").read_bytes() == b"data"


def test_layout_is_deterministic_across_saves(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)

    first = storage.save_asset(_asset(asset_id="a1", version=1), b"one")
    second = storage.save_asset(_asset(asset_id="a1", version=1), b"two")

    assert first.uri == second.uri
    assert storage.load_asset(second) == b"two"


def test_utf8_bytes_round_trip(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    text = "café — 日本語 — clapper 🎬"

    stored = storage.save_asset(
        _asset(kind=AssetKind.SCENE_TABLE), text.encode("utf-8")
    )

    assert storage.load_asset(stored).decode("utf-8") == text


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)

    phantom = _asset(uri="script/never-saved/v1")
    with pytest.raises(FileNotFoundError):
        storage.load_asset(phantom)


@pytest.mark.parametrize(
    "bad_id", ["../evil", "a/b", "a\\b", "..", ".", "", "C:evil", "a\x00b"]
)
def test_unsafe_asset_id_is_rejected_on_save(tmp_path: Path, bad_id: str) -> None:
    storage = LocalFilesystemStorage(tmp_path)

    with pytest.raises(ValueError):
        storage.save_asset(_asset(asset_id=bad_id), b"data")


@pytest.mark.parametrize(
    "bad_uri", ["../../escape", "../secret.txt", "/etc/passwd", ""]
)
def test_path_traversal_uri_is_rejected_on_load(
    tmp_path: Path, bad_uri: str
) -> None:
    storage = LocalFilesystemStorage(tmp_path / "store")

    with pytest.raises(ValueError):
        storage.load_asset(_asset(uri=bad_uri))


def test_traversal_cannot_reach_a_file_outside_the_root(tmp_path: Path) -> None:
    root = tmp_path / "store"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"top secret")
    storage = LocalFilesystemStorage(root)

    with pytest.raises(ValueError):
        storage.load_asset(_asset(uri="../secret.txt"))


def test_storage_root_is_injected_not_global(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    storage_a = LocalFilesystemStorage(root_a)
    storage_b = LocalFilesystemStorage(root_b)

    stored = storage_a.save_asset(_asset(), b"only in a")

    assert (root_a / "script" / "asset-1" / "v1").exists()
    assert not (root_b / "script" / "asset-1" / "v1").exists()
    with pytest.raises(FileNotFoundError):
        storage_b.load_asset(stored)
