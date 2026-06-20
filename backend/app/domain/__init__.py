"""Pure domain objects for OpenVidAgent."""

from backend.app.domain.errors import InvalidRunTransitionError
from backend.app.domain.models import (
    AssetKind,
    ClipCandidate,
    DownloadedClip,
    Job,
    JobStatus,
    RenderSpec,
    Run,
    RUN_STATUS_TRANSITIONS,
    RunStatus,
    SceneSpec,
    SelectedClip,
    StockQuerySpec,
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
    "Run",
    "RUN_STATUS_TRANSITIONS",
    "RunStatus",
    "SceneSpec",
    "SelectedClip",
    "StockQuerySpec",
    "VersionedAsset",
    "VideoAssemblySegment",
    "VoiceoverSegment",
]
