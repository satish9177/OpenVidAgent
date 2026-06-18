"""Health API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.application.use_cases.health_check import HealthCheck

router = APIRouter()


def get_health_check() -> HealthCheck:
    return HealthCheck()


@router.get("/health")
def health(use_case: HealthCheck = Depends(get_health_check)) -> dict[str, str]:
    status = use_case.execute()
    return {"service": status.service, "status": status.status}
