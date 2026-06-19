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

    # 7. Generate a stock plan -> asset-only; run stays `scenes_approved`.
    stock_plan = client.post(f"/runs/{run_id}/stock-plans/generate")
    assert stock_plan.status_code == status.HTTP_201_CREATED
    stock_body = stock_plan.json()
    assert stock_body["kind"] == "stock_plan"
    assert stock_body["version"] == 1
    assert stock_body["metadata"]["source"] == "generated"
    assert client.get(f"/runs/{run_id}").json()["status"] == "scenes_approved"

    # 8. The generated stock plan is retrievable as parsed query specs. The
    # deterministic planner adds no provider hint, downloads no clip, and leaves
    # the run unrendered for the later media phases.
    latest_stock = client.get(f"/runs/{run_id}/stock-plans/latest")
    assert latest_stock.status_code == status.HTTP_200_OK
    latest_stock_body = latest_stock.json()
    assert latest_stock_body["asset"]["version"] == 1
    assert latest_stock_body["asset"]["metadata"]["source"] == "generated"
    assert latest_stock_body["queries"], "expected non-empty parsed queries"
    first_query = latest_stock_body["queries"][0]
    assert first_query["scene_id"]
    assert first_query["query"]
    assert first_query["visual_intent"]
    assert first_query["duration_seconds"] > 0
    assert "provider_hint" in first_query
    assert first_query["provider_hint"] is None
    assert client.get(f"/runs/{run_id}").json()["status"] == "scenes_approved"

    # 9. Retrieve clip candidates -> asset-only; run still stays
    # `scenes_approved` and no render/download stage is used.
    candidates = client.post(f"/runs/{run_id}/clip-candidates/retrieve")
    assert candidates.status_code == status.HTTP_201_CREATED
    candidates_body = candidates.json()
    assert candidates_body["kind"] == "clip_candidates"
    assert candidates_body["version"] == 1
    assert candidates_body["metadata"]["source"] == "retrieved"
    assert client.get(f"/runs/{run_id}").json()["status"] == "scenes_approved"

    # 10. The candidate set is retrievable as parsed metadata-only rows. The
    # deterministic retriever uses memory URLs, never a real provider download.
    latest_candidates = client.get(f"/runs/{run_id}/clip-candidates/latest")
    assert latest_candidates.status_code == status.HTTP_200_OK
    latest_candidates_body = latest_candidates.json()
    assert latest_candidates_body["asset"]["version"] == 1
    assert latest_candidates_body["asset"]["metadata"]["source"] == "retrieved"
    assert latest_candidates_body["candidates"], "expected non-empty candidates"
    scene_ids = {
        candidate["scene_id"]
        for candidate in latest_candidates_body["candidates"]
    }
    assert scene_ids.issuperset(
        query["scene_id"] for query in latest_stock_body["queries"]
    )
    first_candidate = latest_candidates_body["candidates"][0]
    assert first_candidate["scene_id"]
    assert first_candidate["query_text"]
    assert first_candidate["provider"] == "stub"
    assert first_candidate["provider_clip_id"]
    assert first_candidate["title"]
    assert first_candidate["preview_url"].startswith("memory://")
    assert first_candidate["source_url"].startswith("memory://")
    assert first_candidate["duration_seconds"] > 0
    assert first_candidate["width"] == 1920
    assert first_candidate["height"] == 1080
    assert client.get(f"/runs/{run_id}").json()["status"] == "scenes_approved"
