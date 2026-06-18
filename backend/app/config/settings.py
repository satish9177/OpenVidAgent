"""Typed runtime settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping


@dataclass(frozen=True)
class Settings:
    app_name: str = "OpenVidAgent"
    environment: str = "local"
    debug: bool = False
    database_path: str = "data/openvidagent.sqlite"
    storage_root: str = "data/assets"


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    values = env or os.environ
    return Settings(
        app_name=values.get("OPENVIDAGENT_APP_NAME", "OpenVidAgent"),
        environment=values.get("OPENVIDAGENT_ENVIRONMENT", "local"),
        debug=_read_bool(values.get("OPENVIDAGENT_DEBUG")),
        database_path=values.get(
            "OPENVIDAGENT_DATABASE_PATH", "data/openvidagent.sqlite"
        ),
        storage_root=values.get("OPENVIDAGENT_STORAGE_ROOT", "data/assets"),
    )


@lru_cache
def get_settings() -> Settings:
    return load_settings()


def _read_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.lower() in {"1", "true", "yes", "on"}
