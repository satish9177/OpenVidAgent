# Selected Clip Selection Foundation

Design document for the next phase. This records the intended design and slice
plan before any code is written. No backend, test, or product implementation is
part of this document. The approved direction is to mirror the clip-retrieval
slice 1:1: clip retrieval turns each `StockQuerySpec` into `ClipCandidate`
metadata through a provider port; this phase turns the retrieved
`ClipCandidate` set into a `SelectedClip` set through a selector port. It chooses
and stores selected clip metadata only. It does not download media, store media
bytes, or render video.

## Goal

Given the latest clip-candidate set for a run, produce a durable, versioned set
of *selected* clips per run: exactly one chosen `ClipCandidate` per
`(scene_id, query_text)` group, copied into a `SelectedClip` with a recorded
`selection_reason`. The artifact answers, for each planned query: which one
candidate clip would we use, as metadata (title, preview/source URLs, duration,
dimensions)? This phase introduces the selection abstraction only. It does not
call any real provider, perform any network request, download any clip, store
any media bytes, rank/score candidates, edit selections, or transition the run
lifecycle.

## Target Workflow

A new tail is appended to the existing prompt -> script -> scenes -> stock-plan
-> clip-candidates workflow. The run reaches `scenes_approved` exactly as today;
stock planning, clip retrieval, and now clip selection run as asset-only steps
that do not move the lifecycle.

```
create run
-> generate script draft
-> approve script
-> generate scene table
-> approve scenes                 # run reaches scenes_approved
-> generate stock plan            # reads latest scene table, persists STOCK_PLAN
                                  # run STAYS at scenes_approved (asset-only)
-> retrieve clip candidates       # reads latest STOCK_PLAN, calls the
                                  # ClipRetrievalProvider per StockQuerySpec,
                                  # persists CLIP_CANDIDATES,
                                  # run STAYS at scenes_approved (asset-only)
-> select clips                   # NEW: reads latest CLIP_CANDIDATES, calls the
                                  # ClipSelector once over the whole set,
                                  # persists a SELECTED_CLIPS asset,
                                  # run STAYS at scenes_approved (asset-only)
```

So the next target workflow is:

```
prompt -> script draft -> scene table -> stock plan -> clip candidates -> selected clips
```

## Architecture Rule

Dependencies point inward:

`API/UI -> application use-cases -> domain models/services -> ports/interfaces -> infrastructure adapters`

The domain layer does not import FastAPI, databases, HTTP clients, SDKs, or
concrete adapters. The application layer does not import infrastructure. The
selector is a port with a deterministic local adapter; it does not know any real
provider, perform network I/O, score with a model, or download media.
Lifecycle/transition rules live in application and domain, never in API routes.

## Existing Foundation

This phase builds on code that already exists, confirmed by reading the source.
The clip-retrieval phase described in `clip-retrieval-provider-interface.md` is
now merged and is the exact 1:1 template for this phase:

- `VersionedAsset` exists in the domain (`asset_id`, `kind`, `version`, `uri`,
  `metadata`); `metadata` is `Mapping[str, str]`.
- `AssetKind` already includes `SCRIPT`, `SCENE_TABLE`, `STOCK_PLAN`,
  `CLIP_CANDIDATES`, `STOCK_CLIP`, `VOICE`, `SUBTITLE`, `RENDER`.
  `CLIP_CANDIDATES` is the metadata-only search-result set this phase reads;
  `STOCK_CLIP` is the downloaded clip (a later phase) and is distinct from the
  `SELECTED_CLIPS` this phase adds.
- `ClipCandidate` exists in the domain as a frozen dataclass with `scene_id`,
  `query_text`, `provider`, `provider_clip_id`, `title`, `preview_url`,
  `source_url`, `duration_seconds`, `width`, `height`. It is the input this
  phase selects from and the shape `SelectedClip` mirrors.
- A `ClipRetrievalProvider` port exists in `backend/app/ports/providers.py`
  (`retrieve(query: StockQuerySpec) -> Sequence[ClipCandidate]`), with a pure
  `StubClipRetrievalProvider` adapter returning two `memory://` candidates per
  query and downloading nothing. It is the structural template for the
  `ClipSelector` port and `DeterministicClipSelector` adapter this phase adds.
- `GetLatestClipCandidateSet` already parses the latest `CLIP_CANDIDATES` asset
  into a `ClipCandidateSet(asset, candidates)` read model in the application
  layer and raises `AssetNotFoundError(run_id, CLIP_CANDIDATES)` when none
  exists. This is the read path and the natural dependency guard this phase
  reuses.
- The clip-candidate use-cases (`CreateClipCandidateSet`,
  `RetrieveClipCandidates`, `ListClipCandidateSets`,
  `GetLatestClipCandidateSet`) and their JSON `_candidates_to_bytes` /
  `_candidates_from_bytes` helpers in `clip_candidate_assets.py` are the exact
  template for this phase's `selected_clip_assets.py` module. The asset-only
  guard `_CLIP_RETRIEVAL_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})` and
  the guard-before-read ordering in `RetrieveClipCandidates` are copied directly.
- `RunStatus` is `created -> script_ready -> script_approved -> scenes_ready ->
  scenes_approved -> rendered` (plus `failed`). `scenes_approved` only
  transitions to `rendered`/`failed`; there is no planning/retrieval/selection
  status, and this phase adds none.
- Persistence is kind-agnostic, so a new `AssetKind` needs no infrastructure or
  schema change (verified in source for the prior phase): SQLite `assets.kind`
  is `TEXT NOT NULL` with no CHECK constraint; `UNIQUE (run_id, kind, version)`
  and the `idx_assets_run_kind` index are generic; `LocalFilesystemStorage`
  derives paths as `{kind}/{asset_id}/v{version}`, so selected-clip bytes land
  under `data/assets/selected_clips/...`; the in-memory fakes key on
  `(run_id, kind)` generically.
- `.gitignore` already ignores `data/assets/*` (keeping `.gitkeep`), so
  `data/assets/selected_clips/*` is already covered with no change.
- The API surface lives in `backend/app/api/assets.py`, which already holds the
  three clip-candidate routes, the `ClipCandidateModel` / `ClipCandidateSetResponse`
  Pydantic models, and a `get_clip_retrieval_provider` dependency resolver
  reading `request.app.state.clip_retrieval_provider`. These are the template
  for the selected-clip routes, models, and `get_clip_selector` resolver.
- Architecture boundary tests already scan `application` and `api` imports and
  the `infrastructure/generation` package, so new files in those layers inherit
  forbidden-import coverage automatically. A dedicated confinement test exists
  for `StubClipRetrievalProvider` (only `main.py` may import it); this phase adds
  a parallel test for `DeterministicClipSelector`.
- Composition wiring is direct in `main.py` via `app.state` (e.g.
  `clip_retrieval_provider`), not through `provider_registry.py`.
  `provider_registry.py` does not carry the planner/provider-style ports today
  and is not changed by this phase.

## Answers to Design Questions

| # | Question | Decision |
| --- | --- | --- |
| 1 | Name of the selected clip domain model? | `SelectedClip` (D22). Mirrors `ClipCandidate` plus `selection_reason`. |
| 2 | One clip per scene, per `StockQuerySpec`, or per query group? | One per `(scene_id, query_text)` group of the candidate set (D22). The `StockQuerySpec` is gone by selection time; `(scene_id, query_text)` is the available, robust key. With today's one-query-per-scene planner this is effectively one per scene. |
| 3 | New asset kind? | Yes: `AssetKind.SELECTED_CLIPS = "selected_clips"` (D20). Distinct from `CLIP_CANDIDATES` and `STOCK_CLIP`. |
| 4 | Reference the candidate, or copy full metadata? | Copy full candidate metadata into `SelectedClip` and add `selection_reason` (D22). `provider` + `provider_clip_id` are part of that copy, so a stable back-reference is preserved without coupling to a candidate-set version. |
| 5 | Name of the read model? | `SelectedClipSet` application read model, a `NamedTuple(asset, selected_clips)` (D22). No domain wrapper. |
| 6 | Deterministic/stubbed selection now? | Yes (D23/D24). First candidate per `(scene_id, query_text)` group in stable input order; `selection_reason = "first_candidate_for_scene_query"`. |
| 7 | Use-cases needed? | `CreateSelectedClipSet`, `SelectClips`, `ListSelectedClipSets`, `GetLatestSelectedClipSet` (D24/D25). |
| 8 | Selector port? | Yes: `ClipSelector` with `select(candidates: Sequence[ClipCandidate]) -> Sequence[SelectedClip]` (D23). |
| 9 | Default selector deterministic? | Yes: `DeterministicClipSelector` (D23). First-per-group, stable order, pure. |
| 10 | API routes? | `POST .../selected-clips/select`, `GET .../selected-clips`, `GET .../selected-clips/latest` (D25). No manual create route this phase. |
| 11 | Run status gate? | `RunStatus.SCENES_APPROVED`, matching stock planning and clip retrieval (D21). |
| 12 | Transition the run status? | No. Asset-only; no new `RunStatus`; no transition (D21). |
| 13 | Tests for boundaries / no-download? | See Test Checklist. Reuse the auto-scanning boundary suite; add port-location, use-case-hint, confinement, deterministic-selection, round-trip, guard-ordering, and `memory://`-only/no-bytes assertions. |
| 14 | Explicitly deferred? | See Phase-Wide Out of Scope. No real download, ranking/scoring, selection editing UI, manual create route, run transition, or changes to upstream phases. |

## Design Decisions

These decisions are locked for this phase and continue the project decision log
(D1-D7 in the script/scene planning foundation document; D8-D13 in the
stock-clip planning foundation document; D14-D19 in the clip-retrieval provider
interface document; all also recorded in code).

### D20. Add `AssetKind.SELECTED_CLIPS`; do not reuse `CLIP_CANDIDATES` or `STOCK_CLIP`

- Add `SELECTED_CLIPS = "selected_clips"` to `AssetKind`.
- It represents the chosen subset of candidate metadata: one `SelectedClip` per
  `(scene_id, query_text)` group with reference URLs only. It is separate from
  `CLIP_CANDIDATES` (the full retrieved search results) and from `STOCK_CLIP`
  (fetched media bytes, a later phase). Keeping all three distinct lets the
  retrieve, select, and download/render slices evolve and re-run independently
  without colliding versions.
- No SQLite, storage, schema, or `.gitignore` change is required: persistence is
  kind-agnostic (see Existing Foundation), and selected-clip bytes land under
  `data/assets/selected_clips/...`, already covered by the `data/assets/*`
  ignore.

### D21. Asset-only; no new `RunStatus`; allowed only at `scenes_approved`

- Clip selection persists a versioned asset and does not change `RunStatus`.
- The allowed-status guard is `{scenes_approved}` (`_SELECTION_ALLOWED =
  frozenset({RunStatus.SCENES_APPROVED})`), matching stock planning (D9) and clip
  retrieval (D15). The run sits at `scenes_approved` accumulating `STOCK_PLAN`,
  `CLIP_CANDIDATES`, and `SELECTED_CLIPS` versions until a future
  download/render phase fires the transition.
- The use-case never calls a domain transition method. Re-selecting while
  `scenes_approved` simply persists the next version and stays `scenes_approved`.
- Rejection in any other status reuses the existing `AssetCreationRejectedError`
  (mapped to HTTP 409 by the existing handler) with `kind = selected_clips`.

### D22. Add `SelectedClip` as the domain model; `SelectedClipSet` app read model; no domain wrapper

- Add a frozen domain dataclass mirroring `ClipCandidate` plus one field:

  ```python
  @dataclass(frozen=True)
  class SelectedClip:
      scene_id: str          # links the selection back to its scene/query group
      query_text: str        # the stock search query that produced the candidate
      provider: str          # copied from the chosen ClipCandidate
      provider_clip_id: str  # copied; stable back-reference to the candidate
      title: str
      preview_url: str       # reference only; never fetched
      source_url: str        # reference only; never fetched
      duration_seconds: float
      width: int
      height: int
      selection_reason: str  # why this candidate was chosen, e.g.
                             # "first_candidate_for_scene_query"
  ```

- **Copy, not reference (Q4).** A `SelectedClip` copies the full candidate
  metadata so it is a self-contained, durable record of what was chosen. Because
  `CLIP_CANDIDATES` is itself versioned and may be re-retrieved, a bare
  `(provider, provider_clip_id)` pointer could dangle against a later candidate
  version. The copied `provider` + `provider_clip_id` still serve as a stable
  back-reference for any future reconciliation. This matches how `ClipCandidate`
  itself denormalizes `scene_id`/`query_text` rather than referencing the
  `StockQuerySpec`.
- **Granularity (Q2).** One `SelectedClip` per distinct `(scene_id, query_text)`
  pair found in the candidate set, emitted in first-seen order. At selection time
  the input is the latest `ClipCandidateSet`, not the stock plan, so
  `(scene_id, query_text)` is the natural available grouping key. Today's planner
  emits one query per scene, so this is effectively one selected clip per scene;
  the pair key is robust to a future multi-query-per-scene plan without baking in
  a scene-level tie-break policy now.
- Add an application-layer `SelectedClipSet` read model, a
  `NamedTuple(asset, selected_clips)` mirroring `ClipCandidateSet(asset,
  candidates)`. Do not add a domain wrapper: symmetry with the clip-candidate
  slice plus YAGNI; a wrapper can be added later if set-level fields appear.
- Carry no media bytes. URLs are references only, copied verbatim from the chosen
  candidate (so they stay `memory://` under the deterministic provider). Do not
  add rank, score, tags, attribution, downloadable files, or per-clip edits this
  phase (see Phase-Wide Out of Scope).

### D23. `ClipSelector` is a whole-set-level port; the selection policy lives in the adapter

- Define the port in `backend/app/ports/providers.py` alongside the other
  provider ports:

  ```python
  @runtime_checkable
  class ClipSelector(Protocol):
      def select(
          self, candidates: Sequence[ClipCandidate]
      ) -> Sequence[SelectedClip]:
          """Choose selected clips from retrieved candidate metadata."""
          ...
  ```

- **Whole-set-level, not per-group.** Unlike `ClipRetrievalProvider.retrieve`
  (per-query, because a real provider call is per-query), selection must see the
  whole candidate set to group by `(scene_id, query_text)` and pick one per
  group. So the port takes the full `Sequence[ClipCandidate]` and returns the
  `Sequence[SelectedClip]`. The grouping + first-pick *policy* lives entirely in
  the adapter, keeping the use-case free of selection logic.
- **Why a port at all (Q8).** Selection is pure (no I/O), so a port is not
  required for dependency-inversion-over-I/O reasons. It is still preferred
  because the selection *policy* is the part most likely to evolve (ranking,
  scoring, dedup, preference models); isolating it behind a port keeps that churn
  out of the use-case and routes, gives the proven stub/fake test split, and lets
  a future smart selector plug in at `main.py` with zero use-case/route change.
  This reuses an existing, proven pattern rather than inventing one, so it adds
  testability without overengineering. The considered alternative -- a pure
  domain `ClipSelectionService` function -- is rejected only for that
  evolvability/symmetry reason and remains a clean fallback if a port ever feels
  heavy.
- The port imports only domain types. No infrastructure SDK, HTTP client, model,
  or network concern appears in the domain/application layers.

### D24. `SelectClips` loads the latest candidate set via the existing read path; status checked before the read

- `SelectClips` composes the existing `GetLatestClipCandidateSet` use-case to
  obtain the candidates. The API calls one use-case with only `run_id`;
  candidates are not passed in the request and storage is not re-parsed.
- Ordering: the D21 status guard is checked before the candidate read. An invalid
  status therefore yields a clean 409 (`AssetCreationRejectedError`) rather than a
  misleading 404, and no selector work happens on a doomed request. This mirrors
  the guard-before-read ordering of `RetrieveClipCandidates` (D18).
- The dependency on a candidate set is enforced naturally: when no
  `CLIP_CANDIDATES` exists, `GetLatestClipCandidateSet` raises
  `AssetNotFoundError(run_id, CLIP_CANDIDATES)` (mapped to HTTP 404). No
  special-casing is added.
- The canonical guard lives in `CreateSelectedClipSet` (the persistence
  use-case), so any future manual path is guarded too; `SelectClips` performs the
  same status check up front to enforce the ordering above. This small,
  intentional duplication mirrors the clip-retrieval slice (D18) and is tested on
  both paths.
- `SelectClips` persists with `source = "selected"`; `CreateSelectedClipSet`
  defaults `source = "manual"` (mirroring `CreateClipCandidateSet`).

### D25. Select-only public API; no manual `POST /selected-clips` this phase

- Expose only `POST .../selected-clips/select`, `GET .../selected-clips`, and
  `GET .../selected-clips/latest`.
- `CreateSelectedClipSet` exists as the internal persistence use-case (composed
  by `SelectClips`, holding the canonical D21 guard), mirroring
  `CreateClipCandidateSet`, but is not wired to a manual `POST .../selected-clips`
  route in this phase.
- Rationale: keep the HTTP surface minimal. Adding the manual route later is a
  trivial, symmetric one-route change.

## Domain Model Proposal

- `SelectedClip` (frozen dataclass) as shown in D22: the ten `ClipCandidate`
  fields plus `selection_reason: str`.
- Exported from `backend/app/domain/__init__.py` next to `ClipCandidate`.
- `AssetKind.SELECTED_CLIPS = "selected_clips"`.
- Application read model `SelectedClipSet(NamedTuple)` with `asset:
  VersionedAsset` and `selected_clips: tuple[SelectedClip, ...]`, defined in the
  new `selected_clip_assets.py` and exported from
  `backend/app/application/use_cases/__init__.py` next to `ClipCandidateSet`.

## Asset / Storage Decision

- Persist the selected-clip set as JSON bytes through the existing `StoragePort`
  (no media files). Index with `VersionedAssetRepository` under
  `(run_id, AssetKind.SELECTED_CLIPS)`. Metadata includes the source, e.g.
  `{"source": "selected"}` for `SelectClips` and `{"source": "manual"}` for a
  direct `CreateSelectedClipSet` call.
- Serialize/deserialize with private application helpers `_selected_clips_to_bytes`
  / `_selected_clips_from_bytes`, mirroring the clip-candidate
  `_candidates_to_bytes` / `_candidates_from_bytes` style: a JSON list of flat
  objects with the `SelectedClip` fields; `duration_seconds` round-trips as
  `float`, `width`/`height` as `int`, and `selection_reason` as `str`.
- No clip is downloaded and no media file is stored: the only bytes written are
  the JSON selected-clip metadata, whose `preview_url`/`source_url` are the same
  `memory://` references copied from the chosen candidates.

## Port / Selector Decision

- Add the `ClipSelector` port (D23) in `backend/app/ports/providers.py` and
  export it from `backend/app/ports/__init__.py`.
- Add the default adapter `DeterministicClipSelector` in
  `backend/app/infrastructure/generation/deterministic_clip_selector.py`,
  exported from `backend/app/infrastructure/generation/__init__.py`.
  - It iterates `candidates` in order, tracks first-seen `(scene_id, query_text)`
    keys, and emits one `SelectedClip` per key (the first candidate seen for that
    key), copying all fields and stamping
    `selection_reason = "first_candidate_for_scene_query"`.
  - Pure and deterministic: no randomness, network, filesystem, SDK, model, or
    subprocess. URLs are passed through unchanged, so they remain `memory://`.
  - Naming note: the existing composition defaults are named `Stub*`/`Echo*`
    because they stand in for absent external integrations (LLM script gen, scene
    planner, real Pexels). A first-candidate selector is a legitimate v1 policy
    rather than a placeholder for an external service, so it is named for its
    behavior (`Deterministic`) rather than as a stub. `StubClipSelector` is the
    only alternative considered; see Open Questions.
- Add a test fake `FakeClipSelector` in `tests/fakes/providers.py` (a
  recording/spy selector for application/API tests), mirroring
  `FakeClipRetrievalProvider`, exported from `tests/fakes/__init__.py`.

## Use-Case Plan

New module `backend/app/application/use_cases/selected_clip_assets.py`, modeled
exactly on `clip_candidate_assets.py`.

1. **`CreateSelectedClipSet`** -- persists caller-supplied `SelectedClip` entries.
   - `execute(run_id, selected_clips, source="manual") -> VersionedAsset`.
   - Loads the run (`RunNotFoundError` if missing), enforces the D21 status guard
     (`AssetCreationRejectedError` with `kind = selected_clips` for any status
     other than `scenes_approved`), computes `next_version`, writes the JSON via
     `StoragePort`, saves the asset, and returns it. Stores metadata only. Does
     not transition the run.
   - Constructor deps (port types only): `run_repository: RunRepository`,
     `asset_repository: VersionedAssetRepository`, `storage: StoragePort`,
     `asset_id_factory: Callable[[], str] | None`.

2. **`SelectClips`** -- selects deterministically from the latest candidate set.
   - `execute(run_id) -> VersionedAsset`.
   - Loads the run, applies the D21 guard *before* the candidate read (D24), then
     reads the latest set via `GetLatestClipCandidateSet`
     (`AssetNotFoundError(CLIP_CANDIDATES)` when none), calls
     `clip_selector.select(candidate_set.candidates)`, and persists via
     `CreateSelectedClipSet` with `source = "selected"`. Does not transition the
     run.
   - Constructor deps: `run_repository: RunRepository`, `clip_selector:
     ClipSelector`, `get_latest_clip_candidate_set: GetLatestClipCandidateSet`,
     `create_selected_clip_set: CreateSelectedClipSet`.

3. **`ListSelectedClipSets`** -- lists `SELECTED_CLIPS` asset versions for a run.
   - `execute(run_id) -> Sequence[VersionedAsset]` via
     `asset_repository.list_for_run(run_id, AssetKind.SELECTED_CLIPS)`.

4. **`GetLatestSelectedClipSet`** -- returns the latest set parsed.
   - `execute(run_id) -> SelectedClipSet`; raises
     `AssetNotFoundError(run_id, SELECTED_CLIPS)` if missing.

Plus the `SelectedClipSet` read model and the `_selected_clips_to_bytes` /
`_selected_clips_from_bytes` helpers, all in the new module. Export the four
use-cases and `SelectedClipSet` from
`backend/app/application/use_cases/__init__.py`.

## API Route Plan

Explicit, long route names, consistent with the existing asset routes in
`backend/app/api/assets.py`.

| Method | Path | Returns | Purpose |
| --- | --- | --- | --- |
| `POST` | `/runs/{run_id}/selected-clips/select` | `201` `AssetResponse` | Select from the latest clip-candidate set; persist a `SELECTED_CLIPS` asset (next version, `source=selected`). Applies the D21 rule. |
| `GET` | `/runs/{run_id}/selected-clips` | `list[AssetResponse]` | List selected-clip asset versions for the run. |
| `GET` | `/runs/{run_id}/selected-clips/latest` | `SelectedClipSetResponse` | Get the latest selected-clip asset plus its parsed `selected_clips` (mirrors `ClipCandidateSetResponse`). |

New API models in `assets.py`: `SelectedClipModel` (`from_domain`),
`SelectedClipSetResponse` (`from_selected_clip_set`), and a `get_clip_selector`
dependency resolver reading `request.app.state.clip_selector`. No manual create
request model this phase (D25). No raw byte download.

## Composition Root Decision

- Add an optional `clip_selector: ClipSelector | None = None` parameter to
  `create_app(...)`, defaulting to `DeterministicClipSelector()`, and set
  `app.state.clip_selector`. Follow the existing `clip_retrieval_provider`
  wiring style.
- The default selector is pure/deterministic (no disk, network, or SDK), so it
  does not affect the database/storage lifespan decision, consistent with the
  existing generation adapters.
- Do not change `provider_registry.py`: it does not carry the provider-style
  ports today, and leaving it alone respects "do not change existing behavior."

## Test Checklist

Boundary and no-download protections (most reuse the auto-scanning suite in
`tests/test_architecture_boundaries.py`):

- **Domain stays pure** -- `SelectedClip` + `AssetKind.SELECTED_CLIPS` are
  auto-covered by `test_domain_has_no_framework_or_outer_layer_imports`.
  Add `tests/test_selected_clip.py`: `AssetKind.SELECTED_CLIPS.value ==
  "selected_clips"`; `SelectedClip` is frozen (assignment raises);
  `selection_reason` is a required field.
- **Port lives in ports** -- add `ClipSelector` to
  `test_provider_interfaces_live_in_ports`. Add `tests/test_clip_selector_port.py`:
  a fake satisfies `isinstance(fake, ClipSelector)` (runtime-checkable); the port
  resolves to `backend.app.ports.providers`; `get_type_hints(ClipSelector.select)`
  shows `candidates: Sequence[ClipCandidate]` and `return:
  Sequence[SelectedClip]`. Mirrors `tests/test_clip_retrieval_provider_port.py`.
- **Application never imports infrastructure** -- auto-covered by
  `test_application_does_not_import_infrastructure`; the serializer stays in the
  application layer.
- **Use-case dependency hints** -- extend
  `test_stock_asset_use_cases_depend_only_on_expected_ports_and_factories` (or its
  asset-use-case equivalent) with `CreateSelectedClipSet` (run/asset/storage +
  `asset_id_factory`), `ListSelectedClipSets` (asset repo), and
  `GetLatestSelectedClipSet` (asset repo + storage); extend
  `test_generation_use_cases_depend_on_ports_and_create_use_cases` with
  `SelectClips` (`run_repository`, `clip_selector`,
  `get_latest_clip_candidate_set`, `create_selected_clip_set`).
- **Routes call use-cases, not infrastructure** -- auto-covered by
  `test_assets_route_imports_use_cases_not_infrastructure` and
  `test_api_routes_depend_on_use_cases_not_infrastructure` (same file).
- **Adapter confinement** -- add
  `test_deterministic_clip_selector_import_confined_to_composition_root` asserting
  only `main.py` imports `DeterministicClipSelector`.
- **Generation package boundaries** -- the new adapter is auto-covered by
  `test_generation_adapters_import_no_api_application_or_external_modules` and
  `test_generation_package_imports_no_forbidden_modules` (no api/application/SDK/
  HTTP/network/subprocess/ffmpeg imports).
- **Deterministic selection (adapter)** -- extend
  `tests/test_generation_adapters.py`:
  `isinstance(DeterministicClipSelector(), ClipSelector)`; repeatable identical
  output; exactly one `SelectedClip` per `(scene_id, query_text)` group; first
  candidate chosen; first-seen group order preserved; `selection_reason ==
  "first_candidate_for_scene_query"`; all `preview_url`/`source_url` copied
  unchanged and still start with `memory://`; empty input -> empty output.
- **No-download / metadata-only** -- assert the only persisted bytes are JSON
  (`storage.saved` holds JSON, no media), URLs remain `memory://`, and no field
  carries media bytes; the boundary import tests above guarantee no HTTP/FFmpeg
  client is reachable.
- **Use-case behavior** -- add `tests/test_selected_clip_use_cases.py` (mirror
  `tests/test_clip_candidate_use_cases.py`, using a recording `FakeClipSelector`):
  create persists a `SELECTED_CLIPS` asset tagged `source` (`selected` via
  `SelectClips`; `manual` default for `CreateSelectedClipSet`); a second create
  increments to version 2 and the run stays `scenes_approved` (no transition);
  the D21 guard rejects every status except `scenes_approved` with
  `AssetCreationRejectedError(kind = selected_clips)`, checked before the
  candidate read and before selector/persistence work (409, not 404), persisting
  nothing; `RunNotFoundError` when the run is missing (selector not called);
  `ListSelectedClipSets` is version-ordered; `GetLatestSelectedClipSet` returns
  the newest and raises `AssetNotFoundError(SELECTED_CLIPS)` when none; JSON
  round-trip identity of the `SelectedClip` tuple including float
  `duration_seconds` and `selection_reason`; `SelectClips` calls the selector once
  with the latest candidate set and persists its result; `SelectClips` fails
  naturally with `AssetNotFoundError(CLIP_CANDIDATES)` when no candidate set
  exists (seed `scenes_approved` but no candidates), persisting nothing.
- **API** -- extend `tests/test_asset_api.py` (or add
  `tests/test_selected_clip_api.py`) with `TestClient` + injected fakes: `POST
  .../selected-clips/select` returns 201 with `kind=selected_clips`, `version=1`,
  `source=selected`; `GET` list; `GET` latest returns parsed `selected_clips`;
  404 when the run is missing; 404 when no candidate set exists; 409 when status
  is not `scenes_approved`; versioning across two selects.
- **End-to-end** -- extend `tests/test_draft_planning_workflow.py` (or add
  `tests/test_clip_selection_workflow.py`): after `clip-candidates/retrieve`,
  `POST .../selected-clips/select` returns 201 and `GET
  .../selected-clips/latest` shows non-empty `selected_clips`; `selection_reason`
  is `first_candidate_for_scene_query`; `preview_url` uses `memory://`; the run
  stays `scenes_approved` (not rendered, no transition).

## Implementation Slices

Implement one slice at a time, run tests after each, and review at the
checkpoints below. Strict inward-to-outward order: domain, then port, then
adapter and use-cases, then API and wiring, then boundary hardening.

### Slice 1: Domain -- `AssetKind.SELECTED_CLIPS` + `SelectedClip`

- **Goal:** Add the new asset kind and the pure `SelectedClip` dataclass (D20,
  D22).
- **Files likely to change:** `backend/app/domain/models.py` (add
  `AssetKind.SELECTED_CLIPS`; add the frozen `SelectedClip` dataclass with the
  D22 fields); `backend/app/domain/__init__.py` (export `SelectedClip`).
- **Tests to add:** `tests/test_selected_clip.py` -- kind value; frozen;
  `selection_reason` present.
- **Boundaries at risk:** Domain stays framework-free (auto-covered).
- **Out of scope:** Serialization (application layer); any extra fields (D22).
- **Acceptance:** Kind and dataclass added/exported; domain boundary test green.

### Slice 2: Port -- `ClipSelector`

- **Goal:** Define the selection Protocol (`select(Sequence[ClipCandidate]) ->
  Sequence[SelectedClip]`) per D23.
- **Files likely to change:** `backend/app/ports/providers.py` (add the port);
  `backend/app/ports/__init__.py` (export it).
- **Tests to add:** `tests/test_clip_selector_port.py` -- `isinstance` against a
  fake; module is `backend.app.ports.providers`; contract type hints. Mirrors
  `tests/test_clip_retrieval_provider_port.py`.
- **Boundaries at risk:** Port imports domain only; no `sqlite3`, FastAPI, SDK,
  or infrastructure imports.
- **Out of scope:** Adapter, use-cases, routes.
- **Acceptance:** Port defined, exported, `runtime_checkable`; `isinstance` and
  contract hints hold; boundary suite green.

### Slice 3: Deterministic adapter -- `DeterministicClipSelector` + test fake

- **Goal:** Implement the port deterministically (first candidate per
  `(scene_id, query_text)` group, stable order, `selection_reason =
  "first_candidate_for_scene_query"`), pure (D23).
- **Files likely to change:**
  `backend/app/infrastructure/generation/deterministic_clip_selector.py` (new);
  `backend/app/infrastructure/generation/__init__.py` (export);
  `tests/fakes/providers.py` (add `FakeClipSelector`); `tests/fakes/__init__.py`
  (export).
- **Tests to add:** Extend `tests/test_generation_adapters.py` (see Test
  Checklist -- deterministic selection).
- **Boundaries at risk:** Auto-covered by the two generation-import boundary
  tests (no api/application/SDK/HTTP/network/subprocess imports).
- **Out of scope:** Real selectors; any ranking/scoring; multi-select per group.
- **Acceptance:** Deterministic one-per-group mapping; `isinstance` holds;
  generation-import boundary tests green.

### Slice 4: Application -- selected-clip use-cases

- **Goal:** Add `selected_clip_assets.py` with `CreateSelectedClipSet`,
  `SelectClips`, `ListSelectedClipSets`, `GetLatestSelectedClipSet`, the
  `SelectedClipSet` read model, and the JSON helpers (D21, D24).
- **Files likely to change:**
  `backend/app/application/use_cases/selected_clip_assets.py` (new);
  `backend/app/application/use_cases/__init__.py` (export the use-cases and the
  read model).
- **Tests to add:** `tests/test_selected_clip_use_cases.py` (see Test Checklist
  -- use-case behavior), using a recording `FakeClipSelector`.
- **Boundaries at risk:** Application depends on ports and sibling use-cases only;
  no `backend.app.infrastructure` import; serializer stays in the application
  layer; no transition call (D21).
- **Out of scope:** Routes, real selector.
- **Acceptance:** D21 enforced; versioning increments; round-trip fidelity;
  correct errors; selector called once with the latest candidate set; `__init__`
  hints reference port and sibling use-case types; tests green with fakes.

### Slice 5: API routes + composition wiring

- **Goal:** Expose the three selected-clip routes and wire
  `DeterministicClipSelector` into the composition root (D25).
- **Files likely to change:** `backend/app/api/assets.py` (add `SelectedClipModel`,
  `SelectedClipSetResponse`, a `get_clip_selector` resolver, and the three
  routes); `backend/app/main.py` (add a `clip_selector` parameter to
  `create_app`, default `DeterministicClipSelector()`, set
  `app.state.clip_selector`).
- **Tests to add:** Extend `tests/test_asset_api.py` (or add
  `tests/test_selected_clip_api.py`) (see Test Checklist -- API).
- **Boundaries at risk:** Routes import application and ports only; no
  lifecycle/versioning logic in routes; the adapter is imported only in
  `main.py`; long route names.
- **Out of scope:** Manual POST (D25), raw byte download, auth, pagination,
  frontend.
- **Acceptance:** The three endpoints return correct status codes and payloads
  with fakes; `create_app` DI extended; route import boundary clean; tests green.

### Slice 6: Boundary hardening + end-to-end + phase audit

- **Goal:** Lock the new surface into the boundary safety net, extend the
  end-to-end happy path, and confirm hygiene before commit.
- **Files likely to change:** `tests/test_architecture_boundaries.py` (add
  `ClipSelector` to `test_provider_interfaces_live_in_ports`; add the three
  persistence/read use-cases to the asset-use-case hint map; add `SelectClips` to
  the generation-use-case hint map; add the `DeterministicClipSelector`
  confinement test); `tests/test_draft_planning_workflow.py` (extend happy path)
  or new `tests/test_clip_selection_workflow.py`; `.gitignore` (confirm
  `data/assets/selected_clips/*` is covered -- expected no change).
- **Tests to add:** The boundary assertions above; the extended/new workflow test
  (see Test Checklist -- end-to-end). A full `pytest -q` run is green.
- **Boundaries at risk:** This slice is the safety net; guard against
  infrastructure leaking into application/api and against generated artifacts
  being tracked.
- **Out of scope:** Everything in the phase-wide out-of-scope list below.
- **Acceptance:** All boundary tests and the full suite green; ignore rules
  correct; phase-auditor criteria satisfied.

## Slice Order and Dependencies

```
1 (domain) -> 2 (port) -> +-> 3 (deterministic adapter + fake) -+
                          +-> 4 (use-cases) ------------------- +-> 5 (API + wiring) -> 6 (hardening + E2E + audit)
```

Slices 3 and 4 are independent: the use-case tests rely on a fake selector, not
the deterministic adapter. Do Slice 3 before Slice 4 only so the default adapter
exists when wiring in Slice 5. Everything else is strictly sequential. This is
the implementation order for the later Codex phase: (1) domain model and asset
kind, (2) port, (3) deterministic selector and test fake, (4) application
use-cases and JSON helpers, (5) API response models/routes and composition root
wiring, (6) boundary tests, E2E workflow test, then full validation.

## Agent Checkpoints

- **architecture-reviewer after Slice 2:** Ratify the port contract and D23
  (whole-set `select(Sequence[ClipCandidate]) -> Sequence[SelectedClip]`, policy
  in the adapter) before the adapter and use-cases build on it.
- **architecture-reviewer after Slice 4:** Confirm ports-only dependencies, the
  guard-before-read ordering (D21/D24), no transition call, the serializer living
  in the application layer, the natural `AssetNotFoundError(CLIP_CANDIDATES)` when
  no candidate set exists, and no infrastructure import.
- **architecture-reviewer after Slice 5:** Highest-risk slice (routes plus
  composition root); confirm routes call use-cases only, the adapter lives solely
  in `main.py`, and no lifecycle/versioning logic leaked into routes.
- **test-debugger:** Only when tests fail non-obviously. Likely spots: Slice 4
  float JSON round-trip and the 409-vs-404 guard ordering (status before
  candidate read); Slice 5 `TestClient` wiring of the new selector; Slice 6
  `get_type_hints` exact-equality on the new use-cases.
- **phase-auditor before commit at Slice 6:** Verify all acceptance criteria,
  that the full suite is green, that the database, secrets, and generated assets
  are ignored, and that no out-of-scope work leaked in (no real provider, no
  network, no download, no media storage, no render, no ranking/scoring, no
  selection editing, no run transition).

## Validation Plan

Run the full suite with the documented Windows venv command after each slice and
before commit:

```
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: the existing suite stays green and grows by the new domain, port,
adapter, use-case, API, and boundary/E2E tests above. For this docs-only change,
also run `git diff --check` (whitespace/conflict markers) and, optionally,
`pytest -q` to confirm the documentation commit leaves the suite untouched.

## Phase-Wide Out of Scope

Not implemented in this phase (Q14):

- Real clip download or any file/cache of media bytes (only JSON selected-clip
  metadata is persisted).
- Real Pexels/Pixabay (or any real provider) API or SDK.
- API key / secret handling.
- HTTP clients or any network I/O (`httpx`, `requests`, `urllib`, `aiohttp`,
  `socket`).
- FFmpeg and rendering; subtitles; voice/TTS.
- AI ranking, scoring, dedup, preference models, or any selection beyond the
  deterministic first-per-group order.
- More than one selected clip per `(scene_id, query_text)` group, or collapsing
  multiple queries of a scene into one scene-level clip.
- Selected-clip editing/approval UI, manual re-pick, or per-clip overrides.
- Scene refinement or any change to stock planning or clip candidate retrieval
  behavior.
- A new `RunStatus` or any run transition; clip selection is asset-only (D21).
- A `SelectedClip` domain wrapper / set wrapper (D22).
- A manual `POST /runs/{run_id}/selected-clips` route (D25).
- A `provider_registry.py` refactor (composition stays direct in `main.py`).
- Redis/Postgres/S3/SaaS features; workers/queues; pagination; auth; frontend.

## Open Questions

- **Selector adapter name.** `DeterministicClipSelector` (chosen, behavior-named)
  vs `StubClipSelector` (strict symmetry with `Stub*` composition defaults). The
  confinement test name follows whichever is chosen. Resolve at Slice 3; no
  downstream impact beyond the class/test name.
- **Scene-level collapse (future).** If a later plan emits multiple queries per
  scene and the timeline needs exactly one clip per scene, a scene-level
  selection policy will be needed. Deferred; the `ClipSelector` port is the place
  it would live, with no use-case/route change.
