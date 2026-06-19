"""GenerateScriptDraft use-case tests (Slice 4)."""

from __future__ import annotations

import itertools

import pytest

from backend.app.application.errors import (
    AssetCreationRejectedError,
    RunNotFoundError,
)
from backend.app.application.use_cases import CreateScriptDraft, GenerateScriptDraft
from backend.app.domain import AssetKind, Run, RunStatus
from backend.app.ports import ScriptDraftGenerator
from tests.fakes import (
    InMemoryRunRepository,
    InMemoryStorage,
    InMemoryVersionedAssetRepository,
)


class _RecordingScriptDraftGenerator(ScriptDraftGenerator):
    """Spy generator: records its calls and returns a fixed script.

    Lets the tests assert the exact ``(prompt, language)`` the use-case forwards.
    The production ``FakeScriptDraftGenerator`` ignores ``language``, so it cannot
    prove that input is threaded through.
    """

    def __init__(self, script: str = "# Generated\nBody text.") -> None:
        self._script = script
        self.calls: list[tuple[str, str]] = []

    def generate(self, prompt: str, language: str) -> str:
        self.calls.append((prompt, language))
        return self._script


def _triple() -> tuple[
    InMemoryRunRepository, InMemoryVersionedAssetRepository, InMemoryStorage
]:
    return (
        InMemoryRunRepository(),
        InMemoryVersionedAssetRepository(),
        InMemoryStorage(),
    )


def _seed_run(
    runs: InMemoryRunRepository,
    status: RunStatus = RunStatus.CREATED,
    *,
    prompt: str = "make a coffee video",
    language: str = "en",
    run_id: str = "run-1",
) -> Run:
    run = Run(run_id=run_id, prompt=prompt, language=language, status=status)
    runs.save(run)
    return run


def _generate_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    generator: ScriptDraftGenerator,
) -> GenerateScriptDraft:
    ids = (f"asset-{n}" for n in itertools.count(1))
    create = CreateScriptDraft(
        runs, assets, storage, asset_id_factory=lambda: next(ids)
    )
    return GenerateScriptDraft(runs, generator, create)


def test_generate_forwards_run_prompt_and_language_to_generator() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, prompt="brewing pour-over coffee", language="es")
    generator = _RecordingScriptDraftGenerator()

    _generate_use_case(runs, assets, storage, generator).execute("run-1")

    assert generator.calls == [("brewing pour-over coffee", "es")]


def test_generate_persists_script_asset_tagged_generated() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    generator = _RecordingScriptDraftGenerator("# Generated\nBody text.")

    asset = _generate_use_case(runs, assets, storage, generator).execute("run-1")

    assert asset.kind is AssetKind.SCRIPT
    assert asset.version == 1
    assert asset.metadata == {"source": "generated"}
    # The generated text is what was persisted and indexed.
    assert storage.saved[asset.uri] == b"# Generated\nBody text."
    assert list(assets.list_for_run("run-1", AssetKind.SCRIPT)) == [asset]


def test_generate_transitions_created_to_script_ready() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.CREATED)
    generator = _RecordingScriptDraftGenerator("# Generated\nBody text.")

    _generate_use_case(runs, assets, storage, generator).execute("run-1")

    stored = runs.get("run-1")
    assert stored is not None
    assert stored.status is RunStatus.SCRIPT_READY
    # The generated text flows through to the lifecycle transition.
    assert stored.script == "# Generated\nBody text."


def test_generate_second_draft_increments_version_and_stays_script_ready() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.CREATED)
    use_case = _generate_use_case(
        runs, assets, storage, _RecordingScriptDraftGenerator()
    )

    first = use_case.execute("run-1")
    second = use_case.execute("run-1")

    assert (first.version, second.version) == (1, 2)
    assert second.metadata == {"source": "generated"}
    stored = runs.get("run-1")
    assert stored is not None
    assert stored.status is RunStatus.SCRIPT_READY


def test_generate_raises_run_not_found_when_run_missing() -> None:
    runs, assets, storage = _triple()
    generator = _RecordingScriptDraftGenerator()

    with pytest.raises(RunNotFoundError, match="Run 'missing' was not found"):
        _generate_use_case(runs, assets, storage, generator).execute("missing")

    # The generator is never reached and nothing is persisted.
    assert generator.calls == []
    assert storage.saved == {}
    assert list(assets.list_for_run("missing", AssetKind.SCRIPT)) == []


@pytest.mark.parametrize(
    "status",
    [
        RunStatus.SCRIPT_APPROVED,
        RunStatus.SCENES_READY,
        RunStatus.SCENES_APPROVED,
        RunStatus.RENDERED,
        RunStatus.FAILED,
    ],
)
def test_generate_rejects_invalid_states_via_d7_guard(status: RunStatus) -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, status)

    with pytest.raises(AssetCreationRejectedError) as exc_info:
        _generate_use_case(
            runs, assets, storage, _RecordingScriptDraftGenerator()
        ).execute("run-1")

    assert exc_info.value.status is status
    # The D7 guard inside CreateScriptDraft rejects before any persistence.
    assert list(assets.list_for_run("run-1", AssetKind.SCRIPT)) == []
    assert storage.saved == {}
