"""Fake provider implementations for tests."""

from tests.fakes.providers import (
    FakeRenderer,
    FakeSceneTablePlanner,
    FakeScriptDraftGenerator,
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
    "FakeRenderer",
    "FakeSceneTablePlanner",
    "FakeScriptDraftGenerator",
    "FakeStockProvider",
    "FakeSubtitleBuilder",
    "FakeTTSProvider",
    "InMemoryRunRepository",
    "InMemoryStorage",
    "InMemoryVersionedAssetRepository",
]
