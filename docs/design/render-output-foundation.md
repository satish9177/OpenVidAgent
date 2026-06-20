# Render Output Foundation

Design document for the next phase. This records the intended design and slice
plan before any code is written. No backend, test, or product implementation is
part of this document. The approved direction is a metadata-only render output
manifest: it records that a render was intentionally not performed, preserves
the render-plan provenance/profile, and establishes the output API boundary
without creating a video, invoking FFmpeg, or fabricating a file URI.

## Goal

Given the latest render plan for a run, produce a durable, versioned
`RenderOutputManifest` that describes the intended output profile and estimated
timeline while stating explicitly that no video exists. The artifact answers:
which render plan was considered, what output profile would be used, how many
segments and how much planned duration it contains, and why no rendered file is
available.

This phase establishes output lifecycle, provenance, persistence, API shape,
dependency injection, and no-real-render architecture protections. It does not
create an MP4, invoke or preview FFmpeg, inspect media, resolve paths, check file
existence, transition the run, or activate the existing real-render contracts.

## Target Workflow

The asset-only pipeline gains one final metadata artifact while the run remains
at `scenes_approved`:

```text
create run
-> generate script draft
-> approve script
-> generate scene table
-> approve scenes
-> generate stock plan
-> retrieve clip candidates
-> select clips
-> generate video assembly plan
-> download clips                 # metadata-only manifest
-> generate voiceover             # metadata-only manifest
-> generate subtitles             # metadata-only manifest
-> generate render plan           # metadata-only joined timeline
-> generate render output         # NEW: metadata-only, not rendered
```

The target workflow for this phase is:

```text
prompt -> script draft -> scene table -> stock plan -> clip candidates
       -> selected clips -> video assembly plan -> downloaded clips
       -> voiceover -> subtitles -> render plan -> render output manifest
```

## Architecture Rule

Dependencies point inward:

`API/UI -> application use-cases -> domain models/services -> ports/interfaces -> infrastructure adapters`

- The domain remains framework-free and serialization-free.
- Application use-cases own lifecycle guards, latest-asset composition,
  render-profile default resolution, provenance, versioning, and persistence.
- `RenderOutputGenerator` is a metadata-only port expressed with domain and
  standard-library types. It is not a renderer.
- `StubRenderOutputGenerator` is a pure deterministic adapter. It performs no
  filesystem, media, network, subprocess, or FFmpeg operation.
- API routes call application use-cases only and contain no lifecycle,
  versioning, profile, or output-generation policy.
- Concrete adapter wiring remains explicit in `backend/app/main.py`.
- Existing `Renderer` and `RenderSpec` stay reserved for the future phase that
  creates actual rendered video bytes.

## Existing Foundation

This design is grounded in the current implementation:

- `AssetKind.RENDER_PLAN = "render_plan"` identifies the latest metadata join
  artifact. `AssetKind.RENDER = "render"` still represents future rendered
  video output and is not used by current asset use-cases.
- `RenderPlanSegment` is a frozen domain dataclass containing ordered clip,
  voiceover, subtitle, and visual timeline metadata. It contains no output path,
  FFmpeg command, media bytes, or render result.
- `RenderPlan` is an application read model pairing a `VersionedAsset` with
  parsed `RenderPlanSegment` entries.
- `GetLatestRenderPlan` reads the latest `RENDER_PLAN` JSON asset and naturally
  raises `AssetNotFoundError(run_id, RENDER_PLAN)` when none exists.
- `GenerateRenderPlan` already validates upstream order-index sets and stores
  provenance for assembly, downloaded clips, voiceover, and subtitles. The
  output phase therefore needs only the latest render plan; it must not re-read
  or rejoin those upstream artifacts.
- Render-plan asset metadata already carries string render-profile values:
  `aspect_ratio`, `resolution_width`, `resolution_height`, `fps`, `container`,
  and `render_intent`.
- `RunStatus.SCENES_APPROVED` is the current asset-only gate. Render planning
  does not transition the run. `RunStatus.RENDERED` already exists and remains
  reserved for the future real-render phase. This metadata-only render output
  phase adds no new status and performs no run transition.
- Existing `Renderer.render(RenderSpec) -> VersionedAsset` remains a port for a
  future real-render phase. Activating it now would conflate a metadata manifest
  with actual video bytes.
- The generic asset repository and storage ports support new kinds without a
  SQLite migration. Local storage writes JSON under a path derived from the
  asset kind, and in-memory tests use `memory://` storage URIs.
- Architecture tests already protect domain/application/API imports, generation
  adapter imports, constructor type hints, and concrete-adapter confinement.
- `provider_registry.py` is not part of composition for these deterministic
  pipeline adapters and remains unchanged.

## Problem Being Solved

`RENDER_PLAN` is complete render intent, not an output. It says which clip,
voiceover, subtitle, and timing metadata belong together, but there is no
versioned artifact describing the result boundary. Jumping directly to a real
FFmpeg implementation would introduce executable command construction,
filesystem destinations, installed-binary detection, media validation,
no-clobber rules, process failure handling, and output-byte semantics all at
once.

The project has deliberately introduced each pipeline boundary first as a safe,
versioned artifact. This phase applies the same pattern to output. It creates a
truthful manifest that says `not_rendered`, carries no fake URI, and records only
facts derivable from the render plan. A later phase can activate `Renderer` and
produce `AssetKind.RENDER` after those execution and security decisions receive
their own design.

## Design Questions and Answers

| # | Question | Decision |
| --- | --- | --- |
| 1 | Create a real MP4? | No (D56). Metadata-only JSON. |
| 2 | Invoke FFmpeg? | No. No subprocess and no command preview (D56). |
| 3 | Create a render output/job manifest? | Yes: one versioned `RENDER_OUTPUT` asset (D56/D57). |
| 4 | New asset kind? | `AssetKind.RENDER_OUTPUT = "render_output"` (D56). |
| 5 | Reuse `RENDER`? | No. `RENDER` remains reserved for future video bytes (D56). |
| 6 | Activate `Renderer`/`RenderSpec`? | No; both stay reserved for real rendering (D56/D58). |
| 7 | New port? | `RenderOutputGenerator`, distinct from `Renderer` (D58). |
| 8 | Domain model name? | `RenderOutputManifest` (D57). It is explicit that this is metadata, not a rendered video. |
| 9 | Manifest contents? | Status, render-plan provenance, profile, segment count, estimated duration, nullable output URI, and reason (D57). |
| 10 | Output URI now? | Field present but always `None`; JSON stores `null` (D57). |
| 11 | Fake `memory://` output URI? | No. A URI would falsely imply a file exists (D57). |
| 12 | Status? | `"not_rendered"`, never `"available"` (D57). |
| 13 | Fake size/checksum/duration? | No size/checksum. Estimated duration is derived from render-plan timing (D57/D59). |
| 14 | Future path fields? | No output path or storage key this phase (D57). |
| 15 | Copy render profile? | Yes, from latest render-plan metadata after use-case-owned default resolution (D59/D60). |
| 16 | Carry provenance? | Yes, in both the manifest and asset metadata (D57/D60). |
| 17 | Check media existence? | No (D59). |
| 18 | Revalidate internal timing? | No broad validation. Estimate duration from the maximum visual end time (D59). |
| 19 | Require a non-empty plan? | No. Empty plans are represented truthfully (D59). |
| 20 | Empty-plan behavior? | Persist `segment_count=0`, `estimated_duration_seconds=0.0`, `not_rendered`, and `output_uri=None` (D59). |
| 21 | New run status? | No (D56). |
| 22 | Transition to completed/rendered? | No. The run stays `scenes_approved` (D56). |
| 23 | Use-cases? | `CreateRenderOutput`, `GenerateRenderOutput`, `ListRenderOutputs`, `GetLatestRenderOutput` (D60). |
| 24 | API routes? | Generate/list/latest under `/render-outputs`; no manual create (D61). |
| 25 | No-real-render tests? | Domain/port/adapter/use-case/API/boundary/E2E checks listed below. |
| 26 | Deferred? | Real FFmpeg, video bytes, paths, probing, output validation, and lifecycle completion. |

## Design Decisions

These decisions continue the project log: D1-D49 cover the pipeline through
subtitles, and D50-D55 define the Render Plan Foundation.

### D56. Choose metadata-only output; add `RENDER_OUTPUT`; reserve all real-render contracts

- Add `AssetKind.RENDER_OUTPUT = "render_output"`.
- Do not reuse `AssetKind.RENDER`. `RENDER_OUTPUT` is one JSON manifest
  describing an absent/not-yet-rendered result; `RENDER` remains the future
  versioned video-file asset.
- Do not activate or modify `Renderer` or `RenderSpec`. The new phase-specific
  port has no compatibility obligation with real rendering.
- Add no `RunStatus` and make no transition. Generating or regenerating the
  manifest while `scenes_approved` creates another version and leaves the run
  unchanged.
- No video, FFmpeg invocation, FFmpeg command preview, subprocess, output path,
  media probe, file-existence check, or non-JSON write is allowed.

### D57. Add `RenderOutputManifest`; represent absence honestly; use an application `RenderOutput` read model

Add a frozen domain dataclass:

```python
@dataclass(frozen=True)
class RenderOutputManifest:
    status: str
    render_plan_asset_id: str
    render_plan_version: int
    render_intent: str
    aspect_ratio: str
    container: str
    resolution_width: int
    resolution_height: int
    fps: float
    segment_count: int
    estimated_duration_seconds: float
    output_uri: str | None
    generation_reason: str
```

Locked deterministic values and semantics:

- `status = "not_rendered"`.
- `output_uri = None`. The serializer emits JSON `null`; it does not omit the
  field and does not invent a `memory://` reference.
- `generation_reason = "metadata_only_foundation"`.
- `render_plan_asset_id` and `render_plan_version` identify the exact source.
- Profile values are copied from the resolved render-plan profile.
- `segment_count = len(render_plan.segments)`.
- `estimated_duration_seconds` is the maximum `visual_end_seconds` across render
  plan segments, or `0.0` for an empty plan. This is a metadata-derived estimate,
  not a media probe and not an assertion about a real file. It is a visual-track
  estimate by design: it is intentionally not a whole-timeline maximum across
  voiceover/subtitle windows, and this phase does not reconcile any
  visual/audio/subtitle duration divergence.
- Do not add output path, filename, byte size, checksum, codec, bitrate, command,
  process ID, progress, or file-existence fields.

Add an application read model:

```python
class RenderOutput(NamedTuple):
    asset: VersionedAsset
    manifest: RenderOutputManifest
```

The manifest is a single object, not one record per render-plan segment.

### D58. Add a metadata-only `RenderOutputGenerator` port distinct from `Renderer`

Define a runtime-checkable port in `backend/app/ports/providers.py`:

```python
@runtime_checkable
class RenderOutputGenerator(Protocol):
    def generate(
        self,
        render_plan_asset_id: str,
        render_plan_version: int,
        render_plan_segments: Sequence[RenderPlanSegment],
        render_profile: Mapping[str, str],
    ) -> RenderOutputManifest:
        ...
```

- The port uses only domain and standard-library types.
- It receives a fully resolved string profile from the application use-case.
- It has no `run_id` because this phase creates no run-scoped output URI or file.
- It has no storage, path, process, command, or settings dependency.
- `Renderer` remains the future executable boundary. A fake `Renderer` is not
  used because returning a render asset would falsely model real output.

Add `StubRenderOutputGenerator` under
`backend/app/infrastructure/generation`. It returns exactly the D57 manifest,
parsing profile integers/floats and deriving count/max visual end purely. Add a
recording `FakeRenderOutputGenerator` for application/API tests.

### D59. Read only the latest render plan; gate first; allow empty plans; do not inspect media or revalidate joins

- Define `_RENDER_OUTPUT_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})`.
- `GenerateRenderOutput` requires the run and checks status before reading the
  render plan. Invalid status therefore produces
  `AssetCreationRejectedError(RENDER_OUTPUT)` (HTTP 409) before a dependency 404.
- Read only via `GetLatestRenderPlan`. Missing input naturally raises
  `AssetNotFoundError(RENDER_PLAN)`.
- Do not read assembly, downloaded clips, voiceover, or subtitles. Their exact
  provenance already flows through the render-plan asset metadata.
- Do not check that clip/audio URIs resolve, inspect local paths, probe media, or
  validate that files exist.
- Do not re-run the render plan's four-way order validation. Do not reject
  overlaps/gaps or require visual/voiceover/subtitle duration equality. The
  output phase consumes the approved render-plan contract.
- Empty render plans are valid metadata inputs and produce the explicit zero
  manifest described in D57. The generator is still called once because it
  creates the single output manifest, not one item per segment.

### D60. Resolve profile/provenance in the use-case; persist one JSON object; creation remains internal

`GenerateRenderOutput` resolves these profile keys from render-plan asset
metadata, using the established render-plan defaults when a key is absent:

```text
aspect_ratio      = 16:9
resolution_width  = 1920
resolution_height = 1080
fps               = 30
container         = mp4
render_intent     = voiceover_b_roll
```

- Defaults live in application code, not the adapter.
- The use-case passes the resolved `Mapping[str, str]` to the generator.
- The generated asset metadata contains only strings:
  `source=generated`, `render_plan_asset_id`, `render_plan_version`, and all six
  resolved profile values.
- The manifest repeats provenance/profile as typed, durable content. This is
  intentional: asset metadata supports list/index inspection; the manifest is
  self-contained when loaded.
- `CreateRenderOutput` is the internal guarded persistence use-case. It stores a
  single JSON object through `StoragePort`, computes the next version, and never
  transitions the run.
- Expose no manual create route this phase.

### D61. Public API is generate/list/latest; composition uses the stub directly; no output/download/render route

Expose only:

```text
POST /runs/{run_id}/render-outputs/generate
GET  /runs/{run_id}/render-outputs
GET  /runs/{run_id}/render-outputs/latest
```

- Generate returns `201 AssetResponse`.
- Latest returns `RenderOutputResponse` containing the asset and parsed
  manifest.
- Add no manual `POST /render-outputs`, raw bytes, output file, download, render,
  FFmpeg, command-preview, progress, or cancellation route.
- Add optional `render_output_generator: RenderOutputGenerator | None` to
  `create_app`, default it to `StubRenderOutputGenerator()`, and store it on
  `app.state`.
- Only `main.py` imports the concrete adapter outside infrastructure/tests.
- Do not modify `provider_registry.py`, settings, lifespan, or environment
  variables. The stub owns no resource.

## Domain Model Proposal

- Add `AssetKind.RENDER_OUTPUT = "render_output"`.
- Add/export frozen `RenderOutputManifest` with exactly the D57 fields.
- Keep `AssetKind.RENDER`, `Renderer`, `RenderSpec`, and `RunStatus` unchanged.
- Add no file/path/command/progress/checksum/size fields.
- Add `RenderOutput` only as the application read model pairing a stored asset
  with the parsed domain manifest.

## Asset / Storage Decision

- Persist one JSON object per `RENDER_OUTPUT` version through `StoragePort`.
- Index it under `(run_id, AssetKind.RENDER_OUTPUT)` through
  `VersionedAssetRepository`.
- Use private application helpers `_render_output_to_bytes` and
  `_render_output_from_bytes`.
- Deserialize versions/count/dimensions as `int`, FPS/duration as `float`, and
  preserve `output_uri` as `None` or `str`.
- A second generation creates version 2 without overwriting version 1.
- The only bytes written are JSON manifest bytes. No storage adapter or schema
  change is needed; generic persistence already accepts new kinds.

## Port Decision

- Add/export `RenderOutputGenerator` from the ports package using the D58
  signature.
- Keep it separate from `Renderer`: the former explains a non-rendered output;
  the latter will eventually create a rendered asset from executable input.
- Application/API code depends only on `RenderOutputGenerator`.
- Add a recording fake that captures asset ID, version, segments, and profile and
  returns configured manifests for use-case/API tests.

## Deterministic Generator Decision

`StubRenderOutputGenerator`:

- Is pure and repeatable.
- Returns `status="not_rendered"`, `output_uri=None`, and
  `generation_reason="metadata_only_foundation"`.
- Copies provenance/profile and parses numeric profile fields.
- Derives segment count and maximum visual end time; empty input yields zeroes.
- Performs no media/path/file/command/process/network operation.
- Imports no API/application layer, provider SDK, HTTP client, filesystem,
  subprocess, FFmpeg, moviepy, audio, or subtitle-file module.

## Use-Case Plan

Create `backend/app/application/use_cases/render_output_assets.py`.

1. **`CreateRenderOutput`**
   - `execute(run_id, manifest, source="manual", asset_metadata=None) -> VersionedAsset`.
   - Requires the run and enforces the `scenes_approved` gate.
   - Persists one JSON object under `RENDER_OUTPUT`, with next-version semantics.
   - Constructor dependencies: `RunRepository`, `VersionedAssetRepository`,
     `StoragePort`, optional `asset_id_factory`.
   - Does not transition the run.

2. **`GenerateRenderOutput`**
   - `execute(run_id) -> VersionedAsset`.
   - Requires run/status before dependencies, reads `GetLatestRenderPlan`,
     resolves D60 profile defaults, calls the generator exactly once, and
     persists through `CreateRenderOutput` with generated metadata.
   - Constructor dependencies: `RunRepository`, `RenderOutputGenerator`,
     `GetLatestRenderPlan`, `CreateRenderOutput`.
   - Does not read older upstream artifacts and does not transition the run.

3. **`ListRenderOutputs`**
   - Lists `RENDER_OUTPUT` assets in version order.

4. **`GetLatestRenderOutput`**
   - Returns `RenderOutput(asset, manifest)`.
   - Raises `AssetNotFoundError(RENDER_OUTPUT)` when absent.

Export all four use-cases and the read model from the use-case package.

## API Route Plan

| Method | Path | Returns | Purpose |
| --- | --- | --- | --- |
| `POST` | `/runs/{run_id}/render-outputs/generate` | `201 AssetResponse` | Generate a metadata-only non-rendered output manifest from latest render plan. |
| `GET` | `/runs/{run_id}/render-outputs` | `list[AssetResponse]` | List output-manifest versions. |
| `GET` | `/runs/{run_id}/render-outputs/latest` | `RenderOutputResponse` | Return latest asset plus parsed manifest. |

Add `RenderOutputManifestModel.from_domain`,
`RenderOutputResponse.from_render_output`, and
`get_render_output_generator(request)`. There is no request body, manual create
DTO, raw-byte response, or executable render route.

## Composition Root Decision

- Add optional `render_output_generator: RenderOutputGenerator | None = None` to
  `create_app`.
- Default to `StubRenderOutputGenerator()` and assign
  `app.state.render_output_generator`.
- The concrete adapter is pure and does not affect database/storage lifespan.
- Do not wire through `provider_registry.py` and do not add configuration/API
  keys/binary paths.

## Test Checklist

### Domain and Serialization

- New kind value/distinction from `RENDER_PLAN` and `RENDER`.
- Exact frozen manifest fields; `output_uri` supports `None`.
- No output path, command, size, checksum, or media-byte field.
- JSON round-trip preserves integer/float/nullable types.
- Latest/list/versioning and missing-latest behavior.

### Port and Adapter

- Runtime protocol conformance, module location, exact safe type hints, and
  distinction from `Renderer`.
- Deterministic exact manifest values.
- Segment count and max-end duration, including out-of-order segments.
- Empty input produces count 0/duration 0.0.
- `output_uri is None`, status is not available, no fake URI.
- Generation adapter forbidden-import boundary remains green.

### Use-Cases and Lifecycle

- Create persists JSON `RENDER_OUTPUT`, defaults `source=manual`, and increments
  versions.
- Generate checks status before latest render plan, calls generator once, and
  persists source/provenance/profile metadata as strings.
- Missing run, missing render plan, and invalid status paths persist nothing.
- Generated manifest and asset metadata use the exact latest render-plan ID and
  version.
- Missing profile keys receive D60 defaults; present keys are copied.
- Empty render plan is accepted and still invokes the whole-manifest generator
  once.
- Run remains exactly `scenes_approved`.

### API

- Generate returns 201, `kind=render_output`, version 1, source/provenance/profile.
- Latest returns manifest with `status=not_rendered`, `output_uri=null`, and no
  output path/command.
- List and second-generation versioning.
- 404 missing run/render plan; 409 invalid status before dependency 404.
- Injected fake used (the recording `FakeRenderOutputGenerator`, not the default
  `StubRenderOutputGenerator`); no manual/output/download/render/FFmpeg routes
  registered.

### Architecture Boundaries and No-Real-Render Safety

- Domain/application/API import scans remain green.
- Add `RenderOutputGenerator` to provider-location checks.
- Add constructor-hint checks for all four use-cases.
- Add concrete adapter confinement test.
- Generation adapter scan forbids API/application, filesystem/path modules,
  HTTP/network, subprocess, FFmpeg/moviepy, and provider SDKs.
- Diff audit finds no media probe, existence check, output path, command preview,
  real write, render call, or run transition.

### End-to-End

Extend the workflow through render output. Assert generation 201; latest
manifest points to the exact render-plan asset/version; profile matches render
plan; segment count matches; estimated duration equals the maximum visual end;
status is `not_rendered`; output URI is null; generation reason is fixed; and
the run remains `scenes_approved` rather than `rendered`.

## Implementation Slices

### Slice 1: Domain model and asset kind

- Add/export `RENDER_OUTPUT` and `RenderOutputManifest`.
- Tests: kind distinction, exact fields, frozen/nullable behavior, no path or
  command fields, domain boundary.
- Acceptance: focused domain tests and `git diff --check` pass.

### Slice 2: Port

- Add/export runtime-checkable `RenderOutputGenerator` with D58 signature.
- Tests: structural fake, location, exact hints, distinction from `Renderer`.
- Acceptance: focused port tests and `git diff --check` pass.

### Slice 3: Stub metadata generator and fake

- Add `StubRenderOutputGenerator`, generation export, recording fake/export.
- Tests: exact values, profile parsing, max-end estimate, empty input,
  repeatability, no fake URI, import boundary.
- Acceptance: adapter/fake tests and `git diff --check` pass.

### Slice 4: Application use-cases

- Add read model, JSON helpers, create/generate/list/latest use-cases and exports.
- Tests: round-trip/versioning, metadata/defaults, guard ordering, natural 404,
  empty input, exact generator call, no transition, application boundary.
- Acceptance: focused use-case tests and `git diff --check` pass.

### Slice 5: API and composition wiring

- Add response DTOs, resolver, three routes, `create_app` parameter/default/state.
- Tests: 201/404/409, latest/list/versioning, null URI, route absence, injected
  fake, default wiring, route boundaries.
- Acceptance: focused API tests and `git diff --check` pass.

### Slice 6: Boundary tests, E2E, and phase audit

- Extend port/use-case/confinement boundaries and full workflow.
- Run focused architecture/E2E tests, full suite, and forbidden-capability audit.
- Confirm no generated files, secrets, databases, caches, or virtualenv files
  are staged.
- Acceptance: full suite and `git diff --check` pass.

### Slice Order and Dependencies

```text
1 domain -> 2 port -> 3 stub generator + fake
                   -> 4 application use-cases
                   -> 5 API + composition root
                   -> 6 boundaries + E2E + audit
```

Slices 3 and 4 can be developed independently after Slice 2 because application
tests use the fake. The stub must exist before composition wiring.

## Validation Plan

For this docs-only change, run:

```powershell
git diff --check
```

The full suite is optional because no product code changes:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

For the later implementation phase, run focused tests after every slice and the
full suite at the end. Before commit, inspect staged files for generated media,
secrets, SQLite files, caches, and virtual environments.

## Explicit Non-Goals / Deferred Work

- Real MP4/video output or any `AssetKind.RENDER` creation.
- FFmpeg invocation, command preview/construction, binary discovery, subprocess,
  progress, cancellation, stderr parsing, or process error handling.
- Output filesystem paths, filenames, directories, no-clobber rules, storage
  keys, file existence, checksums, byte sizes, or output validation.
- Media probing, codecs, bitrate, pixel-format, frame inspection, or duration
  verification against real files.
- Clip/audio/subtitle file materialization or caption burn-in.
- Activating/modifying `Renderer` or `RenderSpec`.
- Audio/TTS or subtitle-file generation.
- Provider integrations, API keys, HTTP/network clients.
- Frontend UI, ranking/scoring, actor dialogue, lip-sync, multi-speaker dialogue,
  or scene refinement.
- Run completion/rendered transition or a new output status.
- Schema/storage-adapter/provider-registry refactors.
- Workers, queues, Redis, Postgres, S3, cloud/SaaS features, auth, pagination.

## Open Questions

- **Real rendering boundary.** The next phase must decide whether `Renderer`
  consumes the current `RenderPlan` directly or a new executable render request
  that resolves metadata URIs into verified local paths.
- **Output storage/no-clobber.** A real renderer needs a version-scoped output
  destination, atomic write/rename behavior, and a clear relationship between
  `RENDER_OUTPUT` metadata and future `RENDER` bytes.
- **FFmpeg availability and security.** Future design must cover binary
  discovery/version checks, argument-list construction without shell parsing,
  path containment, timeouts, cancellation, and useful stderr errors.
- **Lifecycle completion.** Only a successfully persisted real rendered-video
  asset should make a future transition to `rendered`; this metadata manifest
  must never do so.
- **Profile validation.** Generated render plans provide known profile strings.
  If manual render-plan creation becomes public, malformed numeric/profile values
  may need a named validation error before render-output generation.
