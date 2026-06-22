"""Render-readiness asset use-case tests."""

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
    CreateRenderOutput,
    CreateRenderPlan,
    CreateRenderReadiness,
    GenerateRenderReadiness,
    GetLatestRenderOutput,
    GetLatestRenderPlan,
    GetLatestRenderReadiness,
    ListRenderReadiness,
)
from backend.app.domain import (
    AssetKind,
    RenderInputReadiness,
    RenderOutputManifest,
    RenderPlanSegment,
    RenderReadinessReport,
    Run,
    RunStatus,
)
from tests.fakes import (
    FakeFfmpegAvailabilityProbe,
    FakeRenderReadinessChecker,
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
) -> None:
    runs.save(Run(run_id="run-1", prompt="prompt", status=status))


def _segment(index: int = 0) -> RenderPlanSegment:
    return RenderPlanSegment(
        order_index=index,
        scene_id=f"scene-{index + 1}",
        clip_uri=f"memory://clips/{index}.mp4",
        clip_provider="stub",
        clip_provider_id=f"clip-{index}",
        visual_start_seconds=float(index * 4),
        visual_end_seconds=float((index + 1) * 4),
        visual_duration_seconds=4.0,
        voiceover_uri=f"memory://voiceovers/{index}.mp3",
        voiceover_start_seconds=float(index * 4),
        voiceover_end_seconds=float((index + 1) * 4),
        voiceover_duration_seconds=4.0,
        subtitle_text="Narration",
        subtitle_start_seconds=float(index * 4),
        subtitle_end_seconds=float((index + 1) * 4),
        subtitle_language="en",
    )


def _output_manifest(plan_id: str, plan_version: int) -> RenderOutputManifest:
    return RenderOutputManifest(
        status="not_rendered",
        render_plan_asset_id=plan_id,
        render_plan_version=plan_version,
        render_intent="voiceover_b_roll",
        aspect_ratio="16:9",
        container="mp4",
        resolution_width=1920,
        resolution_height=1080,
        fps=30.0,
        segment_count=1,
        estimated_duration_seconds=4.0,
        output_uri=None,
        generation_reason="metadata_only_foundation",
    )


def _report(status: str = "blocked") -> RenderReadinessReport:
    return RenderReadinessReport(
        status=status,
        render_plan_asset_id="checker-plan",
        render_plan_version=99,
        render_output_asset_id=None,
        render_output_version=None,
        ffmpeg_availability="not_checked",
        segment_count=1,
        materialized_required_count=0,
        total_required_count=2,
        inputs=(
            RenderInputReadiness(
                order_index=0,
                scene_id="scene-1",
                role="clip",
                uri="memory://clips/0.mp4",
                scheme="memory",
                required=True,
                status="placeholder",
                blocker_reason="clip_not_materialized",
            ),
        ),
        blocker_summary=("clip_not_materialized",),
        warnings=("subtitle_manifest_only",),
        generation_reason="fake_check",
    )


def _create_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
) -> CreateRenderReadiness:
    ids = (f"readiness-{number}" for number in itertools.count(1))
    return CreateRenderReadiness(
        runs, assets, storage, asset_id_factory=lambda: next(ids)
    )


def _seed_plan_and_output(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    *,
    versions: int = 1,
) -> tuple[tuple[RenderPlanSegment, ...], RenderOutputManifest]:
    plan_ids = iter(f"plan-{number}" for number in range(1, versions + 1))
    output_ids = iter(f"output-{number}" for number in range(1, versions + 1))
    create_plan = CreateRenderPlan(
        runs, assets, storage, asset_id_factory=lambda: next(plan_ids)
    )
    create_output = CreateRenderOutput(
        runs, assets, storage, asset_id_factory=lambda: next(output_ids)
    )
    latest_segments: tuple[RenderPlanSegment, ...] = ()
    latest_manifest = _output_manifest("plan-1", 1)
    for version in range(1, versions + 1):
        latest_segments = (_segment(version - 1),)
        plan = create_plan.execute("run-1", latest_segments)
        latest_manifest = _output_manifest(plan.asset_id, plan.version)
        create_output.execute("run-1", latest_manifest)
    return latest_segments, latest_manifest


def _generate_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    checker: FakeRenderReadinessChecker,
    probe: FakeFfmpegAvailabilityProbe,
) -> GenerateRenderReadiness:
    return GenerateRenderReadiness(
        runs,
        checker,
        probe,
        GetLatestRenderPlan(assets, storage),
        GetLatestRenderOutput(assets, storage),
        _create_use_case(runs, assets, storage),
    )


def test_create_versions_json_and_round_trips_nested_types() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    create = _create_use_case(runs, assets, storage)
    report = _report()

    first = create.execute("run-1", report)
    second = create.execute("run-1", report)

    assert first.kind is AssetKind.RENDER_READINESS
    assert (first.version, second.version) == (1, 2)
    assert first.metadata == {"source": "manual"}
    assert [asset.version for asset in ListRenderReadiness(assets).execute(
        "run-1"
    )] == [1, 2]
    latest = GetLatestRenderReadiness(assets, storage).execute("run-1")
    assert latest.asset == second
    assert latest.report == report
    payload = json.loads(storage.saved[first.uri].decode("utf-8"))
    assert isinstance(payload, dict)
    assert isinstance(payload["render_plan_version"], int)
    assert payload["render_output_asset_id"] is None
    assert payload["render_output_version"] is None
    assert isinstance(payload["inputs"][0]["order_index"], int)
    assert isinstance(payload["inputs"][0]["required"], bool)
    assert payload["inputs"][0]["blocker_reason"] == "clip_not_materialized"


def test_generate_reads_latest_plan_and_output_and_persists_blocked_report() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    segments, output_manifest = _seed_plan_and_output(
        runs, assets, storage, versions=2
    )
    checker = FakeRenderReadinessChecker(_report())
    probe = FakeFfmpegAvailabilityProbe()

    asset = _generate_use_case(
        runs, assets, storage, checker, probe
    ).execute("run-1")

    assert checker.calls == [
        ("plan-2", 2, segments, output_manifest, "not_checked")
    ]
    assert probe.call_count == 1
    assert asset.metadata == {
        "render_plan_asset_id": "plan-2",
        "render_plan_version": "2",
        "render_output_asset_id": "output-2",
        "render_output_version": "2",
        "status": "blocked",
        "ffmpeg_availability": "not_checked",
        "source": "generated",
    }
    assert all(isinstance(value, str) for value in asset.metadata.values())
    latest = GetLatestRenderReadiness(assets, storage).execute("run-1")
    assert latest.report.render_plan_asset_id == "plan-2"
    assert latest.report.render_output_asset_id == "output-2"
    assert latest.report.render_output_version == 2
    assert latest.report.status == "blocked"
    assert runs.get("run-1").status is RunStatus.SCENES_APPROVED


def test_generate_tolerates_missing_render_output() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    CreateRenderPlan(
        runs, assets, storage, asset_id_factory=lambda: "plan-1"
    ).execute("run-1", (_segment(),))
    checker = FakeRenderReadinessChecker(_report())
    probe = FakeFfmpegAvailabilityProbe()

    asset = _generate_use_case(
        runs, assets, storage, checker, probe
    ).execute("run-1")

    assert checker.calls[0][3] is None
    assert asset.metadata["render_output_asset_id"] == ""
    assert asset.metadata["render_output_version"] == ""
    latest = GetLatestRenderReadiness(assets, storage).execute("run-1")
    assert latest.report.render_output_asset_id is None
    assert latest.report.render_output_version is None


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
        _create_use_case(runs, assets, storage).execute("run-1", _report())

    assert exc_info.value.kind is AssetKind.RENDER_READINESS
    assert assets.list_for_run("run-1", AssetKind.RENDER_READINESS) == []
    assert storage.saved == {}


def test_generate_invalid_status_wins_before_dependency_reads() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.CREATED)
    checker = FakeRenderReadinessChecker(_report())
    probe = FakeFfmpegAvailabilityProbe()

    with pytest.raises(AssetCreationRejectedError) as exc_info:
        _generate_use_case(runs, assets, storage, checker, probe).execute(
            "run-1"
        )

    assert exc_info.value.kind is AssetKind.RENDER_READINESS
    assert checker.calls == []
    assert probe.call_count == 0


def test_generate_missing_render_plan_raises_naturally() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    checker = FakeRenderReadinessChecker(_report())
    probe = FakeFfmpegAvailabilityProbe()

    with pytest.raises(AssetNotFoundError) as exc_info:
        _generate_use_case(runs, assets, storage, checker, probe).execute(
            "run-1"
        )

    assert exc_info.value.kind is AssetKind.RENDER_PLAN
    assert checker.calls == []
    assert probe.call_count == 0


def test_generate_missing_run_raises_before_dependency_reads() -> None:
    runs, assets, storage = _triple()
    checker = FakeRenderReadinessChecker(_report())
    probe = FakeFfmpegAvailabilityProbe()

    with pytest.raises(RunNotFoundError):
        _generate_use_case(runs, assets, storage, checker, probe).execute(
            "missing"
        )

    assert checker.calls == []
    assert probe.call_count == 0


def test_latest_raises_when_render_readiness_is_missing() -> None:
    _, assets, storage = _triple()

    with pytest.raises(AssetNotFoundError) as exc_info:
        GetLatestRenderReadiness(assets, storage).execute("run-1")

    assert exc_info.value.kind is AssetKind.RENDER_READINESS
