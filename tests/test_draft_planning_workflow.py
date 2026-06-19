"""End-to-end happy-path test for the prompt -> script -> scenes workflow (Slice 7).

Drives the whole HTTP flow against the default deterministic generation adapters
(``EchoScriptDraftGenerator`` / ``StubSceneTablePlanner``) with in-memory
repositories and storage. No real external provider is involved: the generation
adapters are the local defaults, and ``test_architecture_boundaries.py`` proves
they import no provider SDK, network, or subprocess module.
"""

from __future__ import annotations

from fastapi import status
from fastapi.testclient import TestClient

from backend.app.main import create_app
from tests.fakes import (
    InMemoryRunRepository,
    InMemoryStorage,
    InMemoryVersionedAssetRepository,
)


def _client() -> TestClient:
    # Inject in-memory persistence; leave the generators defaulting to the
    # deterministic local adapters so the default generation path is exercised.
    return TestClient(
        create_app(
            run_repository=InMemoryRunRepository(),
            versioned_asset_repository=InMemoryVersionedAssetRepository(),
            storage=InMemoryStorage(),
        )
    )


def test_prompt_to_scenes_happy_path_advances_through_every_status() -> None:
    client = _client()

    # 1. Intake: a new run starts in `created` and echoes its intake fields.
    created = client.post(
        "/runs",
        json={
            "prompt": "a short coffee documentary",
            "title": "Coffee 101",
            "language": "en",
        },
    )
    assert created.status_code == status.HTTP_201_CREATED
    run = created.json()
    run_id = run["run_id"]
    assert run["status"] == "created"
    assert run["title"] == "Coffee 101"
    assert run["language"] == "en"

    # 2. Generate the script draft -> `script_ready` (source=generated, v1).
    script = client.post(f"/runs/{run_id}/script-drafts/generate")
    assert script.status_code == status.HTTP_201_CREATED
    script_body = script.json()
    assert script_body["kind"] == "script"
    assert script_body["version"] == 1
    assert script_body["metadata"]["source"] == "generated"
    assert client.get(f"/runs/{run_id}").json()["status"] == "script_ready"

    # 3. Approve the script -> `script_approved`.
    approved_script = client.post(f"/runs/{run_id}/approve-script")
    assert approved_script.status_code == status.HTTP_200_OK
    assert approved_script.json()["status"] == "script_approved"

    # 4. Generate the scene table -> `scenes_ready` (source=generated, v1).
    scene_table = client.post(f"/runs/{run_id}/scene-tables/generate")
    assert scene_table.status_code == status.HTTP_201_CREATED
    scene_body = scene_table.json()
    assert scene_body["kind"] == "scene_table"
    assert scene_body["version"] == 1
    assert scene_body["metadata"]["source"] == "generated"
    assert client.get(f"/runs/{run_id}").json()["status"] == "scenes_ready"

    # 5. The generated scene table is retrievable as parsed scenes.
    latest = client.get(f"/runs/{run_id}/scene-tables/latest")
    assert latest.status_code == status.HTTP_200_OK
    latest_body = latest.json()
    assert latest_body["asset"]["version"] == 1
    assert latest_body["asset"]["metadata"]["source"] == "generated"
    assert latest_body["scenes"], "expected non-empty parsed scenes"
    first_scene = latest_body["scenes"][0]
    assert first_scene["scene_id"]
    assert first_scene["narration"]
    assert first_scene["visual_query"]
    assert first_scene["duration_seconds"] > 0

    # 6. Approve the scenes -> `scenes_approved` (phase terminal state).
    approved_scenes = client.post(f"/runs/{run_id}/approve-scenes")
    assert approved_scenes.status_code == status.HTTP_200_OK
    assert approved_scenes.json()["status"] == "scenes_approved"
