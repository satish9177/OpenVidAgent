"""Metadata-only downloaded clip manifest use-cases."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import NamedTuple
from uuid import uuid4

from backend.app.application.errors import (
    AssetCreationRejectedError,
    AssetNotFoundError,
    RunNotFoundError,
)
from backend.app.application.use_cases.video_assembly_plan_assets import (
    GetLatestVideoAssemblyPlan,
)
from backend.app.domain import (
    AssetKind,
    DownloadedClip,
    Run,
    RunStatus,
    VersionedAsset,
)
from backend.app.ports import (
    ClipDownloader,
    RunRepository,
    StoragePort,
    VersionedAssetRepository,
)

AssetIdFactory = Callable[[], str]

_DOWNLOAD_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})


class DownloadedClipSet(NamedTuple):
    """Read model bundling a manifest asset with parsed clip records."""

    asset: VersionedAsset
    downloaded_clips: tuple[DownloadedClip, ...]


class CreateDownloadedClipSet:
    def __init__(
        self,
        run_repository: RunRepository,
        asset_repository: VersionedAssetRepository,
        storage: StoragePort,
        asset_id_factory: AssetIdFactory | None = None,
    ) -> None:
        self._run_repository = run_repository
        self._asset_repository = asset_repository
        self._storage = storage
        self._asset_id_factory = asset_id_factory or _new_asset_id

    def execute(
        self,
        run_id: str,
        downloaded_clips: Sequence[DownloadedClip],
        source: str = "manual",
        asset_metadata: Mapping[str, str] | None = None,
    ) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        _require_allowed_status(run)

        metadata = dict(asset_metadata or {})
        metadata["source"] = source
        version = self._asset_repository.next_version(
            run_id, AssetKind.DOWNLOADED_CLIPS
        )
        manifest = VersionedAsset(
            asset_id=self._asset_id_factory(),
            kind=AssetKind.DOWNLOADED_CLIPS,
            version=version,
            uri="",
            metadata=metadata,
        )
        stored = self._storage.save_asset(
            manifest, _downloaded_clips_to_bytes(downloaded_clips)
        )
        self._asset_repository.save(run_id, stored)
        return stored


class DownloadClips:
    def __init__(
        self,
        run_repository: RunRepository,
        clip_downloader: ClipDownloader,
        get_latest_video_assembly_plan: GetLatestVideoAssemblyPlan,
        create_downloaded_clip_set: CreateDownloadedClipSet,
    ) -> None:
        self._run_repository = run_repository
        self._clip_downloader = clip_downloader
        self._get_latest_video_assembly_plan = get_latest_video_assembly_plan
        self._create_downloaded_clip_set = create_downloaded_clip_set

    def execute(self, run_id: str) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        _require_allowed_status(run)

        plan = self._get_latest_video_assembly_plan.execute(run_id)
        downloaded_clips = tuple(
            self._clip_downloader.download(run_id, segment)
            for segment in plan.segments
        )
        return self._create_downloaded_clip_set.execute(
            run_id,
            downloaded_clips,
            source="downloaded",
            asset_metadata={
                "video_assembly_plan_asset_id": plan.asset.asset_id,
                "video_assembly_plan_version": str(plan.asset.version),
            },
        )


class ListDownloadedClipSets:
    def __init__(self, asset_repository: VersionedAssetRepository) -> None:
        self._asset_repository = asset_repository

    def execute(self, run_id: str) -> Sequence[VersionedAsset]:
        return self._asset_repository.list_for_run(
            run_id, AssetKind.DOWNLOADED_CLIPS
        )


class GetLatestDownloadedClipSet:
    def __init__(
        self,
        asset_repository: VersionedAssetRepository,
        storage: StoragePort,
    ) -> None:
        self._asset_repository = asset_repository
        self._storage = storage

    def execute(self, run_id: str) -> DownloadedClipSet:
        latest = self._asset_repository.get_latest(
            run_id, AssetKind.DOWNLOADED_CLIPS
        )
        if latest is None:
            raise AssetNotFoundError(run_id, AssetKind.DOWNLOADED_CLIPS)
        downloaded_clips = _downloaded_clips_from_bytes(
            self._storage.load_asset(latest)
        )
        return DownloadedClipSet(
            asset=latest, downloaded_clips=downloaded_clips
        )


def _downloaded_clips_to_bytes(
    downloaded_clips: Sequence[DownloadedClip],
) -> bytes:
    payload = [
        {
            "scene_id": clip.scene_id,
            "query_text": clip.query_text,
            "provider": clip.provider,
            "provider_clip_id": clip.provider_clip_id,
            "title": clip.title,
            "source_url": clip.source_url,
            "local_uri": clip.local_uri,
            "content_type": clip.content_type,
            "duration_seconds": clip.duration_seconds,
            "width": clip.width,
            "height": clip.height,
            "order_index": clip.order_index,
            "download_status": clip.download_status,
            "download_reason": clip.download_reason,
        }
        for clip in downloaded_clips
    ]
    return json.dumps(payload).encode("utf-8")


def _downloaded_clips_from_bytes(data: bytes) -> tuple[DownloadedClip, ...]:
    payload = json.loads(data.decode("utf-8"))
    return tuple(
        DownloadedClip(
            scene_id=item["scene_id"],
            query_text=item["query_text"],
            provider=item["provider"],
            provider_clip_id=item["provider_clip_id"],
            title=item["title"],
            source_url=item["source_url"],
            local_uri=item["local_uri"],
            content_type=item["content_type"],
            duration_seconds=float(item["duration_seconds"]),
            width=int(item["width"]),
            height=int(item["height"]),
            order_index=int(item["order_index"]),
            download_status=item["download_status"],
            download_reason=item["download_reason"],
        )
        for item in payload
    )


def _require_run(repository: RunRepository, run_id: str) -> Run:
    run = repository.get(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    return run


def _require_allowed_status(run: Run) -> None:
    if run.status not in _DOWNLOAD_ALLOWED:
        raise AssetCreationRejectedError(
            run.run_id, AssetKind.DOWNLOADED_CLIPS, run.status
        )


def _new_asset_id() -> str:
    return str(uuid4())
