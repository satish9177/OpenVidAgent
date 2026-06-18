"""Minimal use-case for app health."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class HealthStatus:
    service: str
    status: Literal["ok"]


class HealthCheck:
    def execute(self) -> HealthStatus:
        return HealthStatus(service="openvidagent", status="ok")
