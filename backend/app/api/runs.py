"""Run lifecycle API routes.

These routes translate HTTP requests into application use-case calls and
serialize the resulting domain ``Run``. They hold no transition rules and never
mutate a ``Run`` directly -- both responsibilities live in the domain, reached
through use-cases.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

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
from backend.app.domain import Run
from backend.app.ports import RunRepository

router = APIRouter(prefix="/runs", tags=["runs"])


def get_run_repository(request: Request) -> RunRepository:
    """Resolve the repository wired onto the app at composition time."""
    return request.app.state.run_repository


class CreateRunRequest(BaseModel):
    prompt: str
    title: str | None = None
    language: str = "en"


class ScriptReadyRequest(BaseModel):
    script: str


class ApproveScriptRequest(BaseModel):
    approved_script: str | None = None


class MarkFailedRequest(BaseModel):
    reason: str


class RunResponse(BaseModel):
    run_id: str
    prompt: str
    title: str | None = None
    language: str
    status: str
    script: str | None = None
    approved_script: str | None = None
    failure_reason: str | None = None

    @classmethod
    def from_run(cls, run: Run) -> "RunResponse":
        return cls(
            run_id=run.run_id,
            prompt=run.prompt,
            title=run.title,
            language=run.language,
            status=run.status.value,
            script=run.script,
            approved_script=run.approved_script,
            failure_reason=run.failure_reason,
        )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=RunResponse)
def create_run(
    body: CreateRunRequest,
    repository: RunRepository = Depends(get_run_repository),
) -> RunResponse:
    run = CreateRun(repository).execute(body.prompt, body.title, body.language)
    return RunResponse.from_run(run)


@router.get("/{run_id}", response_model=RunResponse)
def get_run(
    run_id: str,
    repository: RunRepository = Depends(get_run_repository),
) -> RunResponse:
    run = GetRun(repository).execute(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    return RunResponse.from_run(run)


@router.post("/{run_id}/script-ready", response_model=RunResponse)
def mark_script_ready(
    run_id: str,
    body: ScriptReadyRequest,
    repository: RunRepository = Depends(get_run_repository),
) -> RunResponse:
    run = MarkScriptReady(repository).execute(run_id, body.script)
    return RunResponse.from_run(run)


@router.post("/{run_id}/approve-script", response_model=RunResponse)
def approve_script(
    run_id: str,
    repository: RunRepository = Depends(get_run_repository),
    body: ApproveScriptRequest | None = None,
) -> RunResponse:
    approved_script = body.approved_script if body is not None else None
    run = ApproveScript(repository).execute(run_id, approved_script)
    return RunResponse.from_run(run)


@router.post("/{run_id}/scenes-ready", response_model=RunResponse)
def mark_scenes_ready(
    run_id: str,
    repository: RunRepository = Depends(get_run_repository),
) -> RunResponse:
    run = MarkScenesReady(repository).execute(run_id)
    return RunResponse.from_run(run)


@router.post("/{run_id}/approve-scenes", response_model=RunResponse)
def approve_scenes(
    run_id: str,
    repository: RunRepository = Depends(get_run_repository),
) -> RunResponse:
    run = ApproveScenes(repository).execute(run_id)
    return RunResponse.from_run(run)


@router.post("/{run_id}/failed", response_model=RunResponse)
def mark_failed(
    run_id: str,
    body: MarkFailedRequest,
    repository: RunRepository = Depends(get_run_repository),
) -> RunResponse:
    run = MarkFailed(repository).execute(run_id, body.reason)
    return RunResponse.from_run(run)
