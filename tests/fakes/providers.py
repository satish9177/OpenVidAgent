"""Fake providers that satisfy production ports without real integrations."""

from __future__ import annotations

from collections.abc import Sequence

from backend.app.domain import (
    AssetKind,
    ClipCandidate,
    RenderSpec,
    SceneSpec,
    StockQuerySpec,
    VersionedAsset,
)
from backend.app.ports import (
    ClipRetrievalProvider,
    Renderer,
    SceneTablePlanner,
    ScriptDraftGenerator,
    StockClipPlanner,
    StockProvider,
    SubtitleBuilder,
    TTSProvider,
)


class FakeScriptDraftGenerator(ScriptDraftGenerator):
    def generate(self, prompt: str, language: str) -> str:
        return f"Draft script for: {prompt}"


class FakeSceneTablePlanner(SceneTablePlanner):
    def plan(self, approved_script: str, language: str) -> Sequence[SceneSpec]:
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


class FakeStockClipPlanner(StockClipPlanner):
    def plan_stock_clips(
        self, scenes: Sequence[SceneSpec], language: str
    ) -> Sequence[StockQuerySpec]:
        return tuple(
            StockQuerySpec(
                scene_id=scene.scene_id,
                query=scene.visual_query,
                visual_intent=scene.narration,
                duration_seconds=scene.duration_seconds,
            )
            for scene in scenes
        )


class FakeClipRetrievalProvider(ClipRetrievalProvider):
    def __init__(
        self,
        candidates_by_scene_id: dict[str, Sequence[ClipCandidate]] | None = None,
    ) -> None:
        self.candidates_by_scene_id = candidates_by_scene_id or {}
        self.queries: list[StockQuerySpec] = []

    def retrieve(self, query: StockQuerySpec) -> Sequence[ClipCandidate]:
        self.queries.append(query)
        candidates = self.candidates_by_scene_id.get(query.scene_id)
        if candidates is not None:
            return tuple(candidates)

        return (
            ClipCandidate(
                scene_id=query.scene_id,
                query_text=query.query,
                provider="fake",
                provider_clip_id=f"{query.scene_id}-fake-1",
                title=f"{query.query} fake candidate",
                preview_url=f"memory://fake-clips/{query.scene_id}/preview.jpg",
                source_url=f"memory://fake-clips/{query.scene_id}",
                duration_seconds=query.duration_seconds,
                width=1280,
                height=720,
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
