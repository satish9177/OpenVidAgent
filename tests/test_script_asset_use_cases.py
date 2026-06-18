"""Script draft use-case tests (Slice 4)."""

from __future__ import annotations

import itertools

import pytest

from backend.app.application.errors import (
    AssetCreationRejectedError,
    AssetNotFoundError,
    RunNotFoundError,
)
from backend.app.application.use_cases import (
    CreateScriptDraft,
    GetLatestScriptDraft,
    ListScriptDrafts,
)
from backend.app.domain import AssetKind, Run, RunStatus
from tests.fakes import (
    InMemoryRunRepository,
    InMemoryStorage,
    InMemoryVersionedAssetRepository,
)


def _triple() -> tuple[
    InMemoryRunRepository, InMemoryVersionedAssetRepository, InMemoryStorage
]:
    return (
        InMemoryRunRepository(),
        InMemoryVersionedAssetRepository(),
        InMemoryStorage(),
    )


def _seed_run(
    runs: InMemoryRunRepository,
    status: RunStatus = RunStatus.CREATED,
    run_id: str = "run-1",
) -> Run:
    run = Run(run_id=run_id, prompt="prompt", status=status)
    runs.save(run)
    return run


def _create_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
) -> CreateScriptDraft:
    ids = (f"asset-{n}" for n in itertools.count(1))
    return CreateScriptDraft(
        runs, assets, storage, asset_id_factory=lambda: next(ids)
    )


def test_first_draft_from_created_transitions_to_script_ready() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.CREATED)

    draft = _create_use_case(runs, assets, storage).execute("run-1", "hello")

    assert draft.kind is AssetKind.SCRIPT
    assert draft.version == 1
    assert draft.uri  # populated by StoragePort
    assert draft.metadata == {"source": "manual"}
    stored_run = runs.get("run-1")
    assert stored_run is not None
    assert stored_run.status is RunStatus.SCRIPT_READY


def test_second_draft_increments_version_and_stays_script_ready() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.CREATED)
    create = _create_use_case(runs, assets, storage)

    first = create.execute("run-1", "v1")
    run_after_first = runs.get("run-1")

    second = create.execute("run-1", "v2")
    run_after_second = runs.get("run-1")

    assert first.version == 1
    assert second.version == 2
    # Same-status case: no self-transition was attempted (no exception) and the
    # run was not mutated/re-saved on the second draft.
    assert run_after_second is not None
    assert run_after_second.status is RunStatus.SCRIPT_READY
    assert run_after_second == run_after_first
    assert [
        asset.version for asset in assets.list_for_run("run-1", AssetKind.SCRIPT)
    ] == [1, 2]


@pytest.mark.parametrize(
    "status",
    [
        RunStatus.SCRIPT_APPROVED,
        RunStatus.SCENES_READY,
        RunStatus.SCENES_APPROVED,
        RunStatus.RENDERED,
    ],
)
def test_reject_draft_when_script_approved_or_later(status: RunStatus) -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, status)

    with pytest.raises(AssetCreationRejectedError) as exc_info:
        _create_use_case(runs, assets, storage).execute("run-1", "x")

    assert exc_info.value.status is status
    # Rejection happens before any side effects.
    assert list(assets.list_for_run("run-1", AssetKind.SCRIPT)) == []
    assert storage.saved == {}


def test_reject_draft_when_failed() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.FAILED)

    with pytest.raises(AssetCreationRejectedError):
        _create_use_case(runs, assets, storage).execute("run-1", "x")

    assert list(assets.list_for_run("run-1", AssetKind.SCRIPT)) == []
    assert storage.saved == {}


def test_create_raises_run_not_found_when_run_missing() -> None:
    runs, assets, storage = _triple()

    with pytest.raises(RunNotFoundError, match="Run 'missing' was not found"):
        _create_use_case(runs, assets, storage).execute("missing", "x")


def test_get_latest_raises_asset_not_found_when_none_exists() -> None:
    _, assets, _ = _triple()

    with pytest.raises(AssetNotFoundError):
        GetLatestScriptDraft(assets).execute("run-1")


def test_list_returns_empty_when_no_script_asset() -> None:
    _, assets, _ = _triple()

    assert list(ListScriptDrafts(assets).execute("run-1")) == []


def test_script_bytes_are_persisted_via_storage() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.CREATED)
    text = "café — 日本語 🎬"

    stored = _create_use_case(runs, assets, storage).execute("run-1", text)

    assert storage.saved[stored.uri] == text.encode("utf-8")


def test_get_latest_returns_newest_version() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.CREATED)
    create = _create_use_case(runs, assets, storage)

    create.execute("run-1", "v1")
    create.execute("run-1", "v2")

    latest = GetLatestScriptDraft(assets).execute("run-1")
    assert latest.version == 2
