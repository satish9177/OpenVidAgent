"""Selected clip asset use-cases.

These use-cases persist metadata-only selected clip results. Selection is an
asset-only step: it is allowed only after scenes are approved and never
transitions the run.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import NamedTuple
from uuid import uuid4

from backend.app.application.errors import (
    AssetCreationRejectedError,
    AssetNotFoundError,
    RunNotFoundError,
)
from backend.app.application.use_cases.clip_candidate_assets import (
    GetLatestClipCandidateSet,
)
from backend.app.domain import (
    AssetKind,
    Run,
    RunStatus,
    SelectedClip,
    VersionedAsset,
)
from backend.app.ports import (
    ClipSelector,
    RunRepository,
    StoragePort,
    VersionedAssetRepository,
)

AssetIdFactory = Callable[[], str]

# D21: clip selection is asset-only and allowed only after scene approval.
_SELECTION_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})


class SelectedClipSet(NamedTuple):
    """Read model bundling the stored asset with parsed selected clips."""

    asset: VersionedAsset
    selected_clips: tuple[SelectedClip, ...]


class CreateSelectedClipSet:
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
        selected_clips: Sequence[SelectedClip],
        source: str = "manual",
    ) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        if run.status not in _SELECTION_ALLOWED:
            raise AssetCreationRejectedError(
                run_id, AssetKind.SELECTED_CLIPS, run.status
            )

        version = self._asset_repository.next_version(
            run_id, AssetKind.SELECTED_CLIPS
        )
        selected_clip_set = VersionedAsset(
            asset_id=self._asset_id_factory(),
            kind=AssetKind.SELECTED_CLIPS,
            version=version,
            uri="",
            metadata={"source": source},
        )
        stored = self._storage.save_asset(
            selected_clip_set, _selected_clips_to_bytes(selected_clips)
        )
        self._asset_repository.save(run_id, stored)
        return stored


class SelectClips:
    """Select metadata-only clips from the latest candidate set."""

    def __init__(
        self,
        run_repository: RunRepository,
        clip_selector: ClipSelector,
        get_latest_clip_candidate_set: GetLatestClipCandidateSet,
        create_selected_clip_set: CreateSelectedClipSet,
    ) -> None:
        self._run_repository = run_repository
        self._clip_selector = clip_selector
        self._get_latest_clip_candidate_set = get_latest_clip_candidate_set
        self._create_selected_clip_set = create_selected_clip_set

    def execute(self, run_id: str) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        if run.status not in _SELECTION_ALLOWED:
            raise AssetCreationRejectedError(
                run_id, AssetKind.SELECTED_CLIPS, run.status
            )

        candidate_set = self._get_latest_clip_candidate_set.execute(run_id)
        selected_clips = self._clip_selector.select(candidate_set.candidates)
        return self._create_selected_clip_set.execute(
            run_id, selected_clips, source="selected"
        )


class ListSelectedClipSets:
    def __init__(self, asset_repository: VersionedAssetRepository) -> None:
        self._asset_repository = asset_repository

    def execute(self, run_id: str) -> Sequence[VersionedAsset]:
        return self._asset_repository.list_for_run(
            run_id, AssetKind.SELECTED_CLIPS
        )


class GetLatestSelectedClipSet:
    def __init__(
        self,
        asset_repository: VersionedAssetRepository,
        storage: StoragePort,
    ) -> None:
        self._asset_repository = asset_repository
        self._storage = storage

    def execute(self, run_id: str) -> SelectedClipSet:
        latest = self._asset_repository.get_latest(
            run_id, AssetKind.SELECTED_CLIPS
        )
        if latest is None:
            raise AssetNotFoundError(run_id, AssetKind.SELECTED_CLIPS)
        selected_clips = _selected_clips_from_bytes(
            self._storage.load_asset(latest)
        )
        return SelectedClipSet(asset=latest, selected_clips=selected_clips)


def _selected_clips_to_bytes(selected_clips: Sequence[SelectedClip]) -> bytes:
    """Serialize selected clip metadata to JSON bytes."""
    payload = [
        {
            "scene_id": selected_clip.scene_id,
            "query_text": selected_clip.query_text,
            "provider": selected_clip.provider,
            "provider_clip_id": selected_clip.provider_clip_id,
            "title": selected_clip.title,
            "preview_url": selected_clip.preview_url,
            "source_url": selected_clip.source_url,
            "duration_seconds": selected_clip.duration_seconds,
            "width": selected_clip.width,
            "height": selected_clip.height,
            "selection_reason": selected_clip.selection_reason,
        }
        for selected_clip in selected_clips
    ]
    return json.dumps(payload).encode("utf-8")


def _selected_clips_from_bytes(data: bytes) -> tuple[SelectedClip, ...]:
    """Parse JSON bytes back into a ``SelectedClip`` tuple."""
    payload = json.loads(data.decode("utf-8"))
    return tuple(
        SelectedClip(
            scene_id=item["scene_id"],
            query_text=item["query_text"],
            provider=item["provider"],
            provider_clip_id=item["provider_clip_id"],
            title=item["title"],
            preview_url=item["preview_url"],
            source_url=item["source_url"],
            duration_seconds=float(item["duration_seconds"]),
            width=int(item["width"]),
            height=int(item["height"]),
            selection_reason=item["selection_reason"],
        )
        for item in payload
    )


def _require_run(repository: RunRepository, run_id: str) -> Run:
    run = repository.get(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    return run


def _new_asset_id() -> str:
    return str(uuid4())
