"""Metadata-only video assembly plan asset use-cases."""

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
from backend.app.application.use_cases.scene_assets import GetLatestSceneTable
from backend.app.application.use_cases.selected_clip_assets import (
    GetLatestSelectedClipSet,
)
from backend.app.domain import (
    AssetKind,
    Run,
    RunStatus,
    VersionedAsset,
    VideoAssemblySegment,
)
from backend.app.ports import (
    RunRepository,
    StoragePort,
    VersionedAssetRepository,
    VideoAssemblyPlanner,
)

AssetIdFactory = Callable[[], str]

_VIDEO_ASSEMBLY_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})
_DEFAULT_ASPECT_RATIO = "16:9"
_DEFAULT_RENDER_INTENT = "voiceover_b_roll"


class VideoAssemblyPlan(NamedTuple):
    """Read model bundling a stored plan asset with parsed segments."""

    asset: VersionedAsset
    segments: tuple[VideoAssemblySegment, ...]


class CreateVideoAssemblyPlan:
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
        segments: Sequence[VideoAssemblySegment],
        source: str = "manual",
        asset_metadata: Mapping[str, str] | None = None,
    ) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        _require_allowed_status(run)

        metadata = dict(asset_metadata or {})
        metadata.update(
            {
                "source": source,
                "aspect_ratio": _DEFAULT_ASPECT_RATIO,
                "render_intent": _DEFAULT_RENDER_INTENT,
            }
        )
        version = self._asset_repository.next_version(
            run_id, AssetKind.VIDEO_ASSEMBLY_PLAN
        )
        plan = VersionedAsset(
            asset_id=self._asset_id_factory(),
            kind=AssetKind.VIDEO_ASSEMBLY_PLAN,
            version=version,
            uri="",
            metadata=metadata,
        )
        stored = self._storage.save_asset(plan, _segments_to_bytes(segments))
        self._asset_repository.save(run_id, stored)
        return stored


class GenerateVideoAssemblyPlan:
    def __init__(
        self,
        run_repository: RunRepository,
        video_assembly_planner: VideoAssemblyPlanner,
        get_latest_selected_clip_set: GetLatestSelectedClipSet,
        get_latest_scene_table: GetLatestSceneTable,
        create_video_assembly_plan: CreateVideoAssemblyPlan,
    ) -> None:
        self._run_repository = run_repository
        self._video_assembly_planner = video_assembly_planner
        self._get_latest_selected_clip_set = get_latest_selected_clip_set
        self._get_latest_scene_table = get_latest_scene_table
        self._create_video_assembly_plan = create_video_assembly_plan

    def execute(self, run_id: str) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        _require_allowed_status(run)

        selected_clip_set = self._get_latest_selected_clip_set.execute(run_id)
        scene_table = self._get_latest_scene_table.execute(run_id)
        segments = self._video_assembly_planner.plan(
            scene_table.scenes, selected_clip_set.selected_clips
        )
        return self._create_video_assembly_plan.execute(
            run_id,
            segments,
            source="generated",
            asset_metadata={
                "scene_table_asset_id": scene_table.asset.asset_id,
                "scene_table_version": str(scene_table.asset.version),
                "selected_clips_asset_id": selected_clip_set.asset.asset_id,
                "selected_clips_version": str(selected_clip_set.asset.version),
            },
        )


class ListVideoAssemblyPlans:
    def __init__(self, asset_repository: VersionedAssetRepository) -> None:
        self._asset_repository = asset_repository

    def execute(self, run_id: str) -> Sequence[VersionedAsset]:
        return self._asset_repository.list_for_run(
            run_id, AssetKind.VIDEO_ASSEMBLY_PLAN
        )


class GetLatestVideoAssemblyPlan:
    def __init__(
        self,
        asset_repository: VersionedAssetRepository,
        storage: StoragePort,
    ) -> None:
        self._asset_repository = asset_repository
        self._storage = storage

    def execute(self, run_id: str) -> VideoAssemblyPlan:
        latest = self._asset_repository.get_latest(
            run_id, AssetKind.VIDEO_ASSEMBLY_PLAN
        )
        if latest is None:
            raise AssetNotFoundError(run_id, AssetKind.VIDEO_ASSEMBLY_PLAN)
        segments = _segments_from_bytes(self._storage.load_asset(latest))
        return VideoAssemblyPlan(asset=latest, segments=segments)


def _segments_to_bytes(segments: Sequence[VideoAssemblySegment]) -> bytes:
    payload = [
        {
            "scene_id": segment.scene_id,
            "query_text": segment.query_text,
            "narration": segment.narration,
            "visual_query": segment.visual_query,
            "provider": segment.provider,
            "provider_clip_id": segment.provider_clip_id,
            "title": segment.title,
            "preview_url": segment.preview_url,
            "source_url": segment.source_url,
            "target_duration_seconds": segment.target_duration_seconds,
            "source_duration_seconds": segment.source_duration_seconds,
            "width": segment.width,
            "height": segment.height,
            "order_index": segment.order_index,
            "transition": segment.transition,
            "continuity_note": segment.continuity_note,
            "selection_reason": segment.selection_reason,
        }
        for segment in segments
    ]
    return json.dumps(payload).encode("utf-8")


def _segments_from_bytes(data: bytes) -> tuple[VideoAssemblySegment, ...]:
    payload = json.loads(data.decode("utf-8"))
    return tuple(
        VideoAssemblySegment(
            scene_id=item["scene_id"],
            query_text=item["query_text"],
            narration=item["narration"],
            visual_query=item["visual_query"],
            provider=item["provider"],
            provider_clip_id=item["provider_clip_id"],
            title=item["title"],
            preview_url=item["preview_url"],
            source_url=item["source_url"],
            target_duration_seconds=float(item["target_duration_seconds"]),
            source_duration_seconds=float(item["source_duration_seconds"]),
            width=int(item["width"]),
            height=int(item["height"]),
            order_index=int(item["order_index"]),
            transition=item["transition"],
            continuity_note=item["continuity_note"],
            selection_reason=item["selection_reason"],
        )
        for item in payload
    )


def _require_run(repository: RunRepository, run_id: str) -> Run:
    run = repository.get(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    return run


def _require_allowed_status(run: Run) -> None:
    if run.status not in _VIDEO_ASSEMBLY_ALLOWED:
        raise AssetCreationRejectedError(
            run.run_id, AssetKind.VIDEO_ASSEMBLY_PLAN, run.status
        )


def _new_asset_id() -> str:
    return str(uuid4())
