# Local FFmpeg Renderer Design

Design document for the next phase. This records the intended design and slice
plan before any code is written. No backend, test, or product implementation is
part of this document. It is documentation only.

This note designs the first move from metadata-only artifacts toward real local
video materialization. It does two things at once, deliberately:

1. It designs the **local FFmpeg renderer** fully -- ports, output shape, path
   containment, command construction, error model, Windows handling, and
   lifecycle -- so the eventual real renderer is additive and its boundaries are
   fixed now.
2. It applies a **reality check** to the current repository and concludes that
   the next *implementable* phase is **not** the FFmpeg renderer. The upstream
   clip, voiceover, and subtitle artifacts are still metadata-only `memory://`
   references; no real media bytes exist on disk yet, so a real FFmpeg invocation
   has nothing to read. The recommended next implementable phase is a
   metadata-only **Render Readiness / Materialization Gate** that reports, per
   render-plan reference, whether a real local file exists, and explains exactly
   what blocks real rendering -- without invoking FFmpeg, creating a video, or
   transitioning the run.

The FFmpeg renderer architecture in this document is therefore **designed but
deferred**; the readiness gate is the architecture that ships first.

## Goal

Lock the architecture for real local video materialization while staying honest
about what the repository can actually render today.

- **Renderer goal (designed, deferred):** Given the latest render plan for a run
  and real local media files, produce a real `.mp4` through a local FFmpeg
  adapter that lives strictly in infrastructure, behind the reserved `Renderer`
  port, write it to a contained, version-scoped output path with no-clobber
  behavior, register it as an `AssetKind.RENDER` `VersionedAsset`, record a new
  `RENDER_OUTPUT` version that flips `status` to `available`, and only then
  transition the run `SCENES_APPROVED -> RENDERED`. Unit tests never require
  FFmpeg.
- **Gate goal (next implementable phase):** Given the latest render plan and
  latest render output manifest, produce a durable, versioned, metadata-only
  **render readiness report** that classifies every clip / voiceover / subtitle
  reference as a real local file or a still-unmaterialized `memory://`
  placeholder, names each blocker, and states whether real rendering is possible
  yet. It invokes no FFmpeg, creates no video, resolves no media bytes, and never
  transitions the run.

## Current Workflow

The asset-only pipeline currently ends at the render output manifest while the
run remains at `scenes_approved`:

```text
create run
-> generate script draft
-> approve script
-> generate scene table
-> approve scenes                 # run reaches scenes_approved
-> generate stock plan
-> retrieve clip candidates
-> select clips
-> generate video assembly plan
-> download clips                 # metadata-only: memory://downloads/...
-> generate voiceover             # metadata-only: memory://voiceovers/...
-> generate subtitles             # metadata-only: subtitle text inline
-> generate render plan           # metadata-only joined timeline
-> generate render output         # metadata-only: status=not_rendered, output_uri=null
```

The product workflow as implemented:

```text
prompt -> script draft -> scene table -> stock plan -> clip candidates
       -> selected clips -> video assembly plan -> downloaded clips
       -> voiceover -> subtitles -> render plan -> render output manifest
```

The target workflow this phase adds one honest step to:

```text
... -> render plan -> render output manifest
                   -> render readiness report   # NEW: metadata-only gate
```

The **eventual** real-render workflow (designed here, deferred until media is
materialized) is:

```text
... -> render readiness report (ready)
    -> materialize clips (real files)
    -> materialize voiceover audio (real files)
    -> generate subtitle file (real .srt/.vtt)
    -> render (FFmpeg) -> RENDER video asset
                       -> RENDER_OUTPUT (status=available, output_uri=...)
                       -> run transition SCENES_APPROVED -> RENDERED
```

## Architecture Rule

Dependencies point inward:

`API/UI -> application use-cases -> domain models/services -> ports/interfaces -> infrastructure adapters`

- The domain stays framework-free and serialization-free.
- Application use-cases own lifecycle guards, latest-asset composition,
  readiness/profile policy, provenance, versioning, and persistence. They never
  import infrastructure, open sockets, spawn a subprocess, invoke FFmpeg, probe
  media, or touch the filesystem directly.
- All FFmpeg invocation, subprocess management, media I/O, command construction,
  path resolution, and output-byte writing live **only** in an infrastructure
  adapter behind a port. This is the central rule of the renderer phase and the
  reason the renderer is introduced behind the already-reserved `Renderer` port
  rather than inline.
- The readiness gate's checker and the renderer are **separate ports**. The
  checker is metadata-only and FFmpeg-free; the renderer is the executable
  boundary.
- API routes call application use-cases only. Concrete adapter wiring stays
  explicit in `backend/app/main.py`.
- Existing `Renderer`, `RenderSpec`, and `RunStatus.RENDERED` stay reserved until
  the real renderer phase activates them.

This phase is the most boundary-sensitive yet: it is the first phase whose
*eventual* sibling spawns a subprocess and writes non-JSON bytes. The readiness
gate that ships first writes only JSON and runs no subprocess, so the boundary
risk for the shipping code is zero; the renderer design below fixes where the
risk lives when it does arrive.

## Existing Foundation

Grounded in the current source, not only the earlier design notes:

- `AssetKind` already includes `RENDER_PLAN = "render_plan"`,
  `RENDER_OUTPUT = "render_output"`, and `RENDER = "render"`
  (`backend/app/domain/models.py`). `RENDER` is still **unused by any use-case**
  -- it remains reserved for the future rendered-video-bytes asset.
- `RenderPlanSegment` is a frozen domain dataclass carrying, per timeline
  position: `order_index`, `scene_id`, `clip_uri`, `clip_provider`,
  `clip_provider_id`, a visual window (`visual_start/end/duration_seconds`),
  `voiceover_uri`, a voiceover window, and `subtitle_text` / `subtitle_*` fields.
  It carries no output path, FFmpeg command, or media bytes.
- `RenderOutputManifest` is a frozen domain dataclass with `status`,
  render-plan provenance, profile fields (`aspect_ratio`, `container`,
  `resolution_width`, `resolution_height`, `fps`), `segment_count`,
  `estimated_duration_seconds`, `output_uri: str | None`, and
  `generation_reason`. Today it is always `status="not_rendered"`,
  `output_uri=None`, `generation_reason="metadata_only_foundation"`.
- `GetLatestRenderPlan` and `GetLatestRenderOutput` return the latest parsed read
  models (`RenderPlan`, `RenderOutput`) and raise `AssetNotFoundError(run_id,
  <kind>)` when absent.
- `RenderSpec` is a frozen domain dataclass: `run_id`, `scenes:
  tuple[SceneSpec, ...]`, `clips: tuple[VersionedAsset, ...]`, `voice:
  VersionedAsset`, `subtitles: VersionedAsset | None`. **This shape predates the
  render plan** -- it references scenes and raw asset handles, not
  `RenderPlanSegment`. It is reserved and unused (see Open Questions: the real
  renderer should derive a request from the `RenderPlan`, not force this legacy
  shape).
- `Renderer.render(spec: RenderSpec) -> VersionedAsset`
  (`backend/app/ports/providers.py`) is the reserved executable boundary,
  runtime-checkable, unused. No adapter implements it.
- `RunStatus` is `created -> script_ready -> script_approved -> scenes_ready ->
  scenes_approved -> rendered` (plus `failed`). `SCENES_APPROVED` transitions
  only to `RENDERED` or `FAILED`; `Run.mark_rendered()` already exists and
  performs that transition. No use-case calls it yet.
- `StoragePort.save_asset(asset, data: bytes) -> VersionedAsset` writes bytes for
  a `VersionedAsset`. `LocalFilesystemStorage` derives the path
  `{kind}/{asset_id}/v{version}` under an injected root, validates each path
  component (rejects `/`, `\`, `:`, `\x00`, `.`, `..`), and confirms every
  resolved path stays within the root via `Path.is_relative_to`. This is the
  exact containment pattern the renderer's output path must reuse.
- `StubClipDownloader` emits `memory://downloads/{run_id}/{order:04d}/...mp4`
  and `StubVoiceoverGenerator` emits
  `memory://voiceovers/{run_id}/{order:04d}/...mp3`. **These are not files.**
  Subtitles are manifest-only (caption text inline in the render plan; no
  `.srt`/`.vtt` file is written). This is the decisive fact for the reality
  check below.
- `.gitignore` already ignores `data/renders/*` (keeping
  `data/renders/.gitkeep`, which exists) and `data/assets/*`. No `.gitignore`
  change is needed: render output bytes land under `data/renders/...` and the
  readiness report's JSON lands under `data/assets/render_readiness/...`.
- Persistence is kind-agnostic: SQLite stores `assets.kind` as text without an
  enum check constraint, local storage derives paths from `kind.value`, and the
  in-memory fakes key on `(run_id, kind)`. A new asset kind needs no migration.
- Architecture tests scan domain/application/API/generation imports, confine each
  concrete adapter to `main.py`, list provider protocols in
  `test_provider_interfaces_live_in_ports`, and check constructor type-hint maps.
  New layers inherit forbidden-import coverage automatically.

## Reality Check

This is the section the design turns on. The core question is: *should this phase
finally create a real `.mp4` using local FFmpeg, or should there be one more
dry-run / materialization-precheck phase first?*

The answer is dictated by what the upstream artifacts actually contain, confirmed
by reading the adapters:

- **Downloaded clips are not files.** `StubClipDownloader.download` returns a
  `DownloadedClip` whose `local_uri` is `memory://downloads/...`. Nothing is
  written to disk. The render plan copies this `memory://` reference verbatim
  into `RenderPlanSegment.clip_uri`.
- **Voiceover audio is not a file.** `StubVoiceoverGenerator.generate` returns a
  `VoiceoverSegment` whose `audio_uri` is `memory://voiceovers/...`. No audio
  bytes exist. The render plan copies it into `RenderPlanSegment.voiceover_uri`.
- **Subtitles are manifest-only.** The render plan carries `subtitle_text`
  inline; no caption file (`.srt`/`.vtt`) is generated anywhere.
- **FFmpeg availability is unknown.** Nothing in the repo probes for an installed
  `ffmpeg` binary; there is no binary-discovery code.

Therefore a real FFmpeg renderer **cannot produce a meaningful video yet**.
FFmpeg's `-i` inputs must be real, readable, contained local paths; `memory://`
URIs resolve to nothing. Building a real renderer now would force one of two
dishonest outcomes: (a) it would crash on the first `memory://` input, or (b) it
would silently fabricate a video unrelated to the user's selected clips and
narration. Both violate the project's local-first honesty principle -- every
prior phase introduced a boundary as a truthful, versioned artifact before
performing real work.

The hard constraints reinforce this: do not assume `memory://` URIs are real
files, do not fabricate video availability, and do not transition the run to
`RENDERED` unless a future implementation really creates a rendered video file.

**Conclusion:** the repository does not yet hold real local media files, so
Outcome A (real FFmpeg now) is off the table. The next implementable phase is the
materialization gate (Outcome B), and the real renderer is designed here but
deferred behind media materialization (Outcome D's prerequisites).

## Core Question and Possible Outcomes

| Outcome | Description | Verdict |
| --- | --- | --- |
| **A. Real FFmpeg render now** | Invoke local FFmpeg on the render plan's references to produce a real `.mp4`. | **Rejected.** Only acceptable if upstream artifacts already hold usable local file paths. They hold `memory://` placeholders. FFmpeg has nothing real to read. |
| **B. Render materialization precheck (gate)** | A metadata-only readiness check that reads the render plan + render output, classifies each reference as real-file vs placeholder, and reports blockers. No FFmpeg, no video, no transition. | **Chosen as the next implementable phase.** It is honest, additive, fully unit-testable without FFmpeg, and it precisely defines the contract the materialization phases must satisfy. |
| **C. Local placeholder render** | Generate a simple video from metadata only (e.g. text cards), ignoring upstream media files. | **Rejected for the immediate step.** It requires real FFmpeg invocation (disallowed in this docs branch and heavily constrained), and a video built from metadata alone implies an availability that does not reflect the user's actual clips/narration. Reconsidered later only as a dev-only smoke harness, never as the product render path. |
| **D. Defer real render; materialize media first** | Implement real clip download, real voiceover audio, and real subtitle files before the renderer. | **Adopted as the sequencing after the gate.** The renderer is designed now; its prerequisites (real clip / audio / subtitle files) are the phases the gate's report will demand. |

**Decision:** Ship **B** next. Design the FFmpeg renderer fully (this document).
Sequence **D**'s materialization phases between the gate and the real renderer.

## Design Questions and Answers

The 32 questions, answered. "Gate" = the next implementable phase; "Renderer" =
the designed-but-deferred real-render phase.

| # | Question | Decision |
| --- | --- | --- |
| 1 | Use `AssetKind.RENDER = "render"` for actual rendered video bytes? | Yes -- when the Renderer phase lands, `RENDER` is the kind for rendered video bytes. The Gate does not create `RENDER`. |
| 2 | `RENDER_OUTPUT` stays the metadata/job manifest, `RENDER` becomes actual video output? | Yes. `RENDER_OUTPUT` is the output/job manifest (status, provenance, profile, `output_uri`); `RENDER` is the video file asset the manifest points at once rendered. |
| 3 | Do `Renderer` / `RenderSpec` become active now? | No. Both stay reserved. The Renderer phase activates `Renderer`; it should derive a fresh render request from the `RenderPlan` rather than reuse the legacy `RenderSpec` shape (Q4, Open Questions). |
| 4 | Derive the render request from latest `RenderPlan` and/or latest `RenderOutputManifest`? | From the latest **`RenderPlan`** (per-position resolved local paths + windows + profile). The `RenderOutputManifest` is the output-side record the renderer updates, not its input. |
| 5 | Does the renderer read latest `RENDER_PLAN`, latest `RENDER_OUTPUT`, or both? | Renderer reads latest `RENDER_PLAN` (the renderable intent) and writes a new `RENDER_OUTPUT`. The Gate reads **both** (plan for references, output for current status/provenance). |
| 6 | Exact output asset shape? | A `RENDER` `VersionedAsset`: `kind=render`, next version, `uri` = relative contained local path, metadata = provenance (`render_plan_asset_id/version`, `render_output_asset_id/version`), `container`, `resolution`, `fps`, `duration_seconds`. Size/checksum deferred to the Renderer phase. |
| 7 | Real rendered artifact = `VersionedAsset` with `kind=RENDER` and a file URI? | Yes. |
| 8 | Update/create `RENDER_OUTPUT` after rendering, or is the rendered video enough? | Both. The Renderer creates the `RENDER` video asset **and** appends a new `RENDER_OUTPUT` version pointing at it. The two are linked, never merged. |
| 9 | Flip `RENDER_OUTPUT` `not_rendered -> available`, or create a `RENDER` asset only? | Append a **new** `RENDER_OUTPUT` version with `status="available"` and `output_uri` referencing the `RENDER` asset, **and** create the `RENDER` asset. Never mutate the prior `not_rendered` manifest (append-only). |
| 10 | What happens to `RunStatus.RENDERED`? | Stays reserved. Only a successfully persisted real `RENDER` asset triggers `Run.mark_rendered()`. The Gate never touches it. |
| 11 | Does a successful real render transition `SCENES_APPROVED -> RENDERED`? | Yes -- that is the existing legal transition, performed by the Renderer phase **after** the video is persisted. The Gate does not transition. |
| 12 | What happens on render failure? | No `RENDER` asset; no `RENDERED` transition; the run stays `SCENES_APPROVED` (render failure is recoverable, not a terminal run `FAILED`). Append a `RENDER_OUTPUT` version with `status="failed"` + reason, and raise a mapped error. |
| 13 | Error type for FFmpeg unavailable? | `RendererUnavailableError` (binary missing / not discoverable). Distinct, mapped to HTTP 503. |
| 14 | Error type for render process failure? | `RenderProcessError` (non-zero exit), carrying exit code and a bounded stderr tail. Mapped to HTTP 500. |
| 15 | How is output path containment guaranteed? | Reuse the `LocalFilesystemStorage` pattern: validate path components, resolve, and assert `is_relative_to(render_root)`. The renderer is **handed** a contained destination path; it never composes its own. |
| 16 | How does no-clobber work? | Choose the version-scoped final path `data/renders/{run_id}/render-v{version}.mp4` first (version from `RENDER` `next_version`); refuse if it already exists; FFmpeg writes to a temp sibling; the adapter atomically renames temp -> final on success and deletes the temp on failure. FFmpeg `-n` is not relied on as the primary no-clobber mechanism. |
| 17 | Where do output files live? | `data/renders/{run_id}/render-v{version}.mp4` -- already covered by the `data/renders/*` ignore. |
| 18 | Storage layer writes bytes, or renderer writes to a path then records an asset? | **Renderer writes the file to a handed path; the use-case then records the asset.** FFmpeg streams output to a filesystem path; routing multi-hundred-MB video through `StoragePort.save_asset(bytes)` is wrong. A `RenderOutputLocation` resolver (infra) computes the contained, no-clobber path; the renderer writes there; the use-case persists the `RENDER` index entry with that relative URI. |
| 19 | How are file URIs represented? | **Relative local URI** (root-relative path like `renders/{run_id}/render-v{n}.mp4`), consistent with how `LocalFilesystemStorage` already returns `/`-relative URIs. Not absolute `file://` (leaks host paths, non-portable), not a storage SDK URI. |
| 20 | Is Windows path handling explicitly covered? | Yes. `pathlib.Path` everywhere, argument lists (never a shell string), no drive-letter `:` in safe components (already enforced), forward/back-slash normalization, reserved-name and long-path awareness, and an explicit Windows path-containment test. |
| 21 | How are FFmpeg arguments safely constructed? | A pure command-builder returns an **argument list** for `subprocess.run([...], shell=False)`. No shell, no string interpolation of paths, no user-controlled format string in the command; numeric profile values are validated/whitelisted before they reach the list. |
| 22 | How are input media paths sanitized/contained? | Each `clip_uri`/`voiceover_uri`/subtitle path is resolved within an allowed media root and asserted contained; **`memory://` and any non-local scheme are rejected** (they are unmaterialized). This rejection is exactly what the Gate detects ahead of time. |
| 23 | Can real FFmpeg render yet, given metadata-only `memory://` clips/voiceover/subtitles? | **No.** Confirmed in code: clips/voiceover are `memory://` placeholders; subtitles are manifest-only. No readable local media exists. |
| 24 | Placeholder renderer now, or defer real FFmpeg until clips/voiceover are real files? | **Defer.** Build the readiness Gate now (Outcome B); sequence media materialization (Outcome D) before the renderer. Do **not** build a metadata-only placeholder video as the product path. |
| 25 | Minimal meaningful real-render path? | Once real files exist: per-position clip trimmed to its visual window, concatenated in `order_index` order, with the voiceover muxed as the audio track, encoded to the profile (1920x1080, 30fps, H.264/AAC, mp4). No transitions, no styling. |
| 26 | Subtitle burn-in now? | No. Deferred (needs a real subtitle file + styling decisions; a renderer concern). |
| 27 | Audio muxing now? | Designed, deferred (needs real audio files). |
| 28 | Clip trimming/concatenation now? | Designed, deferred (needs real clip files). |
| 29 | Aspect ratio / resolution / fps honored now? | Designed into the render request from the profile; honored by the Renderer phase. Not exercised now (no encode). |
| 30 | How do tests verify command construction without running FFmpeg? | The command-builder is a pure function; unit tests assert the exact argument list for given resolved paths + profile. The subprocess call sits behind a thin runner seam tests fake. |
| 31 | Unit-tested vs integration/manual-tested? | Unit: readiness classification, command-builder args, path containment, no-clobber path math, error mapping, availability probe behind a fake. Integration/manual: a single real FFmpeg encode, optional and documented. |
| 32 | Explicitly deferred? | Real FFmpeg invocation; real media materialization; burn-in; audio mux; trim/concat; transitions; the `RENDERED` transition; `Renderer`/`RenderSpec` activation; progress/cancellation; codecs/GPU. |

## Design Decisions

These continue the project decision log: D1-D49 cover the pipeline through
subtitles, D50-D55 the Render Plan Foundation, and D56-D61 the Render Output
Foundation. This phase adds D62-D69.

### D62. Choose the Render Readiness Gate (Outcome B) as the next implementable phase; design the FFmpeg renderer but defer it behind media materialization

- The repository holds `memory://` placeholders, not real media files (Reality
  Check). A real FFmpeg renderer would crash on or fabricate over those inputs.
- Ship a metadata-only readiness gate next. Design the renderer fully (D67-D69)
  so that when real clip / audio / subtitle files exist, the renderer is a purely
  additive infrastructure adapter behind the already-reserved `Renderer` port.
- The gate is the contract the materialization phases must satisfy: its report
  enumerates exactly which references must become real local files, in pipeline
  order, before rendering is possible.

### D63. Add `AssetKind.RENDER_READINESS`; the gate is metadata-only, reads the latest render plan and render output, classifies references, and never invokes FFmpeg or transitions the run

- Add `RENDER_READINESS = "render_readiness"` to `AssetKind`. It is a versioned
  JSON report distinct from `RENDER_PLAN` (intent), `RENDER_OUTPUT` (output/job
  manifest), and `RENDER` (future video bytes).
- The gate reads `GetLatestRenderPlan` (per-position references + profile) and
  `GetLatestRenderOutput` (current status + provenance). The render output is
  optional context; missing render output is not fatal (the report can be
  produced from the plan alone), but missing render **plan** raises
  `AssetNotFoundError(RENDER_PLAN)`. Reading the latest render output has **low
  value today** -- it is always `status="not_rendered"` with `output_uri=None` --
  but it preserves forward symmetry and provenance and becomes meaningful once
  real render attempts and `available`/`failed` output states exist.
- The gate classifies each `clip_uri`, `voiceover_uri`, and the subtitle
  representation by URI scheme/shape only (string inspection): a `memory://`
  scheme (or any non-local, non-existent reference) is `status="placeholder"`; a
  root-relative local path that resolves within the media root is
  `status="materialized"`. Each input also carries `required` (clips and voiceover
  are required; subtitles are optional while burn-in is deferred). In the
  **current** repository every clip/voiceover reference classifies as `placeholder`
  and subtitles classify as manifest-only (a non-blocking warning).
- The gate performs **no** media probe, **no** `open`/`stat` of bytes for content
  inspection, **no** FFmpeg call, **no** subprocess, and **no** run transition.
  (Whether the gate may `Path.exists()` a candidate local path is an Open
  Question; the default is scheme-classification only, so the gate stays pure and
  trivially Windows-safe.)
- FFmpeg availability is reported as `"not_checked"` by default and, when
  `"not_checked"`, **never blocks readiness** -- it means "input readiness was
  evaluated; FFmpeg availability was not checked." Only an explicit `"missing"`
  from an enabled probe blocks. Real binary discovery is an infrastructure concern
  introduced with the renderer phase (D69), modeled behind a port whose default
  stub returns `"not_checked"`, so the gate's core stays subprocess-free and unit
  tests stay FFmpeg-free.

### D64. Add `RenderReadinessReport` and `RenderInputReadiness` domain models; an application `RenderReadiness` read model

Add frozen domain dataclasses (illustrative field set; exact list fixed in
Slice 1):

```python
@dataclass(frozen=True)
class RenderInputReadiness:
    order_index: int          # render-plan timeline position
    scene_id: str
    role: str                 # "clip" | "voiceover" | "subtitle"
    uri: str                  # the reference as carried by the render plan
    scheme: str               # "memory" | "file" | "relative" | "inline" | ...
    required: bool            # True if the minimal renderer consumes this input
    status: str               # "materialized" | "placeholder" | "missing" | "not_checked"
    blocker_reason: str | None  # None when materialized/optional; else a stable reason code


@dataclass(frozen=True)
class RenderReadinessReport:
    status: str               # "ready" | "blocked"
    render_plan_asset_id: str
    render_plan_version: int
    render_output_asset_id: str | None
    render_output_version: int | None
    ffmpeg_availability: str  # "not_checked" | "available" | "missing"
    segment_count: int
    materialized_required_count: int   # counts required inputs only
    total_required_count: int          # counts required inputs only
    inputs: tuple[RenderInputReadiness, ...]
    blocker_summary: tuple[str, ...]   # de-duplicated, ordered required-blocker codes
    warnings: tuple[str, ...]          # optional/deferred gaps (e.g. subtitles), non-blocking
    generation_reason: str
```

- Overall `status` is derived **only from required inputs**. `status = "blocked"`
  whenever any *required* input is not materialized, or FFmpeg availability is
  explicitly `"missing"`. A `"not_checked"` availability **never blocks** (it means
  "input readiness was evaluated; FFmpeg availability was not checked"), so the
  gate's `"ready"` state is reachable without a probe. `status = "ready"` only when
  every required input is a real contained local file and availability is not
  `"missing"`. In the current repository the report is always `"blocked"` (clips
  and voiceover are required and unmaterialized).
- For the first/minimal renderer (clip trim + concat + voiceover mux, no
  burn-in), **clips and voiceover are `required=True`; subtitles are
  `required=False`** because subtitle burn-in is deferred. A manifest-only
  subtitle therefore produces a **warning**, not a blocker, and does not by itself
  prevent `status="ready"`.
- Subtitles are classified `role="subtitle"`, `scheme="inline"`, `required=False`,
  `status="placeholder"`, `blocker_reason="subtitle_manifest_only"` -- the render
  plan carries caption text, not a caption file. This reason is surfaced in
  `warnings`, never in `blocker_summary`.
- `materialized_required_count` / `total_required_count` count required inputs
  only, so a fully materialized clip+voiceover set reports
  `materialized_required_count == total_required_count` and `status="ready"` even
  while subtitles remain manifest-only.
- The report carries **no** FFmpeg command, output path, video bytes, codec, or
  fabricated availability. It is a truthful description of blockers and warnings.

Add an application read model:

```python
class RenderReadiness(NamedTuple):
    asset: VersionedAsset
    report: RenderReadinessReport
```

### D65. Add a metadata-only `RenderReadinessChecker` port distinct from `Renderer`; `StubRenderReadinessChecker` classifies by URI scheme; FFmpeg availability sits behind its own optional port

Define a runtime-checkable port in `backend/app/ports/providers.py`, separate
from the reserved `Renderer`:

```python
@runtime_checkable
class RenderReadinessChecker(Protocol):
    def check(
        self,
        render_plan_asset_id: str,
        render_plan_version: int,
        render_plan_segments: Sequence[RenderPlanSegment],
        render_output: RenderOutputManifest | None,
        ffmpeg_availability: str,
    ) -> RenderReadinessReport:
        """Classify render-plan references as materialized or blocked."""
        ...
```

- The port uses only domain and standard-library types. It receives the resolved
  `ffmpeg_availability` string from the use-case (which obtained it from the
  availability port, default `"not_checked"`), so the checker stays a pure
  classifier with no subprocess concern.
- `StubRenderReadinessChecker` (infrastructure/generation) is pure and
  deterministic: it inspects each `clip_uri`/`voiceover_uri` scheme and the
  subtitle representation, sets each input's `required`/`status`/`blocker_reason`,
  counts materialized vs total **required** inputs, derives the overall `status`
  from required inputs only, de-duplicates required-blocker reasons, and collects
  optional gaps (e.g. manifest-only subtitles) into `warnings`. It performs no
  network, filesystem-byte, subprocess, FFmpeg, or media operation.
- FFmpeg availability is a separate, optional concern. Introduce
  `FfmpegAvailabilityProbe` (port) with a default stub returning `"not_checked"`.
  A real `subprocess`-based probe (`ffmpeg -version` / binary discovery) is an
  infrastructure adapter introduced **with the renderer phase**, wired only in
  `main.py`, and never exercised by unit tests. Keeping it behind a port and
  defaulting to `"not_checked"` is what keeps the gate FFmpeg-free.

### D66. Gate use-cases; gated at `scenes_approved`; never transitions; creation kept internal

Create `backend/app/application/use_cases/render_readiness_assets.py`, using
`render_output_assets.py` as the structural template.

1. `CreateRenderReadiness.execute(run_id, report, source="manual",
   asset_metadata=None) -> VersionedAsset` -- requires the run, enforces
   `_RENDER_READINESS_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})`, computes
   the next `RENDER_READINESS` version, writes one JSON object through
   `StoragePort`, sets provenance/status metadata, never transitions the run.
2. `GenerateRenderReadiness.execute(run_id) -> VersionedAsset` -- guard first,
   then read `GetLatestRenderPlan` (required) and `GetLatestRenderOutput`
   (optional context), resolve `ffmpeg_availability` from the probe port, call the
   checker once, and persist via `CreateRenderReadiness` with `source="generated"`
   plus provenance/status metadata. Constructor deps: `RunRepository`,
   `RenderReadinessChecker`, `FfmpegAvailabilityProbe`, `GetLatestRenderPlan`,
   `GetLatestRenderOutput`, `CreateRenderReadiness`.
3. `ListRenderReadiness` / `GetLatestRenderReadiness` -- version listing and
   latest parsed read model (`AssetNotFoundError(RENDER_READINESS)` when absent).

The status guard is checked **before** any read, so an invalid run returns
`AssetCreationRejectedError` (409) before a dependency 404.

### D67. Renderer phase (designed, deferred): activate `Renderer` behind a `LocalFfmpegRenderer` adapter; derive the render request from the `RenderPlan`; write a `RENDER` asset, append an `available` `RENDER_OUTPUT`, then transition

This decision is design-only; no code is written for it in this phase.

- Add `LocalFfmpegRenderer` under `backend/app/infrastructure` (its own package,
  e.g. `infrastructure/rendering`, **not** `generation`, because `generation`'s
  boundary tests forbid subprocess/FFmpeg imports and must keep forbidding them).
  It implements the reserved `Renderer` port.
- The render **request** is derived from the latest `RenderPlan`, not the legacy
  `RenderSpec`. A `GenerateRender` use-case: enforces `SCENES_APPROVED`; reads
  `GetLatestRenderPlan`; resolves each `clip_uri`/`voiceover_uri` to a contained
  local path (rejecting `memory://`); obtains a contained, version-scoped,
  no-clobber output destination from a `RenderOutputLocation` resolver; calls the
  renderer; on success creates the `RENDER` `VersionedAsset`, appends a
  `RENDER_OUTPUT` version (`status="available"`, `output_uri` -> the `RENDER`
  asset), and calls `Run.mark_rendered()`; on failure appends a `failed`
  `RENDER_OUTPUT` and raises.
- The renderer adapter owns: the pure command-builder (argument list), the
  subprocess runner seam, stderr capture, exit-code handling, and writing FFmpeg
  output to the **handed** destination path. It owns no lifecycle, versioning,
  provenance, or asset-index logic -- those stay in the use-case.
- Whether `RenderSpec` is updated to the plan-derived shape or replaced by a new
  `RenderRequest` value object is an Open Question; either way the request
  carries resolved local paths + windows + profile, never `memory://`.

### D68. Output containment, no-clobber, path representation, and Windows handling for the renderer

- **Containment.** Reuse the `LocalFilesystemStorage` discipline: a
  `RenderOutputLocation` resolver validates components, resolves, and asserts
  `is_relative_to(render_root)` (where `render_root` is the configured
  `data/renders`). Input media paths are resolved and asserted contained within
  an allowed media root; `memory://` and any non-local scheme are rejected.
- **No-clobber.** Choose the final destination
  `data/renders/{run_id}/render-v{version}.mp4` first (with `version` from the
  `RENDER` `next_version`). Refuse if the final path already exists. FFmpeg writes
  to a temp sibling path; on success the adapter atomically renames the temp to
  the final path; on failure it deletes the temp. The atomic rename, not FFmpeg's
  `-n`/`-y` flag, is the primary no-clobber mechanism -- FFmpeg only ever sees the
  fresh temp path.
- **Path representation.** Stored `RENDER.uri` and the `RENDER_OUTPUT.output_uri`
  are **root-relative** local URIs (e.g. `renders/{run_id}/render-v{n}.mp4`),
  matching the existing relative-URI convention. No absolute `file://`.
- **Windows.** `pathlib.Path` throughout; argument lists with `shell=False`; the
  existing safe-component check already rejects drive-letter `:`; normalize
  separators when classifying URIs; be aware of reserved device names and long
  paths; add an explicit Windows containment/no-clobber test.

### D69. Error model for the gate and the renderer

- **Gate:** no new dedicated error beyond the existing ones. Missing render plan
  -> `AssetNotFoundError(RENDER_PLAN)` (404); invalid status ->
  `AssetCreationRejectedError` (409); missing run -> `RunNotFoundError` (404). A
  "blocked" report is a **successful 201** -- being not-ready is a valid,
  truthful outcome, not an error.
- **Renderer (designed, deferred):**
  - `RenderNotReadyError` (application) -- a render was requested while inputs are
    unmaterialized (`memory://` reference reached the renderer path). Maps to 409.
    The render request resolution raises this before any subprocess.
  - `RendererUnavailableError` (application, raised when the renderer/probe
    reports the FFmpeg binary missing/undiscoverable). Maps to 503.
  - `RenderProcessError` (application, wrapping a non-zero FFmpeg exit) carrying
    exit code and a bounded stderr tail. Maps to 500.
  - On any of these the run stays `SCENES_APPROVED`; a `failed` `RENDER_OUTPUT`
    version is appended; no `RENDER` asset is created; no `RENDERED` transition.

## Recommended Phase Choice

**Build the Render Readiness / Materialization Gate (Outcome B) next.** Then
sequence media materialization (Outcome D) before activating the FFmpeg renderer:

```text
1. Render Readiness Gate            <-- this phase (metadata-only, no FFmpeg)
2. Real clip materialization        (download real clip bytes to data/clips)
3. Real voiceover materialization   (synthesize real audio to data/audio)
4. Subtitle file generation         (.srt/.vtt to data/subtitles)
5. Local FFmpeg renderer            (RENDER asset + available RENDER_OUTPUT + RENDERED)
```

The gate makes the dependency explicit and testable: its report is "blocked"
until phases 2-4 land, then "ready", at which point phase 5 (designed here) is a
purely additive infrastructure adapter.

## Domain Model Proposal

- Add `AssetKind.RENDER_READINESS = "render_readiness"`.
- Add and export frozen `RenderInputReadiness` and `RenderReadinessReport` with
  the D64 fields, next to `RenderOutputManifest` in `domain/models.py` and
  `domain/__init__.py`.
- Do **not** change `RenderSpec`, `Renderer`, `RunStatus`, `AssetKind.RENDER`,
  `RenderPlanSegment`, `RenderOutputManifest`, or run-transition rules.
- Add no output path, FFmpeg command, codec, byte-size, checksum, or
  fabricated-availability field.
- Add `RenderReadiness` only as an application read model.
- The renderer's request value object (`RenderRequest` vs an updated `RenderSpec`)
  is **not** added in this phase; it is designed in D67 and flagged in Open
  Questions.

## Port / Use-Case / API Plan

### Gate (this phase)

- **Port:** `RenderReadinessChecker` (D65), plus optional `FfmpegAvailabilityProbe`
  defaulting to `"not_checked"`. Both separate from `Renderer`.
- **Adapter:** `StubRenderReadinessChecker` and a default
  `StubFfmpegAvailabilityProbe` under `infrastructure/generation`; a recording
  `FakeRenderReadinessChecker` in `tests/fakes/providers.py` for use-case/API
  tests.
- **Use-cases:** `CreateRenderReadiness`, `GenerateRenderReadiness`,
  `ListRenderReadiness`, `GetLatestRenderReadiness` (D66).
- **API:**

  | Method | Path | Returns |
  | --- | --- | --- |
  | `POST` | `/runs/{run_id}/render-readiness/generate` | `201 AssetResponse` |
  | `GET` | `/runs/{run_id}/render-readiness` | `list[AssetResponse]` |
  | `GET` | `/runs/{run_id}/render-readiness/latest` | `RenderReadinessResponse` |

  Add `RenderInputReadinessModel.from_domain`,
  `RenderReadinessResponse.from_render_readiness`, and a
  `get_render_readiness_checker(request)` resolver. No manual create route, raw
  bytes, render route, or FFmpeg/command route. Add optional
  `render_readiness_checker` (and `ffmpeg_availability_probe`) to `create_app`,
  defaulting to the stubs and stored on `app.state`.

### Renderer (designed, deferred)

- **Port:** activate the reserved `Renderer`; introduce `RenderOutputLocation`
  and the real `FfmpegAvailabilityProbe` adapter; introduce a
  `LocalFfmpegRenderer` in a new `infrastructure/rendering` package.
- **Use-cases:** `GenerateRender` (D67), `ListRenders`, `GetLatestRender`.
- **API:** `POST /runs/{run_id}/renders/generate`, `GET .../renders`,
  `GET .../renders/latest`. None of these are built in this phase.

## Error Model

See D69. Summary:

| Error | Layer | When | HTTP |
| --- | --- | --- | --- |
| `RunNotFoundError` | application (existing) | run missing | 404 |
| `AssetNotFoundError(RENDER_PLAN)` | application (existing) | no render plan | 404 |
| `AssetCreationRejectedError` | application (existing) | status != `scenes_approved` | 409 |
| *(blocked report)* | n/a | inputs unmaterialized | **201** (truthful, not an error) |
| `RenderNotReadyError` | application (deferred) | render requested over `memory://` inputs | 409 |
| `RendererUnavailableError` | application (deferred) | FFmpeg binary missing | 503 |
| `RenderProcessError` | application (deferred) | FFmpeg non-zero exit | 500 |

The gate adds no new error type. The renderer's three errors are designed now and
introduced with the renderer phase.

## Testing Strategy

### Gate -- unit (no FFmpeg)

- **Domain/serialization:** `RENDER_READINESS` value and distinction from
  `RENDER_PLAN`/`RENDER_OUTPUT`/`RENDER`; frozen models with exactly the D64
  fields; JSON round-trip preserving `int`/`float`/`bool`/nullable types; no
  command/path/codec/availability-fabrication field.
- **Port/adapter:** runtime conformance of a fake; port resolves to
  `backend.app.ports.providers`; exact `check` type hints; `RenderReadinessChecker`
  is a different object from `Renderer`; the checker is deterministic and
  repeatable.
- **Classification:** a `memory://` clip/voiceover classifies
  `status="placeholder"`, `required=True` with a stable reason; inline subtitles
  classify `status="placeholder"`, `required=False`,
  `blocker_reason="subtitle_manifest_only"` surfaced as a **warning** (never a
  blocker); a (hypothetical) contained local path classifies
  `status="materialized"`; `materialized_required_count`/`total_required_count`
  and overall `status` derive from required inputs only; a `"not_checked"`
  availability does not block; current-pipeline inputs all block on
  clips+voiceover; a clip+voiceover-materialized fixture reports `status="ready"`
  despite a manifest-only subtitle warning; `blocker_summary` is de-duplicated and
  ordered.
- **Use-cases/lifecycle:** create stores JSON and increments versions; generate
  tags `source=generated` with provenance/status metadata, calls the checker once,
  resolves availability from the (default `"not_checked"`) probe; status guard
  rejects every non-`scenes_approved` state with 409 before any read; missing
  render plan -> 404; missing render output is tolerated (report still produced);
  run stays exactly `scenes_approved`; a second generate creates version 2.
- **API:** 201 with `kind=render_readiness`, version 1, source/provenance; latest
  returns the parsed report with `status=blocked` and per-input rows; list/version
  ordering; 404 missing run, 404 missing render plan, 409 invalid status; only
  generate/list/latest routes registered; injected fake used.
- **Boundaries/no-real-render safety:** domain/application/API import scans green;
  `RenderReadinessChecker` (and `FfmpegAvailabilityProbe`) added to the
  port-location test; constructor-hint maps extended; concrete-adapter confinement
  test; generation-adapter scan still forbids API/application/FFmpeg/subprocess
  imports (the stub inherits it); a diff audit asserts no FFmpeg call, no
  subprocess, no media probe, no output path, no run transition.

### Renderer -- planned (designed, deferred)

- **Unit (no FFmpeg):** the pure command-builder returns the exact argument list
  for given resolved paths + profile; path-containment accepts contained inputs
  and rejects escaping/`memory://` ones; no-clobber path math is correct and a
  pre-existing destination is refused; Windows path/containment cases; error
  mapping (`RenderNotReady`/`RendererUnavailable`/`RenderProcess`); the subprocess
  runner behind a fake yields success and failure paths without a real binary.
- **Integration/manual:** one real FFmpeg encode over real fixture media,
  optional and documented (below); never in the default unit suite; FFmpeg must
  not be a unit-test dependency.

## Manual Smoke Strategy

For the gate: none required (pure, metadata-only). Optionally `GET
.../render-readiness/latest` after generating and confirm `status=blocked` with
the expected per-input reasons.

For the renderer (when it lands), an **optional, documented, dev-only** smoke,
gated behind an explicit opt-in (e.g. an env flag or a `-m ffmpeg` pytest
marker), never in CI's default run:

1. Materialize a tiny real fixture clip and a short real audio file under the
   media root (or use the materialization phases' outputs).
2. Run `GenerateRender` for a `scenes_approved` run with a ready readiness report.
3. Assert a `RENDER` asset exists at `data/renders/{run_id}/render-v1.mp4`, that
   `ffprobe` (manual) reports the expected container/resolution/fps/duration, that
   a new `available` `RENDER_OUTPUT` points at it, and that the run is `rendered`.
4. Re-run and assert no-clobber (a fresh `render-v2.mp4`, the prior file intact).

Document FFmpeg install prerequisites and that the smoke is excluded from the
default `pytest -q`.

## Hard Constraints

- Do not write implementation code in this phase (docs only).
- Do not add real FFmpeg invocation in this docs branch.
- Do not assume `memory://` URIs are real files.
- Do not fabricate video availability (the gate reports `blocked` truthfully).
- Do not transition the run to `RENDERED` unless a future implementation really
  creates a rendered video file.
- Do not put FFmpeg/subprocess in the application or domain layers -- ever.
- Do not require FFmpeg for unit tests; availability sits behind a port defaulting
  to `"not_checked"`.
- Do not add cloud/SaaS storage, frontend UI, or actor dialogue / lip-sync /
  multi-speaker scope.

## Explicit Non-Goals / Deferred Work

- Real MP4/video output or any `AssetKind.RENDER` creation **in this phase**.
- FFmpeg invocation, command construction/preview, binary discovery, subprocess,
  stderr parsing, progress, or cancellation in the shipping gate code.
- Output filesystem paths, no-clobber writes, file URIs, or output validation in
  the gate (designed in D68 for the renderer phase).
- Media probing, codecs, bitrate, pixel format, or duration verification against
  real files.
- Real clip download bytes, real voiceover audio bytes, or subtitle-file
  generation (these are the materialization phases that precede the renderer).
- Subtitle burn-in, audio mixing/ducking/normalization, transitions, color
  grading, scaling/cropping, or aspect-ratio conversion.
- Activating or modifying `Renderer`, `RenderSpec`, or `RunStatus`.
- The `rendered` transition or any new run status.
- Provider integrations, API keys, HTTP/network clients, workers, queues, Redis,
  Postgres, S3, cloud/SaaS, auth, pagination.
- Database schema changes, storage-adapter refactors, or provider-registry
  changes.

## Implementation Slices

Inward-to-outward, one slice at a time; focused tests after each, full suite at
the end. (These describe the **gate** phase; the renderer is designed only.)

### Slice 1: Domain -- asset kind and records

- Add `AssetKind.RENDER_READINESS`, frozen `RenderInputReadiness` and
  `RenderReadinessReport` (D63/D64) plus exports.
- Tests: kind value/distinction (incl. distinct from `RENDER`/`RENDER_OUTPUT`),
  exact fields, frozen behavior, domain boundary scan.

### Slice 2: Ports

- Add/export runtime-checkable `RenderReadinessChecker` and
  `FfmpegAvailabilityProbe` (D65), separate from `Renderer`.
- Tests: structural fakes, module location, exact type hints, distinction from
  `Renderer`.

### Slice 3: Stub checker + availability stub + fakes

- Add `StubRenderReadinessChecker` and `StubFfmpegAvailabilityProbe`
  (default `"not_checked"`), generation exports, and recording fakes.
- Tests: classification of `memory://` clip/voiceover (required) and inline
  subtitle (optional warning), `required`/`status` per input, required-only counts
  and overall `status` derivation, `"not_checked"` availability is non-blocking,
  repeatability, no fake "available", import boundary (no
  API/application/FFmpeg/subprocess).

### Slice 4: Application use-cases

- Add the `RenderReadiness` read model, JSON helpers, and
  create/generate/list/latest use-cases with the D66 guard ordering and
  provenance/status metadata.
- Tests: round-trip/versioning, metadata/defaults, guard-before-read, natural 404
  for missing render plan, tolerated missing render output, exact single checker
  call, no transition, application boundary.

### Slice 5: API + composition wiring

- Add response DTOs, the `get_render_readiness_checker` resolver, three routes,
  and `create_app` parameters/defaults/state.
- Tests: 201/404/409, latest/list/versioning, route absence (no render/FFmpeg
  route), injected fake, default wiring, route boundaries.

### Slice 6: Boundary tests, E2E, phase audit

- Extend port-location, constructor-hint, and confinement tests; extend the
  workflow E2E through render readiness asserting `status=blocked`.
- Run focused architecture/E2E tests, the full suite, and a forbidden-capability
  audit (no FFmpeg/subprocess/media-probe/output-path/render-transition in the
  diff). Confirm no generated media, secrets, databases, caches, or virtualenv
  files are staged.

```text
1 domain -> 2 ports -> 3 stub checker + probe + fakes
                    -> 4 application use-cases
                    -> 5 API + composition root
                    -> 6 boundaries + E2E + audit
```

## Open Questions

- **Render request shape.** The reserved `RenderSpec` predates the render plan
  (it references `SceneSpec`/`VersionedAsset`, not `RenderPlanSegment`). The
  renderer phase must decide whether to reshape `RenderSpec` to a plan-derived
  request or introduce a new `RenderRequest` value object carrying resolved local
  paths + windows + profile. Either is additive; the recommendation is a new
  `RenderRequest` so the legacy `RenderSpec` is retired cleanly.
- **Gate `Path.exists()` vs scheme-only.** The default classifies by URI scheme
  only (pure, Windows-trivial). A later option lets the gate `Path.exists()` a
  candidate contained local path to distinguish "claims to be local but missing"
  from "memory placeholder". This adds a real filesystem read to the gate; it is
  deferred and would be gated behind the same containment discipline as the
  renderer.
- **Persisted readiness staleness.** A readiness report is a point-in-time
  diagnostic: a stored `blocked` report can become stale the moment media is
  materialized, with no new version to reflect the change. Should readiness remain
  a versioned generated asset (auditable provenance, consistent with the
  generate/list/latest pattern), or should a future route compute current
  readiness read-only on demand? For now the design chooses the **versioned
  artifact** for consistency and provenance; the read-only option is left open for
  the materialization phases.
- **FFmpeg availability ownership.** Availability is `"not_checked"` until the
  renderer phase introduces a real probe. Whether the gate should optionally run
  the probe (so a "ready except FFmpeg missing" state is reportable) or leave all
  binary discovery to the renderer phase is open; the default keeps the gate
  subprocess-free.
- **Output storage seam.** The renderer writes video to a handed filesystem path
  rather than routing bytes through `StoragePort.save_asset(bytes)`. Whether to
  formalize a `RenderOutputWriter`/`RenderOutputLocation` port or extend
  `StoragePort` with a "reserve contained path" capability is an Open Question for
  the renderer phase.
- **Failed-render manifest vs error only.** D69 appends a `failed` `RENDER_OUTPUT`
  version *and* raises. An alternative raises only (no failed manifest). The
  recommendation is to persist the failed manifest for auditability, but this is
  confirmed when the renderer phase lands.
- **Codec/profile validation.** Generated render plans provide known profile
  strings. If manual render-plan creation becomes public, malformed
  numeric/profile values need a named validation error before the renderer builds
  a command (carried over from the Render Output Foundation open questions).
- **Three timelines reconciliation.** The render plan carries separate visual,
  voiceover, and subtitle windows that coincide today. When real synthesized
  narration diverges from the visual slot, the renderer must decide
  trim/pad/stretch; that reconciliation is deferred to the renderer phase, not
  the gate.
