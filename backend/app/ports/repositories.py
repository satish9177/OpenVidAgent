"""Persistence and queue interfaces for durable local work."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.app.domain import Job, Run, VersionedAsset


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
