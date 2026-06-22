"""Metadata-only render-readiness report use-cases."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import NamedTuple
from uuid import uuid4

from backend.app.application.errors import (
    AssetCreationRejectedError,
    AssetNotFoundError,
    RunNotFoundError,
)
from backend.app.application.use_cases.render_output_assets import (
    GetLatestRenderOutput,
    RenderOutput,
)
from backend.app.application.use_cases.render_plan_assets import (
    GetLatestRenderPlan,
)
from backend.app.domain import (
    AssetKind,
    RenderInputReadiness,
    RenderReadinessReport,
    Run,
    RunStatus,
    VersionedAsset,
)
from backend.app.ports import (
    FfmpegAvailabilityProbe,
    RenderReadinessChecker,
    RunRepository,
    StoragePort,
    VersionedAssetRepository,
)

AssetIdFactory = Callable[[], str]

_RENDER_READINESS_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})


class RenderReadiness(NamedTuple):
    """Read model bundling a readiness asset with its parsed report."""

    asset: VersionedAsset
    report: RenderReadinessReport


class CreateRenderReadiness:
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
        report: RenderReadinessReport,
        source: str = "manual",
        asset_metadata: Mapping[str, str] | None = None,
    ) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        _require_allowed_status(run)

        metadata = dict(asset_metadata or {})
        metadata["source"] = source
        version = self._asset_repository.next_version(
            run_id, AssetKind.RENDER_READINESS
        )
        readiness = VersionedAsset(
            asset_id=self._asset_id_factory(),
            kind=AssetKind.RENDER_READINESS,
            version=version,
            uri="",
            metadata=metadata,
        )
        stored = self._storage.save_asset(
            readiness, _render_readiness_report_to_bytes(report)
        )
        self._asset_repository.save(run_id, stored)
        return stored


class GenerateRenderReadiness:
    def __init__(
        self,
        run_repository: RunRepository,
        render_readiness_checker: RenderReadinessChecker,
        ffmpeg_availability_probe: FfmpegAvailabilityProbe,
        get_latest_render_plan: GetLatestRenderPlan,
        get_latest_render_output: GetLatestRenderOutput,
        create_render_readiness: CreateRenderReadiness,
    ) -> None:
        self._run_repository = run_repository
        self._render_readiness_checker = render_readiness_checker
        self._ffmpeg_availability_probe = ffmpeg_availability_probe
        self._get_latest_render_plan = get_latest_render_plan
        self._get_latest_render_output = get_latest_render_output
        self._create_render_readiness = create_render_readiness

    def execute(self, run_id: str) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        _require_allowed_status(run)

        render_plan = self._get_latest_render_plan.execute(run_id)
        render_output = self._optional_render_output(run_id)
        availability = self._ffmpeg_availability_probe.check()
        report = self._render_readiness_checker.check(
            render_plan.asset.asset_id,
            render_plan.asset.version,
            render_plan.segments,
            None if render_output is None else render_output.manifest,
            availability,
        )
        output_asset = None if render_output is None else render_output.asset
        report = replace(
            report,
            render_plan_asset_id=render_plan.asset.asset_id,
            render_plan_version=render_plan.asset.version,
            render_output_asset_id=(
                None if output_asset is None else output_asset.asset_id
            ),
            render_output_version=(
                None if output_asset is None else output_asset.version
            ),
            ffmpeg_availability=availability,
        )
        return self._create_render_readiness.execute(
            run_id,
            report,
            source="generated",
            asset_metadata={
                "render_plan_asset_id": render_plan.asset.asset_id,
                "render_plan_version": str(render_plan.asset.version),
                "render_output_asset_id": (
                    "" if output_asset is None else output_asset.asset_id
                ),
                "render_output_version": (
                    "" if output_asset is None else str(output_asset.version)
                ),
                "status": report.status,
                "ffmpeg_availability": report.ffmpeg_availability,
            },
        )

    def _optional_render_output(self, run_id: str) -> RenderOutput | None:
        try:
            return self._get_latest_render_output.execute(run_id)
        except AssetNotFoundError as error:
            if error.kind is not AssetKind.RENDER_OUTPUT:
                raise
            return None


class ListRenderReadiness:
    def __init__(self, asset_repository: VersionedAssetRepository) -> None:
        self._asset_repository = asset_repository

    def execute(self, run_id: str) -> Sequence[VersionedAsset]:
        return self._asset_repository.list_for_run(
            run_id, AssetKind.RENDER_READINESS
        )


class GetLatestRenderReadiness:
    def __init__(
        self,
        asset_repository: VersionedAssetRepository,
        storage: StoragePort,
    ) -> None:
        self._asset_repository = asset_repository
        self._storage = storage

    def execute(self, run_id: str) -> RenderReadiness:
        latest = self._asset_repository.get_latest(
            run_id, AssetKind.RENDER_READINESS
        )
        if latest is None:
            raise AssetNotFoundError(run_id, AssetKind.RENDER_READINESS)
        report = _render_readiness_report_from_bytes(
            self._storage.load_asset(latest)
        )
        return RenderReadiness(asset=latest, report=report)


def _render_readiness_report_to_bytes(report: RenderReadinessReport) -> bytes:
    payload = {
        "status": report.status,
        "render_plan_asset_id": report.render_plan_asset_id,
        "render_plan_version": report.render_plan_version,
        "render_output_asset_id": report.render_output_asset_id,
        "render_output_version": report.render_output_version,
        "ffmpeg_availability": report.ffmpeg_availability,
        "segment_count": report.segment_count,
        "materialized_required_count": report.materialized_required_count,
        "total_required_count": report.total_required_count,
        "inputs": [
            {
                "order_index": item.order_index,
                "scene_id": item.scene_id,
                "role": item.role,
                "uri": item.uri,
                "scheme": item.scheme,
                "required": item.required,
                "status": item.status,
                "blocker_reason": item.blocker_reason,
            }
            for item in report.inputs
        ],
        "blocker_summary": list(report.blocker_summary),
        "warnings": list(report.warnings),
        "generation_reason": report.generation_reason,
    }
    return json.dumps(payload).encode("utf-8")


def _render_readiness_report_from_bytes(data: bytes) -> RenderReadinessReport:
    item = json.loads(data.decode("utf-8"))
    output_asset_id = item["render_output_asset_id"]
    output_version = item["render_output_version"]
    return RenderReadinessReport(
        status=str(item["status"]),
        render_plan_asset_id=str(item["render_plan_asset_id"]),
        render_plan_version=int(item["render_plan_version"]),
        render_output_asset_id=(
            None if output_asset_id is None else str(output_asset_id)
        ),
        render_output_version=(
            None if output_version is None else int(output_version)
        ),
        ffmpeg_availability=str(item["ffmpeg_availability"]),
        segment_count=int(item["segment_count"]),
        materialized_required_count=int(item["materialized_required_count"]),
        total_required_count=int(item["total_required_count"]),
        inputs=tuple(
            RenderInputReadiness(
                order_index=int(input_item["order_index"]),
                scene_id=str(input_item["scene_id"]),
                role=str(input_item["role"]),
                uri=str(input_item["uri"]),
                scheme=str(input_item["scheme"]),
                required=bool(input_item["required"]),
                status=str(input_item["status"]),
                blocker_reason=(
                    None
                    if input_item["blocker_reason"] is None
                    else str(input_item["blocker_reason"])
                ),
            )
            for input_item in item["inputs"]
        ),
        blocker_summary=tuple(str(value) for value in item["blocker_summary"]),
        warnings=tuple(str(value) for value in item["warnings"]),
        generation_reason=str(item["generation_reason"]),
    )


def _require_run(repository: RunRepository, run_id: str) -> Run:
    run = repository.get(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    return run


def _require_allowed_status(run: Run) -> None:
    if run.status not in _RENDER_READINESS_ALLOWED:
        raise AssetCreationRejectedError(
            run.run_id, AssetKind.RENDER_READINESS, run.status
        )


def _new_asset_id() -> str:
    return str(uuid4())
