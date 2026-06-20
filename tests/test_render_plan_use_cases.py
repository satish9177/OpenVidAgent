"""Render plan asset use-case tests."""

from __future__ import annotations

import itertools
import json

import pytest

from backend.app.application.errors import (
    AssetCreationRejectedError,
    AssetNotFoundError,
    RenderPlanInputMismatchError,
    RunNotFoundError,
)
from backend.app.application.use_cases import (
    CreateDownloadedClipSet,
    CreateRenderPlan,
    CreateSubtitles,
    CreateVideoAssemblyPlan,
    CreateVoiceover,
    GenerateRenderPlan,
    GetLatestDownloadedClipSet,
    GetLatestRenderPlan,
    GetLatestSubtitles,
    GetLatestVideoAssemblyPlan,
    GetLatestVoiceover,
    ListRenderPlans,
)
from backend.app.domain import (
    AssetKind,
    DownloadedClip,
    RenderPlanSegment,
    Run,
    RunStatus,
    SubtitleSegment,
    VideoAssemblySegment,
    VoiceoverSegment,
)
from tests.fakes import (
    FakeRenderPlanner,
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


def _assembly(index: int) -> VideoAssemblySegment:
    return VideoAssemblySegment(
        scene_id=f"scene-{index}",
        query_text=f"query {index}",
        narration=f"Narration {index}",
        visual_query=f"Visual {index}",
        provider="stub",
        provider_clip_id=f"clip-{index}",
        title=f"Clip {index}",
        preview_url=f"memory://clips/{index}/preview.jpg",
        source_url=f"memory://clips/{index}",
        target_duration_seconds=4.0,
        source_duration_seconds=6.0,
        width=1920,
        height=1080,
        order_index=index,
        transition="cut",
        continuity_note="ordered_by_scene_table",
        selection_reason="first_candidate_for_scene_query",
    )


def _downloaded(index: int) -> DownloadedClip:
    return DownloadedClip(
        scene_id=f"scene-{index}",
        query_text=f"query {index}",
        provider="stub",
        provider_clip_id=f"clip-{index}",
        title=f"Clip {index}",
        source_url=f"memory://clips/{index}",
        local_uri=f"memory://downloads/run-1/{index:04d}/clip.mp4",
        content_type="video/mp4",
        duration_seconds=6.0,
        width=1920,
        height=1080,
        order_index=index,
        download_status="available",
        download_reason="deterministic_placeholder",
    )


def _voiceover(index: int) -> VoiceoverSegment:
    return VoiceoverSegment(
        scene_id=f"scene-{index}",
        order_index=index,
        narration_text=f"Narration {index}",
        language="en",
        voice_id="stub-narrator",
        provider="stub",
        audio_uri=f"memory://voiceovers/run-1/{index:04d}/scene.mp3",
        content_type="audio/mpeg",
        duration_seconds=4.0,
        status="available",
        generation_reason="deterministic_placeholder",
    )


def _subtitle(index: int) -> SubtitleSegment:
    start = 4.0 * index
    return SubtitleSegment(
        scene_id=f"scene-{index}",
        order_index=index,
        text=f"Narration {index}",
        language="en",
        start_seconds=start,
        end_seconds=start + 4.0,
        duration_seconds=4.0,
        format="manifest",
        status="available",
        generation_reason="deterministic_placeholder",
    )


def _render_segment(index: int) -> RenderPlanSegment:
    start = 4.0 * index
    return RenderPlanSegment(
        order_index=index,
        scene_id=f"scene-{index}",
        clip_uri=f"memory://downloads/run-1/{index:04d}/clip.mp4",
        clip_provider="stub",
        clip_provider_id=f"clip-{index}",
        visual_start_seconds=start,
        visual_end_seconds=start + 4.0,
        visual_duration_seconds=4.0,
        voiceover_uri=f"memory://voiceovers/run-1/{index:04d}/scene.mp3",
        voiceover_start_seconds=start,
        voiceover_end_seconds=start + 4.0,
        voiceover_duration_seconds=4.0,
        subtitle_text=f"Narration {index}",
        subtitle_start_seconds=start,
        subtitle_end_seconds=start + 4.0,
        subtitle_language="en",
    )


def _create_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
) -> CreateRenderPlan:
    ids = (f"render-plan-{n}" for n in itertools.count(1))
    return CreateRenderPlan(
        runs, assets, storage, asset_id_factory=lambda: next(ids)
    )


def _seed_upstreams(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    *,
    assembly_indexes: tuple[int, ...] = (0, 1),
    downloaded_indexes: tuple[int, ...] = (0, 1),
    voiceover_indexes: tuple[int, ...] = (0, 1),
    subtitle_indexes: tuple[int, ...] = (0, 1),
) -> None:
    CreateVideoAssemblyPlan(
        runs, assets, storage, asset_id_factory=lambda: "assembly-1"
    ).execute("run-1", tuple(_assembly(i) for i in assembly_indexes))
    CreateDownloadedClipSet(
        runs, assets, storage, asset_id_factory=lambda: "downloads-1"
    ).execute("run-1", tuple(_downloaded(i) for i in downloaded_indexes))
    CreateVoiceover(
        runs, assets, storage, asset_id_factory=lambda: "voiceover-1"
    ).execute("run-1", tuple(_voiceover(i) for i in voiceover_indexes))
    CreateSubtitles(
        runs, assets, storage, asset_id_factory=lambda: "subtitles-1"
    ).execute("run-1", tuple(_subtitle(i) for i in subtitle_indexes))


def _generate_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    planner: FakeRenderPlanner,
) -> GenerateRenderPlan:
    return GenerateRenderPlan(
        runs,
        planner,
        GetLatestVideoAssemblyPlan(assets, storage),
        GetLatestDownloadedClipSet(assets, storage),
        GetLatestVoiceover(assets, storage),
        GetLatestSubtitles(assets, storage),
        _create_use_case(runs, assets, storage),
    )


def test_create_versions_json_and_latest_round_trip() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    create = _create_use_case(runs, assets, storage)

    first = create.execute("run-1", (_render_segment(0),))
    second = create.execute("run-1", (_render_segment(1),))

    assert first.kind is AssetKind.RENDER_PLAN
    assert (first.version, second.version) == (1, 2)
    assert first.metadata == {"source": "manual"}
    assert [asset.version for asset in ListRenderPlans(assets).execute(
        "run-1"
    )] == [1, 2]
    latest = GetLatestRenderPlan(assets, storage).execute("run-1")
    assert latest.asset == second
    assert latest.segments == (_render_segment(1),)
    payload = json.loads(storage.saved[first.uri].decode("utf-8"))[0]
    assert isinstance(payload["order_index"], int)
    for field in (
        "visual_start_seconds",
        "visual_end_seconds",
        "visual_duration_seconds",
        "voiceover_start_seconds",
        "voiceover_end_seconds",
        "voiceover_duration_seconds",
        "subtitle_start_seconds",
        "subtitle_end_seconds",
    ):
        assert isinstance(payload[field], float)


def test_generate_calls_planner_once_and_stores_provenance_profile() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    _seed_upstreams(runs, assets, storage)
    planner = FakeRenderPlanner((_render_segment(0), _render_segment(1)))

    asset = _generate_use_case(runs, assets, storage, planner).execute("run-1")

    assert planner.calls == [
        (
            (_assembly(0), _assembly(1)),
            (_downloaded(0), _downloaded(1)),
            (_voiceover(0), _voiceover(1)),
            (_subtitle(0), _subtitle(1)),
        )
    ]
    assert asset.metadata == {
        "video_assembly_plan_asset_id": "assembly-1",
        "video_assembly_plan_version": "1",
        "downloaded_clips_asset_id": "downloads-1",
        "downloaded_clips_version": "1",
        "voiceover_asset_id": "voiceover-1",
        "voiceover_version": "1",
        "subtitles_asset_id": "subtitles-1",
        "subtitles_version": "1",
        "aspect_ratio": "16:9",
        "resolution_width": "1920",
        "resolution_height": "1080",
        "fps": "30",
        "container": "mp4",
        "render_intent": "voiceover_b_roll",
        "source": "generated",
    }
    assert all(isinstance(value, str) for value in asset.metadata.values())
    assert runs.get("run-1").status is RunStatus.SCENES_APPROVED


@pytest.mark.parametrize(
    ("source", "downloaded", "voiceover", "subtitles", "missing", "extra"),
    [
        ("downloaded_clips", (0,), (0, 1), (0, 1), (1,), ()),
        ("downloaded_clips", (0, 1, 2), (0, 1), (0, 1), (), (2,)),
        ("voiceover", (0, 1), (0,), (0, 1), (1,), ()),
        ("voiceover", (0, 1), (0, 1, 2), (0, 1), (), (2,)),
        ("subtitles", (0, 1), (0, 1), (0,), (1,), ()),
        ("subtitles", (0, 1), (0, 1), (0, 1, 2), (), (2,)),
    ],
)
def test_generate_rejects_order_mismatch_before_planner(
    source: str,
    downloaded: tuple[int, ...],
    voiceover: tuple[int, ...],
    subtitles: tuple[int, ...],
    missing: tuple[int, ...],
    extra: tuple[int, ...],
) -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    _seed_upstreams(
        runs,
        assets,
        storage,
        downloaded_indexes=downloaded,
        voiceover_indexes=voiceover,
        subtitle_indexes=subtitles,
    )
    planner = FakeRenderPlanner()

    with pytest.raises(RenderPlanInputMismatchError) as exc_info:
        _generate_use_case(runs, assets, storage, planner).execute("run-1")

    assert exc_info.value.run_id == "run-1"
    assert exc_info.value.source == source
    assert exc_info.value.missing_order_indexes == missing
    assert exc_info.value.extra_order_indexes == extra
    assert planner.calls == []
    assert assets.list_for_run("run-1", AssetKind.RENDER_PLAN) == []


@pytest.mark.parametrize(
    ("seed_count", "missing_kind"),
    [
        (0, AssetKind.VIDEO_ASSEMBLY_PLAN),
        (1, AssetKind.DOWNLOADED_CLIPS),
        (2, AssetKind.VOICEOVER),
        (3, AssetKind.SUBTITLE_MANIFEST),
    ],
)
def test_generate_missing_upstream_raises_naturally(
    seed_count: int, missing_kind: AssetKind
) -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    creators = (
        lambda: CreateVideoAssemblyPlan(
            runs, assets, storage, asset_id_factory=lambda: "assembly-1"
        ).execute("run-1", (_assembly(0),)),
        lambda: CreateDownloadedClipSet(
            runs, assets, storage, asset_id_factory=lambda: "downloads-1"
        ).execute("run-1", (_downloaded(0),)),
        lambda: CreateVoiceover(
            runs, assets, storage, asset_id_factory=lambda: "voiceover-1"
        ).execute("run-1", (_voiceover(0),)),
    )
    for creator in creators[:seed_count]:
        creator()
    planner = FakeRenderPlanner()

    with pytest.raises(AssetNotFoundError) as exc_info:
        _generate_use_case(runs, assets, storage, planner).execute("run-1")

    assert exc_info.value.kind is missing_kind
    assert planner.calls == []


def test_generate_invalid_status_wins_over_missing_upstreams() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.CREATED)
    planner = FakeRenderPlanner()

    with pytest.raises(AssetCreationRejectedError) as exc_info:
        _generate_use_case(runs, assets, storage, planner).execute("run-1")

    assert exc_info.value.kind is AssetKind.RENDER_PLAN
    assert planner.calls == []


def test_generate_missing_run_raises_before_upstream_reads() -> None:
    runs, assets, storage = _triple()
    planner = FakeRenderPlanner()

    with pytest.raises(RunNotFoundError):
        _generate_use_case(runs, assets, storage, planner).execute("missing")

    assert planner.calls == []


def test_latest_raises_when_render_plan_is_missing() -> None:
    _, assets, storage = _triple()

    with pytest.raises(AssetNotFoundError) as exc_info:
        GetLatestRenderPlan(assets, storage).execute("run-1")

    assert exc_info.value.kind is AssetKind.RENDER_PLAN
