"""End-to-end happy path through metadata-only video assembly planning.

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

    # 11. Select clips -> asset-only; run still stays `scenes_approved` and no
    # render/download stage is used.
    selected = client.post(f"/runs/{run_id}/selected-clips/select")
    assert selected.status_code == status.HTTP_201_CREATED
    selected_body = selected.json()
    assert selected_body["kind"] == "selected_clips"
    assert selected_body["version"] == 1
    assert selected_body["metadata"]["source"] == "selected"
    assert client.get(f"/runs/{run_id}").json()["status"] == "scenes_approved"

    # 12. The selected clip set is retrievable as parsed metadata-only rows.
    # The deterministic selector copies memory URLs from the candidates and
    # records why each first-per-scene/query candidate was chosen.
    latest_selected = client.get(f"/runs/{run_id}/selected-clips/latest")
    assert latest_selected.status_code == status.HTTP_200_OK
    latest_selected_body = latest_selected.json()
    assert latest_selected_body["asset"]["version"] == 1
    assert latest_selected_body["asset"]["metadata"]["source"] == "selected"
    assert latest_selected_body["selected_clips"], "expected selected clips"
    selected_scene_ids = {
        clip["scene_id"] for clip in latest_selected_body["selected_clips"]
    }
    assert selected_scene_ids.issubset(scene_ids)
    first_selected = latest_selected_body["selected_clips"][0]
    assert first_selected["scene_id"]
    assert first_selected["query_text"]
    assert first_selected["provider"] == "stub"
    assert first_selected["provider_clip_id"]
    assert first_selected["title"]
    assert first_selected["preview_url"].startswith("memory://")
    assert first_selected["source_url"].startswith("memory://")
    assert first_selected["duration_seconds"] > 0
    assert first_selected["width"] == 1920
    assert first_selected["height"] == 1080
    assert first_selected["selection_reason"] == (
        "first_candidate_for_scene_query"
    )

    # 13. Generate a metadata-only assembly plan from the latest selected clips
    # and scene table. No media URL is opened and the run remains approved.
    assembly = client.post(
        f"/runs/{run_id}/video-assembly-plans/generate"
    )
    assert assembly.status_code == status.HTTP_201_CREATED
    assembly_body = assembly.json()
    assert assembly_body["kind"] == "video_assembly_plan"
    assert assembly_body["version"] == 1
    metadata = assembly_body["metadata"]
    assert metadata["source"] == "generated"
    assert metadata["aspect_ratio"] == "16:9"
    assert metadata["render_intent"] == "voiceover_b_roll"
    assert metadata["scene_table_asset_id"] == latest_body["asset"]["asset_id"]
    assert metadata["scene_table_version"] == "1"
    assert metadata["selected_clips_asset_id"] == (
        latest_selected_body["asset"]["asset_id"]
    )
    assert metadata["selected_clips_version"] == "1"

    # 14. Parsed segments preserve scene-table order and combine scene timing
    # with selected provider metadata. The hints are descriptive strings only.
    latest_assembly = client.get(
        f"/runs/{run_id}/video-assembly-plans/latest"
    )
    assert latest_assembly.status_code == status.HTTP_200_OK
    latest_assembly_body = latest_assembly.json()
    assert latest_assembly_body["asset"] == assembly_body
    segments = latest_assembly_body["segments"]
    assert segments, "expected non-empty assembly segments"

    scenes_by_id = {
        scene["scene_id"]: scene for scene in latest_body["scenes"]
    }
    selected_by_id = {
        (clip["provider"], clip["provider_clip_id"]): clip
        for clip in latest_selected_body["selected_clips"]
    }
    expected_scene_order = [
        scene["scene_id"]
        for scene in latest_body["scenes"]
        if scene["scene_id"] in selected_scene_ids
    ]
    assert [segment["scene_id"] for segment in segments] == expected_scene_order
    assert [segment["order_index"] for segment in segments] == list(
        range(len(segments))
    )

    for segment in segments:
        scene = scenes_by_id[segment["scene_id"]]
        selected_clip = selected_by_id[
            (segment["provider"], segment["provider_clip_id"])
        ]
        assert segment["narration"] == scene["narration"]
        assert segment["visual_query"] == scene["visual_query"]
        assert segment["target_duration_seconds"] == scene["duration_seconds"]
        assert segment["query_text"] == selected_clip["query_text"]
        assert segment["source_duration_seconds"] == (
            selected_clip["duration_seconds"]
        )
        assert segment["title"] == selected_clip["title"]
        assert segment["selection_reason"] == selected_clip["selection_reason"]
        assert segment["preview_url"].startswith("memory://")
        assert segment["source_url"].startswith("memory://")
        assert segment["transition"] == "cut"
        assert segment["continuity_note"] == "ordered_by_scene_table"

    # 15. Download clips into a metadata-only manifest. The default downloader
    # fabricates stable memory references and writes no media files.
    downloaded = client.post(f"/runs/{run_id}/downloaded-clips/download")
    assert downloaded.status_code == status.HTTP_201_CREATED
    downloaded_body = downloaded.json()
    assert downloaded_body["kind"] == "downloaded_clips"
    assert downloaded_body["version"] == 1
    assert downloaded_body["metadata"] == {
        "video_assembly_plan_asset_id": assembly_body["asset_id"],
        "video_assembly_plan_version": "1",
        "source": "downloaded",
    }

    # 16. Every assembly segment has one ordered downloaded record with copied
    # provider/source metadata and an unmistakably non-file memory URI.
    latest_downloaded = client.get(
        f"/runs/{run_id}/downloaded-clips/latest"
    )
    assert latest_downloaded.status_code == status.HTTP_200_OK
    latest_downloaded_body = latest_downloaded.json()
    assert latest_downloaded_body["asset"] == downloaded_body
    downloaded_clips = latest_downloaded_body["downloaded_clips"]
    assert len(downloaded_clips) == len(segments)
    assert [clip["order_index"] for clip in downloaded_clips] == [
        segment["order_index"] for segment in segments
    ]

    segments_by_order = {
        segment["order_index"]: segment for segment in segments
    }
    for clip in downloaded_clips:
        segment = segments_by_order[clip["order_index"]]
        assert clip["scene_id"] == segment["scene_id"]
        assert clip["query_text"] == segment["query_text"]
        assert clip["provider"] == segment["provider"]
        assert clip["provider_clip_id"] == segment["provider_clip_id"]
        assert clip["title"] == segment["title"]
        assert clip["source_url"] == segment["source_url"]
        assert clip["duration_seconds"] == segment["source_duration_seconds"]
        assert clip["width"] == segment["width"]
        assert clip["height"] == segment["height"]
        assert clip["local_uri"].startswith("memory://downloads/")
        assert clip["content_type"] == "video/mp4"
        assert clip["download_status"] == "available"
        assert clip["download_reason"] == "deterministic_placeholder"

    # 17. Generate a metadata-only voiceover manifest from the same assembly
    # plan. The default generator creates references only, never audio bytes.
    voiceover = client.post(f"/runs/{run_id}/voiceovers/generate")
    assert voiceover.status_code == status.HTTP_201_CREATED
    voiceover_body = voiceover.json()
    assert voiceover_body["kind"] == "voiceover"
    assert voiceover_body["version"] == 1
    assert voiceover_body["metadata"] == {
        "video_assembly_plan_asset_id": assembly_body["asset_id"],
        "video_assembly_plan_version": "1",
        "language": "en",
        "source": "generated",
    }

    # 18. Every assembly segment has one ordered narration record with target
    # duration and deterministic memory URI metadata.
    latest_voiceover = client.get(f"/runs/{run_id}/voiceovers/latest")
    assert latest_voiceover.status_code == status.HTTP_200_OK
    latest_voiceover_body = latest_voiceover.json()
    assert latest_voiceover_body["asset"] == voiceover_body
    voiceover_segments = latest_voiceover_body["segments"]
    assert len(voiceover_segments) == len(segments)
    assert [segment["order_index"] for segment in voiceover_segments] == [
        segment["order_index"] for segment in segments
    ]

    for voiceover_segment in voiceover_segments:
        segment = segments_by_order[voiceover_segment["order_index"]]
        assert voiceover_segment["scene_id"] == segment["scene_id"]
        assert voiceover_segment["narration_text"] == segment["narration"]
        assert voiceover_segment["duration_seconds"] == (
            segment["target_duration_seconds"]
        )
        assert voiceover_segment["language"] == "en"
        assert voiceover_segment["voice_id"] == "stub-narrator"
        assert voiceover_segment["provider"] == "stub"
        assert voiceover_segment["audio_uri"].startswith(
            "memory://voiceovers/"
        )
        assert voiceover_segment["content_type"] == "audio/mpeg"
        assert voiceover_segment["status"] == "available"
        assert voiceover_segment["generation_reason"] == (
            "deterministic_placeholder"
        )

    final_run = client.get(f"/runs/{run_id}").json()
    assert final_run["status"] == "scenes_approved"
    assert final_run["status"] != "rendered"
