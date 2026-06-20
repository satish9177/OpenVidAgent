"""Deterministic metadata-only clip downloader adapter."""

from __future__ import annotations

from backend.app.domain import DownloadedClip, VideoAssemblySegment
from backend.app.ports import ClipDownloader


class StubClipDownloader(ClipDownloader):
    def download(
        self, run_id: str, segment: VideoAssemblySegment
    ) -> DownloadedClip:
        safe_run_id = _safe_component(run_id, "run_id")
        safe_provider = _safe_component(segment.provider, "provider")
        safe_provider_clip_id = _safe_component(
            segment.provider_clip_id, "provider_clip_id"
        )
        local_uri = (
            f"memory://downloads/{safe_run_id}/{segment.order_index:04d}/"
            f"{safe_provider}-{safe_provider_clip_id}.mp4"
        )
        return DownloadedClip(
            scene_id=segment.scene_id,
            query_text=segment.query_text,
            provider=segment.provider,
            provider_clip_id=segment.provider_clip_id,
            title=segment.title,
            source_url=segment.source_url,
            local_uri=local_uri,
            content_type="video/mp4",
            duration_seconds=segment.source_duration_seconds,
            width=segment.width,
            height=segment.height,
            order_index=segment.order_index,
            download_status="available",
            download_reason="deterministic_placeholder",
        )


def _safe_component(value: str, name: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or ":" in value
        or "\x00" in value
    ):
        raise ValueError(f"{name} must be a safe URI path component")
    return value
