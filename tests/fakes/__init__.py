"""Fake provider implementations for tests."""

from tests.fakes.providers import (
    FakeClipDownloader,
    FakeClipRetrievalProvider,
    FakeClipSelector,
    FakeRenderer,
    FakeRenderPlanner,
    FakeRenderOutputGenerator,
    FakeSceneTablePlanner,
    FakeScriptDraftGenerator,
    FakeStockClipPlanner,
    FakeStockProvider,
    FakeSubtitleComposer,
    FakeSubtitleBuilder,
    FakeTTSProvider,
    FakeVideoAssemblyPlanner,
    FakeVoiceoverGenerator,
)
from tests.fakes.repositories import (
    InMemoryRunRepository,
    InMemoryVersionedAssetRepository,
)
from tests.fakes.storage import InMemoryStorage

__all__ = [
    "FakeClipDownloader",
    "FakeClipRetrievalProvider",
    "FakeClipSelector",
    "FakeRenderer",
    "FakeRenderPlanner",
    "FakeRenderOutputGenerator",
    "FakeSceneTablePlanner",
    "FakeScriptDraftGenerator",
    "FakeStockClipPlanner",
    "FakeStockProvider",
    "FakeSubtitleComposer",
    "FakeSubtitleBuilder",
    "FakeTTSProvider",
    "FakeVideoAssemblyPlanner",
    "FakeVoiceoverGenerator",
    "InMemoryRunRepository",
    "InMemoryStorage",
    "InMemoryVersionedAssetRepository",
]
