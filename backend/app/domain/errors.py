"""Domain errors."""

from __future__ import annotations


class InvalidRunTransitionError(ValueError):
    """Raised when a run lifecycle transition is not allowed."""

    def __init__(self, current_status: str, next_status: str) -> None:
        super().__init__(
            f"Cannot transition run from {current_status!r} to {next_status!r}"
        )
        self.current_status = current_status
        self.next_status = next_status
