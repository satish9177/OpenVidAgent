"""Provider interfaces for replaceable local plugins and adapters."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from backend.app.domain import (
    ClipCandidate,
    DownloadedClip,
    RenderPlanSegment,
    RenderSpec,
    SceneSpec,
    SelectedClip,
    StockQuerySpec,
    SubtitleSegment,
    VersionedAsset,
    VideoAssemblySegment,
    VoiceoverSegment,
)


@runtime_checkable
class ScriptDraftGenerator(Protocol):
    def generate(self, prompt: str, language: str) -> str:
        """Create an editable script draft from a user prompt."""
        ...


@runtime_checkable
class SceneTablePlanner(Protocol):
    def plan(
        self, approved_script: str, language: str
    ) -> Sequence[SceneSpec]:
        """Turn an approved script into scene specs."""
        ...


@runtime_checkable
class StockProvider(Protocol):
    def find_clips(self, scene: SceneSpec) -> Sequence[VersionedAsset]:
        """Find versioned stock clips for a scene."""
        ...


@runtime_checkable
class StockClipPlanner(Protocol):
    def plan_stock_clips(
        self, scenes: Sequence[SceneSpec], language: str
    ) -> Sequence[StockQuerySpec]:
        """Plan stock clip search queries for approved scenes."""
        ...


@runtime_checkable
class ClipRetrievalProvider(Protocol):
    def retrieve(self, query: StockQuerySpec) -> Sequence[ClipCandidate]:
        """Return metadata-only clip candidates for one stock query."""
        ...


@runtime_checkable
class ClipSelector(Protocol):
    def select(
        self, candidates: Sequence[ClipCandidate]
    ) -> Sequence[SelectedClip]:
        """Choose selected clips from retrieved candidate metadata."""
        ...


@runtime_checkable
class VideoAssemblyPlanner(Protocol):
    def plan(
        self,
        scenes: Sequence[SceneSpec],
        selected_clips: Sequence[SelectedClip],
    ) -> Sequence[VideoAssemblySegment]:
        """Create metadata-only timeline segments."""
        ...


@runtime_checkable
class ClipDownloader(Protocol):
    def download(
        self, run_id: str, segment: VideoAssemblySegment
    ) -> DownloadedClip:
        """Create a local clip reference from assembly segment metadata."""
        ...


@runtime_checkable
class VoiceoverGenerator(Protocol):
    def generate(
        self,
        run_id: str,
        segment: VideoAssemblySegment,
        language: str,
    ) -> VoiceoverSegment:
        """Create a metadata-only voiceover segment reference."""
        ...


@runtime_checkable
class SubtitleComposer(Protocol):
    def compose(
        self,
        voiceover_segment: VoiceoverSegment,
        start_seconds: float,
        language: str,
    ) -> SubtitleSegment:
        """Create one metadata-only timed subtitle segment."""
        ...


@runtime_checkable
class RenderPlanner(Protocol):
    def plan(
        self,
        assembly_segments: Sequence[VideoAssemblySegment],
        downloaded_clips: Sequence[DownloadedClip],
        voiceover_segments: Sequence[VoiceoverSegment],
        subtitle_segments: Sequence[SubtitleSegment],
    ) -> Sequence[RenderPlanSegment]:
        """Join upstream metadata into an ordered render plan."""
        ...


@runtime_checkable
class TTSProvider(Protocol):
    def synthesize(self, text: str) -> VersionedAsset:
        """Create a versioned voice asset."""
        ...


@runtime_checkable
class SubtitleBuilder(Protocol):
    def build(self, script: str, voice: VersionedAsset) -> VersionedAsset:
        """Create a versioned subtitle asset."""
        ...


@runtime_checkable
class Renderer(Protocol):
    def render(self, spec: RenderSpec) -> VersionedAsset:
        """Render the final video from an explicit render spec."""
        ...
