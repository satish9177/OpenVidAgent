"""Clip candidate asset use-case tests."""

from __future__ import annotations

import itertools
import json
from collections.abc import Sequence

import pytest

from backend.app.application.errors import (
    AssetCreationRejectedError,
    AssetNotFoundError,
    RunNotFoundError,
)
from backend.app.application.use_cases import (
    CreateClipCandidateSet,
    CreateStockPlan,
    GetLatestClipCandidateSet,
    GetLatestStockPlan,
    ListClipCandidateSets,
    RetrieveClipCandidates,
)
from backend.app.domain import (
    AssetKind,
    ClipCandidate,
    Run,
    RunStatus,
    StockQuerySpec,
)
from tests.fakes import (
    FakeClipRetrievalProvider,
    InMemoryRunRepository,
    InMemoryStorage,
    InMemoryVersionedAssetRepository,
)


class _RecordingStockPlanReader:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, run_id: str) -> object:
        self.calls.append(run_id)
        raise AssertionError("stock-plan reader should not be called")


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
    status: RunStatus = RunStatus.SCENES_APPROVED,
    run_id: str = "run-1",
) -> Run:
    run = Run(run_id=run_id, prompt="prompt", status=status)
    runs.save(run)
    return run


def _create_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
) -> CreateClipCandidateSet:
    ids = (f"clip-candidates-{n}" for n in itertools.count(1))
    return CreateClipCandidateSet(
        runs, assets, storage, asset_id_factory=lambda: next(ids)
    )


def _retrieve_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    provider: FakeClipRetrievalProvider,
) -> RetrieveClipCandidates:
    return RetrieveClipCandidates(
        runs,
        provider,
        GetLatestStockPlan(assets, storage),
        _create_use_case(runs, assets, storage),
    )


def _queries() -> tuple[StockQuerySpec, ...]:
    return (
        StockQuerySpec(
            scene_id="scene-1",
            query="city skyline sunrise",
            visual_intent="Open with an establishing city shot.",
            duration_seconds=4.0,
        ),
        StockQuerySpec(
            scene_id="scene-2",
            query="focused office work",
            visual_intent="Show the user solving the problem.",
            duration_seconds=5.25,
        ),
    )


def _candidates() -> tuple[ClipCandidate, ...]:
    return (
        ClipCandidate(
            scene_id="scene-1",
            query_text="city skyline sunrise",
            provider="fake",
            provider_clip_id="scene-1-fake-1",
            title="City skyline sunrise",
            preview_url="memory://clips/scene-1/preview.jpg",
            source_url="memory://clips/scene-1",
            duration_seconds=4.0,
            width=1280,
            height=720,
        ),
        ClipCandidate(
            scene_id="scene-2",
            query_text="focused office work",
            provider="fake",
            provider_clip_id="scene-2-fake-1",
            title="Focused office work",
            preview_url="memory://clips/scene-2/preview.jpg",
            source_url="memory://clips/scene-2",
            duration_seconds=5.25,
            width=1920,
            height=1080,
        ),
    )


def _seed_stock_plan(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    queries: Sequence[StockQuerySpec] | None = None,
) -> None:
    CreateStockPlan(
        runs,
        assets,
        storage,
        asset_id_factory=lambda: "stock-plan-1",
    ).execute("run-1", tuple(queries) if queries is not None else _queries())


def test_create_persists_clip_candidate_set_tagged_manual_by_default() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)

    candidate_set = _create_use_case(runs, assets, storage).execute(
        "run-1", _candidates()
    )

    assert candidate_set.kind is AssetKind.CLIP_CANDIDATES
    assert candidate_set.version == 1
    assert candidate_set.uri
    assert candidate_set.metadata == {"source": "manual"}
    assert list(assets.list_for_run("run-1", AssetKind.CLIP_CANDIDATES)) == [
        candidate_set
    ]


def test_second_create_increments_version_and_keeps_scenes_approved() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    create = _create_use_case(runs, assets, storage)

    first = create.execute("run-1", _candidates())
    run_after_first = runs.get("run-1")
    second = create.execute("run-1", _candidates())
    run_after_second = runs.get("run-1")

    assert (first.version, second.version) == (1, 2)
    assert run_after_second is not None
    assert run_after_second.status is RunStatus.SCENES_APPROVED
    assert run_after_second == run_after_first
    assert [
        asset.version
        for asset in assets.list_for_run("run-1", AssetKind.CLIP_CANDIDATES)
    ] == [1, 2]


@pytest.mark.parametrize(
    "status",
    [
        RunStatus.CREATED,
        RunStatus.SCRIPT_READY,
        RunStatus.SCRIPT_APPROVED,
        RunStatus.SCENES_READY,
        RunStatus.RENDERED,
        RunStatus.FAILED,
    ],
)
def test_create_rejects_every_status_except_scenes_approved(
    status: RunStatus,
) -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, status)

    with pytest.raises(AssetCreationRejectedError) as exc_info:
        _create_use_case(runs, assets, storage).execute("run-1", _candidates())

    assert exc_info.value.status is status
    assert exc_info.value.kind is AssetKind.CLIP_CANDIDATES
    assert list(assets.list_for_run("run-1", AssetKind.CLIP_CANDIDATES)) == []
    assert storage.saved == {}


def test_create_raises_run_not_found_when_run_missing() -> None:
    runs, assets, storage = _triple()

    with pytest.raises(RunNotFoundError, match="Run 'missing' was not found"):
        _create_use_case(runs, assets, storage).execute("missing", _candidates())


def test_list_returns_ordered_clip_candidate_versions() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    create = _create_use_case(runs, assets, storage)

    first = create.execute("run-1", _candidates())
    second = create.execute("run-1", _candidates())

    assert list(ListClipCandidateSets(assets).execute("run-1")) == [
        first,
        second,
    ]


def test_get_latest_raises_asset_not_found_when_none_exists() -> None:
    _, assets, storage = _triple()

    with pytest.raises(AssetNotFoundError) as exc_info:
        GetLatestClipCandidateSet(assets, storage).execute("run-1")

    assert exc_info.value.kind is AssetKind.CLIP_CANDIDATES


def test_clip_candidate_bytes_are_persisted_as_valid_json() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)

    stored = _create_use_case(runs, assets, storage).execute(
        "run-1", _candidates()
    )

    payload = json.loads(storage.saved[stored.uri].decode("utf-8"))
    assert isinstance(payload, list)
    assert [item["scene_id"] for item in payload] == ["scene-1", "scene-2"]
    assert payload[0]["query_text"] == "city skyline sunrise"
    assert payload[1]["width"] == 1920


def test_round_trip_identity_of_clip_candidate_tuple() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)

    _create_use_case(runs, assets, storage).execute("run-1", _candidates())

    result = GetLatestClipCandidateSet(assets, storage).execute("run-1")
    assert result.candidates == _candidates()
    assert isinstance(result.candidates[0].duration_seconds, float)
    asset, parsed = result
    assert asset.kind is AssetKind.CLIP_CANDIDATES
    assert parsed == _candidates()


def test_get_latest_returns_newest_clip_candidate_version() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    create = _create_use_case(runs, assets, storage)

    create.execute("run-1", _candidates())
    create.execute(
        "run-1",
        (
            ClipCandidate(
                scene_id="scene-new",
                query_text="new query",
                provider="fake",
                provider_clip_id="new-1",
                title="New candidate",
                preview_url="memory://clips/new/preview.jpg",
                source_url="memory://clips/new",
                duration_seconds=1.5,
                width=640,
                height=360,
            ),
        ),
    )

    result = GetLatestClipCandidateSet(assets, storage).execute("run-1")
    assert result.asset.version == 2
    assert result.candidates[0].scene_id == "scene-new"


def test_retrieve_calls_provider_for_every_query_and_persists_retrieved_set() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    _seed_stock_plan(runs, assets, storage)
    provider = FakeClipRetrievalProvider()

    asset = _retrieve_use_case(runs, assets, storage, provider).execute("run-1")

    assert asset.kind is AssetKind.CLIP_CANDIDATES
    assert asset.version == 1
    assert asset.metadata == {"source": "retrieved"}
    assert provider.queries == list(_queries())
    latest = GetLatestClipCandidateSet(assets, storage).execute("run-1")
    assert [candidate.scene_id for candidate in latest.candidates] == [
        "scene-1",
        "scene-2",
    ]
    assert [candidate.query_text for candidate in latest.candidates] == [
        "city skyline sunrise",
        "focused office work",
    ]


def test_retrieve_second_set_increments_version_and_keeps_scenes_approved() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    _seed_stock_plan(runs, assets, storage)
    use_case = _retrieve_use_case(
        runs, assets, storage, FakeClipRetrievalProvider()
    )

    first = use_case.execute("run-1")
    run_after_first = runs.get("run-1")
    second = use_case.execute("run-1")
    run_after_second = runs.get("run-1")

    assert (first.version, second.version) == (1, 2)
    assert run_after_second is not None
    assert run_after_second.status is RunStatus.SCENES_APPROVED
    assert run_after_second == run_after_first


def test_retrieve_fails_naturally_when_no_stock_plan_exists() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    provider = FakeClipRetrievalProvider()

    with pytest.raises(AssetNotFoundError) as exc_info:
        _retrieve_use_case(runs, assets, storage, provider).execute("run-1")

    assert exc_info.value.kind is AssetKind.STOCK_PLAN
    assert provider.queries == []
    assert list(assets.list_for_run("run-1", AssetKind.CLIP_CANDIDATES)) == []


@pytest.mark.parametrize(
    "status",
    [
        RunStatus.CREATED,
        RunStatus.SCRIPT_READY,
        RunStatus.SCRIPT_APPROVED,
        RunStatus.SCENES_READY,
        RunStatus.RENDERED,
        RunStatus.FAILED,
    ],
)
def test_retrieve_rejects_invalid_status_before_plan_read_or_provider(
    status: RunStatus,
) -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, status)
    provider = FakeClipRetrievalProvider()
    reader = _RecordingStockPlanReader()
    use_case = RetrieveClipCandidates(
        runs,
        provider,
        reader,
        _create_use_case(runs, assets, storage),
    )

    with pytest.raises(AssetCreationRejectedError) as exc_info:
        use_case.execute("run-1")

    assert exc_info.value.status is status
    assert exc_info.value.kind is AssetKind.CLIP_CANDIDATES
    assert reader.calls == []
    assert provider.queries == []
    assert list(assets.list_for_run("run-1", AssetKind.CLIP_CANDIDATES)) == []
    assert storage.saved == {}
