"""Provider interfaces for replaceable local plugins and adapters."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from backend.app.domain import RenderSpec, SceneSpec, VersionedAsset


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
