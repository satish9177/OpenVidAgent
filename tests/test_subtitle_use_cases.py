"""Subtitle manifest use-case tests."""

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
    CreateSubtitles,
    CreateVoiceover,
    GenerateSubtitles,
    GetLatestSubtitles,
    GetLatestVoiceover,
    ListSubtitles,
)
from backend.app.domain import (
    AssetKind,
    Run,
    RunStatus,
    SubtitleSegment,
    VoiceoverSegment,
)
from tests.fakes import (
    FakeSubtitleComposer,
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
) -> Run:
    run = Run(run_id="run-1", prompt="prompt", status=status)
    runs.save(run)
    return run


def _create_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
) -> CreateSubtitles:
    ids = (f"subtitles-{n}" for n in itertools.count(1))
    return CreateSubtitles(
        runs, assets, storage, asset_id_factory=lambda: next(ids)
    )


def _voiceover_segment(
    order_index: int,
    *,
    language: str = "en",
    duration_seconds: float | None = None,
) -> VoiceoverSegment:
    duration = duration_seconds if duration_seconds is not None else 3.0 + order_index
    return VoiceoverSegment(
        scene_id=f"scene-{order_index + 1}",
        order_index=order_index,
        narration_text=f"Narration {order_index}",
        language=language,
        voice_id="stub-narrator",
        provider="stub",
        audio_uri=f"memory://voiceovers/run-1/{order_index:04d}/scene.mp3",
        content_type="audio/mpeg",
        duration_seconds=duration,
        status="available",
        generation_reason="deterministic_placeholder",
    )


def _subtitle_segment(
    order_index: int = 0,
    *,
    language: str = "en",
    start_seconds: float = 0.0,
    duration_seconds: float | None = None,
) -> SubtitleSegment:
    voiceover_segment = _voiceover_segment(
        order_index,
        language=language,
        duration_seconds=duration_seconds,
    )
    duration = voiceover_segment.duration_seconds
    return SubtitleSegment(
        scene_id=voiceover_segment.scene_id,
        order_index=order_index,
        text=voiceover_segment.narration_text,
        language=language,
        start_seconds=start_seconds,
        end_seconds=start_seconds + duration,
        duration_seconds=duration,
        format="manifest",
        status="available",
        generation_reason="fake_composition",
    )


def _seed_voiceover(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    segments: tuple[VoiceoverSegment, ...],
    *,
    metadata_language: str | None = None,
) -> None:
    metadata = (
        {"language": metadata_language}
        if metadata_language is not None
        else None
    )
    CreateVoiceover(
        runs,
        assets,
        storage,
        asset_id_factory=lambda: "voiceover-1",
    ).execute(
        "run-1",
        segments,
        source="generated",
        asset_metadata=metadata,
    )


def _generate_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    composer: FakeSubtitleComposer,
) -> GenerateSubtitles:
    return GenerateSubtitles(
        runs,
        composer,
        GetLatestVoiceover(assets, storage),
        _create_use_case(runs, assets, storage),
    )


def test_create_versions_json_manifest_and_latest_round_trip() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    create = _create_use_case(runs, assets, storage)

    first = create.execute("run-1", (_subtitle_segment(0),))
    second = create.execute(
        "run-1", (_subtitle_segment(1, start_seconds=3.0),)
    )

    assert first.kind is AssetKind.SUBTITLE_MANIFEST
    assert (first.version, second.version) == (1, 2)
    assert first.metadata == {"source": "manual"}
    assert [asset.version for asset in ListSubtitles(assets).execute(
        "run-1"
    )] == [1, 2]
    latest = GetLatestSubtitles(assets, storage).execute("run-1")
    assert latest.asset == second
    assert latest.segments == (_subtitle_segment(1, start_seconds=3.0),)
    payload = json.loads(storage.saved[first.uri].decode("utf-8"))
    assert isinstance(payload[0]["order_index"], int)
    assert isinstance(payload[0]["start_seconds"], float)
    assert isinstance(payload[0]["end_seconds"], float)
    assert isinstance(payload[0]["duration_seconds"], float)
    assert "subtitle_uri" not in payload[0]
    assert runs.get("run-1").status is RunStatus.SCENES_APPROVED


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
        _create_use_case(runs, assets, storage).execute(
            "run-1", (_subtitle_segment(),)
        )

    assert exc_info.value.kind is AssetKind.SUBTITLE_MANIFEST
    assert assets.list_for_run("run-1", AssetKind.SUBTITLE_MANIFEST) == []
    assert storage.saved == {}


def test_generate_sorts_segments_and_folds_timing_with_metadata_language() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    first = _voiceover_segment(0, language="en", duration_seconds=4.25)
    second = _voiceover_segment(1, language="en", duration_seconds=3.75)
    _seed_voiceover(
        runs,
        assets,
        storage,
        (second, first),
        metadata_language="te",
    )
    composer = FakeSubtitleComposer()

    asset = _generate_use_case(runs, assets, storage, composer).execute("run-1")

    assert composer.calls == [
        (first, 0.0, "te"),
        (second, 4.25, "te"),
    ]
    assert asset.metadata == {
        "voiceover_asset_id": "voiceover-1",
        "voiceover_version": "1",
        "language": "te",
        "source": "generated",
    }
    subtitles = GetLatestSubtitles(assets, storage).execute("run-1")
    assert [segment.order_index for segment in subtitles.segments] == [0, 1]
    assert subtitles.segments[0].start_seconds == 0.0
    assert subtitles.segments[0].end_seconds == 4.25
    assert subtitles.segments[1].start_seconds == 4.25
    assert subtitles.segments[1].end_seconds == 8.0
    assert runs.get("run-1").status is RunStatus.SCENES_APPROVED


def test_generate_language_falls_back_to_first_stored_segment() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    stored_first = _voiceover_segment(1, language="te")
    _seed_voiceover(
        runs,
        assets,
        storage,
        (stored_first, _voiceover_segment(0, language="en")),
    )
    composer = FakeSubtitleComposer()

    asset = _generate_use_case(runs, assets, storage, composer).execute("run-1")

    assert asset.metadata["language"] == "te"
    assert [call[2] for call in composer.calls] == ["te", "te"]


def test_generate_empty_voiceover_uses_english_and_skips_composer() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    _seed_voiceover(runs, assets, storage, ())
    composer = FakeSubtitleComposer()

    asset = _generate_use_case(runs, assets, storage, composer).execute("run-1")

    assert asset.metadata["language"] == "en"
    assert composer.calls == []
    assert GetLatestSubtitles(assets, storage).execute("run-1").segments == ()


def test_generate_invalid_status_wins_over_missing_voiceover() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.CREATED)
    composer = FakeSubtitleComposer()

    with pytest.raises(AssetCreationRejectedError) as exc_info:
        _generate_use_case(runs, assets, storage, composer).execute("run-1")

    assert exc_info.value.kind is AssetKind.SUBTITLE_MANIFEST
    assert composer.calls == []
    assert assets.list_for_run("run-1", AssetKind.SUBTITLE_MANIFEST) == []


def test_generate_missing_voiceover_raises_naturally() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    composer = FakeSubtitleComposer()

    with pytest.raises(AssetNotFoundError) as exc_info:
        _generate_use_case(runs, assets, storage, composer).execute("run-1")

    assert exc_info.value.kind is AssetKind.VOICEOVER
    assert composer.calls == []


def test_generate_missing_run_raises_before_voiceover_read() -> None:
    runs, assets, storage = _triple()
    composer = FakeSubtitleComposer()

    with pytest.raises(RunNotFoundError):
        _generate_use_case(runs, assets, storage, composer).execute("missing")

    assert composer.calls == []


def test_latest_raises_when_subtitle_manifest_is_missing() -> None:
    _, assets, storage = _triple()

    with pytest.raises(AssetNotFoundError) as exc_info:
        GetLatestSubtitles(assets, storage).execute("run-1")

    assert exc_info.value.kind is AssetKind.SUBTITLE_MANIFEST
