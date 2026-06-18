"""Source-level checks for Clean Architecture boundaries."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import get_type_hints

from backend.app.application.use_cases import (
    ApproveScenes,
    ApproveScript,
    CreateRun,
    CreateSceneTable,
    CreateScriptDraft,
    GetLatestSceneTable,
    GetLatestScriptDraft,
    GetRun,
    ListSceneTables,
    ListScriptDrafts,
    MarkFailed,
    MarkScenesReady,
    MarkScriptReady,
)
from backend.app.ports import (
    LLMProvider,
    Renderer,
    RunRepository,
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
    providers = (LLMProvider, StockProvider, TTSProvider, SubtitleBuilder, Renderer)

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


def test_assets_route_imports_use_cases_not_infrastructure() -> None:
    imports = _imports_for(APP_ROOT / "api" / "assets.py")

    assert _matching_imports(imports, {"backend.app.application"})
    assert not _matching_imports(imports, {"backend.app.infrastructure"})


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


def _matching_imports(imports: set[str], forbidden: set[str]) -> set[str]:
    return {
        imported
        for imported in imports
        for prefix in forbidden
        if imported == prefix or imported.startswith(f"{prefix}.")
    }
