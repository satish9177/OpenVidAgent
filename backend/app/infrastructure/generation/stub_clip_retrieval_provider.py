"""Deterministic metadata-only clip retrieval adapter.

This composition-root default mirrors a stock provider search without network,
SDK, filesystem, download, or subprocess behavior.
"""

from __future__ import annotations

from collections.abc import Sequence

from backend.app.domain import ClipCandidate, StockQuerySpec
from backend.app.ports import ClipRetrievalProvider


class StubClipRetrievalProvider(ClipRetrievalProvider):
    def retrieve(self, query: StockQuerySpec) -> Sequence[ClipCandidate]:
        return tuple(
            ClipCandidate(
                scene_id=query.scene_id,
                query_text=query.query,
                provider="stub",
                provider_clip_id=f"{query.scene_id}-{index}",
                title=f"{query.query} (candidate {index})",
                preview_url=f"memory://clips/{query.scene_id}/{index}/preview.jpg",
                source_url=f"memory://clips/{query.scene_id}/{index}",
                duration_seconds=query.duration_seconds,
                width=1920,
                height=1080,
            )
            for index in range(1, 3)
        )
