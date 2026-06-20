from __future__ import annotations

from dataclasses import replace

import pytest

from backend.app.domain import DownloadedClip, VideoAssemblySegment
from backend.app.infrastructure.generation import StubClipDownloader
from backend.app.ports import ClipDownloader
from tests.fakes import FakeClipDownloader


def _segment() -> VideoAssemblySegment:
    return VideoAssemblySegment(
        scene_id="scene-1",
        query_text="coffee beans roasting",
        narration="Coffee beans develop their flavor while roasting.",
        visual_query="close-up coffee roasting",
        provider="stub",
        provider_clip_id="scene-1-1",
        title="Coffee beans roasting",
        preview_url="memory://clips/scene-1/1/preview.jpg",
        source_url="memory://clips/scene-1/1",
        target_duration_seconds=4.0,
        source_duration_seconds=7.5,
        width=1920,
        height=1080,
        order_index=2,
        transition="cut",
        continuity_note="ordered_by_scene_table",
        selection_reason="first_candidate_for_scene_query",
    )


def test_stub_downloader_satisfies_port_and_is_repeatable() -> None:
    downloader = StubClipDownloader()
    segment = _segment()

    assert isinstance(downloader, ClipDownloader)
    assert downloader.download("run-1", segment) == downloader.download(
        "run-1", segment
    )


def test_stub_downloader_copies_metadata_and_creates_memory_uri() -> None:
    downloaded = StubClipDownloader().download("run-1", _segment())

    assert downloaded == DownloadedClip(
        scene_id="scene-1",
        query_text="coffee beans roasting",
        provider="stub",
        provider_clip_id="scene-1-1",
        title="Coffee beans roasting",
        source_url="memory://clips/scene-1/1",
        local_uri="memory://downloads/run-1/0002/stub-scene-1-1.mp4",
        content_type="video/mp4",
        duration_seconds=7.5,
        width=1920,
        height=1080,
        order_index=2,
        download_status="available",
        download_reason="deterministic_placeholder",
    )
    relative_reference = downloaded.local_uri.removeprefix(
        "memory://downloads/"
    )
    assert not relative_reference.startswith(("/", "\\"))
    assert ".." not in relative_reference.split("/")
    assert "\\" not in relative_reference


@pytest.mark.parametrize(
    "bad_value",
    ["", ".", "..", "nested/value", "nested\\value", "C:drive", "bad\x00id"],
)
@pytest.mark.parametrize("component", ["run_id", "provider", "provider_clip_id"])
def test_stub_downloader_rejects_unsafe_uri_components(
    component: str, bad_value: str
) -> None:
    segment = _segment()
    run_id = "run-1"
    if component == "run_id":
        run_id = bad_value
    else:
        segment = replace(segment, **{component: bad_value})

    with pytest.raises(ValueError, match=component):
        StubClipDownloader().download(run_id, segment)


def test_fake_downloader_records_calls_and_returns_configured_clip() -> None:
    configured = StubClipDownloader().download("run-config", _segment())
    fake = FakeClipDownloader((configured,))

    assert fake.download("run-1", _segment()) == configured
    assert fake.calls == [("run-1", _segment())]
