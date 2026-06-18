"""Fake repositories for application tests."""

from __future__ import annotations

from backend.app.domain import Run
from backend.app.ports import RunRepository


class InMemoryRunRepository(RunRepository):
    def __init__(self) -> None:
        self.saved: dict[str, Run] = {}

    def get(self, run_id: str) -> Run | None:
        return self.saved.get(run_id)

    def save(self, run: Run) -> None:
        self.saved[run.run_id] = run
