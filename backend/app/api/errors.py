"""Translation of domain and application errors into HTTP responses.

Keeping this mapping in the API layer lets routes and use-cases raise meaningful
errors without knowing about HTTP status codes.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from backend.app.application.errors import (
    ApprovedScriptRequiredError,
    AssetCreationRejectedError,
    AssetNotFoundError,
    RenderPlanInputMismatchError,
    RunNotFoundError,
)
from backend.app.domain import InvalidRunTransitionError


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RunNotFoundError, _handle_run_not_found)
    app.add_exception_handler(AssetNotFoundError, _handle_asset_not_found)
    app.add_exception_handler(
        AssetCreationRejectedError, _handle_asset_creation_rejected
    )
    app.add_exception_handler(
        ApprovedScriptRequiredError, _handle_approved_script_required
    )
    app.add_exception_handler(InvalidRunTransitionError, _handle_invalid_transition)
    app.add_exception_handler(
        RenderPlanInputMismatchError, _handle_render_plan_input_mismatch
    )


async def _handle_run_not_found(
    request: Request, exc: RunNotFoundError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc), "run_id": exc.run_id},
    )


async def _handle_asset_not_found(
    request: Request, exc: AssetNotFoundError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "detail": str(exc),
            "run_id": exc.run_id,
            "kind": exc.kind.value,
        },
    )


async def _handle_asset_creation_rejected(
    request: Request, exc: AssetCreationRejectedError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": str(exc),
            "run_id": exc.run_id,
            "kind": exc.kind.value,
            "status": exc.status.value,
        },
    )


async def _handle_approved_script_required(
    request: Request, exc: ApprovedScriptRequiredError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc), "run_id": exc.run_id},
    )


async def _handle_invalid_transition(
    request: Request, exc: InvalidRunTransitionError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": str(exc),
            "current_status": exc.current_status,
            "next_status": exc.next_status,
        },
    )


async def _handle_render_plan_input_mismatch(
    request: Request, exc: RenderPlanInputMismatchError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": str(exc),
            "run_id": exc.run_id,
            "source": exc.source,
            "expected_order_indexes": list(exc.expected_order_indexes),
            "actual_order_indexes": list(exc.actual_order_indexes),
            "missing_order_indexes": list(exc.missing_order_indexes),
            "extra_order_indexes": list(exc.extra_order_indexes),
            "expected_count": exc.expected_count,
            "actual_count": exc.actual_count,
        },
    )
