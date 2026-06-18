"""Persistence and queue interfaces for durable local work."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from backend.app.domain import AssetKind, Job, Run, VersionedAsset


@runtime_checkable
class StoragePort(Protocol):
    def save_asset(self, asset: VersionedAsset, data: bytes) -> VersionedAsset:
        """Persist a versioned asset and return the stored reference."""
        ...

    def load_asset(self, asset: VersionedAsset) -> bytes:
        """Load a stored asset by versioned reference."""
        ...


@runtime_checkable
class JobQueuePort(Protocol):
    def enqueue(self, job: Job) -> None:
        """Persist a durable unit of work for later execution."""
        ...


@runtime_checkable
class RunRepository(Protocol):
    def get(self, run_id: str) -> Run | None:
        """Load a run aggregate."""
        ...

    def save(self, run: Run) -> None:
        """Persist a run aggregate."""
        ...


@runtime_checkable
class VersionedAssetRepository(Protocol):
    """Metadata/version index for durable assets associated with a run.

    The ``run_id`` is a method parameter rather than a field on
    ``VersionedAsset`` so the domain asset stays reusable across provider ports
    (D1). Asset bytes live behind ``StoragePort``; this port owns only the
    per-``(run_id, kind)`` version index and metadata.
    """

    def save(self, run_id: str, asset: VersionedAsset) -> None:
        """Persist asset metadata for a run."""
        ...

    def get_latest(self, run_id: str, kind: AssetKind) -> VersionedAsset | None:
        """Return the highest-version asset of ``kind`` for a run, or ``None``."""
        ...

    def list_for_run(
        self, run_id: str, kind: AssetKind
    ) -> Sequence[VersionedAsset]:
        """Return all asset versions of ``kind`` for a run, ordered by version."""
        ...

    def next_version(self, run_id: str, kind: AssetKind) -> int:
        """Return the next version number for ``kind`` within a run."""
        ...
