"""Downloaded clip manifest use-case tests."""

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
    CreateDownloadedClipSet,
    CreateVideoAssemblyPlan,
    DownloadClips,
    GetLatestDownloadedClipSet,
    GetLatestVideoAssemblyPlan,
    ListDownloadedClipSets,
)
from backend.app.domain import (
    AssetKind,
    DownloadedClip,
    Run,
    RunStatus,
    VideoAssemblySegment,
)
from tests.fakes import (
    FakeClipDownloader,
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
    status: RunStatus = RunStatus.SCENES_APPROVED,
) -> Run:
    run = Run(run_id="run-1", prompt="prompt", status=status)
    runs.save(run)
    return run


def _create_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
) -> CreateDownloadedClipSet:
    ids = (f"downloaded-clips-{n}" for n in itertools.count(1))
    return CreateDownloadedClipSet(
        runs, assets, storage, asset_id_factory=lambda: next(ids)
    )


def _segment(order_index: int = 0) -> VideoAssemblySegment:
    return VideoAssemblySegment(
        scene_id=f"scene-{order_index + 1}",
        query_text=f"query {order_index}",
        narration=f"Narration {order_index}",
        visual_query=f"Visual {order_index}",
        provider="stub",
        provider_clip_id=f"clip-{order_index}",
        title=f"Clip {order_index}",
        preview_url=f"memory://clips/{order_index}/preview.jpg",
        source_url=f"memory://clips/{order_index}",
        target_duration_seconds=4.0,
        source_duration_seconds=7.5 + order_index,
        width=1920,
        height=1080,
        order_index=order_index,
        transition="cut",
        continuity_note="ordered_by_scene_table",
        selection_reason="first_candidate_for_scene_query",
    )


def _downloaded_clip(order_index: int = 0) -> DownloadedClip:
    segment = _segment(order_index)
    return DownloadedClip(
        scene_id=segment.scene_id,
        query_text=segment.query_text,
        provider=segment.provider,
        provider_clip_id=segment.provider_clip_id,
        title=segment.title,
        source_url=segment.source_url,
        local_uri=(
            f"memory://downloads/run-1/{order_index:04d}/"
            f"stub-clip-{order_index}.mp4"
        ),
        content_type="video/mp4",
        duration_seconds=segment.source_duration_seconds,
        width=segment.width,
        height=segment.height,
        order_index=order_index,
        download_status="available",
        download_reason="fake_download",
    )


def _seed_plan(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    segments: tuple[VideoAssemblySegment, ...] = (_segment(0), _segment(1)),
) -> None:
    CreateVideoAssemblyPlan(
        runs,
        assets,
        storage,
        asset_id_factory=lambda: "video-assembly-plan-1",
    ).execute("run-1", segments, source="generated")


def _download_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    downloader: FakeClipDownloader,
) -> DownloadClips:
    return DownloadClips(
        runs,
        downloader,
        GetLatestVideoAssemblyPlan(assets, storage),
        _create_use_case(runs, assets, storage),
    )


def test_create_versions_json_manifest_and_latest_round_trip() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    create = _create_use_case(runs, assets, storage)

    first = create.execute("run-1", (_downloaded_clip(0),))
    second = create.execute("run-1", (_downloaded_clip(1),))

    assert first.kind is AssetKind.DOWNLOADED_CLIPS
    assert (first.version, second.version) == (1, 2)
    assert first.metadata == {"source": "manual"}
    assert [asset.version for asset in ListDownloadedClipSets(assets).execute(
        "run-1"
    )] == [1, 2]
    latest = GetLatestDownloadedClipSet(assets, storage).execute("run-1")
    assert latest.asset == second
    assert latest.downloaded_clips == (_downloaded_clip(1),)
    payload = json.loads(storage.saved[first.uri].decode("utf-8"))
    assert isinstance(payload, list)
    assert isinstance(payload[0]["duration_seconds"], float)
    assert isinstance(payload[0]["width"], int)
    assert isinstance(payload[0]["height"], int)
    assert isinstance(payload[0]["order_index"], int)
    assert payload[0]["local_uri"].startswith("memory://downloads/")
    assert runs.get("run-1").status is RunStatus.SCENES_APPROVED


@pytest.mark.parametrize(
    "status",
    [status for status in RunStatus if status is not RunStatus.SCENES_APPROVED],
)
def test_create_rejects_every_status_except_scenes_approved(
    status: RunStatus,
) -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, status)

    with pytest.raises(AssetCreationRejectedError) as exc_info:
        _create_use_case(runs, assets, storage).execute(
            "run-1", (_downloaded_clip(),)
        )

    assert exc_info.value.kind is AssetKind.DOWNLOADED_CLIPS
    assert assets.list_for_run("run-1", AssetKind.DOWNLOADED_CLIPS) == []
    assert storage.saved == {}


def test_create_raises_when_run_is_missing() -> None:
    runs, assets, storage = _triple()

    with pytest.raises(RunNotFoundError):
        _create_use_case(runs, assets, storage).execute(
            "missing", (_downloaded_clip(),)
        )


def test_download_calls_downloader_once_per_segment_in_order() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    _seed_plan(runs, assets, storage)
    downloader = FakeClipDownloader(
        (_downloaded_clip(0), _downloaded_clip(1))
    )

    asset = _download_use_case(runs, assets, storage, downloader).execute(
        "run-1"
    )

    assert downloader.calls == [
        ("run-1", _segment(0)),
        ("run-1", _segment(1)),
    ]
    assert asset.metadata == {
        "video_assembly_plan_asset_id": "video-assembly-plan-1",
        "video_assembly_plan_version": "1",
        "source": "downloaded",
    }
    assert all(isinstance(value, str) for value in asset.metadata.values())
    manifest = GetLatestDownloadedClipSet(assets, storage).execute("run-1")
    assert manifest.downloaded_clips == (
        _downloaded_clip(0),
        _downloaded_clip(1),
    )
    assert runs.get("run-1").status is RunStatus.SCENES_APPROVED


def test_download_empty_plan_persists_empty_manifest_without_call() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    _seed_plan(runs, assets, storage, segments=())
    downloader = FakeClipDownloader()

    asset = _download_use_case(runs, assets, storage, downloader).execute(
        "run-1"
    )

    assert asset.kind is AssetKind.DOWNLOADED_CLIPS
    assert downloader.calls == []
    assert GetLatestDownloadedClipSet(assets, storage).execute(
        "run-1"
    ).downloaded_clips == ()
    assert runs.get("run-1").status is RunStatus.SCENES_APPROVED


def test_download_invalid_status_wins_over_missing_plan() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.CREATED)
    downloader = FakeClipDownloader()

    with pytest.raises(AssetCreationRejectedError) as exc_info:
        _download_use_case(runs, assets, storage, downloader).execute("run-1")

    assert exc_info.value.kind is AssetKind.DOWNLOADED_CLIPS
    assert downloader.calls == []
    assert assets.list_for_run("run-1", AssetKind.DOWNLOADED_CLIPS) == []


def test_download_missing_plan_raises_naturally() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    downloader = FakeClipDownloader()

    with pytest.raises(AssetNotFoundError) as exc_info:
        _download_use_case(runs, assets, storage, downloader).execute("run-1")

    assert exc_info.value.kind is AssetKind.VIDEO_ASSEMBLY_PLAN
    assert downloader.calls == []
    assert assets.list_for_run("run-1", AssetKind.DOWNLOADED_CLIPS) == []


def test_download_missing_run_raises_before_plan_read() -> None:
    runs, assets, storage = _triple()
    downloader = FakeClipDownloader()

    with pytest.raises(RunNotFoundError):
        _download_use_case(runs, assets, storage, downloader).execute("missing")

    assert downloader.calls == []


def test_latest_raises_when_downloaded_clip_set_is_missing() -> None:
    _, assets, storage = _triple()

    with pytest.raises(AssetNotFoundError) as exc_info:
        GetLatestDownloadedClipSet(assets, storage).execute("run-1")

    assert exc_info.value.kind is AssetKind.DOWNLOADED_CLIPS
