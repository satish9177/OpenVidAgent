"""Metadata-only render plan asset use-cases."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import NamedTuple
from uuid import uuid4

from backend.app.application.errors import (
    AssetCreationRejectedError,
    AssetNotFoundError,
    RenderPlanInputMismatchError,
    RunNotFoundError,
)
from backend.app.application.use_cases.downloaded_clip_assets import (
    GetLatestDownloadedClipSet,
)
from backend.app.application.use_cases.subtitle_assets import GetLatestSubtitles
from backend.app.application.use_cases.video_assembly_plan_assets import (
    GetLatestVideoAssemblyPlan,
)
from backend.app.application.use_cases.voiceover_assets import GetLatestVoiceover
from backend.app.domain import (
    AssetKind,
    RenderPlanSegment,
    Run,
    RunStatus,
    VersionedAsset,
)
from backend.app.ports import (
    RenderPlanner,
    RunRepository,
    StoragePort,
    VersionedAssetRepository,
)

AssetIdFactory = Callable[[], str]

_RENDER_PLAN_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})
_RENDER_PROFILE = {
    "aspect_ratio": "16:9",
    "resolution_width": "1920",
    "resolution_height": "1080",
    "fps": "30",
    "container": "mp4",
    "render_intent": "voiceover_b_roll",
}


class RenderPlan(NamedTuple):
    """Read model bundling a render-plan asset with parsed segments."""

    asset: VersionedAsset
    segments: tuple[RenderPlanSegment, ...]


class CreateRenderPlan:
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
        render_plan_segments: Sequence[RenderPlanSegment],
        source: str = "manual",
        asset_metadata: Mapping[str, str] | None = None,
    ) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        _require_allowed_status(run)

        metadata = dict(asset_metadata or {})
        metadata["source"] = source
        version = self._asset_repository.next_version(
            run_id, AssetKind.RENDER_PLAN
        )
        render_plan = VersionedAsset(
            asset_id=self._asset_id_factory(),
            kind=AssetKind.RENDER_PLAN,
            version=version,
            uri="",
            metadata=metadata,
        )
        stored = self._storage.save_asset(
            render_plan, _render_plan_segments_to_bytes(render_plan_segments)
        )
        self._asset_repository.save(run_id, stored)
        return stored


class GenerateRenderPlan:
    def __init__(
        self,
        run_repository: RunRepository,
        render_planner: RenderPlanner,
        get_latest_video_assembly_plan: GetLatestVideoAssemblyPlan,
        get_latest_downloaded_clip_set: GetLatestDownloadedClipSet,
        get_latest_voiceover: GetLatestVoiceover,
        get_latest_subtitles: GetLatestSubtitles,
        create_render_plan: CreateRenderPlan,
    ) -> None:
        self._run_repository = run_repository
        self._render_planner = render_planner
        self._get_latest_video_assembly_plan = get_latest_video_assembly_plan
        self._get_latest_downloaded_clip_set = get_latest_downloaded_clip_set
        self._get_latest_voiceover = get_latest_voiceover
        self._get_latest_subtitles = get_latest_subtitles
        self._create_render_plan = create_render_plan

    def execute(self, run_id: str) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        _require_allowed_status(run)

        assembly_plan = self._get_latest_video_assembly_plan.execute(run_id)
        downloaded_clips = self._get_latest_downloaded_clip_set.execute(run_id)
        voiceover = self._get_latest_voiceover.execute(run_id)
        subtitles = self._get_latest_subtitles.execute(run_id)

        expected_order = tuple(
            segment.order_index for segment in assembly_plan.segments
        )
        _validate_order_indexes(
            run_id,
            "downloaded_clips",
            expected_order,
            tuple(clip.order_index for clip in downloaded_clips.downloaded_clips),
        )
        _validate_order_indexes(
            run_id,
            "voiceover",
            expected_order,
            tuple(segment.order_index for segment in voiceover.segments),
        )
        _validate_order_indexes(
            run_id,
            "subtitles",
            expected_order,
            tuple(segment.order_index for segment in subtitles.segments),
        )

        segments = self._render_planner.plan(
            assembly_plan.segments,
            downloaded_clips.downloaded_clips,
            voiceover.segments,
            subtitles.segments,
        )
        metadata = {
            "video_assembly_plan_asset_id": assembly_plan.asset.asset_id,
            "video_assembly_plan_version": str(assembly_plan.asset.version),
            "downloaded_clips_asset_id": downloaded_clips.asset.asset_id,
            "downloaded_clips_version": str(downloaded_clips.asset.version),
            "voiceover_asset_id": voiceover.asset.asset_id,
            "voiceover_version": str(voiceover.asset.version),
            "subtitles_asset_id": subtitles.asset.asset_id,
            "subtitles_version": str(subtitles.asset.version),
            **_RENDER_PROFILE,
        }
        return self._create_render_plan.execute(
            run_id,
            segments,
            source="generated",
            asset_metadata=metadata,
        )


class ListRenderPlans:
    def __init__(self, asset_repository: VersionedAssetRepository) -> None:
        self._asset_repository = asset_repository

    def execute(self, run_id: str) -> Sequence[VersionedAsset]:
        return self._asset_repository.list_for_run(run_id, AssetKind.RENDER_PLAN)


class GetLatestRenderPlan:
    def __init__(
        self,
        asset_repository: VersionedAssetRepository,
        storage: StoragePort,
    ) -> None:
        self._asset_repository = asset_repository
        self._storage = storage

    def execute(self, run_id: str) -> RenderPlan:
        latest = self._asset_repository.get_latest(run_id, AssetKind.RENDER_PLAN)
        if latest is None:
            raise AssetNotFoundError(run_id, AssetKind.RENDER_PLAN)
        segments = _render_plan_segments_from_bytes(
            self._storage.load_asset(latest)
        )
        return RenderPlan(asset=latest, segments=segments)


def _render_plan_segments_to_bytes(
    segments: Sequence[RenderPlanSegment],
) -> bytes:
    payload = [
        {
            "order_index": segment.order_index,
            "scene_id": segment.scene_id,
            "clip_uri": segment.clip_uri,
            "clip_provider": segment.clip_provider,
            "clip_provider_id": segment.clip_provider_id,
            "visual_start_seconds": segment.visual_start_seconds,
            "visual_end_seconds": segment.visual_end_seconds,
            "visual_duration_seconds": segment.visual_duration_seconds,
            "voiceover_uri": segment.voiceover_uri,
            "voiceover_start_seconds": segment.voiceover_start_seconds,
            "voiceover_end_seconds": segment.voiceover_end_seconds,
            "voiceover_duration_seconds": segment.voiceover_duration_seconds,
            "subtitle_text": segment.subtitle_text,
            "subtitle_start_seconds": segment.subtitle_start_seconds,
            "subtitle_end_seconds": segment.subtitle_end_seconds,
            "subtitle_language": segment.subtitle_language,
        }
        for segment in segments
    ]
    return json.dumps(payload).encode("utf-8")


def _render_plan_segments_from_bytes(
    data: bytes,
) -> tuple[RenderPlanSegment, ...]:
    payload = json.loads(data.decode("utf-8"))
    return tuple(
        RenderPlanSegment(
            order_index=int(item["order_index"]),
            scene_id=item["scene_id"],
            clip_uri=item["clip_uri"],
            clip_provider=item["clip_provider"],
            clip_provider_id=item["clip_provider_id"],
            visual_start_seconds=float(item["visual_start_seconds"]),
            visual_end_seconds=float(item["visual_end_seconds"]),
            visual_duration_seconds=float(item["visual_duration_seconds"]),
            voiceover_uri=item["voiceover_uri"],
            voiceover_start_seconds=float(item["voiceover_start_seconds"]),
            voiceover_end_seconds=float(item["voiceover_end_seconds"]),
            voiceover_duration_seconds=float(
                item["voiceover_duration_seconds"]
            ),
            subtitle_text=item["subtitle_text"],
            subtitle_start_seconds=float(item["subtitle_start_seconds"]),
            subtitle_end_seconds=float(item["subtitle_end_seconds"]),
            subtitle_language=item["subtitle_language"],
        )
        for item in payload
    )


def _validate_order_indexes(
    run_id: str,
    source: str,
    expected_order_indexes: tuple[int, ...],
    actual_order_indexes: tuple[int, ...],
) -> None:
    if (
        len(actual_order_indexes) != len(expected_order_indexes)
        or set(actual_order_indexes) != set(expected_order_indexes)
    ):
        raise RenderPlanInputMismatchError(
            run_id,
            source,
            expected_order_indexes,
            actual_order_indexes,
        )


def _require_run(repository: RunRepository, run_id: str) -> Run:
    run = repository.get(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    return run


def _require_allowed_status(run: Run) -> None:
    if run.status not in _RENDER_PLAN_ALLOWED:
        raise AssetCreationRejectedError(
            run.run_id, AssetKind.RENDER_PLAN, run.status
        )


def _new_asset_id() -> str:
    return str(uuid4())
