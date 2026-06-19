from dataclasses import FrozenInstanceError

import pytest

from backend.app.domain import AssetKind, StockQuerySpec


def test_stock_plan_asset_kind_value() -> None:
    assert AssetKind.STOCK_PLAN.value == "stock_plan"


def test_stock_query_spec_stores_all_fields() -> None:
    spec = StockQuerySpec(
        scene_id="scene-1",
        query="aerial city skyline at sunrise",
        visual_intent="Establish the city waking up before the narration starts.",
        duration_seconds=4.5,
        provider_hint="stock-provider",
    )

    assert spec.scene_id == "scene-1"
    assert spec.query == "aerial city skyline at sunrise"
    assert spec.visual_intent == (
        "Establish the city waking up before the narration starts."
    )
    assert spec.duration_seconds == 4.5
    assert spec.provider_hint == "stock-provider"


def test_stock_query_spec_provider_hint_defaults_to_none() -> None:
    spec = StockQuerySpec(
        scene_id="scene-1",
        query="hands typing on laptop",
        visual_intent="Show focused work in progress.",
        duration_seconds=3.0,
    )

    assert spec.provider_hint is None


def test_stock_query_spec_is_frozen() -> None:
    spec = StockQuerySpec(
        scene_id="scene-1",
        query="closeup coffee pour",
        visual_intent="Show a quiet morning routine.",
        duration_seconds=2.5,
    )

    with pytest.raises(FrozenInstanceError):
        spec.query = "new query"
