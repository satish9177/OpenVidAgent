"""Metadata-only subtitle manifest use-cases."""

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
from backend.app.application.use_cases.voiceover_assets import GetLatestVoiceover
from backend.app.domain import (
    AssetKind,
    Run,
    RunStatus,
    SubtitleSegment,
    VersionedAsset,
)
from backend.app.ports import (
    RunRepository,
    StoragePort,
    SubtitleComposer,
    VersionedAssetRepository,
)

AssetIdFactory = Callable[[], str]

_SUBTITLE_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})


class Subtitles(NamedTuple):
    """Read model bundling a subtitle manifest with parsed segments."""

    asset: VersionedAsset
    segments: tuple[SubtitleSegment, ...]


class CreateSubtitles:
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
        subtitle_segments: Sequence[SubtitleSegment],
        source: str = "manual",
        asset_metadata: Mapping[str, str] | None = None,
    ) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        _require_allowed_status(run)

        metadata = dict(asset_metadata or {})
        metadata["source"] = source
        version = self._asset_repository.next_version(
            run_id, AssetKind.SUBTITLE_MANIFEST
        )
        subtitles = VersionedAsset(
            asset_id=self._asset_id_factory(),
            kind=AssetKind.SUBTITLE_MANIFEST,
            version=version,
            uri="",
            metadata=metadata,
        )
        stored = self._storage.save_asset(
            subtitles, _subtitle_segments_to_bytes(subtitle_segments)
        )
        self._asset_repository.save(run_id, stored)
        return stored


class GenerateSubtitles:
    def __init__(
        self,
        run_repository: RunRepository,
        subtitle_composer: SubtitleComposer,
        get_latest_voiceover: GetLatestVoiceover,
        create_subtitles: CreateSubtitles,
    ) -> None:
        self._run_repository = run_repository
        self._subtitle_composer = subtitle_composer
        self._get_latest_voiceover = get_latest_voiceover
        self._create_subtitles = create_subtitles

    def execute(self, run_id: str) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        _require_allowed_status(run)

        voiceover = self._get_latest_voiceover.execute(run_id)
        language = voiceover.asset.metadata.get(
            "language",
            voiceover.segments[0].language if voiceover.segments else "en",
        )
        ordered_voiceover_segments = sorted(
            voiceover.segments, key=lambda segment: segment.order_index
        )
        start_seconds = 0.0
        subtitle_segments: list[SubtitleSegment] = []
        for voiceover_segment in ordered_voiceover_segments:
            subtitle_segments.append(
                self._subtitle_composer.compose(
                    voiceover_segment, start_seconds, language
                )
            )
            start_seconds += voiceover_segment.duration_seconds

        return self._create_subtitles.execute(
            run_id,
            subtitle_segments,
            source="generated",
            asset_metadata={
                "voiceover_asset_id": voiceover.asset.asset_id,
                "voiceover_version": str(voiceover.asset.version),
                "language": language,
            },
        )


class ListSubtitles:
    def __init__(self, asset_repository: VersionedAssetRepository) -> None:
        self._asset_repository = asset_repository

    def execute(self, run_id: str) -> Sequence[VersionedAsset]:
        return self._asset_repository.list_for_run(
            run_id, AssetKind.SUBTITLE_MANIFEST
        )


class GetLatestSubtitles:
    def __init__(
        self,
        asset_repository: VersionedAssetRepository,
        storage: StoragePort,
    ) -> None:
        self._asset_repository = asset_repository
        self._storage = storage

    def execute(self, run_id: str) -> Subtitles:
        latest = self._asset_repository.get_latest(
            run_id, AssetKind.SUBTITLE_MANIFEST
        )
        if latest is None:
            raise AssetNotFoundError(run_id, AssetKind.SUBTITLE_MANIFEST)
        segments = _subtitle_segments_from_bytes(
            self._storage.load_asset(latest)
        )
        return Subtitles(asset=latest, segments=segments)


def _subtitle_segments_to_bytes(
    segments: Sequence[SubtitleSegment],
) -> bytes:
    payload = [
        {
            "scene_id": segment.scene_id,
            "order_index": segment.order_index,
            "text": segment.text,
            "language": segment.language,
            "start_seconds": segment.start_seconds,
            "end_seconds": segment.end_seconds,
            "duration_seconds": segment.duration_seconds,
            "format": segment.format,
            "status": segment.status,
            "generation_reason": segment.generation_reason,
        }
        for segment in segments
    ]
    return json.dumps(payload).encode("utf-8")


def _subtitle_segments_from_bytes(data: bytes) -> tuple[SubtitleSegment, ...]:
    payload = json.loads(data.decode("utf-8"))
    return tuple(
        SubtitleSegment(
            scene_id=item["scene_id"],
            order_index=int(item["order_index"]),
            text=item["text"],
            language=item["language"],
            start_seconds=float(item["start_seconds"]),
            end_seconds=float(item["end_seconds"]),
            duration_seconds=float(item["duration_seconds"]),
            format=item["format"],
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
    if run.status not in _SUBTITLE_ALLOWED:
        raise AssetCreationRejectedError(
            run.run_id, AssetKind.SUBTITLE_MANIFEST, run.status
        )


def _new_asset_id() -> str:
    return str(uuid4())
