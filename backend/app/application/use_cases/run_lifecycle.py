"""Run lifecycle use-cases."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from backend.app.application.errors import RunNotFoundError
from backend.app.domain import Run
from backend.app.ports import RunRepository


RunIdFactory = Callable[[], str]


class CreateRun:
    def __init__(
        self,
        repository: RunRepository,
        run_id_factory: RunIdFactory | None = None,
    ) -> None:
        self._repository = repository
        self._run_id_factory = run_id_factory or _new_run_id

    def execute(self, prompt: str) -> Run:
        run = Run(run_id=self._run_id_factory(), prompt=prompt)
        self._repository.save(run)
        return run


class GetRun:
    def __init__(self, repository: RunRepository) -> None:
        self._repository = repository

    def execute(self, run_id: str) -> Run | None:
        return self._repository.get(run_id)


class MarkScriptReady:
    def __init__(self, repository: RunRepository) -> None:
        self._repository = repository

    def execute(self, run_id: str, script: str) -> Run:
        run = _require_run(self._repository, run_id)
        updated = run.mark_script_ready(script)
        self._repository.save(updated)
        return updated


class ApproveScript:
    def __init__(self, repository: RunRepository) -> None:
        self._repository = repository

    def execute(self, run_id: str, approved_script: str | None = None) -> Run:
        run = _require_run(self._repository, run_id)
        updated = run.approve_script(approved_script)
        self._repository.save(updated)
        return updated


class MarkScenesReady:
    def __init__(self, repository: RunRepository) -> None:
        self._repository = repository

    def execute(self, run_id: str) -> Run:
        run = _require_run(self._repository, run_id)
        updated = run.mark_scenes_ready()
        self._repository.save(updated)
        return updated


class ApproveScenes:
    def __init__(self, repository: RunRepository) -> None:
        self._repository = repository

    def execute(self, run_id: str) -> Run:
        run = _require_run(self._repository, run_id)
        updated = run.approve_scenes()
        self._repository.save(updated)
        return updated


class MarkFailed:
    def __init__(self, repository: RunRepository) -> None:
        self._repository = repository

    def execute(self, run_id: str, reason: str) -> Run:
        run = _require_run(self._repository, run_id)
        updated = run.mark_failed(reason)
        self._repository.save(updated)
        return updated


def _require_run(repository: RunRepository, run_id: str) -> Run:
    run = repository.get(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    return run


def _new_run_id() -> str:
    return str(uuid4())
