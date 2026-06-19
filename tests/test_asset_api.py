"""Asset API tests (Slice 6) using TestClient with injected fakes.

Slice 7 adds composition-root tests proving injected fakes skip the default
lifespan disk/database initialization.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from fastapi import status
from fastapi.testclient import TestClient

from backend.app.config.settings import Settings
from backend.app.domain import Run, RunStatus, SceneSpec, StockQuerySpec
from backend.app.infrastructure.generation import (
    EchoScriptDraftGenerator,
    StubSceneTablePlanner,
    StubStockClipPlanner,
)
from backend.app.main import create_app
from backend.app.ports import (
    SceneTablePlanner,
    ScriptDraftGenerator,
    StockClipPlanner,
)
from tests.fakes import (
    InMemoryRunRepository,
    InMemoryStorage,
    InMemoryVersionedAssetRepository,
)


def _client(
    run_status: RunStatus = RunStatus.CREATED,
    run_id: str = "run-1",
    *,
    approved_script: str | None = None,
    script_generator: ScriptDraftGenerator | None = None,
    scene_planner: SceneTablePlanner | None = None,
    stock_planner: StockClipPlanner | None = None,
) -> TestClient:
    runs = InMemoryRunRepository()
    runs.save(
        Run(
            run_id=run_id,
            prompt="prompt",
            status=run_status,
            approved_script=approved_script,
        )
    )
    return TestClient(
        create_app(
            run_repository=runs,
            versioned_asset_repository=InMemoryVersionedAssetRepository(),
            storage=InMemoryStorage(),
            script_generator=script_generator,
            scene_planner=scene_planner,
            stock_planner=stock_planner,
        )
    )


def _scenes_payload(scene_id: str = "scene-1") -> dict:
    return {
        "scenes": [
            {
                "scene_id": scene_id,
                "narration": "Opening narration",
                "visual_query": "city skyline",
                "duration_seconds": 4.0,
            },
            {
                "scene_id": "scene-2",
                "narration": "Closing narration",
                "visual_query": "quiet desk",
                "duration_seconds": 3.5,
            },
        ]
    }


def _approve_scenes_after_scene_table(client: TestClient) -> None:
    scene_table = client.post("/runs/run-1/scene-tables", json=_scenes_payload())
    assert scene_table.status_code == status.HTTP_201_CREATED
    approved = client.post("/runs/run-1/approve-scenes")
    assert approved.status_code == status.HTTP_200_OK
    assert approved.json()["status"] == "scenes_approved"


# --- script drafts ---


def test_post_script_draft_creates_v1_and_advances_run() -> None:
    client = _client(RunStatus.CREATED)

    response = client.post("/runs/run-1/script-drafts", json={"text": "hello"})

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body["kind"] == "script"
    assert body["version"] == 1
    assert body["uri"]
    # The route triggered the lifecycle transition via the use-case, not itself.
    assert client.get("/runs/run-1").json()["status"] == "script_ready"


def test_second_post_script_draft_creates_v2() -> None:
    client = _client(RunStatus.CREATED)
    client.post("/runs/run-1/script-drafts", json={"text": "v1"})

    response = client.post("/runs/run-1/script-drafts", json={"text": "v2"})

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["version"] == 2
    # D7 same-status path: second draft stays script_ready (no self-transition).
    assert client.get("/runs/run-1").json()["status"] == "script_ready"


def test_get_script_draft_list_returns_ordered_versions() -> None:
    client = _client(RunStatus.CREATED)
    client.post("/runs/run-1/script-drafts", json={"text": "v1"})
    client.post("/runs/run-1/script-drafts", json={"text": "v2"})

    response = client.get("/runs/run-1/script-drafts")

    assert response.status_code == status.HTTP_200_OK
    assert [asset["version"] for asset in response.json()] == [1, 2]


def test_get_latest_script_draft_returns_newest_version() -> None:
    client = _client(RunStatus.CREATED)
    client.post("/runs/run-1/script-drafts", json={"text": "v1"})
    client.post("/runs/run-1/script-drafts", json={"text": "v2"})

    response = client.get("/runs/run-1/script-drafts/latest")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["version"] == 2


def test_missing_run_for_script_draft_returns_404() -> None:
    client = _client(RunStatus.CREATED)

    response = client.post("/runs/missing/script-drafts", json={"text": "x"})

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_latest_script_draft_when_none_returns_404() -> None:
    client = _client(RunStatus.CREATED)

    response = client.get("/runs/run-1/script-drafts/latest")

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_invalid_script_draft_state_returns_409() -> None:
    client = _client(RunStatus.SCRIPT_APPROVED)

    response = client.post("/runs/run-1/script-drafts", json={"text": "x"})

    assert response.status_code == status.HTTP_409_CONFLICT


# --- scene tables ---


def test_post_scene_table_creates_v1_and_advances_run() -> None:
    client = _client(RunStatus.SCRIPT_APPROVED)

    response = client.post("/runs/run-1/scene-tables", json=_scenes_payload())

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body["asset"]["kind"] == "scene_table"
    assert body["asset"]["version"] == 1
    assert [scene["scene_id"] for scene in body["scenes"]] == [
        "scene-1",
        "scene-2",
    ]
    assert body["scenes"][0]["duration_seconds"] == 4.0
    assert client.get("/runs/run-1").json()["status"] == "scenes_ready"


def test_second_post_scene_table_creates_v2() -> None:
    client = _client(RunStatus.SCRIPT_APPROVED)
    client.post("/runs/run-1/scene-tables", json=_scenes_payload())

    response = client.post("/runs/run-1/scene-tables", json=_scenes_payload())

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["asset"]["version"] == 2
    # D7 same-status path: second table stays scenes_ready (no self-transition).
    assert client.get("/runs/run-1").json()["status"] == "scenes_ready"


def test_get_scene_table_list_returns_ordered_versions() -> None:
    client = _client(RunStatus.SCRIPT_APPROVED)
    client.post("/runs/run-1/scene-tables", json=_scenes_payload())
    client.post("/runs/run-1/scene-tables", json=_scenes_payload())

    response = client.get("/runs/run-1/scene-tables")

    assert response.status_code == status.HTTP_200_OK
    assert [asset["version"] for asset in response.json()] == [1, 2]


def test_get_latest_scene_table_returns_newest_parsed_scenes() -> None:
    client = _client(RunStatus.SCRIPT_APPROVED)
    client.post("/runs/run-1/scene-tables", json=_scenes_payload("old"))
    client.post(
        "/runs/run-1/scene-tables",
        json={
            "scenes": [
                {
                    "scene_id": "new",
                    "narration": "n",
                    "visual_query": "q",
                    "duration_seconds": 9.5,
                }
            ]
        },
    )

    response = client.get("/runs/run-1/scene-tables/latest")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["asset"]["version"] == 2
    assert [scene["scene_id"] for scene in body["scenes"]] == ["new"]
    assert body["scenes"][0]["duration_seconds"] == 9.5


def test_missing_run_for_scene_table_returns_404() -> None:
    client = _client(RunStatus.SCRIPT_APPROVED)

    response = client.post("/runs/missing/scene-tables", json=_scenes_payload())

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_latest_scene_table_when_none_returns_404() -> None:
    client = _client(RunStatus.SCRIPT_APPROVED)

    response = client.get("/runs/run-1/scene-tables/latest")

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_invalid_scene_table_state_returns_409() -> None:
    client = _client(RunStatus.CREATED)

    response = client.post("/runs/run-1/scene-tables", json=_scenes_payload())

    assert response.status_code == status.HTTP_409_CONFLICT


# --- composition root (Slice 7) ---


def test_injected_fakes_skip_default_lifespan_disk_io(tmp_path: Path) -> None:
    database_path = tmp_path / "should_not_exist.sqlite"
    storage_root = tmp_path / "should_not_exist_assets"
    settings = Settings(
        database_path=str(database_path), storage_root=str(storage_root)
    )

    app = create_app(
        settings,
        run_repository=InMemoryRunRepository(),
        versioned_asset_repository=InMemoryVersionedAssetRepository(),
        storage=InMemoryStorage(),
    )

    # Entering TestClient as a context manager runs startup/shutdown (the
    # lifespan, if one was installed). With all fakes injected none should be.
    with TestClient(app):
        assert isinstance(app.state.run_repository, InMemoryRunRepository)
        assert isinstance(
            app.state.versioned_asset_repository,
            InMemoryVersionedAssetRepository,
        )
        assert isinstance(app.state.storage, InMemoryStorage)

    assert not database_path.exists()
    assert not storage_root.exists()


def test_default_infra_initializes_database_and_storage_root(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "db.sqlite"
    storage_root = tmp_path / "assets"
    settings = Settings(
        database_path=str(database_path), storage_root=str(storage_root)
    )

    app = create_app(settings)  # all defaults -> SQLite + filesystem adapters

    with TestClient(app):
        pass

    assert database_path.exists()
    assert storage_root.exists()


# --- generation endpoints (Slice 6) ---


class _SpyScriptGenerator(ScriptDraftGenerator):
    """Records calls so a test can prove the injected generator was used."""

    def __init__(self, script: str = "# Injected generated script") -> None:
        self._script = script
        self.calls: list[tuple[str, str]] = []

    def generate(self, prompt: str, language: str) -> str:
        self.calls.append((prompt, language))
        return self._script


class _SpyScenePlanner(SceneTablePlanner):
    """Records calls so a test can prove the injected planner was used."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def plan(self, approved_script: str, language: str) -> Sequence[SceneSpec]:
        self.calls.append((approved_script, language))
        return (
            SceneSpec(
                scene_id="injected-scene",
                narration="injected narration",
                visual_query="injected query",
                duration_seconds=3.0,
            ),
        )


class _SpyStockPlanner(StockClipPlanner):
    """Records calls so a test can prove the injected stock planner was used."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[SceneSpec, ...], str]] = []

    def plan_stock_clips(
        self, scenes: Sequence[SceneSpec], language: str
    ) -> Sequence[StockQuerySpec]:
        self.calls.append((tuple(scenes), language))
        return (
            StockQuerySpec(
                scene_id="stock-scene-1",
                query="injected stock query",
                visual_intent="injected stock intent",
                duration_seconds=7.5,
            ),
            StockQuerySpec(
                scene_id="stock-scene-2",
                query="second injected query",
                visual_intent="second injected intent",
                duration_seconds=2.25,
                provider_hint=None,
            ),
        )


def test_generate_script_draft_creates_generated_asset_and_advances_run() -> None:
    client = _client(RunStatus.CREATED)

    response = client.post("/runs/run-1/script-drafts/generate")

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body["kind"] == "script"
    assert body["version"] == 1
    assert body["uri"]
    assert body["metadata"]["source"] == "generated"
    # The route advanced the lifecycle via the use-case, not itself.
    assert client.get("/runs/run-1").json()["status"] == "script_ready"


def test_generate_script_draft_uses_injected_generator() -> None:
    spy = _SpyScriptGenerator()
    client = _client(RunStatus.CREATED, script_generator=spy)

    response = client.post("/runs/run-1/script-drafts/generate")

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["metadata"]["source"] == "generated"
    # The run's prompt/language were forwarded through the use-case to the
    # injected generator, proving no infrastructure default was substituted.
    assert spy.calls == [("prompt", "en")]


def test_generate_script_draft_missing_run_returns_404() -> None:
    client = _client(RunStatus.CREATED)

    response = client.post("/runs/missing/script-drafts/generate")

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_generate_script_draft_invalid_state_returns_409() -> None:
    client = _client(RunStatus.SCRIPT_APPROVED)

    response = client.post("/runs/run-1/script-drafts/generate")

    assert response.status_code == status.HTTP_409_CONFLICT


def test_generate_scene_table_creates_generated_asset_and_advances_run() -> None:
    client = _client(RunStatus.SCRIPT_APPROVED, approved_script="approved script")

    response = client.post("/runs/run-1/scene-tables/generate")

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body["kind"] == "scene_table"
    assert body["version"] == 1
    assert body["metadata"]["source"] == "generated"
    assert client.get("/runs/run-1").json()["status"] == "scenes_ready"


def test_generate_scene_table_uses_injected_planner() -> None:
    spy = _SpyScenePlanner()
    client = _client(
        RunStatus.SCRIPT_APPROVED,
        approved_script="approved body",
        scene_planner=spy,
    )

    response = client.post("/runs/run-1/scene-tables/generate")

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["metadata"]["source"] == "generated"
    assert spy.calls == [("approved body", "en")]


def test_generate_scene_table_missing_run_returns_404() -> None:
    client = _client(RunStatus.SCRIPT_APPROVED, approved_script="approved script")

    response = client.post("/runs/missing/scene-tables/generate")

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_generate_scene_table_invalid_state_returns_409() -> None:
    # CREATED is not a valid state for scene-table creation (D7 guard).
    client = _client(RunStatus.CREATED, approved_script="approved script")

    response = client.post("/runs/run-1/scene-tables/generate")

    assert response.status_code == status.HTTP_409_CONFLICT


def test_generate_scene_table_missing_approved_script_returns_409() -> None:
    # Valid status but no approved script -> ApprovedScriptRequiredError -> 409.
    client = _client(RunStatus.SCRIPT_APPROVED, approved_script=None)

    response = client.post("/runs/run-1/scene-tables/generate")

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["run_id"] == "run-1"


def test_generate_stock_plan_creates_generated_asset_and_keeps_run_approved() -> None:
    client = _client(RunStatus.SCRIPT_APPROVED)
    _approve_scenes_after_scene_table(client)

    response = client.post("/runs/run-1/stock-plans/generate")

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body["kind"] == "stock_plan"
    assert body["version"] == 1
    assert body["metadata"]["source"] == "generated"
    assert client.get("/runs/run-1").json()["status"] == "scenes_approved"


def test_generate_stock_plan_uses_injected_planner() -> None:
    spy = _SpyStockPlanner()
    client = _client(RunStatus.SCRIPT_APPROVED, stock_planner=spy)
    _approve_scenes_after_scene_table(client)

    response = client.post("/runs/run-1/stock-plans/generate")

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["metadata"]["source"] == "generated"
    expected_scenes = (
        SceneSpec(
            scene_id="scene-1",
            narration="Opening narration",
            visual_query="city skyline",
            duration_seconds=4.0,
        ),
        SceneSpec(
            scene_id="scene-2",
            narration="Closing narration",
            visual_query="quiet desk",
            duration_seconds=3.5,
        ),
    )
    assert spy.calls == [(expected_scenes, "en")]


def test_generate_stock_plan_missing_run_returns_404() -> None:
    client = _client(RunStatus.SCENES_APPROVED)

    response = client.post("/runs/missing/stock-plans/generate")

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_generate_stock_plan_invalid_state_returns_409() -> None:
    client = _client(RunStatus.CREATED)

    response = client.post("/runs/run-1/stock-plans/generate")

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["kind"] == "stock_plan"
    assert response.json()["status"] == "created"


def test_get_stock_plan_list_returns_ordered_versions() -> None:
    client = _client(RunStatus.SCRIPT_APPROVED)
    _approve_scenes_after_scene_table(client)
    client.post("/runs/run-1/stock-plans/generate")
    client.post("/runs/run-1/stock-plans/generate")

    response = client.get("/runs/run-1/stock-plans")

    assert response.status_code == status.HTTP_200_OK
    assert [asset["version"] for asset in response.json()] == [1, 2]


def test_get_latest_stock_plan_returns_parsed_queries() -> None:
    spy = _SpyStockPlanner()
    client = _client(RunStatus.SCRIPT_APPROVED, stock_planner=spy)
    _approve_scenes_after_scene_table(client)
    client.post("/runs/run-1/stock-plans/generate")

    response = client.get("/runs/run-1/stock-plans/latest")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["asset"]["kind"] == "stock_plan"
    assert body["asset"]["version"] == 1
    assert body["asset"]["metadata"]["source"] == "generated"
    assert body["queries"] == [
        {
            "scene_id": "stock-scene-1",
            "query": "injected stock query",
            "visual_intent": "injected stock intent",
            "duration_seconds": 7.5,
            "provider_hint": None,
        },
        {
            "scene_id": "stock-scene-2",
            "query": "second injected query",
            "visual_intent": "second injected intent",
            "duration_seconds": 2.25,
            "provider_hint": None,
        },
    ]


def test_latest_stock_plan_when_none_returns_404() -> None:
    client = _client(RunStatus.SCRIPT_APPROVED)
    _approve_scenes_after_scene_table(client)

    response = client.get("/runs/run-1/stock-plans/latest")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["kind"] == "stock_plan"


def test_default_app_wires_deterministic_generation_adapters() -> None:
    # All infra injected except the generators, which must default to the
    # deterministic local adapters (no external calls, no SDKs).
    app = create_app(
        run_repository=InMemoryRunRepository(),
        versioned_asset_repository=InMemoryVersionedAssetRepository(),
        storage=InMemoryStorage(),
    )

    assert isinstance(app.state.script_generator, EchoScriptDraftGenerator)
    assert isinstance(app.state.scene_planner, StubSceneTablePlanner)
    assert isinstance(app.state.stock_planner, StubStockClipPlanner)
