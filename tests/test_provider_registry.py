import pytest

from backend.app.config.provider_registry import ProviderRegistry
from tests.fakes import FakeLLMProvider


def test_registry_returns_registered_provider() -> None:
    registry = ProviderRegistry(llm=FakeLLMProvider())

    assert registry.require_llm().draft_script("test") == "Draft script for: test"


def test_registry_rejects_missing_provider() -> None:
    registry = ProviderRegistry()

    with pytest.raises(LookupError, match="LLMProvider is not registered"):
        registry.require_llm()
