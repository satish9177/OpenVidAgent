"""Metadata-only voiceover manifest use-cases."""

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
    Run,
    RunStatus,
    VersionedAsset,
    VoiceoverSegment,
)
from backend.app.ports import (
    RunRepository,
    StoragePort,
    VersionedAssetRepository,
    VoiceoverGenerator,
)

AssetIdFactory = Callable[[], str]

_VOICEOVER_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})


class Voiceover(NamedTuple):
    """Read model bundling a voiceover asset with parsed segments."""

    asset: VersionedAsset
    segments: tuple[VoiceoverSegment, ...]


class CreateVoiceover:
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
        voiceover_segments: Sequence[VoiceoverSegment],
        source: str = "manual",
        asset_metadata: Mapping[str, str] | None = None,
    ) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        _require_allowed_status(run)

        metadata = dict(asset_metadata or {})
        metadata["source"] = source
        version = self._asset_repository.next_version(
            run_id, AssetKind.VOICEOVER
        )
        voiceover = VersionedAsset(
            asset_id=self._asset_id_factory(),
            kind=AssetKind.VOICEOVER,
            version=version,
            uri="",
            metadata=metadata,
        )
        stored = self._storage.save_asset(
            voiceover, _voiceover_segments_to_bytes(voiceover_segments)
        )
        self._asset_repository.save(run_id, stored)
        return stored


class GenerateVoiceover:
    def __init__(
        self,
        run_repository: RunRepository,
        voiceover_generator: VoiceoverGenerator,
        get_latest_video_assembly_plan: GetLatestVideoAssemblyPlan,
        create_voiceover: CreateVoiceover,
    ) -> None:
        self._run_repository = run_repository
        self._voiceover_generator = voiceover_generator
        self._get_latest_video_assembly_plan = get_latest_video_assembly_plan
        self._create_voiceover = create_voiceover

    def execute(self, run_id: str) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        _require_allowed_status(run)

        plan = self._get_latest_video_assembly_plan.execute(run_id)
        segments = tuple(
            self._voiceover_generator.generate(run_id, segment, run.language)
            for segment in plan.segments
        )
        return self._create_voiceover.execute(
            run_id,
            segments,
            source="generated",
            asset_metadata={
                "video_assembly_plan_asset_id": plan.asset.asset_id,
                "video_assembly_plan_version": str(plan.asset.version),
                "language": run.language,
            },
        )


class ListVoiceovers:
    def __init__(self, asset_repository: VersionedAssetRepository) -> None:
        self._asset_repository = asset_repository

    def execute(self, run_id: str) -> Sequence[VersionedAsset]:
        return self._asset_repository.list_for_run(run_id, AssetKind.VOICEOVER)


class GetLatestVoiceover:
    def __init__(
        self,
        asset_repository: VersionedAssetRepository,
        storage: StoragePort,
    ) -> None:
        self._asset_repository = asset_repository
        self._storage = storage

    def execute(self, run_id: str) -> Voiceover:
        latest = self._asset_repository.get_latest(run_id, AssetKind.VOICEOVER)
        if latest is None:
            raise AssetNotFoundError(run_id, AssetKind.VOICEOVER)
        segments = _voiceover_segments_from_bytes(
            self._storage.load_asset(latest)
        )
        return Voiceover(asset=latest, segments=segments)


def _voiceover_segments_to_bytes(
    segments: Sequence[VoiceoverSegment],
) -> bytes:
    payload = [
        {
            "scene_id": segment.scene_id,
            "order_index": segment.order_index,
            "narration_text": segment.narration_text,
            "language": segment.language,
            "voice_id": segment.voice_id,
            "provider": segment.provider,
            "audio_uri": segment.audio_uri,
            "content_type": segment.content_type,
            "duration_seconds": segment.duration_seconds,
            "status": segment.status,
            "generation_reason": segment.generation_reason,
        }
        for segment in segments
    ]
    return json.dumps(payload).encode("utf-8")


def _voiceover_segments_from_bytes(data: bytes) -> tuple[VoiceoverSegment, ...]:
    payload = json.loads(data.decode("utf-8"))
    return tuple(
        VoiceoverSegment(
            scene_id=item["scene_id"],
            order_index=int(item["order_index"]),
            narration_text=item["narration_text"],
            language=item["language"],
            voice_id=item["voice_id"],
            provider=item["provider"],
            audio_uri=item["audio_uri"],
            content_type=item["content_type"],
            duration_seconds=float(item["duration_seconds"]),
            status=item["status"],
            generation_reason=item["generation_reason"],
        )
        for item in payload
    )


def _require_run(repository: RunRepository, run_id: str) -> Run:
    run = repository.get(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    return run


def _require_allowed_status(run: Run) -> None:
    if run.status not in _VOICEOVER_ALLOWED:
        raise AssetCreationRejectedError(
            run.run_id, AssetKind.VOICEOVER, run.status
        )


def _new_asset_id() -> str:
    return str(uuid4())
