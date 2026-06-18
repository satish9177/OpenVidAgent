from pathlib import Path

from backend.app.domain import Run, RunStatus
from backend.app.infrastructure.db import SQLiteRunRepository, initialize_database
from backend.app.ports import RunRepository


def test_sqlite_run_repository_creates_and_gets_run(tmp_path: Path) -> None:
    database_path = tmp_path / "openvidagent.sqlite"
    initialize_database(database_path)
    repository: RunRepository = SQLiteRunRepository(database_path)

    run = Run(run_id="run-1", prompt="prompt")
    repository.save(run)

    assert repository.get("run-1") == run


def test_sqlite_run_repository_updates_run(tmp_path: Path) -> None:
    database_path = tmp_path / "openvidagent.sqlite"
    initialize_database(database_path)
    repository = SQLiteRunRepository(database_path)

    run = Run(run_id="run-1", prompt="prompt")
    repository.save(run)
    updated = run.mark_script_ready("draft script").approve_script("approved script")
    repository.save(updated)

    stored = repository.get("run-1")
    assert stored == updated
    assert stored is not None
    assert stored.status is RunStatus.SCRIPT_APPROVED
    assert stored.script == "draft script"
    assert stored.approved_script == "approved script"


def test_sqlite_run_repository_returns_none_for_missing_run(tmp_path: Path) -> None:
    database_path = tmp_path / "openvidagent.sqlite"
    initialize_database(database_path)
    repository = SQLiteRunRepository(database_path)

    assert repository.get("missing") is None


def test_sqlite_run_repository_satisfies_run_repository_port(tmp_path: Path) -> None:
    repository = SQLiteRunRepository(tmp_path / "openvidagent.sqlite")

    assert isinstance(repository, RunRepository)
