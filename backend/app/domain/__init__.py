"""Pure domain objects for OpenVidAgent."""

from backend.app.domain.errors import InvalidRunTransitionError
from backend.app.domain.models import (
    AssetKind,
    ClipCandidate,
    DownloadedClip,
    Job,
    JobStatus,
    RenderSpec,
    RenderPlanSegment,
    Run,
    RUN_STATUS_TRANSITIONS,
    RunStatus,
    SceneSpec,
    SelectedClip,
    StockQuerySpec,
    SubtitleSegment,
    VersionedAsset,
    VideoAssemblySegment,
    VoiceoverSegment,
)

__all__ = [
    "AssetKind",
    "ClipCandidate",
    "DownloadedClip",
    "Job",
    "JobStatus",
    "InvalidRunTransitionError",
    "RenderSpec",
    "RenderPlanSegment",
    "Run",
    "RUN_STATUS_TRANSITIONS",
    "RunStatus",
    "SceneSpec",
    "SelectedClip",
    "StockQuerySpec",
    "SubtitleSegment",
    "VersionedAsset",
    "VideoAssemblySegment",
    "VoiceoverSegment",
]
