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


class ApprovedScriptRequiredError(ValueError):
    """Raised when scene generation runs before the run has an approved script.

    A precondition failure distinct from the D7 status guard
    (``AssetCreationRejectedError``): the run may be in an otherwise valid status
    but lacks the ``approved_script`` text the planner needs. Intended to map to a
    409 in the API layer (Slice 6).
    """

    def __init__(self, run_id: str) -> None:
        super().__init__(
            f"Run {run_id!r} has no approved script to plan scenes from"
        )
        self.run_id = run_id


class RenderPlanInputMismatchError(ValueError):
    """Raised when an upstream render-plan artifact has incompatible order."""

    def __init__(
        self,
        run_id: str,
        source: str,
        expected_order_indexes: tuple[int, ...],
        actual_order_indexes: tuple[int, ...],
    ) -> None:
        expected = set(expected_order_indexes)
        actual = set(actual_order_indexes)
        self.run_id = run_id
        self.source = source
        self.expected_order_indexes = tuple(sorted(expected))
        self.actual_order_indexes = tuple(sorted(actual))
        self.missing_order_indexes = tuple(sorted(expected - actual))
        self.extra_order_indexes = tuple(sorted(actual - expected))
        self.expected_count = len(expected_order_indexes)
        self.actual_count = len(actual_order_indexes)
        super().__init__(
            f"Render plan input {source!r} does not match assembly order for "
            f"run {run_id!r}: expected {self.expected_order_indexes} "
            f"({self.expected_count} records), got {self.actual_order_indexes} "
            f"({self.actual_count} records)"
        )
