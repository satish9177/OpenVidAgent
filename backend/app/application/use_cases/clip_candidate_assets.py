"""Clip candidate asset use-cases.

These use-cases persist metadata-only clip retrieval results. Retrieval is an
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
from backend.app.application.use_cases.stock_assets import GetLatestStockPlan
from backend.app.domain import (
    AssetKind,
    ClipCandidate,
    Run,
    RunStatus,
    VersionedAsset,
)
from backend.app.ports import (
    ClipRetrievalProvider,
    RunRepository,
    StoragePort,
    VersionedAssetRepository,
)

AssetIdFactory = Callable[[], str]

# D15: clip retrieval is asset-only and allowed only after scene approval.
_CLIP_RETRIEVAL_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})


class ClipCandidateSet(NamedTuple):
    """Read model bundling the stored asset with parsed clip candidates."""

    asset: VersionedAsset
    candidates: tuple[ClipCandidate, ...]


class CreateClipCandidateSet:
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
        candidates: Sequence[ClipCandidate],
        source: str = "manual",
    ) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        if run.status not in _CLIP_RETRIEVAL_ALLOWED:
            raise AssetCreationRejectedError(
                run_id, AssetKind.CLIP_CANDIDATES, run.status
            )

        version = self._asset_repository.next_version(
            run_id, AssetKind.CLIP_CANDIDATES
        )
        candidate_set = VersionedAsset(
            asset_id=self._asset_id_factory(),
            kind=AssetKind.CLIP_CANDIDATES,
            version=version,
            uri="",
            metadata={"source": source},
        )
        stored = self._storage.save_asset(
            candidate_set, _candidates_to_bytes(candidates)
        )
        self._asset_repository.save(run_id, stored)
        return stored


class RetrieveClipCandidates:
    """Retrieve metadata-only clip candidates from the latest stock plan."""

    def __init__(
        self,
        run_repository: RunRepository,
        clip_retrieval_provider: ClipRetrievalProvider,
        get_latest_stock_plan: GetLatestStockPlan,
        create_clip_candidate_set: CreateClipCandidateSet,
    ) -> None:
        self._run_repository = run_repository
        self._clip_retrieval_provider = clip_retrieval_provider
        self._get_latest_stock_plan = get_latest_stock_plan
        self._create_clip_candidate_set = create_clip_candidate_set

    def execute(self, run_id: str) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        if run.status not in _CLIP_RETRIEVAL_ALLOWED:
            raise AssetCreationRejectedError(
                run_id, AssetKind.CLIP_CANDIDATES, run.status
            )

        stock_plan = self._get_latest_stock_plan.execute(run_id)
        candidates = tuple(
            candidate
            for query in stock_plan.queries
            for candidate in self._clip_retrieval_provider.retrieve(query)
        )
        return self._create_clip_candidate_set.execute(
            run_id, candidates, source="retrieved"
        )


class ListClipCandidateSets:
    def __init__(self, asset_repository: VersionedAssetRepository) -> None:
        self._asset_repository = asset_repository

    def execute(self, run_id: str) -> Sequence[VersionedAsset]:
        return self._asset_repository.list_for_run(
            run_id, AssetKind.CLIP_CANDIDATES
        )


class GetLatestClipCandidateSet:
    def __init__(
        self,
        asset_repository: VersionedAssetRepository,
        storage: StoragePort,
    ) -> None:
        self._asset_repository = asset_repository
        self._storage = storage

    def execute(self, run_id: str) -> ClipCandidateSet:
        latest = self._asset_repository.get_latest(
            run_id, AssetKind.CLIP_CANDIDATES
        )
        if latest is None:
            raise AssetNotFoundError(run_id, AssetKind.CLIP_CANDIDATES)
        candidates = _candidates_from_bytes(self._storage.load_asset(latest))
        return ClipCandidateSet(asset=latest, candidates=candidates)


def _candidates_to_bytes(candidates: Sequence[ClipCandidate]) -> bytes:
    """Serialize clip candidate metadata to JSON bytes."""
    payload = [
        {
            "scene_id": candidate.scene_id,
            "query_text": candidate.query_text,
            "provider": candidate.provider,
            "provider_clip_id": candidate.provider_clip_id,
            "title": candidate.title,
            "preview_url": candidate.preview_url,
            "source_url": candidate.source_url,
            "duration_seconds": candidate.duration_seconds,
            "width": candidate.width,
            "height": candidate.height,
        }
        for candidate in candidates
    ]
    return json.dumps(payload).encode("utf-8")


def _candidates_from_bytes(data: bytes) -> tuple[ClipCandidate, ...]:
    """Parse JSON bytes back into a ``ClipCandidate`` tuple."""
    payload = json.loads(data.decode("utf-8"))
    return tuple(
        ClipCandidate(
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
