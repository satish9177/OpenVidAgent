# Video Assembly Plan Foundation

Design document for the next phase. This records the intended design and slice
plan before any code is written. No backend, test, or product implementation is
part of this document. The phase adds a durable metadata plan between selected
clips and a future renderer. It does not download media, store media bytes,
invoke FFmpeg, generate voice or subtitles, or render video.

## Goal

Given the latest selected-clip set and latest approved scene table for a run,
produce a durable, versioned Video Assembly Plan. The plan explains the intended
timeline as metadata: scene order, the selected clip assigned to each
scene/query, target and source durations, narration context, simple transition
and continuity hints, and plan-level aspect-ratio/render intent.

This foundation is deliberately narrower than a render specification. It makes
the assembly decision inspectable and repeatable without prescribing FFmpeg
filters, downloading source URLs, resolving media paths, generating audio, or
transitioning the run lifecycle.

## Target Workflow

The existing asset-only tail is extended by one step. The run reaches
`scenes_approved` exactly as today and remains there while stock planning, clip
retrieval, clip selection, and assembly planning create independently versioned
JSON assets.

```text
create run
-> generate script draft
-> approve script
-> generate scene table
-> approve scenes                    # run reaches scenes_approved
-> generate stock plan               # run stays scenes_approved
-> retrieve clip candidates          # run stays scenes_approved
-> select clips                      # run stays scenes_approved
-> generate video assembly plan      # NEW: reads latest selected clips and
                                     # latest scene table, persists metadata,
                                     # run stays scenes_approved
```

The target product workflow is:

```text
prompt -> script draft -> scene table -> stock plan -> clip candidates
       -> selected clips -> video assembly plan
```

## Architecture Rule

Dependencies point inward:

`API/UI -> application use-cases -> domain models/services -> ports/interfaces -> infrastructure adapters`

- The domain remains framework-free and serialization-free.
- Application use-cases orchestrate repositories, storage, latest-asset readers,
  and the planner port. They do not import infrastructure or invoke media tools.
- `VideoAssemblyPlanner` is a port expressed only in domain types.
- `DeterministicVideoAssemblyPlanner` is a pure infrastructure adapter with no
  network, filesystem, subprocess, FFmpeg, API, or application dependency.
- API routes call application use-cases only. Lifecycle and versioning rules do
  not move into route functions.
- Concrete planner wiring remains explicit in `backend/app/main.py`.

## Existing Foundation

This design is based on the current implementation, not only the earlier design
notes:

- `VersionedAsset` stores `asset_id`, `kind`, `version`, `uri`, and string
  metadata. The generic repository and storage ports already support new asset
  kinds without a database schema change.
- `AssetKind` currently includes `SCRIPT`, `SCENE_TABLE`, `STOCK_PLAN`,
  `CLIP_CANDIDATES`, `SELECTED_CLIPS`, `STOCK_CLIP`, `VOICE`, `SUBTITLE`, and
  `RENDER`.
- `SceneSpec` is a frozen domain dataclass with `scene_id`, `narration`,
  `visual_query`, and `duration_seconds`. A scene table's tuple order is the
  only authoritative scene order in the current model.
- `SelectedClip` is a frozen domain dataclass containing the ten copied
  `ClipCandidate` fields plus `selection_reason`. It contains `scene_id` and
  `query_text`, but no scene position, narration, or target timeline duration.
- `GetLatestSceneTable` returns the latest parsed `SceneTable(asset, scenes)` and
  raises `AssetNotFoundError(run_id, SCENE_TABLE)` when missing.
- `GetLatestSelectedClipSet` returns the latest parsed
  `SelectedClipSet(asset, selected_clips)` and raises
  `AssetNotFoundError(run_id, SELECTED_CLIPS)` when missing.
- Scene tables cannot be recreated after scene approval. Therefore, while the
  run remains `scenes_approved`, the latest scene table is stable and is the
  correct authority for timeline ordering and narration context.
- Clip selection is allowed only at `scenes_approved`, writes metadata-only JSON,
  and does not transition the run. Assembly planning follows that asset-only
  lifecycle pattern.
- `backend/app/ports/providers.py` holds runtime-checkable planner/provider
  protocols using domain types. `backend/app/infrastructure/generation` holds
  pure deterministic defaults, and `backend/app/main.py` wires those defaults
  through `app.state`.
- Existing architecture tests scan domain, application, API, ports, and the
  generation package for forbidden imports. They also confine concrete defaults
  such as `DeterministicClipSelector` to the composition root.
- Persistence is kind-agnostic: SQLite stores `assets.kind` as text without an
  enum check constraint, local storage derives paths from `kind.value`, and the
  in-memory fakes key generically on `(run_id, kind)`. No SQLite migration or
  storage refactor is needed.

## Answers to Design Questions

| # | Question | Decision |
| --- | --- | --- |
| 1 | Domain model name? | `VideoAssemblySegment` (D28), a frozen metadata-only domain dataclass. |
| 2 | Plan/read model name? | `VideoAssemblyPlan` (D28), an application `NamedTuple(asset, segments)`. No domain plan wrapper. |
| 3 | New asset kind? | Yes: `AssetKind.VIDEO_ASSEMBLY_PLAN = "video_assembly_plan"` (D26). |
| 4 | Reference or copy selected-clip metadata? | Copy the selected clip fields needed for durable planning, including `provider` and `provider_clip_id` as the stable back-reference (D28). |
| 5 | Segment granularity? | One segment per `SelectedClip`, which is currently one per `(scene_id, query_text)` selection group (D28). Preserve selected-clip order within each scene. |
| 6 | Planner port? | Yes: `VideoAssemblyPlanner.plan(scenes, selected_clips) -> Sequence[VideoAssemblySegment]` (D29). It imports only domain types. |
| 7 | Default deterministic behavior? | Iterate scenes in latest scene-table order, emit matching selected clips in their stable input order, assign zero-based `order_index`, copy metadata, use `cut`, and add a fixed continuity note (D29). |
| 8 | Read latest scene table too? | Yes. Selected clips alone cannot provide reliable scene order, narration, visual intent, or target scene duration (D30). Never infer order by sorting `scene_id`. |
| 9 | Use-cases? | `CreateVideoAssemblyPlan`, `GenerateVideoAssemblyPlan`, `ListVideoAssemblyPlans`, and `GetLatestVideoAssemblyPlan` (D30/D31). |
| 10 | API routes? | Generate, list, and latest only under `/video-assembly-plans` (D31). No manual create route. |
| 11 | Run status gate? | `RunStatus.SCENES_APPROVED`, checked before either latest-asset read (D27/D30). |
| 12 | Run transition? | None. The phase is asset-only and adds no `RunStatus` (D27). |
| 13 | Storage format? | Versioned JSON segment metadata plus plan-level string metadata on `VersionedAsset`; no media bytes and no schema migration (D26/D28). |
| 14 | What is deferred? | Downloads, providers, media storage, voice, subtitles, FFmpeg/rendering, executable edit decisions, scoring, UI, lifecycle changes, and upstream behavior changes. |

## Design Decisions

These decisions continue the project decision log: D1-D7 cover script/scene
planning, D8-D13 stock planning, D14-D19 clip retrieval, and D20-D25 selected
clip selection.

### D26. Add `AssetKind.VIDEO_ASSEMBLY_PLAN` as a metadata-only asset

- Add `VIDEO_ASSEMBLY_PLAN = "video_assembly_plan"` to `AssetKind`.
- It represents an intended timeline assembled from selected-clip metadata. It
  is distinct from `SELECTED_CLIPS` (selection results), `STOCK_CLIP` (future
  downloaded media), and `RENDER` (future rendered output).
- Persist only JSON metadata through the existing `StoragePort`, indexed through
  `VersionedAssetRepository`. URLs remain references and are never fetched.
- Store plan-level string metadata on the `VersionedAsset`:
  - `source`: `"generated"` or `"manual"` for internal creation.
  - `aspect_ratio`: `"16:9"` for this foundation.
  - `render_intent`: `"voiceover_b_roll"` (a forward-looking intent label for
    the future render phase; it does not mean voiceover generation is
    implemented in this phase).
  - `scene_table_asset_id` and `scene_table_version` for generated provenance.
  - `selected_clips_asset_id` and `selected_clips_version` for generated
    provenance.
- Provenance version values are encoded as strings because
  `VersionedAsset.metadata` is `Mapping[str, str]`.
- The JSON payload itself is a list of flat segment objects, mirroring the
  existing scene, stock-plan, candidate, and selected-clip assets. The read model
  combines this payload with its `VersionedAsset`, so plan-level intent and
  provenance remain available without duplicating them in every segment.
- No SQLite migration, storage adapter change, `.gitignore` change, media path,
  or JSON schema registry is added.

### D27. Assembly planning is asset-only, gated at `scenes_approved`, and never transitions the run

- Define `_VIDEO_ASSEMBLY_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})` in
  the new application module.
- Both `GenerateVideoAssemblyPlan` and the internal
  `CreateVideoAssemblyPlan` enforce this status. The generation use-case checks
  it first so an invalid run returns `AssetCreationRejectedError` (HTTP 409)
  before any dependency can produce a 404.
- Re-generating while `scenes_approved` creates the next
  `VIDEO_ASSEMBLY_PLAN` version and leaves the run unchanged.
- Add no status between `scenes_approved` and `rendered`, and call no run
  transition method. A future renderer remains responsible for the eventual
  `rendered` transition.

### D28. Add `VideoAssemblySegment`; use an application `VideoAssemblyPlan` read model

Add a frozen domain dataclass:

```python
@dataclass(frozen=True)
class VideoAssemblySegment:
    scene_id: str
    query_text: str
    narration: str
    visual_query: str
    provider: str
    provider_clip_id: str
    title: str
    preview_url: str
    source_url: str
    target_duration_seconds: float
    source_duration_seconds: float
    width: int
    height: int
    order_index: int
    transition: str
    continuity_note: str
    selection_reason: str
```

Field semantics:

- `scene_id` and `query_text` preserve the selection grouping relationship.
- `narration` and `visual_query` are copied from the matching `SceneSpec`. The
  narration is planning context tied to the scene, not generated voice audio and
  not an instruction to synthesize or replay narration per segment.
- `provider`, `provider_clip_id`, `title`, `preview_url`, `source_url`, `width`,
  `height`, and `selection_reason` are copied from `SelectedClip`. Copying makes
  each plan version durable even when selected clips are regenerated later.
- `source_duration_seconds` is the selected clip's duration.
- `target_duration_seconds` is timeline intent derived from the scene duration,
  not copied from the source clip. For today's one-selection-per-scene flow it
  equals `SceneSpec.duration_seconds`. If a future selected set contains
  multiple clips for one scene, the deterministic foundation divides the scene
  duration evenly across those clips. Those target durations should
  approximately sum to the scene target, subject to normal floating-point
  precision; the foundation adds no remainder/rounding correction, so tests
  compare sums with a tolerance rather than exact float equality. It does not
  decide trim, loop, speed, crop, or padding behavior.
- `order_index` is zero-based and contiguous over the full plan.
- `transition` is the non-executable hint `"cut"` for every segment.
- `continuity_note` is the non-executable hint `"ordered_by_scene_table"` for
  every segment.

The copied fields are descriptive metadata, not media and not executable render
commands. In particular, the plan does not contain local file paths, byte
ranges, FFmpeg filters, codec settings, frame rates, trim points, crop geometry,
audio tracks, subtitle tracks, or output paths.

Add `VideoAssemblyPlan` in the application layer as:

```python
class VideoAssemblyPlan(NamedTuple):
    asset: VersionedAsset
    segments: tuple[VideoAssemblySegment, ...]
```

Do not add a domain-level plan wrapper. Plan-level aspect ratio, render intent,
and source provenance live on `asset.metadata`; the application read model
already carries that asset.

### D29. `VideoAssemblyPlanner` consumes scenes and selections; the deterministic adapter uses scene-table order

Define a runtime-checkable port in `backend/app/ports/providers.py`:

```python
@runtime_checkable
class VideoAssemblyPlanner(Protocol):
    def plan(
        self,
        scenes: Sequence[SceneSpec],
        selected_clips: Sequence[SelectedClip],
    ) -> Sequence[VideoAssemblySegment]:
        """Create metadata-only timeline segments."""
        ...
```

The port imports only `SceneSpec`, `SelectedClip`, and `VideoAssemblySegment`
from the domain. It has no repository, storage, FastAPI, provider SDK, HTTP,
filesystem, subprocess, or renderer type in its contract.

Add `DeterministicVideoAssemblyPlanner` under
`backend/app/infrastructure/generation`. Its algorithm is:

1. Treat the `scenes` sequence order as authoritative. Never parse or
   lexicographically sort `scene_id`.
2. Group selected clips by `scene_id`, retaining their original input order.
3. Iterate scenes in table order and emit one segment for every selected clip
   matching that scene.
4. If a scene has multiple selected clips, divide the scene duration evenly
   across those clips for this deterministic foundation. The resulting target
   durations should approximately sum to the scene target, subject to normal
   floating-point precision. Scenes with no selected clip emit no segment.
5. Assign contiguous zero-based `order_index` values as segments are emitted.
6. Copy scene and selected-clip metadata and set `transition = "cut"` and
   `continuity_note = "ordered_by_scene_table"`.

The current workflow guarantees that generated selected clips refer to scenes
from the approved scene table. The adapter treats a selected clip whose
`scene_id` is absent from the supplied scene table as an invalid planner input
and raises `ValueError` rather than silently dropping it or inventing narration
and duration. This is an internal invariant violation, not an expected outcome
of the public generate-only flow, so the `ValueError` is intentionally not
mapped to HTTP 409 in this foundation; if the invariant somehow broke through
the public API it would surface as HTTP 500 until a future manual
selection/assembly surface promotes it to a named application/domain error with
explicit 409 mapping.

The adapter is pure and repeatable. Empty scenes or an empty selected-clip set
produce an empty segment sequence. It performs no randomness, ranking, scoring,
deduplication, network request, media probe, file access, subprocess call, or
rendering.

### D30. `GenerateVideoAssemblyPlan` composes both latest read paths; selected clips are read first

`GenerateVideoAssemblyPlan` receives only `run_id` from the API. It composes:

- `RunRepository` for the D27 guard.
- `GetLatestSelectedClipSet` for the immediate upstream selection artifact.
- `GetLatestSceneTable` for authoritative order, narration, visual query, and
  target duration.
- `VideoAssemblyPlanner` for pure mapping policy.
- `CreateVideoAssemblyPlan` for guarded persistence and versioning.

Execution order is locked:

1. Require the run and check `RunStatus.SCENES_APPROVED`.
2. Read the latest selected-clip set.
3. Read the latest scene table.
4. Call the planner once with both parsed sequences.
5. Persist through `CreateVideoAssemblyPlan` with `source = "generated"`, fixed
   aspect/render metadata, and both source asset IDs/versions.

This ordering produces the intended errors:

- A missing run raises `RunNotFoundError`.
- An invalid status raises `AssetCreationRejectedError(VIDEO_ASSEMBLY_PLAN)`
  before either asset read, so the API returns 409 rather than a dependency 404.
- Missing selected clips naturally raises
  `AssetNotFoundError(SELECTED_CLIPS)` from `GetLatestSelectedClipSet`.
- If selected clips exist but the scene table is missing, the existing
  `GetLatestSceneTable` naturally raises `AssetNotFoundError(SCENE_TABLE)`.

Reading the scene table is required. Sorting `scene_id` strings would produce
incorrect order for IDs such as `scene-2` and `scene-10`, and selected clips do
not carry narration, visual query, or a target scene duration. No new ordering
field is added to `SelectedClip`, preserving existing selection behavior.

### D31. Keep creation internal and expose generate/list/latest only

- `CreateVideoAssemblyPlan` is the internal guarded persistence use-case. It
  accepts caller-supplied `VideoAssemblySegment` entries, stores JSON, computes
  the next version, and sets the supplied/default plan metadata. It owns the
  canonical D27 status guard and never transitions the run.
- `GenerateVideoAssemblyPlan` is the only public write path this phase and
  composes `CreateVideoAssemblyPlan`.
- Expose only:
  - `POST /runs/{run_id}/video-assembly-plans/generate`
  - `GET /runs/{run_id}/video-assembly-plans`
  - `GET /runs/{run_id}/video-assembly-plans/latest`
- Do not expose `POST /runs/{run_id}/video-assembly-plans` for manual segment
  creation. Keeping creation internal avoids accepting executable-looking edit
  instructions before validation and rendering semantics exist.
- The latest response returns the parsed `segments` plus its `asset`, including
  aspect ratio, render intent, and source provenance in `asset.metadata`.

## Domain Model Proposal

- Add `AssetKind.VIDEO_ASSEMBLY_PLAN = "video_assembly_plan"`.
- Add and export frozen `VideoAssemblySegment` with exactly the D28 fields.
- Do not change `SceneSpec`, `SelectedClip`, `RenderSpec`, `RunStatus`, or run
  transition rules.
- Do not add media bytes, local media paths, trim/crop/filter fields, or a domain
  plan wrapper.
- Add `VideoAssemblyPlan` only as an application read model pairing a
  `VersionedAsset` with parsed segments.

## Asset / Storage Decision

- Store each plan as JSON bytes through `StoragePort` and index it under
  `(run_id, AssetKind.VIDEO_ASSEMBLY_PLAN)`.
- Use private application helpers `_segments_to_bytes` and
  `_segments_from_bytes`. They serialize a JSON list of flat objects and restore
  `target_duration_seconds`/`source_duration_seconds` as `float`, dimensions and
  `order_index` as `int`, and the remaining fields as strings.
- Store fixed plan intent and generated provenance in `VersionedAsset.metadata`
  as described in D26.
- A second generation creates version 2 and leaves earlier plans and their
  provenance intact.
- The only stored bytes are JSON metadata. `preview_url` and `source_url` are
  copied references and are never opened.
- Existing generic SQLite, filesystem, and in-memory adapters require no code or
  schema behavior change beyond accepting the new enum value naturally.

## Port / Planner Decision

- Add and export `VideoAssemblyPlanner` from the ports package.
- Add and export `DeterministicVideoAssemblyPlanner` from the generation adapter
  package.
- Add a recording `FakeVideoAssemblyPlanner` in test fakes for use-case and API
  tests. It records scene and selection arguments and returns configured
  segments; those tests do not depend on the concrete adapter.
- Wire only the port into application/API code. The concrete adapter is imported
  only by `main.py` and its own adapter tests.
- Do not place the planner in `provider_registry.py`; direct composition-root
  wiring matches the current scene/stock/retrieval/selection pattern and avoids
  an unrelated registry refactor.

## Use-Case Plan

Create `backend/app/application/use_cases/video_assembly_plan_assets.py`, using
the existing metadata-asset modules as the structural template.

1. **`CreateVideoAssemblyPlan`**
   - `execute(run_id, segments, source="manual", asset_metadata=None) -> VersionedAsset`.
   - Requires the run and enforces D27.
   - Computes the next `VIDEO_ASSEMBLY_PLAN` version, merges the fixed
     `aspect_ratio`/`render_intent` defaults with source/provenance metadata,
     writes JSON through `StoragePort`, and saves the asset index.
   - Constructor dependencies are ports/factories only: `RunRepository`,
     `VersionedAssetRepository`, `StoragePort`, and optional `asset_id_factory`.
   - Does not transition the run.

2. **`GenerateVideoAssemblyPlan`**
   - `execute(run_id) -> VersionedAsset`.
   - Applies the D27 guard before reads, then follows the exact D30 dependency
     order.
   - Calls the planner exactly once and persists through
     `CreateVideoAssemblyPlan` with generated provenance.
   - Constructor dependencies are `RunRepository`, `VideoAssemblyPlanner`,
     `GetLatestSelectedClipSet`, `GetLatestSceneTable`, and
     `CreateVideoAssemblyPlan`.
   - Does not parse storage itself and does not transition the run.

3. **`ListVideoAssemblyPlans`**
   - `execute(run_id) -> Sequence[VersionedAsset]`.
   - Lists `VIDEO_ASSEMBLY_PLAN` assets in repository version order.

4. **`GetLatestVideoAssemblyPlan`**
   - `execute(run_id) -> VideoAssemblyPlan`.
   - Reads the latest asset, raises
     `AssetNotFoundError(VIDEO_ASSEMBLY_PLAN)` when absent, loads its JSON, and
     returns the parsed read model.

Export all four use-cases and `VideoAssemblyPlan` from
`backend/app/application/use_cases/__init__.py`.

## API Route Plan

Add response DTOs and routes in the existing `backend/app/api/assets.py` module.

| Method | Path | Returns | Purpose |
| --- | --- | --- | --- |
| `POST` | `/runs/{run_id}/video-assembly-plans/generate` | `201 AssetResponse` | Generate from the latest selected clips and scene table. |
| `GET` | `/runs/{run_id}/video-assembly-plans` | `list[AssetResponse]` | List plan asset versions. |
| `GET` | `/runs/{run_id}/video-assembly-plans/latest` | `VideoAssemblyPlanResponse` | Return the latest asset and parsed segments. |

Add `VideoAssemblySegmentModel.from_domain` and
`VideoAssemblyPlanResponse.from_video_assembly_plan`. Add a
`get_video_assembly_planner(request)` resolver reading
`request.app.state.video_assembly_planner`.

The generate route has no request body in this foundation: aspect ratio and
render intent are fixed deterministic metadata. Existing application error
handlers provide 404/409 behavior. There is no manual-create request DTO, raw
asset-byte endpoint, download endpoint, render endpoint, or media endpoint.

## Composition Root Decision

- Add optional `video_assembly_planner: VideoAssemblyPlanner | None = None` to
  `create_app(...)`.
- Default it to `DeterministicVideoAssemblyPlanner()` and assign
  `app.state.video_assembly_planner`.
- Keep all repository, storage, latest-reader, create-use-case, and generation
  use-case construction explicit in the route dependency functions, following
  the current asset API pattern.
- Do not alter `provider_registry.py`, settings, environment variables, secrets,
  or lifespan behavior. The default planner is pure and owns no resource.

## Test Checklist

### Domain and Serialization

- `AssetKind.VIDEO_ASSEMBLY_PLAN.value == "video_assembly_plan"` and is distinct
  from `SELECTED_CLIPS`, `STOCK_CLIP`, and `RENDER`.
- `VideoAssemblySegment` is frozen and has exactly the D28 fields.
- JSON round-trip preserves all fields and numeric types.
- Latest-read returns the newest parsed plan; missing latest raises
  `AssetNotFoundError(VIDEO_ASSEMBLY_PLAN)`.

### Planner and Port

- A fake satisfies runtime `isinstance(fake, VideoAssemblyPlanner)`.
- Port type hints use only `Sequence[SceneSpec]`, `Sequence[SelectedClip]`, and
  `Sequence[VideoAssemblySegment]`.
- Deterministic planner preserves scene-table order even when `scene_id` lexical
  order differs.
- Multiple selections for one scene preserve selection input order and split
  the scene duration evenly; assert the split sums to the scene target within a
  floating-point tolerance rather than by exact equality.
- A scene present in the scene table with no matching selected clip emits no
  segment, while neighboring scenes still emit and `order_index` stays
  contiguous.
- `order_index` is contiguous and zero-based.
- Scene and clip fields are copied correctly; target and source durations stay
  distinct.
- Transition and continuity values are exactly `cut` and
  `ordered_by_scene_table`.
- Unknown selected-clip scene IDs raise `ValueError`; empty inputs are
  deterministic and produce no segments.
- Repeated calls with the same inputs return equal outputs.

### Use-Cases and Lifecycle

- Create stores `VIDEO_ASSEMBLY_PLAN`, increments versions, and persists only
  JSON.
- Generated metadata includes `source=generated`, `aspect_ratio=16:9`,
  `render_intent=voiceover_b_roll`, and both source asset IDs/versions.
- The status guard rejects every state except `scenes_approved` and persists
  nothing.
- Invalid status is checked before selected-clip and scene-table reads, planner
  work, or persistence.
- Missing selected clips naturally raises `AssetNotFoundError(SELECTED_CLIPS)`.
- With selected clips present but no scene table, generation naturally raises
  `AssetNotFoundError(SCENE_TABLE)`.
- The planner is called once with the latest selected clips and latest scenes.
- Create owns the canonical guard; generate composes create.
- The run remains exactly `scenes_approved` after create and generate.

### API

- Generate returns 201 with `kind=video_assembly_plan`, version 1, and generated
  metadata.
- List returns versions in order; latest returns parsed segments and metadata.
- A second generate creates version 2.
- Missing run/dependencies map to 404; invalid status maps to 409 before a
  dependency 404.
- Only generate/list/latest routes exist; no manual create or render route is
  registered.

### Architecture Boundaries and No-Render Safety

- Domain auto-scan confirms no framework or outer-layer imports.
- Add `VideoAssemblyPlanner` to the provider-interface location test.
- Extend constructor type-hint tests for all four use-cases and their expected
  ports/sibling use-cases.
- Application auto-scan confirms no infrastructure import.
- API route scan confirms routes import use-cases/ports, not concrete adapters.
- Generation-package scans confirm no API/application imports and no external,
  network, filesystem-media, subprocess, or FFmpeg modules.
- Add a confinement test proving only `main.py` imports
  `DeterministicVideoAssemblyPlanner` outside its defining/export modules and
  adapter tests.
- Assert persisted bytes decode as JSON and contain no media bytes/local media
  path fields.
- Search the implementation diff for HTTP clients, provider SDKs, API-key
  handling, FFmpeg/subprocess calls, voice/subtitle generation, ranking/scoring,
  UI, and status transitions; none should be present.

### End-to-End

Extend the existing workflow test through:

```text
prompt -> script -> scene table -> stock plan -> clip candidates
       -> selected clips -> video assembly plan
```

Assert generation returns 201; latest returns non-empty ordered segments; each
segment references a selected provider clip and matching scene; narration and
target duration come from the scene table; source duration comes from the
selected clip; URLs remain `memory://`; metadata declares `16:9` and
`voiceover_b_roll`; and the run remains `scenes_approved`.

## Implementation Slices

Implement one slice at a time in inward-to-outward order. Run focused tests after
each slice and the full suite after the final slice.

### Slice 1: Domain - asset kind and segment

- **Files:** `backend/app/domain/models.py`, `backend/app/domain/__init__.py`,
  new/updated domain tests.
- **Change:** Add D26 asset kind and exact D28 frozen dataclass/export.
- **Tests:** Kind distinction, exact fields, frozen behavior, domain boundary.
- **Boundary:** Domain imports standard library/domain only.
- **Acceptance:** Domain tests and boundary scan pass; no other layer changes.

### Slice 2: Port - `VideoAssemblyPlanner`

- **Files:** `backend/app/ports/providers.py`, `backend/app/ports/__init__.py`,
  new port contract tests.
- **Change:** Add/export the D29 runtime-checkable protocol.
- **Tests:** Runtime conformance, module location, exact type hints.
- **Boundary:** Port imports domain types only.
- **Acceptance:** Port tests and architecture tests pass.

### Slice 3: Deterministic adapter and fake

- **Files:** new
  `backend/app/infrastructure/generation/deterministic_video_assembly_planner.py`,
  generation package export, test fake exports, generation adapter tests.
- **Change:** Implement the D29 stable mapping algorithm and recording fake.
- **Tests:** Order, field copies, duration split, hints, unknown scenes, empty
  input, repeatability, port conformance.
- **Boundary:** No application/API/external/media imports.
- **Acceptance:** Focused adapter and generation-boundary tests pass.

### Slice 4: Application - plan asset use-cases

- **Files:** new
  `backend/app/application/use_cases/video_assembly_plan_assets.py`, use-case
  package export, new use-case tests.
- **Change:** Add read model, JSON helpers, create/generate/list/latest use-cases,
  D27 guard, D30 ordering, and provenance metadata.
- **Tests:** Versioning, round-trip, source metadata, latest/list, errors,
  guard-before-read, planner call, no transition.
- **Boundary:** Dependencies are ports and sibling use-cases only.
- **Acceptance:** Focused use-case and application-boundary tests pass.

### Slice 5: API routes and composition wiring

- **Files:** `backend/app/api/assets.py`, `backend/app/main.py`, API tests.
- **Change:** Add DTOs, generate/list/latest routes, dependency resolver, and
  default planner wiring.
- **Tests:** 201/404/409, latest/list/versioning, route absence, injected fake.
- **Boundary:** Routes contain no planner, lifecycle, storage, or version logic;
  concrete adapter appears only in composition root.
- **Acceptance:** API and route-boundary tests pass.

### Slice 6: Boundary hardening, E2E, and phase audit

- **Files:** `tests/test_architecture_boundaries.py`, existing/new workflow test;
  `.gitignore` only if inspection finds a real gap (none expected).
- **Change:** Lock port/use-case/adapter confinement and extend the full workflow.
- **Tests:** Focused architecture/E2E tests, then full suite.
- **Boundary:** Audit every layer and all explicit non-goals.
- **Acceptance:** Full suite and `git diff --check` pass; no generated media,
  secrets, database files, caches, or virtual-environment files are staged.

## Slice Order and Dependencies

```text
1 domain -> 2 port -> 3 deterministic adapter + fake
                    -> 4 application use-cases
                    -> 5 API + composition root
                    -> 6 boundaries + E2E + audit
```

Slices 3 and 4 can be developed independently after Slice 2 because application
tests use the fake planner. The concrete adapter must exist before Slice 5 wires
the default.

## Validation Plan

For this docs-only change:

```powershell
git diff --check
```

Optionally run the unchanged full suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

For the later implementation phase, run focused tests after every slice, then
both commands above before commit. Also inspect staged files to confirm no media,
secrets, SQLite databases, caches, or virtual-environment files are included.

## Explicit Non-Goals / Deferred Work

- Real clip download, cache, media probing, or local media path resolution.
- Pexels, Pixabay, or any provider/API-key integration.
- HTTP clients, provider SDKs, or network access.
- Media storage or storage-adapter changes.
- FFmpeg, subprocess calls, rendering, codecs, frame rates, filter graphs,
  trim/loop/speed/crop/pad decisions, or output files.
- Voiceover generation, TTS providers, audio alignment, mixing, or ducking.
- Subtitle generation, timing, styling, or burn-in.
- AI ranking, scoring, deduplication, clip replacement, or continuity analysis.
- Selected-clip or assembly-plan editing UI and manual public create routes.
- Scene refinement or changes to script, scene, stock planning, candidate
  retrieval, or selected-clip behavior.
- A new run status or any run transition.
- Provider registry refactoring, a generic pipeline orchestrator, workers, or
  queues.
- Redis, Postgres, S3, cloud/SaaS features, auth, or pagination.
- Database schema changes or a generic JSON schema/version registry.
- Turning transition/continuity strings into executable renderer instructions.

## Open Questions

- **Configurable render intent.** `16:9` and `voiceover_b_roll` are fixed for
  this foundation. A later phase must decide whether they become request fields,
  run settings, or a richer render profile before supporting vertical/square
  output. No generic render-profile model is added now.
- **Source-duration mismatch.** The plan records target and source durations but
  deliberately does not decide whether a future renderer trims, loops, slows,
  crops, pads, or rejects a short source clip.
- **User-reachable mismatch errors.** Unknown selected-clip scene IDs currently
  represent an internal invariant violation. If manual selection/assembly APIs
  are introduced, promote the planner's `ValueError` to a named domain or
  application error with an explicit 409 mapping.
- **Executable transitions.** `cut` is a descriptive placeholder. Transition
  durations, handles, and FFmpeg mapping belong to a future rendering design,
  not this metadata foundation.
