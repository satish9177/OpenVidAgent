from __future__ import annotations

import inspect
from typing import get_type_hints

from backend.app.domain import DownloadedClip, VideoAssemblySegment
from backend.app.ports import ClipDownloader


class _FakeClipDownloader:
    def download(
        self, run_id: str, segment: VideoAssemblySegment
    ) -> DownloadedClip:
        return DownloadedClip(
            scene_id=segment.scene_id,
            query_text=segment.query_text,
            provider=segment.provider,
            provider_clip_id=segment.provider_clip_id,
            title=segment.title,
            source_url=segment.source_url,
            local_uri=f"memory://downloads/{run_id}/clip.mp4",
            content_type="video/mp4",
            duration_seconds=segment.source_duration_seconds,
            width=segment.width,
            height=segment.height,
            order_index=segment.order_index,
            download_status="available",
            download_reason="fake",
        )


def test_fake_satisfies_clip_downloader_protocol() -> None:
    assert isinstance(_FakeClipDownloader(), ClipDownloader)


def test_clip_downloader_resolves_from_provider_ports() -> None:
    assert inspect.getmodule(ClipDownloader).__name__ == (
        "backend.app.ports.providers"
    )


def test_clip_downloader_contract_uses_safe_domain_types() -> None:
    hints = get_type_hints(ClipDownloader.download)

    assert hints["run_id"] is str
    assert hints["segment"] is VideoAssemblySegment
    assert hints["return"] is DownloadedClip
