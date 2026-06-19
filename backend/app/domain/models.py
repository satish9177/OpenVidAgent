"""Domain models with no framework, database, HTTP, or provider imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from backend.app.domain.errors import InvalidRunTransitionError


class AssetKind(str, Enum):
    SCRIPT = "script"
    SCENE_TABLE = "scene_table"
    STOCK_PLAN = "stock_plan"
    CLIP_CANDIDATES = "clip_candidates"
    SELECTED_CLIPS = "selected_clips"
    STOCK_CLIP = "stock_clip"
    VOICE = "voice"
    SUBTITLE = "subtitle"
    RENDER = "render"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunStatus(str, Enum):
    CREATED = "created"
    SCRIPT_READY = "script_ready"
    SCRIPT_APPROVED = "script_approved"
    SCENES_READY = "scenes_ready"
    SCENES_APPROVED = "scenes_approved"
    RENDERED = "rendered"
    FAILED = "failed"

    def can_transition_to(self, next_status: "RunStatus") -> bool:
        return next_status in RUN_STATUS_TRANSITIONS[self]


RUN_STATUS_TRANSITIONS: Mapping[RunStatus, frozenset[RunStatus]] = {
    RunStatus.CREATED: frozenset({RunStatus.SCRIPT_READY, RunStatus.FAILED}),
    RunStatus.SCRIPT_READY: frozenset(
        {RunStatus.SCRIPT_APPROVED, RunStatus.FAILED}
    ),
    RunStatus.SCRIPT_APPROVED: frozenset(
        {RunStatus.SCENES_READY, RunStatus.FAILED}
    ),
    RunStatus.SCENES_READY: frozenset(
        {RunStatus.SCENES_APPROVED, RunStatus.FAILED}
    ),
    RunStatus.SCENES_APPROVED: frozenset({RunStatus.RENDERED, RunStatus.FAILED}),
    RunStatus.RENDERED: frozenset(),
    RunStatus.FAILED: frozenset(),
}


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
class StockQuerySpec:
    scene_id: str
    query: str
    visual_intent: str
    duration_seconds: float
    provider_hint: str | None = None


@dataclass(frozen=True)
class ClipCandidate:
    scene_id: str
    query_text: str
    provider: str
    provider_clip_id: str
    title: str
    preview_url: str
    source_url: str
    duration_seconds: float
    width: int
    height: int


@dataclass(frozen=True)
class SelectedClip:
    scene_id: str
    query_text: str
    provider: str
    provider_clip_id: str
    title: str
    preview_url: str
    source_url: str
    duration_seconds: float
    width: int
    height: int
    selection_reason: str


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
    title: str | None = None
    language: str = "en"
    status: RunStatus = RunStatus.CREATED
    script: str | None = None
    approved_script: str | None = None
    failure_reason: str | None = None

    def mark_script_ready(self, script: str) -> "Run":
        return self._transition_to(RunStatus.SCRIPT_READY, script=script)

    def approve_script(self, approved_script: str | None = None) -> "Run":
        resolved_script = approved_script if approved_script is not None else self.script
        return self._transition_to(
            RunStatus.SCRIPT_APPROVED,
            approved_script=resolved_script,
        )

    def mark_scenes_ready(self) -> "Run":
        return self._transition_to(RunStatus.SCENES_READY)

    def approve_scenes(self) -> "Run":
        return self._transition_to(RunStatus.SCENES_APPROVED)

    def mark_rendered(self) -> "Run":
        return self._transition_to(RunStatus.RENDERED)

    def mark_failed(self, reason: str) -> "Run":
        return self._transition_to(RunStatus.FAILED, failure_reason=reason)

    def _transition_to(self, next_status: RunStatus, **changes: object) -> "Run":
        if not self.status.can_transition_to(next_status):
            raise InvalidRunTransitionError(self.status.value, next_status.value)

        return Run(
            run_id=self.run_id,
            prompt=self.prompt,
            title=self.title,
            language=self.language,
            status=next_status,
            script=_get_change(changes, "script", self.script),
            approved_script=_get_change(
                changes, "approved_script", self.approved_script
            ),
            failure_reason=_get_change(
                changes, "failure_reason", self.failure_reason
            ),
        )


def _get_change(
    changes: Mapping[str, object],
    key: str,
    current_value: str | None,
) -> str | None:
    value = changes.get(key, current_value)
    if value is None or isinstance(value, str):
        return value
    raise TypeError(f"{key} must be a string or None")
