"""SQLite database initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def initialize_database(database_path: str | Path) -> None:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.commit()
