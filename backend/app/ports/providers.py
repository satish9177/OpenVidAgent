"""Provider interfaces for replaceable local plugins and adapters."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from backend.app.domain import RenderSpec, SceneSpec, VersionedAsset


class LLMProvider(Protocol):
    def draft_script(self, prompt: str) -> str:
        """Create an editable script draft from a user prompt."""
        ...

    def build_scene_table(self, approved_script: str) -> Sequence[SceneSpec]:
        """Turn an approved script into scene specs."""
        ...


class StockProvider(Protocol):
    def find_clips(self, scene: SceneSpec) -> Sequence[VersionedAsset]:
        """Find versioned stock clips for a scene."""
        ...


class TTSProvider(Protocol):
    def synthesize(self, text: str) -> VersionedAsset:
        """Create a versioned voice asset."""
        ...


class SubtitleBuilder(Protocol):
    def build(self, script: str, voice: VersionedAsset) -> VersionedAsset:
        """Create a versioned subtitle asset."""
        ...


class Renderer(Protocol):
    def render(self, spec: RenderSpec) -> VersionedAsset:
        """Render the final video from an explicit render spec."""
        ...
