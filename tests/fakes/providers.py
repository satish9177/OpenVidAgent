"""Fake providers that satisfy production ports without real integrations."""

from __future__ import annotations

from collections.abc import Sequence

from backend.app.domain import AssetKind, RenderSpec, SceneSpec, VersionedAsset
from backend.app.ports import (
    LLMProvider,
    Renderer,
    StockProvider,
    SubtitleBuilder,
    TTSProvider,
)


class FakeLLMProvider(LLMProvider):
    def draft_script(self, prompt: str) -> str:
        return f"Draft script for: {prompt}"

    def build_scene_table(self, approved_script: str) -> Sequence[SceneSpec]:
        return (
            SceneSpec(
                scene_id="scene-1",
                narration=approved_script,
                visual_query="local-first video workspace",
                duration_seconds=4.0,
            ),
        )


class FakeStockProvider(StockProvider):
    def find_clips(self, scene: SceneSpec) -> Sequence[VersionedAsset]:
        return (
            VersionedAsset(
                asset_id=f"{scene.scene_id}-clip",
                kind=AssetKind.STOCK_CLIP,
                version=1,
                uri=f"memory://clips/{scene.scene_id}.mp4",
            ),
        )


class FakeTTSProvider(TTSProvider):
    def synthesize(self, text: str) -> VersionedAsset:
        return VersionedAsset(
            asset_id="voice-1",
            kind=AssetKind.VOICE,
            version=1,
            uri="memory://voice/voice-1.wav",
            metadata={"text": text},
        )


class FakeSubtitleBuilder(SubtitleBuilder):
    def build(self, script: str, voice: VersionedAsset) -> VersionedAsset:
        return VersionedAsset(
            asset_id="subtitle-1",
            kind=AssetKind.SUBTITLE,
            version=1,
            uri="memory://subtitles/subtitle-1.srt",
            metadata={"voice_asset_id": voice.asset_id, "script": script},
        )


class FakeRenderer(Renderer):
    def render(self, spec: RenderSpec) -> VersionedAsset:
        return VersionedAsset(
            asset_id=f"{spec.run_id}-render",
            kind=AssetKind.RENDER,
            version=1,
            uri=f"memory://renders/{spec.run_id}.mp4",
        )
