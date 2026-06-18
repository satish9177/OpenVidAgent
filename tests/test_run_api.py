from fastapi import status
from fastapi.testclient import TestClient

from backend.app.main import create_app
from tests.fakes import InMemoryRunRepository


def _client() -> TestClient:
    return TestClient(create_app(run_repository=InMemoryRunRepository()))


def _create_run(client: TestClient, prompt: str = "make a video") -> str:
    response = client.post("/runs", json={"prompt": prompt})
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["run_id"]


def test_post_runs_creates_a_run() -> None:
    client = _client()

    response = client.post("/runs", json={"prompt": "make a video"})

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body["run_id"]
    assert body["prompt"] == "make a video"
    assert body["status"] == "created"


def test_get_run_returns_a_run() -> None:
    client = _client()
    run_id = _create_run(client)

    response = client.get(f"/runs/{run_id}")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["run_id"] == run_id


def test_transition_endpoints_move_state_through_approval() -> None:
    client = _client()
    run_id = _create_run(client)

    ready = client.post(f"/runs/{run_id}/script-ready", json={"script": "draft"})
    assert ready.status_code == status.HTTP_200_OK
    assert ready.json()["status"] == "script_ready"
    assert ready.json()["script"] == "draft"

    approved = client.post(f"/runs/{run_id}/approve-script")
    assert approved.status_code == status.HTTP_200_OK
    assert approved.json()["status"] == "script_approved"
    assert approved.json()["approved_script"] == "draft"

    scenes_ready = client.post(f"/runs/{run_id}/scenes-ready")
    assert scenes_ready.json()["status"] == "scenes_ready"

    scenes_approved = client.post(f"/runs/{run_id}/approve-scenes")
    assert scenes_approved.json()["status"] == "scenes_approved"


def test_approve_script_accepts_an_explicit_script() -> None:
    client = _client()
    run_id = _create_run(client)
    client.post(f"/runs/{run_id}/script-ready", json={"script": "draft"})

    response = client.post(
        f"/runs/{run_id}/approve-script", json={"approved_script": "final"}
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["approved_script"] == "final"


def test_failed_endpoint_records_reason() -> None:
    client = _client()
    run_id = _create_run(client)

    response = client.post(f"/runs/{run_id}/failed", json={"reason": "boom"})

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "failed"
    assert response.json()["failure_reason"] == "boom"


def test_invalid_transition_returns_409() -> None:
    client = _client()
    run_id = _create_run(client)

    # Approving a script is not allowed straight from the created state.
    response = client.post(f"/runs/{run_id}/approve-script")

    assert response.status_code == status.HTTP_409_CONFLICT


def test_missing_run_returns_404_on_get() -> None:
    client = _client()

    response = client.get("/runs/does-not-exist")

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_missing_run_returns_404_on_transition() -> None:
    client = _client()

    response = client.post(
        "/runs/does-not-exist/script-ready", json={"script": "draft"}
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
