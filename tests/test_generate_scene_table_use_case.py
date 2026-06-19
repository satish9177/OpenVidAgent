"""GenerateSceneTable use-case tests (Slice 5)."""

from __future__ import annotations

import itertools
import json
from collections.abc import Sequence

import pytest

from backend.app.application.errors import (
    ApprovedScriptRequiredError,
    AssetCreationRejectedError,
    RunNotFoundError,
)
from backend.app.application.use_cases import CreateSceneTable, GenerateSceneTable
from backend.app.domain import AssetKind, Run, RunStatus, SceneSpec
from backend.app.ports import SceneTablePlanner
from tests.fakes import (
    InMemoryRunRepository,
    InMemoryStorage,
    InMemoryVersionedAssetRepository,
)


class _RecordingSceneTablePlanner(SceneTablePlanner):
    """Spy planner: records its calls and returns fixed scenes.

    Lets the tests assert the exact ``(approved_script, language)`` the use-case
    forwards. The production ``FakeSceneTablePlanner`` ignores ``language``, so it
    cannot prove that input is threaded through.
    """

    def __init__(self, scenes: Sequence[SceneSpec] | None = None) -> None:
        self._scenes: tuple[SceneSpec, ...] = (
            tuple(scenes)
            if scenes is not None
            else (
                SceneSpec(
                    scene_id="scene-1",
                    narration="Generated narration",
                    visual_query="generated query",
                    duration_seconds=5.0,
                ),
            )
        )
        self.calls: list[tuple[str, str]] = []

    def plan(self, approved_script: str, language: str) -> Sequence[SceneSpec]:
        self.calls.append((approved_script, language))
        return self._scenes


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
    status: RunStatus = RunStatus.SCRIPT_APPROVED,
    *,
    approved_script: str | None = "the approved script",
    language: str = "en",
    run_id: str = "run-1",
) -> Run:
    run = Run(
        run_id=run_id,
        prompt="prompt",
        language=language,
        status=status,
        approved_script=approved_script,
    )
    runs.save(run)
    return run


def _generate_use_case(
    runs: InMemoryRunRepository,
    assets: InMemoryVersionedAssetRepository,
    storage: InMemoryStorage,
    planner: SceneTablePlanner,
) -> GenerateSceneTable:
    ids = (f"scene-asset-{n}" for n in itertools.count(1))
    create = CreateSceneTable(
        runs, assets, storage, asset_id_factory=lambda: next(ids)
    )
    return GenerateSceneTable(runs, planner, create)


def test_generate_forwards_approved_script_and_language_to_planner() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, approved_script="approved body", language="fr")
    planner = _RecordingSceneTablePlanner()

    _generate_use_case(runs, assets, storage, planner).execute("run-1")

    assert planner.calls == [("approved body", "fr")]


def test_generate_persists_scene_table_tagged_generated() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs)
    scenes = (
        SceneSpec(
            scene_id="s1",
            narration="n1",
            visual_query="q1",
            duration_seconds=4.0,
        ),
        SceneSpec(
            scene_id="s2",
            narration="n2",
            visual_query="q2",
            duration_seconds=2.5,
        ),
    )
    planner = _RecordingSceneTablePlanner(scenes)

    asset = _generate_use_case(runs, assets, storage, planner).execute("run-1")

    assert asset.kind is AssetKind.SCENE_TABLE
    assert asset.version == 1
    assert asset.metadata == {"source": "generated"}
    assert list(assets.list_for_run("run-1", AssetKind.SCENE_TABLE)) == [asset]
    # The planned scenes are what was persisted.
    payload = json.loads(storage.saved[asset.uri].decode("utf-8"))
    assert [item["scene_id"] for item in payload] == ["s1", "s2"]


def test_generate_transitions_script_approved_to_scenes_ready() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.SCRIPT_APPROVED)
    planner = _RecordingSceneTablePlanner()

    _generate_use_case(runs, assets, storage, planner).execute("run-1")

    stored = runs.get("run-1")
    assert stored is not None
    assert stored.status is RunStatus.SCENES_READY


def test_generate_second_table_increments_version_and_stays_scenes_ready() -> None:
    runs, assets, storage = _triple()
    _seed_run(runs, RunStatus.SCRIPT_APPROVED)
    use_case = _generate_use_case(
        runs, assets, storage, _RecordingSceneTablePlanner()
    )

    first = use_case.execute("run-1")
    second = use_case.execute("run-1")

    assert (first.version, second.version) == (1, 2)
    assert second.metadata == {"source": "generated"}
    stored = runs.get("run-1")
    assert stored is not None
    assert stored.status is RunStatus.SCENES_READY


def test_generate_raises_run_not_found_when_run_missing() -> None:
    runs, assets, storage = _triple()
    planner = _RecordingSceneTablePlanner()

    with pytest.raises(RunNotFoundError, match="Run 'missing' was not found"):
        _generate_use_case(runs, assets, storage, planner).execute("missing")

    # The planner is never reached and nothing is persisted.
    assert planner.calls == []
    assert storage.saved == {}
    assert list(assets.list_for_run("missing", AssetKind.SCENE_TABLE)) == []


def test_generate_raises_precondition_error_when_approved_script_missing() -> None:
    runs, assets, storage = _triple()
    # A valid status for scene generation, but the approved script text is absent.
    _seed_run(runs, RunStatus.SCRIPT_APPROVED, approved_script=None)
    planner = _RecordingSceneTablePlanner()

    with pytest.raises(
        ApprovedScriptRequiredError, match="Run 'run-1' has no approved script"
    ) as exc_info:
        _generate_use_case(runs, assets, storage, planner).execute("run-1")

    assert exc_info.value.run_id == "run-1"
    # Rejected before the planner runs and before any persistence.
    assert planner.calls == []
    assert storage.saved == {}
    assert list(assets.list_for_run("run-1", AssetKind.SCENE_TABLE)) == []


@pytest.mark.parametrize(
    "status",
    [
        RunStatus.CREATED,
        RunStatus.SCRIPT_READY,
        RunStatus.SCENES_APPROVED,
        RunStatus.RENDERED,
        RunStatus.FAILED,
    ],
)
def test_generate_rejects_invalid_states_via_d7_guard(status: RunStatus) -> None:
    runs, assets, storage = _triple()
    # approved_script is present so the precondition passes; the D7 status guard
    # inside CreateSceneTable is what rejects.
    _seed_run(runs, status, approved_script="the approved script")

    with pytest.raises(AssetCreationRejectedError) as exc_info:
        _generate_use_case(
            runs, assets, storage, _RecordingSceneTablePlanner()
        ).execute("run-1")

    assert exc_info.value.status is status
    assert exc_info.value.kind is AssetKind.SCENE_TABLE
    # The D7 guard inside CreateSceneTable rejects before any persistence.
    assert list(assets.list_for_run("run-1", AssetKind.SCENE_TABLE)) == []
    assert storage.saved == {}
