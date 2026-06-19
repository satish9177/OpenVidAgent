"""Source-level checks for Clean Architecture boundaries."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import get_type_hints

from backend.app.application.use_cases import (
    ApproveScenes,
    ApproveScript,
    CreateClipCandidateSet,
    CreateRun,
    CreateSceneTable,
    CreateScriptDraft,
    CreateStockPlan,
    GenerateSceneTable,
    GenerateScriptDraft,
    GenerateStockPlan,
    GetLatestClipCandidateSet,
    GetLatestSceneTable,
    GetLatestScriptDraft,
    GetLatestStockPlan,
    GetRun,
    ListSceneTables,
    ListScriptDrafts,
    ListClipCandidateSets,
    ListStockPlans,
    MarkFailed,
    MarkScenesReady,
    MarkScriptReady,
    RetrieveClipCandidates,
)
from backend.app.ports import (
    ClipRetrievalProvider,
    Renderer,
    RunRepository,
    SceneTablePlanner,
    ScriptDraftGenerator,
    StockClipPlanner,
    StockProvider,
    StoragePort,
    SubtitleBuilder,
    TTSProvider,
    VersionedAssetRepository,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = PROJECT_ROOT / "backend" / "app"


def test_domain_has_no_framework_or_outer_layer_imports() -> None:
    forbidden = {
        "backend.app.api",
        "backend.app.application",
        "backend.app.config",
        "backend.app.infrastructure",
        "backend.app.ports",
        "fastapi",
        "httpx",
        "requests",
        "sqlalchemy",
        "sqlite",
        "sqlite3",
        "os",
        "pathlib",
        "subprocess",
        "openai",
        "anthropic",
        "google",
        "cohere",
        "mistralai",
        "ffmpeg",
        "moviepy",
    }

    for path in _python_files(APP_ROOT / "domain"):
        imports = _imports_for(path)
        assert not _matching_imports(imports, forbidden), path


def test_application_does_not_import_infrastructure() -> None:
    forbidden = {"backend.app.infrastructure"}

    for path in _python_files(APP_ROOT / "application"):
        imports = _imports_for(path)
        assert not _matching_imports(imports, forbidden), path


def test_api_routes_depend_on_use_cases_not_infrastructure() -> None:
    route_files = [
        path
        for path in _python_files(APP_ROOT / "api")
        if path.name != "__init__.py"
    ]

    assert route_files

    for path in route_files:
        imports = _imports_for(path)
        assert _matching_imports(imports, {"backend.app.application"}), path
        assert not _matching_imports(imports, {"backend.app.infrastructure"}), path


def test_provider_interfaces_live_in_ports() -> None:
    providers = (
        ScriptDraftGenerator,
        SceneTablePlanner,
        StockClipPlanner,
        ClipRetrievalProvider,
        StockProvider,
        TTSProvider,
        SubtitleBuilder,
        Renderer,
    )

    for provider in providers:
        assert inspect.getmodule(provider).__name__ == "backend.app.ports.providers"


def test_run_use_cases_depend_on_run_repository_port() -> None:
    use_cases = (
        ApproveScenes,
        ApproveScript,
        CreateRun,
        GetRun,
        MarkFailed,
        MarkScenesReady,
        MarkScriptReady,
    )

    for use_case in use_cases:
        hints = get_type_hints(use_case.__init__)
        assert hints["repository"] is RunRepository


def test_asset_ports_live_in_ports() -> None:
    for port in (VersionedAssetRepository, StoragePort):
        assert (
            inspect.getmodule(port).__name__ == "backend.app.ports.repositories"
        )


def test_asset_use_cases_depend_only_on_port_types() -> None:
    expected: dict[type, dict[str, type]] = {
        CreateScriptDraft: {
            "run_repository": RunRepository,
            "asset_repository": VersionedAssetRepository,
            "storage": StoragePort,
        },
        ListScriptDrafts: {"asset_repository": VersionedAssetRepository},
        GetLatestScriptDraft: {"asset_repository": VersionedAssetRepository},
        CreateSceneTable: {
            "run_repository": RunRepository,
            "asset_repository": VersionedAssetRepository,
            "storage": StoragePort,
        },
        ListSceneTables: {"asset_repository": VersionedAssetRepository},
        GetLatestSceneTable: {
            "asset_repository": VersionedAssetRepository,
            "storage": StoragePort,
        },
    }

    for use_case, port_hints in expected.items():
        hints = get_type_hints(use_case.__init__)
        for name, port in port_hints.items():
            assert hints[name] is port, (use_case.__name__, name)


def test_stock_asset_use_cases_depend_only_on_expected_ports_and_factories() -> None:
    expected: dict[type, dict[str, object]] = {
        CreateStockPlan: {
            "run_repository": RunRepository,
            "asset_repository": VersionedAssetRepository,
            "storage": StoragePort,
            "asset_id_factory": Callable[[], str] | None,
        },
        ListStockPlans: {"asset_repository": VersionedAssetRepository},
        GetLatestStockPlan: {
            "asset_repository": VersionedAssetRepository,
            "storage": StoragePort,
        },
        CreateClipCandidateSet: {
            "run_repository": RunRepository,
            "asset_repository": VersionedAssetRepository,
            "storage": StoragePort,
            "asset_id_factory": Callable[[], str] | None,
        },
        ListClipCandidateSets: {"asset_repository": VersionedAssetRepository},
        GetLatestClipCandidateSet: {
            "asset_repository": VersionedAssetRepository,
            "storage": StoragePort,
        },
    }

    for use_case, constructor_hints in expected.items():
        hints = get_type_hints(use_case.__init__)
        hints.pop("return", None)
        assert hints == constructor_hints, use_case.__name__


def test_assets_route_imports_use_cases_not_infrastructure() -> None:
    imports = _imports_for(APP_ROOT / "api" / "assets.py")

    assert _matching_imports(imports, {"backend.app.application"})
    assert not _matching_imports(imports, {"backend.app.infrastructure"})


def test_stub_stock_clip_planner_import_confined_to_composition_root() -> None:
    allowed = APP_ROOT / "main.py"
    offenders: list[Path] = []

    for path in _python_files(APP_ROOT):
        relative_parts = path.relative_to(APP_ROOT).parts
        if "infrastructure" in relative_parts:
            continue
        if path == allowed:
            continue
        if _imports_symbol(
            path,
            module_prefix="backend.app.infrastructure.generation",
            symbol="StubStockClipPlanner",
        ):
            offenders.append(path)

    assert not offenders


def test_stub_clip_retrieval_provider_import_confined_to_composition_root() -> None:
    allowed = APP_ROOT / "main.py"
    offenders: list[Path] = []

    for path in _python_files(APP_ROOT):
        relative_parts = path.relative_to(APP_ROOT).parts
        if "infrastructure" in relative_parts:
            continue
        if path == allowed:
            continue
        if _imports_symbol(
            path,
            module_prefix="backend.app.infrastructure.generation",
            symbol="StubClipRetrievalProvider",
        ):
            offenders.append(path)

    assert not offenders


def test_generation_use_cases_depend_on_ports_and_create_use_cases() -> None:
    expected: dict[type, dict[str, type]] = {
        GenerateScriptDraft: {
            "run_repository": RunRepository,
            "script_generator": ScriptDraftGenerator,
            "create_script_draft": CreateScriptDraft,
        },
        GenerateSceneTable: {
            "run_repository": RunRepository,
            "scene_planner": SceneTablePlanner,
            "create_scene_table": CreateSceneTable,
        },
        GenerateStockPlan: {
            "run_repository": RunRepository,
            "stock_planner": StockClipPlanner,
            "get_latest_scene_table": GetLatestSceneTable,
            "create_stock_plan": CreateStockPlan,
        },
        RetrieveClipCandidates: {
            "run_repository": RunRepository,
            "clip_retrieval_provider": ClipRetrievalProvider,
            "get_latest_stock_plan": GetLatestStockPlan,
            "create_clip_candidate_set": CreateClipCandidateSet,
        },
    }

    for use_case, constructor_hints in expected.items():
        hints = get_type_hints(use_case.__init__)
        hints.pop("return", None)
        # Exactly these dependencies: the run repository and generation port,
        # plus the sibling Create use-case it composes -- never a concrete
        # infrastructure type.
        assert hints == constructor_hints, use_case.__name__


def test_generation_adapters_import_no_api_application_or_external_modules() -> None:
    forbidden = {
        "backend.app.api",
        "backend.app.application",
        "openai",
        "anthropic",
        "google",
        "cohere",
        "mistralai",
        "httpx",
        "requests",
        "urllib",
        "aiohttp",
        "socket",
        "subprocess",
        "ffmpeg",
        "moviepy",
    }

    generation_files = _python_files(APP_ROOT / "infrastructure" / "generation")
    assert generation_files

    for path in generation_files:
        imports = _imports_for(path)
        assert not _matching_imports(imports, forbidden), path


def _python_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def _imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    return imports


def _imports_symbol(path: Path, module_prefix: str, symbol: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == module_prefix or node.module.startswith(
                f"{module_prefix}."
            ):
                if any(alias.name == symbol for alias in node.names):
                    return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if (
                    alias.name == f"{module_prefix}.{symbol}"
                    or alias.name.endswith(f".{symbol}")
                ):
                    return True

    return False


def _matching_imports(imports: set[str], forbidden: set[str]) -> set[str]:
    return {
        imported
        for imported in imports
        for prefix in forbidden
        if imported == prefix or imported.startswith(f"{prefix}.")
    }
