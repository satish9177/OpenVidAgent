"""Asset API tests (Slice 6) using TestClient with injected fakes.

Slice 7 adds composition-root tests proving injected fakes skip the default
lifespan disk/database initialization.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import status
from fastapi.testclient import TestClient

from backend.app.config.settings import Settings
from backend.app.domain import Run, RunStatus
from backend.app.main import create_app
from tests.fakes import (
    InMemoryRunRepository,
    InMemoryStorage,
    InMemoryVersionedAssetRepository,
)


def _client(run_status: RunStatus = RunStatus.CREATED, run_id: str = "run-1") -> TestClient:
    runs = InMemoryRunRepository()
    runs.save(Run(run_id=run_id, prompt="prompt", status=run_status))
    return TestClient(
        create_app(
            run_repository=runs,
            versioned_asset_repository=InMemoryVersionedAssetRepository(),
            storage=InMemoryStorage(),
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
