# Stock Clip Planning Foundation

Design document for the next phase. This records the intended design and slice
plan before any code is written. No backend, test, or product implementation is
part of this document.

## Goal

Given an approved scene table, produce a durable, versioned stock-clip planning
artifact per run. The artifact answers, for each scene: what stock-video search
query or visual need should a later phase use to fetch clips? This phase plans
only. It does not call any real provider, download any clip, or render anything.

## Target Workflow

A new tail is appended to the existing prompt -> script -> scenes workflow. The
run reaches `scenes_approved` exactly as today; stock planning then runs as an
asset-only step that does not move the lifecycle.

```
create run
-> generate script draft
-> approve script
-> generate scene table
-> approve scenes                 # run reaches scenes_approved
-> generate stock plan            # NEW: reads latest scene table,
                                  # plans queries, persists a STOCK_PLAN asset,
                                  # run STAYS at scenes_approved (asset-only)
```

## Architecture Rule

Dependencies point inward:

`API/UI -> application use-cases -> domain models/services -> ports/interfaces -> infrastructure adapters`

The domain layer does not import FastAPI, databases, HTTP clients, SDKs, or
concrete providers. Lifecycle/transition rules live in application and domain,
never in API routes. The planner is a port with a deterministic local adapter;
it does not know any real provider.

## Existing Foundation

This phase builds on code that already exists, confirmed by reading the source:

- `VersionedAsset` already exists in the domain (`asset_id`, `kind`, `version`,
  `uri`, `metadata`); `metadata` is `Mapping[str, str]`.
- `AssetKind` already includes `SCRIPT`, `SCENE_TABLE`, and `STOCK_CLIP`.
  `STOCK_CLIP` is the downloaded clip (a later phase) and is distinct from the
  `STOCK_PLAN` this phase adds.
- `SceneSpec` already exists in the domain (`scene_id`, `narration`,
  `visual_query`, `duration_seconds`). Its `visual_query` is a natural seed for
  the planner.
- A `StockProvider` port already exists for fetching clips (a later phase). It is
  distinct from the `StockClipPlanner` planning port this phase adds.
- `RunStatus` is `created -> script_ready -> script_approved -> scenes_ready ->
  scenes_approved -> rendered` (plus `failed`). `scenes_approved` only transitions
  to `rendered`/`failed`.
- `GetLatestSceneTable` already parses the latest `SCENE_TABLE` asset into a
  `SceneTable(asset, scenes)` read model in the application layer.
- Persistence is kind-agnostic, so a new `AssetKind` needs no infrastructure or
  schema change:
  - SQLite `assets.kind` is `TEXT NOT NULL` with no CHECK constraint;
    `UNIQUE (run_id, kind, version)` and the `(run_id, kind)` index are generic.
  - `LocalFilesystemStorage` derives paths as `{kind}/{asset_id}/v{version}`.
  - The in-memory fakes key on `(run_id, kind)` generically.
- `.gitignore` already ignores `data/assets/*` (keeping `.gitkeep`), so
  `data/assets/stock_plan/*` is already covered.
- Architecture boundary tests already scan `application` and `api` imports and
  the `infrastructure/generation` package, so new files in those layers inherit
  forbidden-import coverage automatically.

## Answers to Design Questions

| # | Question | Decision |
| --- | --- | --- |
| 1 | New `AssetKind.STOCK_PLAN`? | Yes (D8). Distinct from `STOCK_CLIP`. |
| 2 | New `RunStatus`, or asset-only? | Asset-only; no new status; gated at `scenes_approved` (D9). |
| 3 | Domain model for the plan? | `StockQuerySpec`; plan is a sequence; app-level `StockPlan` read model; no `StockClipPlan` wrapper (D10). |
| 4 | Planner reads `SceneSpec` or raw text? | `SceneSpec` objects (D11). |
| 5 | Use-case loads latest scene table, or scenes passed in? | Loads latest via existing read path; status checked first (D12). |
| 6 | Real Pexels/Pixabay/stock APIs? | No (out of scope). |
| 7 | Download clips? | No (out of scope). |
| 8 | Render video? | No (out of scope). |
| + | Manual POST? | No this phase; generate-only public API (D13). |

## Design Decisions

These decisions are locked for this phase and continue the project decision log
(D1-D7 are recorded in the script/scene planning foundation document and in
code).

### D8. Add `AssetKind.STOCK_PLAN`

- Add `STOCK_PLAN = "stock_plan"` to `AssetKind`.
- It represents stock-video search intent, separate from `STOCK_CLIP`, which
  represents fetched media bytes (a later phase).
- No SQLite, storage, schema, or `.gitignore` change is required: persistence is
  kind-agnostic (see Existing Foundation), and stock-plan bytes land under
  `data/assets/stock_plan/...`, already covered by the `data/assets/*` ignore.

### D9. Asset-only; no new `RunStatus`; allowed only at `scenes_approved`

- Stock planning persists a versioned asset and does not change `RunStatus`.
- The allowed-status guard is `{scenes_approved}`. This matches the target
  workflow, where approving scenes precedes stock-plan generation.
- The use-case never calls a domain transition method. Regenerating a plan while
  `scenes_approved` simply persists the next version and stays `scenes_approved`
  (mirrors the same-status, no-transition rule established in D7).
- Rejection in any other status reuses the existing `AssetCreationRejectedError`
  (mapped to HTTP 409 by the existing handler) with `kind = stock_plan`.
- Rationale: the current map only allows `scenes_approved -> rendered/failed`;
  inserting a planning status would be premature lifecycle expansion. The run
  sits at `scenes_approved` accumulating plan versions until a future
  download/render phase fires the transition.

### D10. Add `StockQuerySpec` as the domain model; no `StockClipPlan` wrapper

- Add a frozen domain dataclass:

  ```python
  @dataclass(frozen=True)
  class StockQuerySpec:
      scene_id: str
      query: str                       # stock-video search query
      visual_intent: str               # what the viewer should see / why
      duration_seconds: float
      provider_hint: str | None = None # stays None in the deterministic adapter
  ```

- The "plan" is an ordered `Sequence[StockQuerySpec]` persisted as one versioned
  JSON asset with `kind = STOCK_PLAN` (mirrors the D3 scene-table storage shape).
- Add an application-layer `StockPlan` read model, a `NamedTuple(asset, queries)`
  mirroring `SceneTable`. Do not add a `StockClipPlan` domain wrapper: the scene
  table is handled with `SceneSpec` plus an app-level `SceneTable` read model and
  no `SceneTablePlan` wrapper. Symmetry plus YAGNI; a wrapper can be added later
  if plan-level fields appear.
- `provider_hint` stays `None` in the deterministic adapter. The planner must not
  know any real provider; provider selection belongs to `StockProvider` in a
  later phase. This preserves the architecture boundary.

### D11. `StockClipPlanner` reads `SceneSpec` objects, not raw text

- Define the port in `backend/app/ports/providers.py` alongside the other
  provider ports:

  ```python
  @runtime_checkable
  class StockClipPlanner(Protocol):
      def plan_stock_clips(
          self, scenes: Sequence[SceneSpec], language: str
      ) -> Sequence[StockQuerySpec]: ...
  ```

- Structured `SceneSpec` input avoids re-parsing text and keeps the planner
  aligned with the upstream scene-table contract.

### D12. `GenerateStockPlan` loads the latest scene table via the existing read path; status checked before the scene read

- `GenerateStockPlan` composes the existing `GetLatestSceneTable` use-case to
  obtain scenes. The API calls one use-case with only `run_id`; scenes are not
  passed in the request and storage is not re-parsed.
- Ordering: the D9 status guard is checked before the scene-table read. An
  invalid status therefore yields a clean 409 (`AssetCreationRejectedError`)
  rather than a misleading 404 from the scene-table reader, and no planner work
  happens on a doomed request.
- The canonical guard lives in `CreateStockPlan` (the persistence use-case), so
  any future manual path is guarded too; `GenerateStockPlan` performs the same
  status check up front to enforce the ordering above. This small, intentional
  duplication is a consequence of the read-before-create flow and is tested on
  both paths.

### D13. Generate-only public API; no manual `POST /stock-plans` this phase

- Expose only `POST .../stock-plans/generate`, `GET .../stock-plans`, and
  `GET .../stock-plans/latest`.
- `CreateStockPlan` exists as the internal persistence use-case (composed by
  `GenerateStockPlan`, holding the canonical D9 guard), mirroring
  `CreateSceneTable`, but is not wired to a manual `POST .../stock-plans` route in
  this phase.
- Rationale: keep the HTTP surface minimal. Adding the manual route later is a
  trivial, symmetric one-route change.

## API Route Plan

Explicit, long route names, consistent with the existing asset routes.

| Method | Path | Returns | Purpose |
| --- | --- | --- | --- |
| `POST` | `/runs/{run_id}/stock-plans/generate` | `201` `AssetResponse` | Plan from the latest scene table; persist a `STOCK_PLAN` asset (next version, `source=generated`). Applies the D9 rule. |
| `GET` | `/runs/{run_id}/stock-plans` | `list[AssetResponse]` | List stock-plan asset versions for the run. |
| `GET` | `/runs/{run_id}/stock-plans/latest` | `StockPlanResponse` | Get the latest stock-plan asset plus its parsed `queries` (mirrors `SceneTableResponse`). |

New API models in `assets.py`: `StockQuerySpecModel` (`to_domain` / `from_domain`),
`StockPlanResponse` (`from_stock_plan`), and a `get_stock_planner` dependency
resolver. No manual create request model this phase (D13). No raw byte download
(D6).

## Planned Slices

Implement one slice at a time, run tests after each, and review at the
checkpoints below. Strict inward-to-outward order: domain, then port, then
adapter and use-cases, then API and wiring, then boundary hardening.

### Slice 1: Domain - `AssetKind.STOCK_PLAN` + `StockQuerySpec`

- **Goal:** Add the new asset kind and the pure `StockQuerySpec` dataclass.
- **Files likely to change:**
  - `backend/app/domain/models.py` (add `AssetKind.STOCK_PLAN`; add the frozen
    `StockQuerySpec` dataclass).
  - `backend/app/domain/__init__.py` (export `StockQuerySpec`).
- **Tests to add:** `tests/test_stock_query_spec.py` - `AssetKind.STOCK_PLAN.value
  == "stock_plan"`; `StockQuerySpec` is frozen; `provider_hint` defaults to
  `None`.
- **Architecture boundaries at risk:** Domain stays framework-free (auto-covered
  by `test_domain_has_no_framework_or_outer_layer_imports`).
- **Out of scope:** No `StockClipPlan` wrapper (D10); no serialization (that is
  the application layer).
- **Acceptance criteria:** Kind and dataclass added and exported; domain boundary
  test green.

### Slice 2: Port - `StockClipPlanner`

- **Goal:** Define the planner Protocol (reads `SceneSpec`, returns
  `StockQuerySpec`).
- **Files likely to change:**
  - `backend/app/ports/providers.py` (add the `StockClipPlanner` Protocol per
    D11).
  - `backend/app/ports/__init__.py` (export the port).
- **Tests to add:** `tests/test_stock_clip_planner_port.py` - a fake satisfies
  `isinstance(fake, StockClipPlanner)` (the port is `runtime_checkable`). Mirrors
  `tests/test_versioned_asset_repository_port.py`.
- **Architecture boundaries at risk:** Port imports domain only; no `sqlite3`,
  FastAPI, SDK, or infrastructure imports.
- **Out of scope:** Adapter, use-cases, routes.
- **Acceptance criteria:** Port defined, exported, and `runtime_checkable`;
  `isinstance` holds; boundary suite green.

### Slice 3: Deterministic adapter - `StubStockClipPlanner`

- **Goal:** Implement the port deterministically. Map each `SceneSpec` to one
  `StockQuerySpec`: `query` from `scene.visual_query`, `visual_intent` from
  `scene.narration`, `duration_seconds` copied, `provider_hint = None`. No
  randomness, network, provider SDK, or subprocess.
- **Files likely to change:**
  - `backend/app/infrastructure/generation/stub_stock_clip_planner.py` (new;
    named for symmetry with `StubSceneTablePlanner`).
  - `backend/app/infrastructure/generation/__init__.py` (export the adapter).
- **Tests to add:** Extend `tests/test_generation_adapters.py` - deterministic,
  repeatable output; one query per scene; field derivation as above;
  `provider_hint is None`.
- **Architecture boundaries at risk:** Auto-covered by
  `test_generation_adapters_import_no_api_application_or_external_modules` (no
  api/application/SDK/network/subprocess imports).
- **Out of scope:** Real providers; any provider knowledge in `provider_hint`.
- **Acceptance criteria:** Deterministic mapping; `isinstance` against the port
  holds; generation-import boundary test green.

### Slice 4: Application - stock-plan use-cases

- **Goal:** Add `CreateStockPlan` (persist queries as one `STOCK_PLAN` JSON asset;
  enforce the D9 guard; no transition), `GenerateStockPlan` (compose
  `GetLatestSceneTable` + `StockClipPlanner` + `CreateStockPlan`, guard before the
  scene read per D12), `ListStockPlans`, `GetLatestStockPlan`, the `StockPlan`
  read model, and the `StockQuerySpec` <-> JSON serializer (application layer per
  D4).
- **Files likely to change:**
  - `backend/app/application/use_cases/stock_assets.py` (new).
  - `backend/app/application/use_cases/__init__.py` (export).
  - `tests/fakes/providers.py` (add `FakeStockClipPlanner`).
  - `tests/fakes/__init__.py` (export the fake).
- **Tests to add:** `tests/test_stock_asset_use_cases.py` and
  `tests/test_generate_stock_plan_use_case.py` (mirror the scene-table use-case
  tests, using a `_RecordingStockClipPlanner` spy):
  - forwards `(scenes, language)` to the planner; scenes come from the latest
    scene table (seed one in the fakes);
  - persists a `STOCK_PLAN` asset tagged `source=generated`; a second generate
    increments to version 2; status stays `scenes_approved` (no transition);
  - round-trip identity of the `StockQuerySpec` tuple including float
    `duration_seconds` and `provider_hint = None`;
  - `RunNotFoundError` when the run is missing (planner not called, nothing
    persisted);
  - D9 guard rejects every status other than `scenes_approved` with
    `AssetCreationRejectedError` (`kind = STOCK_PLAN`), checked before the scene
    read and before planning/persistence (so 409, not 404);
  - `GetLatestStockPlan` raises `AssetNotFoundError(STOCK_PLAN)` when none exists;
    `ListStockPlans` is ordered.
- **Architecture boundaries at risk:** Application depends on ports and sibling
  use-cases only; no `backend.app.infrastructure` import (enforced by the existing
  application boundary test); serializer stays in application (D4); no transition
  call (D9).
- **Out of scope:** Routes, real provider, download.
- **Acceptance criteria:** D9 enforced; versioning increments; round-trip
  fidelity; correct errors; use-case `__init__` type hints reference port and
  sibling use-case types; tests green with fakes.

### Slice 5: API routes + composition wiring

- **Goal:** Expose the three stock-plan routes and wire `StubStockClipPlanner`
  into the composition root.
- **Files likely to change:**
  - `backend/app/api/assets.py` (add `StockQuerySpecModel`, `StockPlanResponse`,
    a `get_stock_planner` resolver, and the three routes from the API Route Plan).
  - `backend/app/main.py` (add a `stock_planner` parameter to `create_app`,
    default `StubStockClipPlanner()`, set `app.state.stock_planner`). The adapter
    is pure/deterministic, so it does not affect the database/storage lifespan
    decision, consistent with the existing generators.
- **Tests to add:** Extend `tests/test_asset_api.py` (or add
  `tests/test_stock_plan_api.py`) using `TestClient` with injected fakes:
  `POST .../generate` returns 201 with `kind=stock_plan`, `version=1`,
  `source=generated`; `GET` list; `GET` latest returns parsed `queries`; 404 when
  the run is missing; 409 when status is not `scenes_approved`; versioning across
  two generates.
- **Architecture boundaries at risk:** Routes import application and ports only
  (enforced by `test_assets_route_imports_use_cases_not_infrastructure`); no
  lifecycle/versioning logic in routes; the adapter is imported only in
  `main.py`; long route names.
- **Out of scope:** Manual POST (D13), raw byte download (D6), auth, pagination,
  frontend.
- **Acceptance criteria:** The three endpoints return correct status codes and
  payloads with fakes; `create_app` dependency injection extended; route import
  boundary clean; tests green.

### Slice 6: Boundary hardening + end-to-end + phase audit

- **Goal:** Lock the new surface into the boundary safety net, extend the
  end-to-end happy path, and confirm hygiene before commit.
- **Files likely to change:**
  - `tests/test_architecture_boundaries.py` (assert `StockClipPlanner` resolves
    to `backend.app.ports.providers`; the new use-cases' `__init__` hints are the
    expected port/use-case types; the assets route imports no infrastructure).
  - `tests/test_draft_planning_workflow.py` (extend the happy path: after
    approve-scenes, `POST .../stock-plans/generate` returns 201 and
    `GET .../stock-plans/latest` shows non-empty `queries`) or a new
    `tests/test_stock_planning_workflow.py`.
  - `.gitignore` (confirm `data/assets/stock_plan/*` is covered; expected no
    change since `data/assets/*` already covers it).
- **Tests to add:** The boundary assertions above; the extended or new workflow
  test; a full `pytest -q` run is green.
- **Architecture boundaries at risk:** This slice is the safety net; guard
  against infrastructure leaking into application/api and against generated
  artifacts being tracked.
- **Out of scope:** Everything in the phase-wide out-of-scope list below.
- **Acceptance criteria:** All boundary tests and the full suite are green; ignore
  rules correct; phase-auditor criteria satisfied.

## Slice Order and Dependencies

```
1 (domain) -> 2 (port) -> +-> 3 (stub adapter) -+
                          +-> 4 (use-cases) ----+-> 5 (API + wiring) -> 6 (hardening + E2E + audit)
```

Slices 3 and 4 are independent: the use-case tests rely on `FakeStockClipPlanner`,
not the stub adapter. Do Slice 3 before Slice 4 only so the default adapter exists
when wiring in Slice 5. Everything else is strictly sequential.

## Agent Checkpoints

- **architecture-reviewer after Slice 2:** Ratify the port contract and D11 (reads
  `SceneSpec`) before the adapter and use-cases build on it.
- **architecture-reviewer after Slice 4:** Confirm ports-only dependencies, the
  guard-before-read ordering (D9/D12), no transition call, the serializer living
  in the application layer (D4), and no infrastructure import.
- **architecture-reviewer after Slice 5:** Highest-risk slice (routes plus
  composition root); confirm routes call use-cases only, the adapter lives solely
  in `main.py`, and no lifecycle/versioning logic leaked into routes.
- **test-debugger:** Only when tests fail non-obviously. Likely spots: Slice 4
  float and `provider_hint = None` JSON round-trip and the 409-vs-404 guard
  ordering; Slice 5 `TestClient` wiring of the new planner; Slice 6
  `get_type_hints` exact-equality on the new use-cases.
- **phase-auditor before commit at Slice 6:** Verify all acceptance criteria, that
  the full suite is green, that the database, secrets, and generated assets are
  ignored, and that no out-of-scope work leaked in (no real provider, no download,
  no render).

## Phase-Wide Out of Scope

Not implemented in this phase:

- Real Pexels API.
- Real Pixabay API.
- Any real stock provider API.
- Clip download and file/cache.
- FFmpeg and rendering.
- Subtitles.
- Voice/TTS.
- Workers/queues.
- Frontend.
- Auth.
- Pagination.
- Full-pipeline orchestration.
- AI video generation.
- Actor dialogue and lip-sync.
- A new `RunStatus` (D9).
- A `StockClipPlan` domain wrapper (D10).
- A manual `POST /runs/{run_id}/stock-plans` route (D13).
- Raw byte streaming/download (D6).
