"""Domain models with no framework, database, HTTP, or provider imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class AssetKind(str, Enum):
    SCRIPT = "script"
    SCENE_TABLE = "scene_table"
    STOCK_CLIP = "stock_clip"
    VOICE = "voice"
    SUBTITLE = "subtitle"
    RENDER = "render"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class VersionedAsset:
    asset_id: str
    kind: AssetKind
    version: int
    uri: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SceneSpec:
    scene_id: str
    narration: str
    visual_query: str
    duration_seconds: float


@dataclass(frozen=True)
class RenderSpec:
    run_id: str
    scenes: tuple[SceneSpec, ...]
    clips: tuple[VersionedAsset, ...]
    voice: VersionedAsset
    subtitles: VersionedAsset | None = None


@dataclass(frozen=True)
class Job:
    job_id: str
    run_id: str
    name: str
    status: JobStatus = JobStatus.QUEUED


@dataclass(frozen=True)
class Run:
    run_id: str
    prompt: str
    approved_script: str | None = None
