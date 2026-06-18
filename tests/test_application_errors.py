"""Tests for application-layer asset errors (Slice 1)."""

from __future__ import annotations

from backend.app.application.errors import (
    AssetCreationRejectedError,
    AssetNotFoundError,
)
from backend.app.domain import AssetKind, RunStatus


def test_asset_not_found_error_is_a_lookup_error_carrying_context() -> None:
    error = AssetNotFoundError("run-1", AssetKind.SCRIPT)

    assert isinstance(error, LookupError)
    assert error.run_id == "run-1"
    assert error.kind is AssetKind.SCRIPT
    assert str(error) == "No script asset was found for run 'run-1'"


def test_asset_creation_rejected_error_carries_run_kind_and_status() -> None:
    error = AssetCreationRejectedError(
        "run-1", AssetKind.SCRIPT, RunStatus.SCRIPT_APPROVED
    )

    assert isinstance(error, ValueError)
    assert error.run_id == "run-1"
    assert error.kind is AssetKind.SCRIPT
    assert error.status is RunStatus.SCRIPT_APPROVED
    assert str(error) == (
        "Cannot create script asset for run 'run-1' in status 'script_approved'"
    )
