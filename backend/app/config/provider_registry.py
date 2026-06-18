"""Explicit provider registry for local composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from backend.app.ports import (
    LLMProvider,
    Renderer,
    StockProvider,
    SubtitleBuilder,
    TTSProvider,
)

ProviderT = TypeVar("ProviderT")


@dataclass(frozen=True)
class ProviderRegistry:
    llm: LLMProvider | None = None
    stock: StockProvider | None = None
    tts: TTSProvider | None = None
    subtitles: SubtitleBuilder | None = None
    renderer: Renderer | None = None

    def require_llm(self) -> LLMProvider:
        return self._require(self.llm, "LLMProvider")

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
