from __future__ import annotations

import inspect
from collections.abc import Sequence
from typing import get_type_hints

from backend.app.domain import ClipCandidate, StockQuerySpec
from backend.app.ports import ClipRetrievalProvider


class _FakeClipRetrievalProvider:
    def retrieve(self, query: StockQuerySpec) -> Sequence[ClipCandidate]:
        return (
            ClipCandidate(
                scene_id=query.scene_id,
                query_text=query.query,
                provider="fake",
                provider_clip_id=f"{query.scene_id}-fake",
                title=f"{query.query} fake candidate",
                preview_url=f"memory://clips/{query.scene_id}/preview.jpg",
                source_url=f"memory://clips/{query.scene_id}",
                duration_seconds=query.duration_seconds,
                width=1280,
                height=720,
            ),
        )


def test_fake_satisfies_clip_retrieval_provider_protocol() -> None:
    assert isinstance(_FakeClipRetrievalProvider(), ClipRetrievalProvider)


def test_fake_can_return_clip_candidates() -> None:
    provider: ClipRetrievalProvider = _FakeClipRetrievalProvider()
    query = StockQuerySpec(
        scene_id="scene-1",
        query="modern office workspace",
        visual_intent="Show a focused work session.",
        duration_seconds=4.0,
    )

    candidates = provider.retrieve(query)

    assert isinstance(candidates, Sequence)
    assert candidates == (
        ClipCandidate(
            scene_id="scene-1",
            query_text="modern office workspace",
            provider="fake",
            provider_clip_id="scene-1-fake",
            title="modern office workspace fake candidate",
            preview_url="memory://clips/scene-1/preview.jpg",
            source_url="memory://clips/scene-1",
            duration_seconds=4.0,
            width=1280,
            height=720,
        ),
    )


def test_clip_retrieval_provider_resolves_from_provider_ports() -> None:
    assert inspect.getmodule(ClipRetrievalProvider).__name__ == (
        "backend.app.ports.providers"
    )


def test_clip_retrieval_provider_contract_uses_stock_query_specs() -> None:
    hints = get_type_hints(ClipRetrievalProvider.retrieve)

    assert hints["query"] is StockQuerySpec
    assert hints["return"] == Sequence[ClipCandidate]
