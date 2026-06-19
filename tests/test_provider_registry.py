import pytest

from backend.app.config.provider_registry import ProviderRegistry
from tests.fakes import FakeScriptDraftGenerator


def test_registry_returns_registered_provider() -> None:
    registry = ProviderRegistry(script_generator=FakeScriptDraftGenerator())

    assert (
        registry.require_script_generator().generate("test", "en")
        == "Draft script for: test"
    )


def test_registry_rejects_missing_provider() -> None:
    registry = ProviderRegistry()

    with pytest.raises(
        LookupError, match="ScriptDraftGenerator is not registered"
    ):
        registry.require_script_generator()
