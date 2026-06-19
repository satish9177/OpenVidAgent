"""Script draft asset use-cases.

``CreateScriptDraft`` persists caller-supplied draft text; ``GenerateScriptDraft``
first obtains that text from the ``ScriptDraftGenerator`` port (a deterministic
adapter or fake, never a real provider in this phase) and then composes
``CreateScriptDraft``. Both compose the ``RunRepository`` (lifecycle),
``StoragePort`` (durable bytes), and ``VersionedAssetRepository`` (version
index/metadata) ports and enforce the D7 script-draft rule in the application
layer, never in API routes. Generated drafts are tagged ``source="generated"`` to
distinguish them from manual (``source="manual"``) entries.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from uuid import uuid4

from backend.app.application.errors import (
    AssetCreationRejectedError,
    AssetNotFoundError,
    RunNotFoundError,
)
from backend.app.domain import AssetKind, Run, RunStatus, VersionedAsset
from backend.app.ports import (
    RunRepository,
    ScriptDraftGenerator,
    StoragePort,
    VersionedAssetRepository,
)

AssetIdFactory = Callable[[], str]

# D7: a new script draft is only allowed while the run is still being drafted.
# Anything at or past approval (or terminal) is rejected for now; revision after
# approval is out of scope for this phase.
_SCRIPT_DRAFT_ALLOWED = frozenset({RunStatus.CREATED, RunStatus.SCRIPT_READY})


class CreateScriptDraft:
    def __init__(
        self,
        run_repository: RunRepository,
        asset_repository: VersionedAssetRepository,
        storage: StoragePort,
        asset_id_factory: AssetIdFactory | None = None,
    ) -> None:
        self._run_repository = run_repository
        self._asset_repository = asset_repository
        self._storage = storage
        self._asset_id_factory = asset_id_factory or _new_asset_id

    def execute(
        self, run_id: str, text: str, source: str = "manual"
    ) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        if run.status not in _SCRIPT_DRAFT_ALLOWED:
            raise AssetCreationRejectedError(run_id, AssetKind.SCRIPT, run.status)

        version = self._asset_repository.next_version(run_id, AssetKind.SCRIPT)
        draft = VersionedAsset(
            asset_id=self._asset_id_factory(),
            kind=AssetKind.SCRIPT,
            version=version,
            uri="",
            metadata={"source": source},
        )
        stored = self._storage.save_asset(draft, _script_to_bytes(text))
        self._asset_repository.save(run_id, stored)

        # Only advance the lifecycle when the status actually changes (D7): a
        # second draft while already ``script_ready`` must NOT call a
        # self-transition, which the domain would reject.
        if run.status is RunStatus.CREATED:
            self._run_repository.save(run.mark_script_ready(text))

        return stored


class GenerateScriptDraft:
    """Generate a script draft from the run prompt, then persist and transition.

    Composes the ``ScriptDraftGenerator`` port (prompt + language -> draft text)
    with ``CreateScriptDraft``, which owns persistence, versioning, and the D7
    lifecycle transition. Prompt and language are read straight off the run
    aggregate so the values captured at intake reach the generator unchanged
    (D4/D5); the resulting asset is tagged ``source="generated"`` to set it apart
    from manually entered drafts.
    """

    def __init__(
        self,
        run_repository: RunRepository,
        script_generator: ScriptDraftGenerator,
        create_script_draft: CreateScriptDraft,
    ) -> None:
        self._run_repository = run_repository
        self._script_generator = script_generator
        self._create_script_draft = create_script_draft

    def execute(self, run_id: str) -> VersionedAsset:
        run = _require_run(self._run_repository, run_id)
        text = self._script_generator.generate(run.prompt, run.language)
        return self._create_script_draft.execute(run_id, text, source="generated")


class ListScriptDrafts:
    def __init__(self, asset_repository: VersionedAssetRepository) -> None:
        self._asset_repository = asset_repository

    def execute(self, run_id: str) -> Sequence[VersionedAsset]:
        return self._asset_repository.list_for_run(run_id, AssetKind.SCRIPT)


class GetLatestScriptDraft:
    def __init__(self, asset_repository: VersionedAssetRepository) -> None:
        self._asset_repository = asset_repository

    def execute(self, run_id: str) -> VersionedAsset:
        latest = self._asset_repository.get_latest(run_id, AssetKind.SCRIPT)
        if latest is None:
            raise AssetNotFoundError(run_id, AssetKind.SCRIPT)
        return latest


def _script_to_bytes(text: str) -> bytes:
    """Serialize script text to durable UTF-8 bytes (domain stays bytes-free)."""
    return text.encode("utf-8")


def _require_run(repository: RunRepository, run_id: str) -> Run:
    run = repository.get(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    return run


def _new_asset_id() -> str:
    return str(uuid4())
