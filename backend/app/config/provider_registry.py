"""Explicit provider registry for local composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from backend.app.ports import (
    Renderer,
    SceneTablePlanner,
    ScriptDraftGenerator,
    StockProvider,
    SubtitleBuilder,
    TTSProvider,
)

ProviderT = TypeVar("ProviderT")


@dataclass(frozen=True)
class ProviderRegistry:
    script_generator: ScriptDraftGenerator | None = None
    scene_planner: SceneTablePlanner | None = None
    stock: StockProvider | None = None
    tts: TTSProvider | None = None
    subtitles: SubtitleBuilder | None = None
    renderer: Renderer | None = None

    def require_script_generator(self) -> ScriptDraftGenerator:
        return self._require(self.script_generator, "ScriptDraftGenerator")

    def require_scene_planner(self) -> SceneTablePlanner:
        return self._require(self.scene_planner, "SceneTablePlanner")

    def require_stock(self) -> StockProvider:
        return self._require(self.stock, "StockProvider")

    def require_tts(self) -> TTSProvider:
        return self._require(self.tts, "TTSProvider")

    def require_subtitles(self) -> SubtitleBuilder:
        return self._require(self.subtitles, "SubtitleBuilder")

    def require_renderer(self) -> Renderer:
        return self._require(self.renderer, "Renderer")

    @staticmethod
    def _require(provider: ProviderT | None, name: str) -> ProviderT:
        if provider is None:
            raise LookupError(f"{name} is not registered")
        return provider
