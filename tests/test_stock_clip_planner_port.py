from __future__ import annotations

import inspect
from collections.abc import Sequence
from typing import get_type_hints

from backend.app.domain import SceneSpec, StockQuerySpec
from backend.app.ports import StockClipPlanner


class _FakeStockClipPlanner:
    def plan_stock_clips(
        self, scenes: Sequence[SceneSpec], language: str
    ) -> Sequence[StockQuerySpec]:
        return tuple(
            StockQuerySpec(
                scene_id=scene.scene_id,
                query=f"{scene.visual_query} in {language}",
                visual_intent=scene.narration,
                duration_seconds=scene.duration_seconds,
            )
            for scene in scenes
        )


def test_fake_satisfies_stock_clip_planner_protocol() -> None:
    assert isinstance(_FakeStockClipPlanner(), StockClipPlanner)


def test_fake_can_return_stock_query_specs() -> None:
    planner: StockClipPlanner = _FakeStockClipPlanner()
    scenes = (
        SceneSpec(
            scene_id="scene-1",
            narration="Introduce the product with calm office visuals.",
            visual_query="modern office desk",
            duration_seconds=4.0,
        ),
    )

    planned = planner.plan_stock_clips(scenes, "en")

    assert isinstance(planned, Sequence)
    assert planned == (
        StockQuerySpec(
            scene_id="scene-1",
            query="modern office desk in en",
            visual_intent="Introduce the product with calm office visuals.",
            duration_seconds=4.0,
        ),
    )


def test_stock_clip_planner_resolves_from_provider_ports() -> None:
    assert inspect.getmodule(StockClipPlanner).__name__ == (
        "backend.app.ports.providers"
    )


def test_stock_clip_planner_contract_uses_scene_specs_and_stock_queries() -> None:
    hints = get_type_hints(StockClipPlanner.plan_stock_clips)

    assert hints["scenes"] == Sequence[SceneSpec]
    assert hints["language"] is str
    assert hints["return"] == Sequence[StockQuerySpec]
