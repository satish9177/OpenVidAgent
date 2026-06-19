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
from backend.app.domain import (
    ClipCandidate,
    Run,
    RunStatus,
    SceneSpec,
    SelectedClip,
    StockQuerySpec,
)
from backend.app.infrastructure.generation import (
    DeterministicClipSelector,
    EchoScriptDraftGenerator,
    StubClipRetrievalProvider,
    StubSceneTablePlanner,
    StubStockClipPlanner,
)
from backend.app.main import create_app
from backend.app.ports import (
    ClipRetrievalProvider,
    ClipSelector,
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
    clip_retrieval_provider: ClipRetrievalProvider | None = None,
    clip_selector: ClipSelector | None = None,
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
            clip_retrieval_provider=clip_retrieval_provider,
            clip_selector=clip_selector,
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


class _SpyClipRetrievalProvider(ClipRetrievalProvider):
    """Records calls so a test can prove the injected retriever was used."""

    def __init__(self) -> None:
        self.calls: list[StockQuerySpec] = []

    def retrieve(self, query: StockQuerySpec) -> Sequence[ClipCandidate]:
        self.calls.append(query)
        return (
            ClipCandidate(
                scene_id=query.scene_id,
                query_text=query.query,
                provider="spy",
                provider_clip_id=f"{query.scene_id}-spy-1",
                title=f"{query.query} spy candidate",
                preview_url=f"memory://clips/{query.scene_id}/preview.jpg",
                source_url=f"memory://clips/{query.scene_id}",
                duration_seconds=query.duration_seconds,
                width=1920,
                height=1080,
            ),
        )


class _SpyClipSelector(ClipSelector):
    """Records calls so a test can prove the injected selector was used."""

    def __init__(self) -> None:
        self.calls: list[tuple[ClipCandidate, ...]] = []

    def select(
        self, candidates: Sequence[ClipCandidate]
    ) -> Sequence[SelectedClip]:
        captured = tuple(candidates)
        self.calls.append(captured)
        return tuple(
            SelectedClip(
                scene_id=candidate.scene_id,
                query_text=candidate.query_text,
                provider=candidate.provider,
                provider_clip_id=candidate.provider_clip_id,
                title=candidate.title,
                preview_url=candidate.preview_url,
                source_url=candidate.source_url,
                duration_seconds=candidate.duration_seconds,
                width=candidate.width,
                height=candidate.height,
                selection_reason="spy_selection",
            )
            for candidate in captured
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


def test_generate_stock_plan_without_scene_table_returns_404_after_status_guard() -> None:
    client = _client(RunStatus.SCENES_APPROVED)

    response = client.post("/runs/run-1/stock-plans/generate")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["kind"] == "scene_table"


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


def test_retrieve_clip_candidates_creates_retrieved_asset_and_keeps_run_approved() -> None:
    stock_spy = _SpyStockPlanner()
    clip_spy = _SpyClipRetrievalProvider()
    client = _client(
        RunStatus.SCRIPT_APPROVED,
        stock_planner=stock_spy,
        clip_retrieval_provider=clip_spy,
    )
    _approve_scenes_after_scene_table(client)
    client.post("/runs/run-1/stock-plans/generate")

    response = client.post("/runs/run-1/clip-candidates/retrieve")

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body["kind"] == "clip_candidates"
    assert body["version"] == 1
    assert body["metadata"]["source"] == "retrieved"
    assert client.get("/runs/run-1").json()["status"] == "scenes_approved"
    assert [query.scene_id for query in clip_spy.calls] == [
        "stock-scene-1",
        "stock-scene-2",
    ]


def test_retrieve_clip_candidates_missing_run_returns_404() -> None:
    clip_spy = _SpyClipRetrievalProvider()
    client = _client(
        RunStatus.SCENES_APPROVED,
        clip_retrieval_provider=clip_spy,
    )

    response = client.post("/runs/missing/clip-candidates/retrieve")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert clip_spy.calls == []


def test_retrieve_clip_candidates_invalid_state_returns_409() -> None:
    clip_spy = _SpyClipRetrievalProvider()
    client = _client(RunStatus.CREATED, clip_retrieval_provider=clip_spy)

    response = client.post("/runs/run-1/clip-candidates/retrieve")

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["kind"] == "clip_candidates"
    assert response.json()["status"] == "created"
    assert clip_spy.calls == []


def test_retrieve_clip_candidates_without_stock_plan_returns_404_after_status_guard() -> None:
    clip_spy = _SpyClipRetrievalProvider()
    client = _client(
        RunStatus.SCENES_APPROVED,
        clip_retrieval_provider=clip_spy,
    )

    response = client.post("/runs/run-1/clip-candidates/retrieve")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["kind"] == "stock_plan"
    assert clip_spy.calls == []


def test_get_clip_candidate_list_returns_ordered_versions() -> None:
    client = _client(RunStatus.SCRIPT_APPROVED)
    _approve_scenes_after_scene_table(client)
    client.post("/runs/run-1/stock-plans/generate")
    client.post("/runs/run-1/clip-candidates/retrieve")
    client.post("/runs/run-1/clip-candidates/retrieve")

    response = client.get("/runs/run-1/clip-candidates")

    assert response.status_code == status.HTTP_200_OK
    assert [asset["version"] for asset in response.json()] == [1, 2]


def test_get_latest_clip_candidates_returns_parsed_candidates() -> None:
    stock_spy = _SpyStockPlanner()
    clip_spy = _SpyClipRetrievalProvider()
    client = _client(
        RunStatus.SCRIPT_APPROVED,
        stock_planner=stock_spy,
        clip_retrieval_provider=clip_spy,
    )
    _approve_scenes_after_scene_table(client)
    client.post("/runs/run-1/stock-plans/generate")
    client.post("/runs/run-1/clip-candidates/retrieve")

    response = client.get("/runs/run-1/clip-candidates/latest")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["asset"]["kind"] == "clip_candidates"
    assert body["asset"]["version"] == 1
    assert body["asset"]["metadata"]["source"] == "retrieved"
    assert body["candidates"] == [
        {
            "scene_id": "stock-scene-1",
            "query_text": "injected stock query",
            "provider": "spy",
            "provider_clip_id": "stock-scene-1-spy-1",
            "title": "injected stock query spy candidate",
            "preview_url": "memory://clips/stock-scene-1/preview.jpg",
            "source_url": "memory://clips/stock-scene-1",
            "duration_seconds": 7.5,
            "width": 1920,
            "height": 1080,
        },
        {
            "scene_id": "stock-scene-2",
            "query_text": "second injected query",
            "provider": "spy",
            "provider_clip_id": "stock-scene-2-spy-1",
            "title": "second injected query spy candidate",
            "preview_url": "memory://clips/stock-scene-2/preview.jpg",
            "source_url": "memory://clips/stock-scene-2",
            "duration_seconds": 2.25,
            "width": 1920,
            "height": 1080,
        },
    ]


def test_latest_clip_candidates_when_none_returns_404() -> None:
    client = _client(RunStatus.SCRIPT_APPROVED)
    _approve_scenes_after_scene_table(client)

    response = client.get("/runs/run-1/clip-candidates/latest")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["kind"] == "clip_candidates"


def test_select_clips_creates_selected_asset_and_keeps_run_approved() -> None:
    stock_spy = _SpyStockPlanner()
    clip_spy = _SpyClipRetrievalProvider()
    selector_spy = _SpyClipSelector()
    client = _client(
        RunStatus.SCRIPT_APPROVED,
        stock_planner=stock_spy,
        clip_retrieval_provider=clip_spy,
        clip_selector=selector_spy,
    )
    _approve_scenes_after_scene_table(client)
    client.post("/runs/run-1/stock-plans/generate")
    client.post("/runs/run-1/clip-candidates/retrieve")

    response = client.post("/runs/run-1/selected-clips/select")

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body["kind"] == "selected_clips"
    assert body["version"] == 1
    assert body["metadata"]["source"] == "selected"
    assert client.get("/runs/run-1").json()["status"] == "scenes_approved"
    assert [candidate.scene_id for candidate in selector_spy.calls[0]] == [
        "stock-scene-1",
        "stock-scene-2",
    ]


def test_select_clips_missing_run_returns_404() -> None:
    selector_spy = _SpyClipSelector()
    client = _client(
        RunStatus.SCENES_APPROVED,
        clip_selector=selector_spy,
    )

    response = client.post("/runs/missing/selected-clips/select")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert selector_spy.calls == []


def test_select_clips_invalid_state_returns_409() -> None:
    selector_spy = _SpyClipSelector()
    client = _client(RunStatus.CREATED, clip_selector=selector_spy)

    response = client.post("/runs/run-1/selected-clips/select")

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["kind"] == "selected_clips"
    assert response.json()["status"] == "created"
    assert selector_spy.calls == []


def test_select_clips_without_candidate_set_returns_404_after_status_guard() -> None:
    selector_spy = _SpyClipSelector()
    client = _client(
        RunStatus.SCENES_APPROVED,
        clip_selector=selector_spy,
    )

    response = client.post("/runs/run-1/selected-clips/select")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["kind"] == "clip_candidates"
    assert selector_spy.calls == []


def test_get_selected_clip_list_returns_ordered_versions() -> None:
    client = _client(RunStatus.SCRIPT_APPROVED)
    _approve_scenes_after_scene_table(client)
    client.post("/runs/run-1/stock-plans/generate")
    client.post("/runs/run-1/clip-candidates/retrieve")
    client.post("/runs/run-1/selected-clips/select")
    client.post("/runs/run-1/selected-clips/select")

    response = client.get("/runs/run-1/selected-clips")

    assert response.status_code == status.HTTP_200_OK
    assert [asset["version"] for asset in response.json()] == [1, 2]


def test_get_latest_selected_clips_returns_parsed_selected_clips() -> None:
    stock_spy = _SpyStockPlanner()
    clip_spy = _SpyClipRetrievalProvider()
    selector_spy = _SpyClipSelector()
    client = _client(
        RunStatus.SCRIPT_APPROVED,
        stock_planner=stock_spy,
        clip_retrieval_provider=clip_spy,
        clip_selector=selector_spy,
    )
    _approve_scenes_after_scene_table(client)
    client.post("/runs/run-1/stock-plans/generate")
    client.post("/runs/run-1/clip-candidates/retrieve")
    client.post("/runs/run-1/selected-clips/select")

    response = client.get("/runs/run-1/selected-clips/latest")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["asset"]["kind"] == "selected_clips"
    assert body["asset"]["version"] == 1
    assert body["asset"]["metadata"]["source"] == "selected"
    assert body["selected_clips"] == [
        {
            "scene_id": "stock-scene-1",
            "query_text": "injected stock query",
            "provider": "spy",
            "provider_clip_id": "stock-scene-1-spy-1",
            "title": "injected stock query spy candidate",
            "preview_url": "memory://clips/stock-scene-1/preview.jpg",
            "source_url": "memory://clips/stock-scene-1",
            "duration_seconds": 7.5,
            "width": 1920,
            "height": 1080,
            "selection_reason": "spy_selection",
        },
        {
            "scene_id": "stock-scene-2",
            "query_text": "second injected query",
            "provider": "spy",
            "provider_clip_id": "stock-scene-2-spy-1",
            "title": "second injected query spy candidate",
            "preview_url": "memory://clips/stock-scene-2/preview.jpg",
            "source_url": "memory://clips/stock-scene-2",
            "duration_seconds": 2.25,
            "width": 1920,
            "height": 1080,
            "selection_reason": "spy_selection",
        },
    ]


def test_latest_selected_clips_when_none_returns_404() -> None:
    client = _client(RunStatus.SCRIPT_APPROVED)
    _approve_scenes_after_scene_table(client)

    response = client.get("/runs/run-1/selected-clips/latest")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["kind"] == "selected_clips"


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
    assert isinstance(app.state.clip_retrieval_provider, StubClipRetrievalProvider)
    assert isinstance(app.state.clip_selector, DeterministicClipSelector)
