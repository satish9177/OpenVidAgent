"""Tests for the deterministic local generation adapters (Slice 3)."""

from __future__ import annotations

import ast
from pathlib import Path

from backend.app.domain import SceneSpec
from backend.app.infrastructure.generation import (
    EchoScriptDraftGenerator,
    StubSceneTablePlanner,
)
from backend.app.ports import SceneTablePlanner, ScriptDraftGenerator

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
