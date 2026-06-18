"""Application-layer errors."""

from __future__ import annotations

from backend.app.domain import AssetKind, RunStatus


class RunNotFoundError(LookupError):
    """Raised when a requested run does not exist."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"Run {run_id!r} was not found")
        self.run_id = run_id


class AssetNotFoundError(LookupError):
    """Raised when no asset of a given kind exists for a run."""

    def __init__(self, run_id: str, kind: AssetKind) -> None:
        super().__init__(
            f"No {kind.value} asset was found for run {run_id!r}"
        )
        self.run_id = run_id
        self.kind = kind


class AssetCreationRejectedError(ValueError):
    """Raised when an asset may not be created for a run in its current status.

    Enforces the D7 product rule in the application layer (not in API routes)
    so an asset never exists in an inconsistent state relative to the run
    lifecycle (for example, a script draft while the run is already approved or
    in a terminal status).
    """

    def __init__(self, run_id: str, kind: AssetKind, status: RunStatus) -> None:
        super().__init__(
            f"Cannot create {kind.value} asset for run {run_id!r} "
            f"in status {status.value!r}"
        )
        self.run_id = run_id
        self.kind = kind
        self.status = status
