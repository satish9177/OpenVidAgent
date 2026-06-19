"""Deterministic local stock-clip planning adapter.

A composition-root default that maps approved scene specs into stock search
queries without randomness, network, provider SDK, file download, or subprocess.
A real stock-planning adapter can replace it later behind the same port.
"""

from __future__ import annotations

from collections.abc import Sequence

from backend.app.domain import SceneSpec, StockQuerySpec
from backend.app.ports import StockClipPlanner


class StubStockClipPlanner(StockClipPlanner):
    def plan_stock_clips(
        self, scenes: Sequence[SceneSpec], language: str
    ) -> Sequence[StockQuerySpec]:
        return tuple(
            StockQuerySpec(
                scene_id=scene.scene_id,
                query=scene.visual_query,
                visual_intent=scene.narration,
                duration_seconds=scene.duration_seconds,
                provider_hint=None,
            )
            for scene in scenes
        )
