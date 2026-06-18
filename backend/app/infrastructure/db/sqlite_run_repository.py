"""SQLite implementation of the RunRepository port."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.app.domain import Run, RunStatus
from backend.app.ports import RunRepository


class SQLiteRunRepository(RunRepository):
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    def get(self, run_id: str) -> Run | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT run_id, prompt, status, script, approved_script, failure_reason
                FROM runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()

        if row is None:
            return None
        return _row_to_run(row)

    def save(self, run: Run) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id,
                    prompt,
                    status,
                    script,
                    approved_script,
                    failure_reason
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    prompt = excluded.prompt,
                    status = excluded.status,
                    script = excluded.script,
                    approved_script = excluded.approved_script,
                    failure_reason = excluded.failure_reason
                """,
                (
                    run.run_id,
                    run.prompt,
                    run.status.value,
                    run.script,
                    run.approved_script,
                    run.failure_reason,
                ),
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _row_to_run(row: sqlite3.Row) -> Run:
    return Run(
        run_id=row["run_id"],
        prompt=row["prompt"],
        status=RunStatus(row["status"]),
        script=row["script"],
        approved_script=row["approved_script"],
        failure_reason=row["failure_reason"],
    )
