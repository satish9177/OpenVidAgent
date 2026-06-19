import pytest

from backend.app.application.errors import RunNotFoundError
from backend.app.application.use_cases import (
    ApproveScenes,
    ApproveScript,
    CreateRun,
    GetRun,
    MarkFailed,
    MarkScenesReady,
    MarkScriptReady,
)
from backend.app.domain import InvalidRunTransitionError, RunStatus
from tests.fakes import InMemoryRunRepository


def test_run_lifecycle_use_cases_persist_each_valid_transition() -> None:
    repository = InMemoryRunRepository()
    run = CreateRun(repository, run_id_factory=lambda: "run-1").execute("prompt")

    assert run.status is RunStatus.CREATED
    assert GetRun(repository).execute("run-1") == run

    run = MarkScriptReady(repository).execute("run-1", "script")
    assert run.status is RunStatus.SCRIPT_READY

    run = ApproveScript(repository).execute("run-1")
    assert run.status is RunStatus.SCRIPT_APPROVED

    run = MarkScenesReady(repository).execute("run-1")
    assert run.status is RunStatus.SCENES_READY

    run = ApproveScenes(repository).execute("run-1")
    assert run.status is RunStatus.SCENES_APPROVED

    assert repository.get("run-1") == run


def test_mark_failed_use_case_persists_failure() -> None:
    repository = InMemoryRunRepository()
    CreateRun(repository, run_id_factory=lambda: "run-1").execute("prompt")

    run = MarkFailed(repository).execute("run-1", "local provider failed")

    assert run.status is RunStatus.FAILED
    assert run.failure_reason == "local provider failed"
    assert repository.get("run-1") == run


def test_use_case_invalid_transition_does_not_mutate_run() -> None:
    repository = InMemoryRunRepository()
    original = CreateRun(repository, run_id_factory=lambda: "run-1").execute("prompt")

    with pytest.raises(InvalidRunTransitionError):
        ApproveScript(repository).execute("run-1")

    assert repository.get("run-1") == original


def test_mutating_use_case_raises_when_run_is_missing() -> None:
    repository = InMemoryRunRepository()

    with pytest.raises(RunNotFoundError, match="Run 'missing' was not found"):
        MarkScriptReady(repository).execute("missing", "script")


def test_create_run_sets_title_and_language() -> None:
    repository = InMemoryRunRepository()

    run = CreateRun(repository, run_id_factory=lambda: "run-1").execute(
        "prompt", title="My Video", language="es"
    )

    assert run.title == "My Video"
    assert run.language == "es"
    assert repository.get("run-1") == run


def test_create_run_defaults_title_none_and_language_en() -> None:
    repository = InMemoryRunRepository()

    run = CreateRun(repository, run_id_factory=lambda: "run-1").execute("prompt")

    assert run.title is None
    assert run.language == "en"
