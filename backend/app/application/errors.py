"""Application-layer errors."""

from __future__ import annotations


class RunNotFoundError(LookupError):
    """Raised when a requested run does not exist."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"Run {run_id!r} was not found")
        self.run_id = run_id
