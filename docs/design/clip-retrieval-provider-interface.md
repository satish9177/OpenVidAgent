# Clip Retrieval Provider Interface

Design document for the next phase. This records the intended design and slice
plan before any code is written. No backend, test, or product implementation is
part of this document. The approved direction is to mirror the stock-clip
planning slice 1:1: stock planning turns scenes into `StockQuerySpec`; this
phase turns `StockQuerySpec` into `ClipCandidate` through a provider port.

## Goal

Given the latest stock plan for a run, produce a durable, versioned set of
candidate stock-clip search results per run. The artifact answers, for each
planned query: what candidate clips would a real provider return, as metadata
(title, preview/source URLs, duration, dimensions)? This phase introduces the
retrieval abstraction only. It does not call any real provider, perform any
network request, download any clip, store any media bytes, rank candidates, or
let a user select a clip.

## Target Workflow

A new tail is appended to the existing prompt -> script -> scenes -> stock-plan
workflow. The run reaches `scenes_approved` exactly as today; stock planning and
clip retrieval then run as asset-only steps that do not move the lifecycle.

```
create run
-> generate script draft
-> approve script
-> generate scene table
-> approve scenes                 # run reaches scenes_approved
-> generate stock plan            # reads latest scene table, persists STOCK_PLAN
                                  # run STAYS at scenes_approved (asset-only)
-> retrieve clip candidates       # NEW: reads latest STOCK_PLAN, calls the
                                  # ClipRetrievalProvider per StockQuerySpec,
                                  # persists a CLIP_CANDIDATES asset,
                                  # run STAYS at scenes_approved (asset-only)
```

## Architecture Rule

Dependencies point inward:

`API/UI -> application use-cases -> domain models/services -> ports/interfaces -> infrastructure adapters`

The domain layer does not import FastAPI, databases, HTTP clients, SDKs, or
concrete providers. The application layer does not import infrastructure. The
provider is a port with a deterministic local adapter; it does not know any real
provider, perform network I/O, or download media. Lifecycle/transition rules
live in application and domain, never in API routes.

## Existing Foundation

This phase builds on code that already exists, confirmed by reading the source:

- `VersionedAsset` already exists in the domain (`asset_id`, `kind`, `version`,
  `uri`, `metadata`); `metadata` is `Mapping[str, str]`.
- `AssetKind` already includes `SCRIPT`, `SCENE_TABLE`, `STOCK_PLAN`,
  `STOCK_CLIP`, `VOICE`, `SUBTITLE`, `RENDER`. `STOCK_CLIP` is the downloaded
  clip (a later phase) and is distinct from the `CLIP_CANDIDATES` this phase
  adds.
- `StockQuerySpec` already exists in the domain (`scene_id`, `query`,
  `visual_intent`, `duration_seconds`, `provider_hint`). It is the input to the
  retrieval port this phase adds.
- A `StockProvider` port already exists for fetching clips into a `STOCK_CLIP`
  asset (a later phase). It is distinct from the `ClipRetrievalProvider`
  search-result port this phase adds: `ClipRetrievalProvider` returns candidate
  metadata only and downloads nothing.
- `GetLatestStockPlan` already parses the latest `STOCK_PLAN` asset into a
  `StockPlan(asset, queries)` read model in the application layer and raises
  `AssetNotFoundError` when no plan exists. This is the read path and the
  natural dependency guard this phase reuses.
- The stock-plan use-cases (`CreateStockPlan`, `GenerateStockPlan`,
  `ListStockPlans`, `GetLatestStockPlan`) and their JSON `_queries_to_bytes` /
  `_queries_from_bytes` helpers in `stock_assets.py` are the exact template for
  this phase's module.
- `RunStatus` is `created -> script_ready -> script_approved -> scenes_ready ->
  scenes_approved -> rendered` (plus `failed`). `scenes_approved` only
  transitions to `rendered`/`failed`; there is no planning/retrieval status.
- Persistence is kind-agnostic, so a new `AssetKind` needs no infrastructure or
  schema change (verified in source):
  - SQLite `assets.kind` is `TEXT NOT NULL` with no CHECK constraint;
    `UNIQUE (run_id, kind, version)` and the `idx_assets_run_kind (run_id, kind)`
    index are generic.
  - `LocalFilesystemStorage` derives paths as `{kind}/{asset_id}/v{version}`, so
    candidate bytes land under `data/assets/clip_candidates/...`.
  - The in-memory fakes key on `(run_id, kind)` generically.
- `.gitignore` already ignores `data/assets/*` (keeping `.gitkeep`), so
  `data/assets/clip_candidates/*` is already covered with no change.
- Architecture boundary tests already scan `application` and `api` imports and
  the `infrastructure/generation` package, so new files in those layers inherit
  forbidden-import coverage automatically. A dedicated confinement test exists
  for `StubStockClipPlanner` (only `main.py` may import it); this phase adds a
  parallel test for the new stub.
- Composition wiring is direct in `main.py` via `app.state` (e.g.
  `stock_planner`), not through `provider_registry.py`. `provider_registry.py`
  does not carry the planner-style ports today and is not changed by this phase.

## Answers to Design Questions

| # | Question | Decision |
| --- | --- | --- |
| 1 | New `AssetKind.CLIP_CANDIDATES`? | Yes (D14). Distinct from `STOCK_CLIP`. |
| 2 | Reuse `STOCK_CLIP`? | No (D14). `CLIP_CANDIDATES` is search-result metadata only; `STOCK_CLIP` stays reserved for a later selected/downloaded clip. |
| 3 | New `RunStatus`, or asset-only? | Asset-only; no new status; gated at `scenes_approved`; no transition (D15). |
| 4 | Domain model for a candidate? | `ClipCandidate`; the set is a sequence; app-level `ClipCandidateSet` read model; no domain wrapper (D16). |
| 5 | Retrieval granularity? | Port is query-level (`retrieve(query)`); the use-case aggregates whole-plan-level into one asset; candidates carry `scene_id` for regrouping (D17). |
| 6 | Use-case loads latest stock plan, or queries passed in? | Loads latest via `GetLatestStockPlan`; status checked before the plan read; missing plan -> `AssetNotFoundError` (D18). |
| 7 | Manual POST `/clip-candidates`? | No this phase; retrieve-only public API (D19). |
| 8 | Real Pexels/Pixabay, downloads, ranking, selection? | No (out of scope). |

## Design Decisions

These decisions are locked for this phase and continue the project decision log
(D1-D7 in the script/scene planning foundation document; D8-D13 in the
stock-clip planning foundation document; both also recorded in code).

### D14. Add `AssetKind.CLIP_CANDIDATES`; do not reuse `STOCK_CLIP`

- Add `CLIP_CANDIDATES = "clip_candidates"` to `AssetKind`.
- It represents provider search-result metadata: a set of candidate clips with
  reference URLs only. It is separate from `STOCK_CLIP`, which represents fetched
  media bytes / a selected clip (a later phase). Keeping them distinct prevents a
  later download/selection slice from colliding with retrieval results.
- No SQLite, storage, schema, or `.gitignore` change is required: persistence is
  kind-agnostic (see Existing Foundation), and candidate bytes land under
  `data/assets/clip_candidates/...`, already covered by the `data/assets/*`
  ignore.

### D15. Asset-only; no new `RunStatus`; allowed only at `scenes_approved`

- Clip retrieval persists a versioned asset and does not change `RunStatus`.
- The allowed-status guard is `{scenes_approved}` (`_CLIP_RETRIEVAL_ALLOWED =
  frozenset({RunStatus.SCENES_APPROVED})`), matching stock planning (D9). The
  run sits at `scenes_approved` accumulating both `STOCK_PLAN` and
  `CLIP_CANDIDATES` versions until a future download/render phase fires the
  transition.
- The use-case never calls a domain transition method. Re-retrieving while
  `scenes_approved` simply persists the next version and stays `scenes_approved`.
- Rejection in any other status reuses the existing `AssetCreationRejectedError`
  (mapped to HTTP 409 by the existing handler) with `kind = clip_candidates`.

### D16. Add `ClipCandidate` as the domain model; `ClipCandidateSet` app read model; no domain wrapper

- Add a frozen domain dataclass mirroring `StockQuerySpec`:

  ```python
  @dataclass(frozen=True)
  class ClipCandidate:
      scene_id: str          # links the candidate back to its scene/query group
      query_text: str        # the stock search query that produced the candidate
      provider: str          # e.g. "stub" (later "pexels"/"pixabay")
      provider_clip_id: str  # the provider's own id for the clip
      title: str             # human-readable label
      preview_url: str       # reference only; never fetched
      source_url: str        # provider page link; reference only
      duration_seconds: float
      width: int
      height: int
  ```

- `scene_id` ties each candidate to its scene/query group (the regrouping key,
  like `StockQuerySpec.scene_id`); `query_text` preserves which planned query
  produced the candidate. The set is an ordered `Sequence[ClipCandidate]`
  persisted as one versioned JSON asset with `kind = CLIP_CANDIDATES` (mirrors
  the stock-plan storage shape).
- Add an application-layer `ClipCandidateSet` read model, a
  `NamedTuple(asset, candidates)` mirroring `StockPlan(asset, queries)`. Do not
  add a domain wrapper: symmetry with the stock-plan slice plus YAGNI; a wrapper
  can be added later if set-level fields appear.
- Carry no media bytes. URLs are references only. Do not add tags, attribution,
  rank, score, downloadable video files, or provider-specific nested file data
  this phase (see Phase-Wide Out of Scope).

### D17. `ClipRetrievalProvider` is a query-level port; the use-case aggregates whole-plan-level

- Define the port in `backend/app/ports/providers.py` alongside the other
  provider ports:

  ```python
  @runtime_checkable
  class ClipRetrievalProvider(Protocol):
      def retrieve(self, query: StockQuerySpec) -> Sequence[ClipCandidate]: ...
  ```

- Query-level is the natural provider boundary: a real Pexels/Pixabay call is
  per-query. The port stays minimal (no `limit`/`language` parameters this
  phase) to match the tight `StockClipPlanner` contract and avoid scope creep.
- The use-case orchestrates across the whole latest stock plan: it iterates the
  plan's `queries`, calls `retrieve` once per `StockQuerySpec`, and aggregates
  the results into a single `CLIP_CANDIDATES` asset. Candidates carry `scene_id`,
  so consumers regroup by scene without a grouping object.
- The port imports only domain types. No infrastructure SDK, HTTP client, or
  network concern appears in the domain/application layers.

### D18. `RetrieveClipCandidates` loads the latest stock plan via the existing read path; status checked before the plan read

- `RetrieveClipCandidates` composes the existing `GetLatestStockPlan` use-case to
  obtain the planned queries. The API calls one use-case with only `run_id`;
  queries are not passed in the request and storage is not re-parsed.
- Ordering: the D15 status guard is checked before the stock-plan read. An
  invalid status therefore yields a clean 409 (`AssetCreationRejectedError`)
  rather than a misleading 404, and no provider work happens on a doomed request.
- The dependency on a stock plan is enforced naturally: when no `STOCK_PLAN`
  exists, `GetLatestStockPlan` raises `AssetNotFoundError(STOCK_PLAN)` (mapped to
  HTTP 404). No special-casing is added.
- The canonical guard lives in `CreateClipCandidateSet` (the persistence
  use-case), so any future manual path is guarded too; `RetrieveClipCandidates`
  performs the same status check up front to enforce the ordering above. This
  small, intentional duplication mirrors the stock-plan slice (D12) and is tested
  on both paths.

### D19. Retrieve-only public API; no manual `POST /clip-candidates` this phase

- Expose only `POST .../clip-candidates/retrieve`, `GET .../clip-candidates`, and
  `GET .../clip-candidates/latest`.
- `CreateClipCandidateSet` exists as the internal persistence use-case (composed
  by `RetrieveClipCandidates`, holding the canonical D15 guard), mirroring
  `CreateStockPlan`, but is not wired to a manual `POST .../clip-candidates`
  route in this phase.
- Rationale: keep the HTTP surface minimal. Adding the manual route later is a
  trivial, symmetric one-route change.

## Storage Decision

- Persist the candidate set as JSON bytes through the existing `StoragePort`
  (no media files). Index with `VersionedAssetRepository` under
  `(run_id, AssetKind.CLIP_CANDIDATES)`. Metadata includes the source, e.g.
  `{"source": "retrieved"}`.
- Serialize/deserialize with private application helpers `_candidates_to_bytes`
  / `_candidates_from_bytes`, mirroring the stock-plan `_queries_to_bytes` /
  `_queries_from_bytes` style (a JSON list of flat objects with the
  `ClipCandidate` fields; `duration_seconds` round-trips as `float`).
- No clip is downloaded and no media file is stored: the only bytes written are
  the JSON candidate metadata, whose `preview_url`/`source_url` are `memory://`
  references in the deterministic adapter.

## API Route Plan

Explicit, long route names, consistent with the existing asset routes in
`backend/app/api/assets.py`.

| Method | Path | Returns | Purpose |
| --- | --- | --- | --- |
| `POST` | `/runs/{run_id}/clip-candidates/retrieve` | `201` `AssetResponse` | Retrieve from the latest stock plan; persist a `CLIP_CANDIDATES` asset (next version, `source=retrieved`). Applies the D15 rule. |
| `GET` | `/runs/{run_id}/clip-candidates` | `list[AssetResponse]` | List clip-candidate asset versions for the run. |
| `GET` | `/runs/{run_id}/clip-candidates/latest` | `ClipCandidateSetResponse` | Get the latest clip-candidate asset plus its parsed `candidates` (mirrors `StockPlanResponse`). |

New API models in `assets.py`: `ClipCandidateModel` (`from_domain`),
`ClipCandidateSetResponse` (`from_clip_candidate_set`), and a
`get_clip_retrieval_provider` dependency resolver reading
`request.app.state.clip_retrieval_provider`. No manual create request model this
phase (D19). No raw byte download.

## Composition Root

- Add an optional `clip_retrieval_provider: ClipRetrievalProvider | None = None`
  parameter to `create_app(...)`, defaulting to `StubClipRetrievalProvider()`,
  and set `app.state.clip_retrieval_provider`. Follow the existing `stock_planner`
  wiring style.
- The stub is pure/deterministic (no disk, network, or SDK), so it does not
  affect the database/storage lifespan decision, consistent with the existing
  generators.
- Do not change `provider_registry.py`: it does not carry the planner-style ports
  today, and leaving it alone respects "do not change existing behavior."

## Planned Slices

Implement one slice at a time, run tests after each, and review at the
checkpoints below. Strict inward-to-outward order: domain, then port, then
adapter and use-cases, then API and wiring, then boundary hardening.

### Slice 1: Domain - `AssetKind.CLIP_CANDIDATES` + `ClipCandidate`

- **Goal:** Add the new asset kind and the pure `ClipCandidate` dataclass (D14,
  D16).
- **Files likely to change:**
  - `backend/app/domain/models.py` (add `AssetKind.CLIP_CANDIDATES`; add the
    frozen `ClipCandidate` dataclass with the D16 fields).
  - `backend/app/domain/__init__.py` (export `ClipCandidate`).
- **Tests to add:** `tests/test_clip_candidate.py` - `AssetKind.CLIP_CANDIDATES
  .value == "clip_candidates"`; `ClipCandidate` is frozen (assignment raises).
- **Architecture boundaries at risk:** Domain stays framework-free (auto-covered
  by `test_domain_has_no_framework_or_outer_layer_imports`).
- **Out of scope:** Serialization (application layer); any extra fields (D16).
- **Acceptance criteria:** Kind and dataclass added and exported; domain boundary
  test green.

### Slice 2: Port - `ClipRetrievalProvider`

- **Goal:** Define the retrieval Protocol (reads `StockQuerySpec`, returns
  `Sequence[ClipCandidate]`) per D17.
- **Files likely to change:**
  - `backend/app/ports/providers.py` (add the `ClipRetrievalProvider` Protocol).
  - `backend/app/ports/__init__.py` (export the port).
- **Tests to add:** `tests/test_clip_retrieval_provider_port.py` - a fake
  satisfies `isinstance(fake, ClipRetrievalProvider)` (the port is
  `runtime_checkable`); the port resolves to `backend.app.ports.providers`;
  `get_type_hints(ClipRetrievalProvider.retrieve)` shows `query: StockQuerySpec`
  and `return: Sequence[ClipCandidate]`. Mirrors
  `tests/test_stock_clip_planner_port.py`.
- **Architecture boundaries at risk:** Port imports domain only; no `sqlite3`,
  FastAPI, SDK, or infrastructure imports.
- **Out of scope:** Adapter, use-cases, routes.
- **Acceptance criteria:** Port defined, exported, and `runtime_checkable`;
  `isinstance` and contract hints hold; boundary suite green.

### Slice 3: Deterministic adapter - `StubClipRetrievalProvider` + test fake

- **Goal:** Implement the port deterministically. For each `StockQuerySpec`,
  return exactly 2 `ClipCandidate` objects derived purely from query fields:
  - `provider = "stub"`
  - `provider_clip_id = f"{query.scene_id}-{i}"`
  - `title = f"{query.query} (candidate {i})"`
  - `query_text = query.query`
  - `preview_url = f"memory://clips/{query.scene_id}/{i}/preview.jpg"`
  - `source_url = f"memory://clips/{query.scene_id}/{i}"`
  - `duration_seconds = query.duration_seconds`
  - `width = 1920`, `height = 1080`
  - No randomness, network, filesystem, provider SDK, or subprocess. The
    `memory://` URLs make clear no download happened.
- **Files likely to change:**
  - `backend/app/infrastructure/generation/stub_clip_retrieval_provider.py`
    (new; named for symmetry with `StubStockClipPlanner`).
  - `backend/app/infrastructure/generation/__init__.py` (export the adapter).
  - `tests/fakes/providers.py` (add `FakeClipRetrievalProvider` for
    application/API tests, mirroring `FakeStockClipPlanner`).
  - `tests/fakes/__init__.py` (export the fake).
- **Tests to add:** Extend `tests/test_generation_adapters.py` -
  `isinstance(StubClipRetrievalProvider(), ClipRetrievalProvider)`; deterministic
  repeatable output; exactly 2 candidates per query; field derivation as above;
  `memory://` URLs; uses query fields.
- **Architecture boundaries at risk:** Auto-covered by
  `test_generation_adapters_import_no_api_application_or_external_modules` and
  `test_generation_package_imports_no_forbidden_modules` (no
  api/application/SDK/network/subprocess imports).
- **Out of scope:** Real providers; any ranking/scoring; >2 candidates.
- **Acceptance criteria:** Deterministic 2-per-query mapping; `isinstance`
  against the port holds; generation-import boundary tests green.

### Slice 4: Application - clip-candidate use-cases

- **Goal:** Add a new module `clip_candidate_assets.py` with `CreateClipCandidate
  Set` (persist candidates as one `CLIP_CANDIDATES` JSON asset; enforce the D15
  guard; no transition), `RetrieveClipCandidates` (compose `GetLatestStockPlan` +
  `ClipRetrievalProvider` + `CreateClipCandidateSet`, guard before the plan read
  per D18, `source = "retrieved"`), `ListClipCandidateSets`,
  `GetLatestClipCandidateSet`, the `ClipCandidateSet` read model, and the
  `ClipCandidate` <-> JSON helpers (`_candidates_to_bytes` /
  `_candidates_from_bytes`).
- **Files likely to change:**
  - `backend/app/application/use_cases/clip_candidate_assets.py` (new).
  - `backend/app/application/use_cases/__init__.py` (export the use-cases and the
    `ClipCandidateSet` read model).
- **Tests to add:** `tests/test_clip_candidate_use_cases.py` (mirror
  `tests/test_stock_asset_use_cases.py`, using a recording/spy fake provider):
  - Create persists a `CLIP_CANDIDATES` asset tagged `source` (`retrieved` via
    `RetrieveClipCandidates`; the Create default may be `manual` like
    `CreateStockPlan`); a second create increments to version 2; status stays
    `scenes_approved` (no transition).
  - D15 guard rejects every status other than `scenes_approved` with
    `AssetCreationRejectedError` (`kind = clip_candidates`), checked before the
    plan read and before provider/persistence work (so 409, not 404); nothing is
    persisted on rejection.
  - `RunNotFoundError` when the run is missing (provider not called).
  - `ListClipCandidateSets` is ordered by version; `GetLatestClipCandidateSet`
    returns the newest version and raises `AssetNotFoundError(CLIP_CANDIDATES)`
    when none exists.
  - JSON round-trip identity of the `ClipCandidate` tuple including float
    `duration_seconds`.
  - `RetrieveClipCandidates` calls the provider once per `StockQuerySpec` in the
    latest stock plan and aggregates every result; candidates cover the plan's
    scene ids.
  - `RetrieveClipCandidates` fails naturally with `AssetNotFoundError(STOCK_PLAN)`
    when no stock plan exists (seed `scenes_approved` but no plan).
- **Architecture boundaries at risk:** Application depends on ports and sibling
  use-cases only; no `backend.app.infrastructure` import (enforced by the
  existing application boundary test); the serializer stays in the application
  layer; no transition call (D15).
- **Out of scope:** Routes, real provider, download.
- **Acceptance criteria:** D15 enforced; versioning increments; round-trip
  fidelity; correct errors; provider called per query; use-case `__init__` type
  hints reference port and sibling use-case types; tests green with fakes.

### Slice 5: API routes + composition wiring

- **Goal:** Expose the three clip-candidate routes and wire
  `StubClipRetrievalProvider` into the composition root.
- **Files likely to change:**
  - `backend/app/api/assets.py` (add `ClipCandidateModel`,
    `ClipCandidateSetResponse`, a `get_clip_retrieval_provider` resolver, and the
    three routes from the API Route Plan).
  - `backend/app/main.py` (add a `clip_retrieval_provider` parameter to
    `create_app`, default `StubClipRetrievalProvider()`, set
    `app.state.clip_retrieval_provider`).
- **Tests to add:** Extend `tests/test_asset_api.py` (or add
  `tests/test_clip_candidate_api.py`) using `TestClient` with injected fakes:
  `POST .../clip-candidates/retrieve` returns 201 with `kind=clip_candidates`,
  `version=1`, `source=retrieved`; `GET` list; `GET` latest returns parsed
  `candidates`; 404 when the run is missing; 404 when no stock plan exists; 409
  when status is not `scenes_approved`; versioning across two retrieves.
- **Architecture boundaries at risk:** Routes import application and ports only
  (enforced by `test_assets_route_imports_use_cases_not_infrastructure`); no
  lifecycle/versioning logic in routes; the adapter is imported only in
  `main.py`; long route names.
- **Out of scope:** Manual POST (D19), raw byte download, auth, pagination,
  frontend.
- **Acceptance criteria:** The three endpoints return correct status codes and
  payloads with fakes; `create_app` dependency injection extended; route import
  boundary clean; tests green.

### Slice 6: Boundary hardening + end-to-end + phase audit

- **Goal:** Lock the new surface into the boundary safety net, extend the
  end-to-end happy path, and confirm hygiene before commit.
- **Files likely to change:**
  - `tests/test_architecture_boundaries.py`:
    - add `ClipRetrievalProvider` to `test_provider_interfaces_live_in_ports`;
    - add `CreateClipCandidateSet`, `ListClipCandidateSets`,
      `GetLatestClipCandidateSet` to the asset-use-case import list and their
      exact `__init__` port-hint maps;
    - add `RetrieveClipCandidates` to the generation-use-case hint map
      (`run_repository`, `clip_retrieval_provider`, `get_latest_stock_plan`,
      `create_clip_candidate_set`);
    - add a parallel confinement test asserting only `main.py` imports
      `StubClipRetrievalProvider`.
  - `tests/test_draft_planning_workflow.py` (extend the happy path: after
    `stock-plans/generate`, `POST .../clip-candidates/retrieve` returns 201 and
    `GET .../clip-candidates/latest` shows non-empty `candidates`) or a new
    `tests/test_clip_retrieval_workflow.py`.
  - `.gitignore` (confirm `data/assets/clip_candidates/*` is covered; expected no
    change since `data/assets/*` already covers it).
- **Tests to add:** The boundary assertions above; the extended or new workflow
  test asserting: `kind=clip_candidates`, `version=1`, `source=retrieved`;
  candidates cover the expected scene ids; `preview_url` uses `memory://`; the
  run stays `scenes_approved` (not rendered, no transition). A full `pytest -q`
  run is green.
- **Architecture boundaries at risk:** This slice is the safety net; guard
  against infrastructure leaking into application/api and against generated
  artifacts being tracked.
- **Out of scope:** Everything in the phase-wide out-of-scope list below.
- **Acceptance criteria:** All boundary tests and the full suite are green; ignore
  rules correct; phase-auditor criteria satisfied.

## Slice Order and Dependencies

```
1 (domain) -> 2 (port) -> +-> 3 (stub adapter + fake) -+
                          +-> 4 (use-cases) -----------+-> 5 (API + wiring) -> 6 (hardening + E2E + audit)
```

Slices 3 and 4 are independent: the use-case tests rely on a fake provider, not
the stub adapter. Do Slice 3 before Slice 4 only so the default adapter exists
when wiring in Slice 5. Everything else is strictly sequential. This ordering is
the implementation order for the later Codex phase: (1) domain model and asset
kind, (2) port, (3) stub provider and test fake, (4) application use-cases and
JSON helpers, (5) API response models/routes, (6) composition root wiring,
boundary tests, E2E workflow test, then full validation.

## Agent Checkpoints

- **architecture-reviewer after Slice 2:** Ratify the port contract and D17
  (query-level `retrieve(StockQuerySpec) -> Sequence[ClipCandidate]`) before the
  adapter and use-cases build on it.
- **architecture-reviewer after Slice 4:** Confirm ports-only dependencies, the
  guard-before-read ordering (D15/D18), no transition call, the serializer living
  in the application layer, the natural `AssetNotFoundError` when no stock plan
  exists, and no infrastructure import.
- **architecture-reviewer after Slice 5:** Highest-risk slice (routes plus
  composition root); confirm routes call use-cases only, the adapter lives solely
  in `main.py`, and no lifecycle/versioning logic leaked into routes.
- **test-debugger:** Only when tests fail non-obviously. Likely spots: Slice 4
  float JSON round-trip and the 409-vs-404 guard ordering (status before plan
  read); Slice 5 `TestClient` wiring of the new provider; Slice 6
  `get_type_hints` exact-equality on the new use-cases.
- **phase-auditor before commit at Slice 6:** Verify all acceptance criteria,
  that the full suite is green, that the database, secrets, and generated assets
  are ignored, and that no out-of-scope work leaked in (no real provider, no
  network, no download, no media storage, no render, no ranking, no selection).

## Validation

Run the full suite with the documented Windows venv command after each slice and
before commit:

```
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: the existing suite stays green and grows by the new domain, port,
adapter, use-case, API, and boundary/E2E tests above.

## Phase-Wide Out of Scope

Not implemented in this phase:

- Real Pexels API.
- Real Pixabay API.
- Any real stock provider API or SDK.
- API key / secret handling.
- HTTP clients or any network I/O (`httpx`, `requests`, `urllib`, `aiohttp`,
  `socket`).
- Clip download and file/cache.
- Storing downloaded media bytes (only JSON candidate metadata is persisted).
- FFmpeg and rendering.
- Subtitles.
- Voice/TTS.
- Ranking, scoring, dedup, or filtering of candidates beyond the deterministic
  fixed order.
- Selected-clip approval (choosing one candidate per scene).
- Tags, attribution, rank/score, downloadable video files, or provider-specific
  nested file data on `ClipCandidate` (D16).
- A new `RunStatus`; clip retrieval is asset-only (D15).
- A `ClipCandidate` domain wrapper / set wrapper (D16).
- A manual `POST /runs/{run_id}/clip-candidates` route (D19).
- A `provider_registry.py` refactor (composition stays direct in `main.py`).
- Redis/Postgres/S3/SaaS features; workers/queues; pagination; auth; frontend.
