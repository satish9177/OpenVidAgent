"""Tests for the deterministic local generation adapters (Slice 3)."""

from __future__ import annotations

import ast
from pathlib import Path

from backend.app.domain import ClipCandidate, SceneSpec, StockQuerySpec
from backend.app.infrastructure.generation import (
    EchoScriptDraftGenerator,
    StubClipRetrievalProvider,
    StubSceneTablePlanner,
    StubStockClipPlanner,
)
from backend.app.ports import (
    ClipRetrievalProvider,
    SceneTablePlanner,
    ScriptDraftGenerator,
    StockClipPlanner,
)

GENERATION_DIR = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "app"
    / "infrastructure"
    / "generation"
)


def test_echo_generator_implements_port() -> None:
    assert isinstance(EchoScriptDraftGenerator(), ScriptDraftGenerator)


def test_stub_planner_implements_port() -> None:
    assert isinstance(StubSceneTablePlanner(), SceneTablePlanner)


def test_stub_stock_clip_planner_implements_port() -> None:
    assert isinstance(StubStockClipPlanner(), StockClipPlanner)


def test_stub_clip_retrieval_provider_implements_port() -> None:
    assert isinstance(StubClipRetrievalProvider(), ClipRetrievalProvider)


def test_echo_generator_is_deterministic() -> None:
    generator = EchoScriptDraftGenerator()

    first = generator.generate("make a coffee video", "en")
    second = generator.generate("make a coffee video", "en")

    assert first == second


def test_echo_generator_uses_prompt_and_language() -> None:
    generator = EchoScriptDraftGenerator()

    script = generator.generate("brewing pour-over coffee", "es")

    assert "brewing pour-over coffee" in script
    assert "Language: es" in script

    # Changing either input changes the output, proving both are used.
    assert generator.generate("brewing pour-over coffee", "en") != script
    assert generator.generate("latte art basics", "es") != script


def test_stub_planner_is_deterministic() -> None:
    planner = StubSceneTablePlanner()

    first = tuple(planner.plan("Line one.\nLine two.", "en"))
    second = tuple(planner.plan("Line one.\nLine two.", "en"))

    assert first == second


def test_stub_planner_returns_valid_scene_specs() -> None:
    planner = StubSceneTablePlanner()

    scenes = tuple(planner.plan("Intro line.\nBody line.", "en"))

    assert scenes
    for scene in scenes:
        assert isinstance(scene, SceneSpec)
        assert scene.scene_id
        assert scene.narration
        assert scene.visual_query
        assert scene.duration_seconds > 0


def test_stub_planner_uses_script_and_language() -> None:
    planner = StubSceneTablePlanner()

    scenes = tuple(planner.plan("Welcome to the show.\nGoodbye now.", "fr"))

    narrations = " ".join(scene.narration for scene in scenes)
    visual_queries = " ".join(scene.visual_query for scene in scenes)

    assert "Welcome to the show." in narrations
    assert "fr" in visual_queries

    # A different language changes the output, proving language is used.
    assert tuple(planner.plan("Welcome to the show.\nGoodbye now.", "en")) != scenes


def test_stub_stock_clip_planner_is_deterministic() -> None:
    planner = StubStockClipPlanner()
    scenes = (
        SceneSpec(
            scene_id="scene-1",
            narration="Show a calm workspace before the narration begins.",
            visual_query="calm modern workspace",
            duration_seconds=3.5,
        ),
    )

    first = tuple(planner.plan_stock_clips(scenes, "en"))
    second = tuple(planner.plan_stock_clips(scenes, "en"))

    assert first == second


def test_stub_stock_clip_planner_maps_scene_specs_to_stock_queries() -> None:
    planner = StubStockClipPlanner()
    scenes = (
        SceneSpec(
            scene_id="scene-1",
            narration="Introduce the product with a clean desk shot.",
            visual_query="clean desk product shot",
            duration_seconds=4.0,
        ),
        SceneSpec(
            scene_id="scene-2",
            narration="Show a customer using the app on a phone.",
            visual_query="person using mobile app",
            duration_seconds=5.25,
        ),
    )

    queries = tuple(planner.plan_stock_clips(scenes, "en"))

    assert queries == (
        StockQuerySpec(
            scene_id="scene-1",
            query="clean desk product shot",
            visual_intent="Introduce the product with a clean desk shot.",
            duration_seconds=4.0,
            provider_hint=None,
        ),
        StockQuerySpec(
            scene_id="scene-2",
            query="person using mobile app",
            visual_intent="Show a customer using the app on a phone.",
            duration_seconds=5.25,
            provider_hint=None,
        ),
    )
    assert len(queries) == len(scenes)
    assert all(query.provider_hint is None for query in queries)


def test_stub_clip_retrieval_provider_is_deterministic() -> None:
    provider = StubClipRetrievalProvider()
    query = StockQuerySpec(
        scene_id="scene-1",
        query="calm modern workspace",
        visual_intent="Show a calm workspace before narration begins.",
        duration_seconds=3.5,
    )

    first = tuple(provider.retrieve(query))
    second = tuple(provider.retrieve(query))

    assert first == second


def test_stub_clip_retrieval_provider_maps_stock_query_to_candidates() -> None:
    provider = StubClipRetrievalProvider()
    query = StockQuerySpec(
        scene_id="scene-1",
        query="clean desk product shot",
        visual_intent="Introduce the product with a clean desk shot.",
        duration_seconds=4.0,
    )

    candidates = tuple(provider.retrieve(query))

    assert candidates == (
        ClipCandidate(
            scene_id="scene-1",
            query_text="clean desk product shot",
            provider="stub",
            provider_clip_id="scene-1-1",
            title="clean desk product shot (candidate 1)",
            preview_url="memory://clips/scene-1/1/preview.jpg",
            source_url="memory://clips/scene-1/1",
            duration_seconds=4.0,
            width=1920,
            height=1080,
        ),
        ClipCandidate(
            scene_id="scene-1",
            query_text="clean desk product shot",
            provider="stub",
            provider_clip_id="scene-1-2",
            title="clean desk product shot (candidate 2)",
            preview_url="memory://clips/scene-1/2/preview.jpg",
            source_url="memory://clips/scene-1/2",
            duration_seconds=4.0,
            width=1920,
            height=1080,
        ),
    )
    assert len(candidates) == 2
    assert all(candidate.preview_url.startswith("memory://") for candidate in candidates)
    assert all(candidate.source_url.startswith("memory://") for candidate in candidates)


def test_generation_package_imports_no_forbidden_modules() -> None:
    forbidden_prefixes = (
        "backend.app.api",
        "backend.app.application",
        "openai",
        "anthropic",
        "google",
        "httpx",
        "requests",
        "urllib",
        "socket",
        "subprocess",
        "ffmpeg",
        "moviepy",
    )

    files = sorted(GENERATION_DIR.rglob("*.py"))
    assert files

    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        for name in imported:
            for prefix in forbidden_prefixes:
                assert not (
                    name == prefix or name.startswith(f"{prefix}.")
                ), f"{path.name} imports forbidden module {name}"
