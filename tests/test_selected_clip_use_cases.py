"""Selected clip asset use-case tests."""

from __future__ import annotations

import itertools
import json

import pytest

from backend.app.application.errors import (
    AssetCreationRejectedError,
    AssetNotFoundError,
    RunNotFoundError,
)
from backend.app.application.use_cases import (
    CreateClipCandidateSet,
    CreateSelectedClipSet,
    GetLatestClipCandidateSet,
    GetLatestSelectedClipSet,
    ListSelectedClipSets,
    SelectClips,
)
from backend.app.domain import (
    AssetKind,
    ClipCandidate,
    Run,
    RunStatus,
    SelectedClip,
)
from tests.fakes import (
    FakeClipSelector,
    InMemoryRunRepository,
    InMemoryStorage,
    InMemoryVersionedAssetRepository,
)


class _RecordingCandidateSetReader:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, run_id: str) -> object:
        self.calls.append(run_id)
        raise AssertionError("candidate-set reader should not be called")


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
) -> CreateSelectedClipSet:
    ids = (f"selected-clips-{n}" for n in itertools.count(1))
    return CreateSelectedClipSet(
        runs, assets, storage, asset_id_factory=lambda: next(ids)
    )


def _select_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    selector: FakeClipSelector,
) -> SelectClips:
    return SelectClips(
        runs,
        selector,
        GetLatestClipCandidateSet(assets, storage),
        _create_use_case(runs, assets, storage),
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


def _selected_clips() -> tuple[SelectedClip, ...]:
    return (
        SelectedClip(
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
            selection_reason="first_candidate_for_scene_query",
        ),
        SelectedClip(
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
            selection_reason="first_candidate_for_scene_query",
        ),
    )


def _seed_candidate_set(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
) -> None:
    CreateClipCandidateSet(
        runs,
        assets,
        storage,
        asset_id_factory=lambda: "clip-candidates-1",
    ).execute("run-1", _candidates())


def test_create_persists_selected_clip_set_tagged_manual_by_default() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)

    selected_set = _create_use_case(runs, assets, storage).execute(
        "run-1", _selected_clips()
    )

    assert selected_set.kind is AssetKind.SELECTED_CLIPS
    assert selected_set.version == 1
    assert selected_set.uri
    assert selected_set.metadata == {"source": "manual"}
    assert list(assets.list_for_run("run-1", AssetKind.SELECTED_CLIPS)) == [
        selected_set
    ]


def test_second_create_increments_version_and_keeps_scenes_approved() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    create = _create_use_case(runs, assets, storage)

    first = create.execute("run-1", _selected_clips())
    run_after_first = runs.get("run-1")
    second = create.execute("run-1", _selected_clips())
    run_after_second = runs.get("run-1")

    assert (first.version, second.version) == (1, 2)
    assert run_after_second is not None
    assert run_after_second.status is RunStatus.SCENES_APPROVED
    assert run_after_second == run_after_first
    assert [
        asset.version
        for asset in assets.list_for_run("run-1", AssetKind.SELECTED_CLIPS)
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
        _create_use_case(runs, assets, storage).execute(
            "run-1", _selected_clips()
        )

    assert exc_info.value.status is status
    assert exc_info.value.kind is AssetKind.SELECTED_CLIPS
    assert list(assets.list_for_run("run-1", AssetKind.SELECTED_CLIPS)) == []
    assert storage.saved == {}


def test_create_raises_run_not_found_when_run_missing() -> None:
    runs, assets, storage = _triple()

    with pytest.raises(RunNotFoundError, match="Run 'missing' was not found"):
        _create_use_case(runs, assets, storage).execute(
            "missing", _selected_clips()
        )


def test_list_returns_ordered_selected_clip_versions() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    create = _create_use_case(runs, assets, storage)

    first = create.execute("run-1", _selected_clips())
    second = create.execute("run-1", _selected_clips())

    assert list(ListSelectedClipSets(assets).execute("run-1")) == [
        first,
        second,
    ]


def test_get_latest_raises_asset_not_found_when_none_exists() -> None:
    _, assets, storage = _triple()

    with pytest.raises(AssetNotFoundError) as exc_info:
        GetLatestSelectedClipSet(assets, storage).execute("run-1")

    assert exc_info.value.kind is AssetKind.SELECTED_CLIPS


def test_selected_clip_bytes_are_persisted_as_valid_json() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)

    stored = _create_use_case(runs, assets, storage).execute(
        "run-1", _selected_clips()
    )

    payload = json.loads(storage.saved[stored.uri].decode("utf-8"))
    assert isinstance(payload, list)
    assert [item["scene_id"] for item in payload] == ["scene-1", "scene-2"]
    assert payload[0]["query_text"] == "city skyline sunrise"
    assert payload[1]["selection_reason"] == "first_candidate_for_scene_query"


def test_round_trip_identity_of_selected_clip_tuple() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)

    _create_use_case(runs, assets, storage).execute(
        "run-1", _selected_clips()
    )

    result = GetLatestSelectedClipSet(assets, storage).execute("run-1")
    assert result.selected_clips == _selected_clips()
    assert isinstance(result.selected_clips[0].duration_seconds, float)
    assert result.selected_clips[0].selection_reason == (
        "first_candidate_for_scene_query"
    )
    asset, parsed = result
    assert asset.kind is AssetKind.SELECTED_CLIPS
    assert parsed == _selected_clips()


def test_get_latest_returns_newest_selected_clip_version() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    create = _create_use_case(runs, assets, storage)

    create.execute("run-1", _selected_clips())
    create.execute(
        "run-1",
        (
            SelectedClip(
                scene_id="scene-new",
                query_text="new query",
                provider="fake",
                provider_clip_id="new-1",
                title="New selected clip",
                preview_url="memory://clips/new/preview.jpg",
                source_url="memory://clips/new",
                duration_seconds=1.5,
                width=640,
                height=360,
                selection_reason="first_candidate_for_scene_query",
            ),
        ),
    )

    result = GetLatestSelectedClipSet(assets, storage).execute("run-1")
    assert result.asset.version == 2
    assert result.selected_clips[0].scene_id == "scene-new"


def test_select_calls_selector_once_and_persists_selected_set() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    _seed_candidate_set(runs, assets, storage)
    selector = FakeClipSelector(_selected_clips())

    asset = _select_use_case(runs, assets, storage, selector).execute("run-1")

    assert asset.kind is AssetKind.SELECTED_CLIPS
    assert asset.version == 1
    assert asset.metadata == {"source": "selected"}
    assert selector.calls == [_candidates()]
    latest = GetLatestSelectedClipSet(assets, storage).execute("run-1")
    assert latest.selected_clips == _selected_clips()


def test_select_second_set_increments_version_and_keeps_scenes_approved() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    _seed_candidate_set(runs, assets, storage)
    use_case = _select_use_case(
        runs, assets, storage, FakeClipSelector(_selected_clips())
    )

    first = use_case.execute("run-1")
    run_after_first = runs.get("run-1")
    second = use_case.execute("run-1")
    run_after_second = runs.get("run-1")

    assert (first.version, second.version) == (1, 2)
    assert run_after_second is not None
    assert run_after_second.status is RunStatus.SCENES_APPROVED
    assert run_after_second == run_after_first


def test_select_fails_naturally_when_no_candidate_set_exists() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    selector = FakeClipSelector(_selected_clips())

    with pytest.raises(AssetNotFoundError) as exc_info:
        _select_use_case(runs, assets, storage, selector).execute("run-1")

    assert exc_info.value.kind is AssetKind.CLIP_CANDIDATES
    assert selector.calls == []
    assert list(assets.list_for_run("run-1", AssetKind.SELECTED_CLIPS)) == []


def test_select_raises_run_not_found_when_run_missing() -> None:
    runs, assets, storage = _triple()
    selector = FakeClipSelector(_selected_clips())
    reader = _RecordingCandidateSetReader()
    use_case = SelectClips(
        runs,
        selector,
        reader,
        _create_use_case(runs, assets, storage),
    )

    with pytest.raises(RunNotFoundError, match="Run 'missing' was not found"):
        use_case.execute("missing")

    assert reader.calls == []
    assert selector.calls == []
    assert list(assets.list_for_run("missing", AssetKind.SELECTED_CLIPS)) == []
    assert storage.saved == {}


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
def test_select_rejects_invalid_status_before_candidate_read_or_selector(
    status: RunStatus,
) -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, status)
    selector = FakeClipSelector(_selected_clips())
    reader = _RecordingCandidateSetReader()
    use_case = SelectClips(
        runs,
        selector,
        reader,
        _create_use_case(runs, assets, storage),
    )

    with pytest.raises(AssetCreationRejectedError) as exc_info:
        use_case.execute("run-1")

    assert exc_info.value.status is status
    assert exc_info.value.kind is AssetKind.SELECTED_CLIPS
    assert reader.calls == []
    assert selector.calls == []
    assert list(assets.list_for_run("run-1", AssetKind.SELECTED_CLIPS)) == []
    assert storage.saved == {}
