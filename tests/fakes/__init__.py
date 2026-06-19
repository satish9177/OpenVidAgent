"""Fake provider implementations for tests."""

from tests.fakes.providers import (
    FakeClipRetrievalProvider,
    FakeRenderer,
    FakeSceneTablePlanner,
    FakeScriptDraftGenerator,
    FakeStockClipPlanner,
    FakeStockProvider,
    FakeSubtitleBuilder,
    FakeTTSProvider,
)
from tests.fakes.repositories import (
    InMemoryRunRepository,
    InMemoryVersionedAssetRepository,
)
from tests.fakes.storage import InMemoryStorage

__all__ = [
    "FakeClipRetrievalProvider",
    "FakeRenderer",
    "FakeSceneTablePlanner",
    "FakeScriptDraftGenerator",
    "FakeStockClipPlanner",
    "FakeStockProvider",
    "FakeSubtitleBuilder",
    "FakeTTSProvider",
    "InMemoryRunRepository",
    "InMemoryStorage",
    "InMemoryVersionedAssetRepository",
]
