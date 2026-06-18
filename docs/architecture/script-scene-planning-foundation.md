# Script and Scene Planning Foundation

Design document for the next phase. This records the intended design and slice
plan before any code is written. No backend, test, or product implementation is
part of this document.

## Goal

Make the run lifecycle meaningful by adding durable script draft assets and
scene table assets. The existing run lifecycle stays in place; this phase adds
versioned, durable assets around it.

## Target Workflow

```
create run
-> create script draft
-> script_ready
-> approve script
-> create scene table
-> scenes_ready
-> approve scenes
```

## Architecture Rule

Dependencies point inward:

`API/UI -> application use-cases -> domain models/services -> ports/interfaces -> infrastructure adapters`

The domain layer does not import FastAPI, databases, HTTP clients, SDKs, or
concrete providers. Lifecycle/transition rules live in application and domain,
never in API routes.

## Existing Foundation

This phase builds on code that already exists:

- `VersionedAsset` already exists in the domain (`asset_id`, `kind`, `version`,
  `uri`, `metadata`).
- `AssetKind` already includes `SCRIPT` and `SCENE_TABLE`.
- `SceneSpec` already exists in the domain (`scene_id`, `narration`,
  `visual_query`, `duration_seconds`).
- `StoragePort` already exists and supports bytes-based `save_asset` / `load_asset`.
- Run lifecycle and run API already exist (`RunStatus`, transition rules,
  `InvalidRunTransitionError`, `RunRepository`, `SQLiteRunRepository`,
  run use-cases, run routes).
- Architecture boundary tests already scan `application` and `api` imports, so
  new files in those layers inherit forbidden-import coverage automatically.

## Design Decisions

### D1. Asset-to-run association

- Keep `run_id` as a parameter on `VersionedAssetRepository` methods and as a
  SQLite metadata column.
- Do not add `run_id` to the domain `VersionedAsset`.
- Rationale: keeps `VersionedAsset` reusable and avoids blast radius into the
  provider ports (`StockProvider`, `TTSProvider`, `Renderer`) that already
  return `VersionedAsset` with no run context.

### D2. Existing Run script fields

- Do not migrate the existing `Run.script` / `Run.approved_script` fields in
  this phase.
- Add durable versioned assets alongside the existing lifecycle.
- Migration/refactor that unifies inline script with assets can be a separate
  later phase.

### D3. Scene table storage shape

- Store the scene table as one versioned JSON asset with `kind=SCENE_TABLE`.
- Do not add per-scene relational rows yet.

### D4. Serialization boundary

- Domain stays serialization-free.
- Application-layer helpers handle script text <-> UTF-8 bytes and
  `SceneSpec` <-> JSON bytes.
- Infrastructure handles only how bytes and metadata rows are persisted.

### D5. Storage URI and root

- Store relative URIs under an injected local storage root.
- SQLite stores asset metadata/index (`VersionedAssetRepository`).
- Local filesystem stores asset bytes (`StoragePort`).
- The storage root is injected, not read from a global, so tests can use a
  temporary directory.

### D6. API response shape

- Asset routes return metadata and/or parsed content responses.
- Do not implement raw byte streaming/download yet.

### D7. Asset creation and lifecycle transition

Use the adjusted product rule so an asset never exists in an inconsistent state
(for example, "a script draft exists but the run is still `created`"). The rule
keeps transition decisions in application/domain, not in API routes.

A subtle implementation note: a same-status case (for example, a second draft
while already `script_ready`) is **not** a domain transition. The use-case must
persist a new asset version **without** calling a transition method in that
case, because `script_ready -> script_ready` is not an allowed transition and
would raise `InvalidRunTransitionError`. Only call the domain transition when the
status actually advances.

#### `create_script_draft`

| Current run status | Behavior |
| --- | --- |
| `created` | Persist a new `SCRIPT` asset (version 1); transition `created -> script_ready`. |
| `script_ready` | Persist a new `SCRIPT` asset (next version); remain `script_ready` (no transition). |
| `script_approved` or later (`scenes_ready`, `scenes_approved`, `rendered`) | Reject the new draft for now (revision-after-approval is out of scope). |
| `failed` | Reject (terminal). |

#### `create_scene_table`

Requires `script_approved` or `scenes_ready`.

| Current run status | Behavior |
| --- | --- |
| `created`, `script_ready` | Reject; a scene table requires `script_approved` first. |
| `script_approved` | Persist a new `SCENE_TABLE` asset (version 1); transition `script_approved -> scenes_ready`. |
| `scenes_ready` | Persist a new `SCENE_TABLE` asset (next version); remain `scenes_ready` (no transition). |
| `scenes_approved` or later (`rendered`) | Reject the new scene table for now (revision-after-approval is out of scope). |
| `failed` | Reject (terminal). |

- Rejections raise an application-layer error (precise type finalized in Slice 4)
  rather than an HTTP error in the route.
- Rationale: avoids inconsistent states like "script draft exists but run is
  still `created`" while keeping transition rules in application/domain, not API.

## API Route Plan

Explicit, long route names. Do not use the shorter `/script` or `/scenes` names.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/runs/{run_id}/script-drafts` | Create a new script draft asset version (applies the D7 script rule). |
| `GET` | `/runs/{run_id}/script-drafts` | List script draft asset versions for the run. |
| `GET` | `/runs/{run_id}/script-drafts/latest` | Get the latest script draft asset for the run. |
| `POST` | `/runs/{run_id}/scene-tables` | Create a new scene table asset version (applies the D7 scene rule). |
| `GET` | `/runs/{run_id}/scene-tables` | List scene table asset versions for the run. |
| `GET` | `/runs/{run_id}/scene-tables/latest` | Get the latest scene table asset for the run. |

## Planned Slices

Implement one slice at a time, run tests after each, and review at the
checkpoints below. Slices 2 and 3 depend only on Slice 1 and the existing
`StoragePort`, so they are independent of each other and may be done in either
order.

### Slice 1: VersionedAssetRepository port + AssetNotFoundError

- **Goal:** Define the metadata/version-index port and the application error,
  with no infrastructure.
- **Files likely to change:**
  - `backend/app/ports/repositories.py` (add `VersionedAssetRepository` Protocol:
    `save(run_id, asset)`, `get_latest(run_id, kind)`, `list_for_run(run_id, kind)`,
    `next_version(run_id, kind)`).
  - `backend/app/ports/__init__.py` (export the port).
  - `backend/app/application/errors.py` (add `AssetNotFoundError`; add the
    creation-rejected error type used by D7).
- **Tests to add:** `tests/test_versioned_asset_repository_port.py` (a fake
  satisfies `isinstance(fake, VersionedAssetRepository)`; the port is
  `runtime_checkable`).
- **Architecture boundaries at risk:** Port must import domain only; no
  `sqlite3`, FastAPI, or infrastructure imports. `run_id` stays a method
  parameter (D1).
- **Out of scope:** Any persistence, filesystem, use-cases, or routes.
- **Acceptance criteria:** Port defined, exported, and `runtime_checkable`;
  errors defined; fake passes `isinstance`; existing boundary suite stays green.

### Slice 2: SQLiteVersionedAssetRepository + schema

- **Goal:** Implement the port on SQLite with versioning per `(run_id, kind)`.
- **Files likely to change:**
  - `backend/app/infrastructure/db/schema.sql` (add an `assets` table with
    `asset_id`, `run_id`, `kind`, `version`, `uri`, `metadata` JSON text;
    `UNIQUE(run_id, kind, version)`; index on `(run_id, kind)`).
  - `backend/app/infrastructure/db/sqlite_versioned_asset_repository.py` (new).
  - `backend/app/infrastructure/db/__init__.py` (export the adapter).
- **Tests to add:** `tests/test_sqlite_versioned_asset_repository.py` using a
  `tmp_path` database: save v1/v2 then `get_latest` returns v2; `list_for_run`
  is ordered; metadata round-trips; empty returns `None`/`[]`; rows isolate by
  `run_id`; `isinstance(..., VersionedAssetRepository)`.
- **Architecture boundaries at risk:** Infrastructure may import `sqlite3`,
  domain, and ports; must not import API or application. Metadata JSON
  (de)serialization stays inside the adapter (D4).
- **Out of scope:** Filesystem bytes, use-cases, routes.
- **Acceptance criteria:** Versioning and metadata round-trip on a temporary
  database; `get_latest` / `list_for_run` correct; `isinstance` against the port
  holds; boundary suite green.

### Slice 3: LocalFilesystemStorage

- **Goal:** Implement the existing `StoragePort` to write/read asset bytes under
  an injected root and populate `uri`.
- **Files likely to change:**
  - `backend/app/infrastructure/storage/__init__.py` and
    `local_filesystem_storage.py` (new package and adapter).
  - `backend/app/config/settings.py` (add a `storage_root` setting).
  - `.gitignore` (ignore newly generated asset directories with `.gitkeep`).
- **Tests to add:** `tests/test_local_filesystem_storage.py` using `tmp_path`:
  bytes round-trip; `uri` populated; deterministic path layout; missing file
  raises; `isinstance(..., StoragePort)`; UTF-8 and Windows path sanity.
- **Architecture boundaries at risk:** Infrastructure only; root injected via
  constructor (no global); no API/application import; path-traversal safety on
  `asset_id` and `kind`.
- **Out of scope:** SQLite metadata, use-cases, routes, media encoding,
  retention/cleanup.
- **Acceptance criteria:** Bytes round-trip on a temporary directory; `uri`
  populated; `isinstance` against `StoragePort` holds; ignore rules updated;
  boundary suite green.

### Slice 4: Script draft use-cases

- **Goal:** Add `CreateScriptDraft` (caller supplies the draft text; no LLM) and
  `GetLatestScript` / `ListScriptDrafts`, composing `RunRepository`,
  `StoragePort`, and `VersionedAssetRepository` and applying the D7 script rule.
- **Files likely to change:**
  - `backend/app/application/use_cases/script_assets.py` (new; UTF-8 text<->bytes
    helper per D4).
  - `backend/app/application/use_cases/__init__.py` (export).
  - `tests/fakes/repositories.py` (and a storage fake) to add
    `InMemoryVersionedAssetRepository` and `InMemoryStorage`.
- **Tests to add:** `tests/test_script_asset_use_cases.py` using fakes: draft v1
  from `created` transitions to `script_ready`; second draft increments version
  and remains `script_ready` (no transition); reject when `script_approved` or
  later; `RunNotFoundError` when the run is missing; `AssetNotFoundError` on get
  when none exists.
- **Architecture boundaries at risk:** Application depends on ports only; no
  `backend.app.infrastructure` import (already enforced by the existing
  application boundary test); serialization helper lives in application (D4);
  same-status case must avoid an illegal self-transition (D7); no FastAPI or
  `sqlite3`.
- **Out of scope:** LLM generation, revision-after-approval, routes.
- **Acceptance criteria:** D7 script rules enforced; versioning increments;
  correct errors; use-case `__init__` type hints reference port types; tests
  green with fakes.

### Slice 5: Scene table use-cases

- **Goal:** Add `CreateSceneTable` (accepts a sequence of `SceneSpec`) and
  `GetLatestSceneTable` / `ListSceneTables`, serializing to JSON bytes, storing a
  `SCENE_TABLE` versioned asset, and applying the D7 scene rule.
- **Files likely to change:**
  - `backend/app/application/use_cases/scene_assets.py` (new; pure
    `SceneSpec`<->JSON serializer per D4).
  - `backend/app/application/use_cases/__init__.py` (export).
- **Tests to add:** `tests/test_scene_asset_use_cases.py` using fakes: create
  from `script_approved` transitions to `scenes_ready`; second create increments
  version and remains `scenes_ready`; reject before `script_approved`; reject
  when `scenes_approved` or later; round-trip identity of the `SceneSpec` tuple
  including float `duration_seconds`; `RunNotFoundError` when the run is missing.
- **Architecture boundaries at risk:** `SceneSpec` stays pure (domain);
  serialization stays in application; ports-only dependencies; same-status case
  avoids an illegal self-transition (D7).
- **Out of scope:** LLM scene generation from the script, per-scene relational
  rows (D3), stock/voice, routes.
- **Acceptance criteria:** D7 scene rules enforced; round-trip fidelity;
  versioning increments; tests green with fakes.

### Slice 6: Thin API routes + composition wiring

- **Goal:** Expose the six asset routes and wire the new adapters into the
  composition root.
- **Files likely to change:**
  - `backend/app/api/assets.py` (new router with the routes from the API Route
    Plan; Pydantic request/response models with `from_*` classmethods mirroring
    `RunResponse`).
  - `backend/app/main.py` (extend `create_app(...)` to inject the versioned
    asset repository and storage; set them on `app.state`; initialize the
    storage root in lifespan; include the router).
  - `backend/app/config/settings.py` (`storage_root`, if not added in Slice 3).
- **Tests to add:** `tests/test_asset_api.py` using `TestClient` with injected
  fakes: `POST` script draft returns 201 with the asset payload; `GET` list and
  latest; `POST` scene table; `GET` list and latest; 404 when the run is missing;
  empty/404 when no asset exists yet; versioning across two `POST`s.
- **Architecture boundaries at risk:** Routes import application and ports only
  (enforced by the existing API boundary test; `assets.py` must import a
  use-case and must not import `backend.app.infrastructure`); no
  lifecycle/versioning logic in routes; only `main.py` imports infrastructure;
  use the long route names.
- **Out of scope:** Raw byte streaming/download (D6), auth, pagination,
  frontend.
- **Acceptance criteria:** All six endpoints return correct status codes and
  payloads with fakes; `create_app` dependency injection extended; route import
  boundary clean; tests green.

### Slice 7: Boundary hardening + phase audit

- **Goal:** Lock the new surface into the boundary safety net and confirm
  hygiene before commit.
- **Files likely to change:**
  - `tests/test_architecture_boundaries.py` (assert the new port resolves to
    `backend.app.ports`; new use-cases' `__init__` hints are port types; the
    assets route imports no infrastructure).
  - `.gitignore` (confirm generated asset directories, database, and secrets are
    ignored).
- **Tests to add:** The boundary assertions above; a full `pytest -q` run is
  green.
- **Architecture boundaries at risk:** This slice is the safety net; guard
  against infrastructure leaking into application/api and against generated
  artifacts being tracked.
- **Out of scope:** Everything in the phase-wide out-of-scope list below.
- **Acceptance criteria:** All boundary tests and the full suite are green;
  ignore rules correct; phase-auditor criteria satisfied.

## Agent Checkpoints

- **architecture-reviewer after Slice 1:** Ratify D1 (run_id placement) and the
  port contract before adapters are built on it.
- **architecture-reviewer after Slice 3:** Both infrastructure adapters present;
  verify infrastructure depends only on domain/ports.
- **architecture-reviewer after Slice 6:** Highest-risk slice (routes plus
  composition root); confirm routes call use-cases only and infrastructure lives
  solely in `main.py`.
- **test-debugger:** Only when tests fail non-obviously (likely spots: Slice 2
  unique/version constraints, Slice 3 Windows path/UTF-8 round-trip, Slice 5
  float JSON round-trip, Slice 6 `TestClient` dependency wiring).
- **phase-auditor before commit at Slice 7:** Verify all acceptance criteria,
  the full suite is green, and database/secrets/generated media are ignored.

## Phase-Wide Out of Scope

Not implemented in this phase:

- Real LLM calls, Pexels, Edge TTS, Sarvam, ElevenLabs, FFmpeg.
- Stock search, subtitles, background workers, frontend.
- Full pipeline orchestrator, AI video generation, actor dialogue, lip-sync.
- Migrating the existing `Run` script fields (D2).
- Per-scene relational rows (D3).
- Raw byte streaming/download (D6).
- Revision-after-approval for scripts or scene tables (D7).
