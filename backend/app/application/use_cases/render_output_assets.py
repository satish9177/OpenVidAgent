"""Metadata-only render output manifest use-cases."""

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
from backend.app.application.use_cases.render_plan_assets import (
    GetLatestRenderPlan,
)
from backend.app.domain import (
    AssetKind,
    RenderOutputManifest,
    Run,
    RunStatus,
    VersionedAsset,
)
from backend.app.ports import (
    RenderOutputGenerator,
    RunRepository,
    StoragePort,
    VersionedAssetRepository,
)

AssetIdFactory = Callable[[], str]

_RENDER_OUTPUT_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})
_RENDER_PROFILE_DEFAULTS = {
    "aspect_ratio": "16:9",
    "resolution_width": "1920",
    "resolution_height": "1080",
    "fps": "30",
    "container": "mp4",
    "render_intent": "voiceover_b_roll",
}


class RenderOutput(NamedTuple):
    """Read model bundling an output asset with its parsed manifest."""

    asset: VersionedAsset
    manifest: RenderOutputManifest


class CreateRenderOutput:
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
        manifest: RenderOutputManifest,
        source: str = "manual",
        asset_metadata: Mapping[str, str] | None = None,
    ) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        _require_allowed_status(run)

        metadata = dict(asset_metadata or {})
        metadata["source"] = source
        version = self._asset_repository.next_version(
            run_id, AssetKind.RENDER_OUTPUT
        )
        render_output = VersionedAsset(
            asset_id=self._asset_id_factory(),
            kind=AssetKind.RENDER_OUTPUT,
            version=version,
            uri="",
            metadata=metadata,
        )
        stored = self._storage.save_asset(
            render_output, _render_output_manifest_to_bytes(manifest)
        )
        self._asset_repository.save(run_id, stored)
        return stored


class GenerateRenderOutput:
    def __init__(
        self,
        run_repository: RunRepository,
        render_output_generator: RenderOutputGenerator,
        get_latest_render_plan: GetLatestRenderPlan,
        create_render_output: CreateRenderOutput,
    ) -> None:
        self._run_repository = run_repository
        self._render_output_generator = render_output_generator
        self._get_latest_render_plan = get_latest_render_plan
        self._create_render_output = create_render_output

    def execute(self, run_id: str) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        _require_allowed_status(run)

        render_plan = self._get_latest_render_plan.execute(run_id)
        render_profile = _resolve_render_profile(render_plan.asset.metadata)
        manifest = self._render_output_generator.generate(
            render_plan.asset.asset_id,
            render_plan.asset.version,
            render_plan.segments,
            render_profile,
        )
        return self._create_render_output.execute(
            run_id,
            manifest,
            source="generated",
            asset_metadata={
                "render_plan_asset_id": render_plan.asset.asset_id,
                "render_plan_version": str(render_plan.asset.version),
                "status": manifest.status,
                **render_profile,
            },
        )


class ListRenderOutputs:
    def __init__(self, asset_repository: VersionedAssetRepository) -> None:
        self._asset_repository = asset_repository

    def execute(self, run_id: str) -> Sequence[VersionedAsset]:
        return self._asset_repository.list_for_run(
            run_id, AssetKind.RENDER_OUTPUT
        )


class GetLatestRenderOutput:
    def __init__(
        self,
        asset_repository: VersionedAssetRepository,
        storage: StoragePort,
    ) -> None:
        self._asset_repository = asset_repository
        self._storage = storage

    def execute(self, run_id: str) -> RenderOutput:
        latest = self._asset_repository.get_latest(
            run_id, AssetKind.RENDER_OUTPUT
        )
        if latest is None:
            raise AssetNotFoundError(run_id, AssetKind.RENDER_OUTPUT)
        manifest = _render_output_manifest_from_bytes(
            self._storage.load_asset(latest)
        )
        return RenderOutput(asset=latest, manifest=manifest)


def _render_output_manifest_to_bytes(manifest: RenderOutputManifest) -> bytes:
    payload = {
        "status": manifest.status,
        "render_plan_asset_id": manifest.render_plan_asset_id,
        "render_plan_version": manifest.render_plan_version,
        "render_intent": manifest.render_intent,
        "aspect_ratio": manifest.aspect_ratio,
        "container": manifest.container,
        "resolution_width": manifest.resolution_width,
        "resolution_height": manifest.resolution_height,
        "fps": manifest.fps,
        "segment_count": manifest.segment_count,
        "estimated_duration_seconds": manifest.estimated_duration_seconds,
        "output_uri": manifest.output_uri,
        "generation_reason": manifest.generation_reason,
    }
    return json.dumps(payload).encode("utf-8")


def _render_output_manifest_from_bytes(data: bytes) -> RenderOutputManifest:
    item = json.loads(data.decode("utf-8"))
    output_uri = item["output_uri"]
    return RenderOutputManifest(
        status=item["status"],
        render_plan_asset_id=item["render_plan_asset_id"],
        render_plan_version=int(item["render_plan_version"]),
        render_intent=item["render_intent"],
        aspect_ratio=item["aspect_ratio"],
        container=item["container"],
        resolution_width=int(item["resolution_width"]),
        resolution_height=int(item["resolution_height"]),
        fps=float(item["fps"]),
        segment_count=int(item["segment_count"]),
        estimated_duration_seconds=float(item["estimated_duration_seconds"]),
        output_uri=None if output_uri is None else str(output_uri),
        generation_reason=item["generation_reason"],
    )


def _resolve_render_profile(metadata: Mapping[str, str]) -> dict[str, str]:
    return {
        key: metadata.get(key, default)
        for key, default in _RENDER_PROFILE_DEFAULTS.items()
    }


def _require_run(repository: RunRepository, run_id: str) -> Run:
    run = repository.get(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    return run


def _require_allowed_status(run: Run) -> None:
    if run.status not in _RENDER_OUTPUT_ALLOWED:
        raise AssetCreationRejectedError(
            run.run_id, AssetKind.RENDER_OUTPUT, run.status
        )


def _new_asset_id() -> str:
    return str(uuid4())
