# Render Plan Foundation

Design document for the next phase. This records the intended design and slice
plan before any code is written. No backend, test, or product implementation is
part of this document. The approved direction continues the asset-only tail of
the pipeline: assembly planning turned selections plus scenes into a
`VideoAssemblyPlan`, clip download turned the plan's segments into a durable
`DownloadedClipSet` of local clip references, voiceover turned the plan's
per-segment narration into a durable `Voiceover` of `VoiceoverSegment` records,
and subtitles turned the voiceover's narration and timing into a durable
`Subtitles` set of `SubtitleSegment` records. Those steps produced four separate
metadata artifacts -- the visual timeline, the downloaded clip references, the
narration plan, and the caption plan -- each independently versioned. This phase
builds the *join*: it reads the latest of all four upstream artifacts and
produces a durable, versioned *render plan* -- a set of `RenderPlanSegment`
records, each joining one timeline position's visual clip reference, voiceover
reference, and subtitle text/timing into a single renderable intent -- plus a
run-level render profile -- produced through a render planner port. It introduces
the render-intent abstraction only. It does not create a real video file, invoke
FFmpeg, generate an FFmpeg command, probe media, check whether any clip/audio
file exists, or transition the run lifecycle.

## Goal

Given the latest video assembly plan, downloaded clip set, voiceover, and
subtitles for a run, produce a durable, versioned *render plan*: one
`RenderPlanSegment` per timeline position, joining -- by `order_index` -- the
visual clip reference (`clip_uri`, provider, provider id) from the downloaded
clip, the narration reference (`voiceover_uri`) and audio timeline from the
voiceover, and the caption text, language, and caption timeline from the
subtitle, alongside a computed visual timeline window. The manifest also records
a run-level render profile (aspect ratio, resolution, fps, container, render
intent). The artifact answers, for each timeline position and as metadata only:
which local clip plays, with which narration audio, under which caption, during
which visual/audio/caption time windows, and into what target format the whole
run would eventually render.

This foundation is deliberately narrower than a real renderer. It makes the "what
would be composited where, against which audio and captions, into what format"
decision inspectable and repeatable *without* creating a video file, building or
previewing an FFmpeg command, probing or opening any media, checking whether any
referenced clip/audio file exists, mixing or ducking audio, styling or burning
captions, or transitioning the run lifecycle. For this foundation the planner is
a deterministic stub that joins the four upstream artifacts by `order_index`,
folds the visual and audio timelines arithmetically, and copies the existing
`memory://` references; no real composition, encode, or output exists.

## Target Workflow

The existing asset-only tail is extended by one step. The run reaches
`scenes_approved` exactly as today and remains there while stock planning, clip
retrieval, clip selection, assembly planning, clip download, voiceover,
subtitles, and now render planning create independently versioned JSON assets.

```text
create run
-> generate script draft
-> approve script
-> generate scene table
-> approve scenes                    # run reaches scenes_approved
-> generate stock plan               # run stays scenes_approved
-> retrieve clip candidates          # run stays scenes_approved
-> select clips                      # run stays scenes_approved
-> generate video assembly plan      # run stays scenes_approved
-> download clips                    # run stays scenes_approved
-> generate voiceover                # run stays scenes_approved
-> generate subtitles                # run stays scenes_approved
-> generate render plan              # NEW: reads the latest video assembly plan,
                                     # downloaded clips, voiceover, and subtitles,
                                     # calls the RenderPlanner to join them,
                                     # persists a RENDER_PLAN asset,
                                     # run stays scenes_approved (asset-only)
```

The target product workflow becomes:

```text
prompt -> script draft -> scene table -> stock plan -> clip candidates
       -> selected clips -> video assembly plan -> downloaded clips
       -> voiceover -> subtitles -> render plan
```

Unlike every prior asset phase, which read from exactly **one** upstream
artifact, render planning is the first phase that **joins multiple upstream
artifacts**. It is the structural analog of the video assembly planner -- which
joined scenes and selected clips into a timeline -- but one layer further down
the pipeline: it joins the visual timeline, the downloaded clips, the narration
plan, and the caption plan into a single renderable timeline (see D51). It is the
last metadata artifact before real rendering; the render plan is the
input contract a future `Renderer` / FFmpeg adapter consumes.

## Architecture Rule

Dependencies point inward:

`API/UI -> application use-cases -> domain models/services -> ports/interfaces -> infrastructure adapters`

- The domain remains framework-free and serialization-free.
- Application use-cases orchestrate repositories, storage, latest-asset readers,
  and the planner port. They do not import infrastructure, open sockets, call a
  media/encoder SDK, spawn a subprocess, invoke FFmpeg, or touch the filesystem
  directly.
- `RenderPlanner` is a port expressed only in domain types.
- `StubRenderPlanner` is a pure infrastructure adapter with no network,
  filesystem, subprocess, FFmpeg, media SDK, video/audio encoder, API, or
  application dependency.
- API routes call application use-cases only. Lifecycle and versioning rules do
  not move into route functions.
- Concrete planner wiring remains explicit in `backend/app/main.py`.

This phase is **render-adjacent**, which makes the boundary rule especially
important -- more so than any prior phase. Where clip download was media-file
adjacent and voiceover/subtitles were byte-output adjacent, this phase is named
"render" and sits immediately before the real renderer. Its *eventual* real
implementation will spawn FFmpeg, read and decode real media bytes, composite
video, mix audio, burn or mux captions, and write a real video file (the `RENDER`
asset). The domain and application layers must never perform any of that work.
All composition, encoding, subprocess, media I/O, and output materialization
belong behind the reserved `Renderer` port and the existing `StoragePort` /
`LocalFilesystemStorage`, orchestrated by a future use-case. This foundation
keeps that risk at zero by writing only JSON manifest bytes, copying upstream
`memory://` references rather than resolving them, never opening or probing any
file, and never constructing an FFmpeg command (see Asset / Storage Decision,
D50, D52, and D53).

## Existing Foundation

This design is based on the current implementation, confirmed by reading the
source, not only the earlier design notes:

- `VersionedAsset` stores `asset_id`, `kind`, `version`, `uri`, and string
  metadata (`metadata` is `Mapping[str, str]`). The generic repository and
  storage ports already support new asset kinds without a database schema change.
- `AssetKind` currently includes `SCRIPT`, `SCENE_TABLE`, `STOCK_PLAN`,
  `CLIP_CANDIDATES`, `SELECTED_CLIPS`, `VIDEO_ASSEMBLY_PLAN`, `DOWNLOADED_CLIPS`,
  `STOCK_CLIP`, `VOICEOVER`, `VOICE`, `SUBTITLE_MANIFEST`, `SUBTITLE`, and
  `RENDER`. Crucially, `RENDER = "render"` **already exists** and is still unused
  in any use-case: `Renderer.render(spec: RenderSpec) -> VersionedAsset` is the
  reserved port shaped to return it, and `RenderSpec` (with `run_id`, `scenes`,
  `clips`, `voice`, and optional `subtitles`) is the reserved render input.
  Across the codebase, `RENDER` is reserved for the future *rendered-video-bytes*
  asset that a real renderer produces -- the final `.mp4` -- exactly as `VOICE` is
  reserved for synthesized-audio bytes, `SUBTITLE` for caption-file bytes, and
  `STOCK_CLIP` for per-file media bytes. This phase does not touch `RENDER`,
  `RenderSpec`, or `Renderer` (see D50).
- `VideoAssemblySegment` is a frozen domain dataclass carrying `scene_id`,
  `order_index` (zero-based, contiguous over the full plan),
  `target_duration_seconds`, `source_duration_seconds`, provider/source metadata,
  and narration/visual context. Its `order_index` and `target_duration_seconds`
  are the per-position key and the visual timeline budget this phase reads.
- `DownloadedClip` carries `scene_id`, `order_index`, `provider`,
  `provider_clip_id`, `local_uri` (a `memory://downloads/...` reference),
  `content_type`, dimensions, and a download status. Its `local_uri`, `provider`,
  and `provider_clip_id` are the visual reference this phase joins in.
- `VoiceoverSegment` carries `scene_id`, `order_index`, `narration_text`,
  `language`, `voice_id`, `provider`, `audio_uri` (a `memory://voiceovers/...`
  reference), `content_type`, `duration_seconds`, `status`, and
  `generation_reason`. Its `audio_uri` and `duration_seconds` are the narration
  reference and audio-timeline input this phase joins in. Note `VoiceoverSegment`
  carries only a per-segment `duration_seconds`, not a start/end window -- the
  voiceover timeline is derived by folding durations in `order_index` order,
  exactly as `GenerateSubtitles` already does.
- `SubtitleSegment` carries `scene_id`, `order_index`, `text`, `language`,
  `start_seconds`, `end_seconds`, `duration_seconds`, `format`, `status`, and
  `generation_reason`. Unlike the voiceover, the subtitle already carries an
  explicit `start_seconds`/`end_seconds` window (computed by `GenerateSubtitles`
  from the voiceover durations). Its `text`, `language`, `start_seconds`, and
  `end_seconds` are the caption inputs this phase joins in.
- `GetLatestVideoAssemblyPlan`, `GetLatestDownloadedClipSet`,
  `GetLatestVoiceover`, and `GetLatestSubtitles` each return the latest parsed
  read model (`VideoAssemblyPlan`, `DownloadedClipSet`, `Voiceover`, `Subtitles`)
  and raise `AssetNotFoundError(run_id, <kind>)` when missing. These four readers
  are the read paths and the natural dependency guards this phase reuses -- one
  per upstream artifact.
- The subtitle use-cases (`CreateSubtitles`, `GenerateSubtitles`,
  `ListSubtitles`, `GetLatestSubtitles`) plus the `_subtitle_segments_to_bytes` /
  `_subtitle_segments_from_bytes` helpers in `subtitle_assets.py`, and the
  `StubSubtitleComposer` adapter, are the closest structural template for this
  phase. The guard `_SUBTITLE_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})`
  and the guard-before-read ordering in `GenerateSubtitles` are copied directly.
  The `order_index` defensive-sort + duration-fold in `GenerateSubtitles` is the
  exact timeline pattern this phase reuses for the visual and voiceover
  timelines.
- `RunStatus` is `created -> script_ready -> script_approved -> scenes_ready ->
  scenes_approved -> rendered` (plus `failed`). `scenes_approved` only transitions
  to `rendered`/`failed`; there is no planning/retrieval/selection/assembly/
  download/voiceover/subtitle/render-plan status, and this phase adds none. The
  eventual `rendered` transition belongs to the future real renderer, not this
  phase.
- `backend/app/ports/providers.py` holds runtime-checkable provider protocols
  using domain types (`ClipRetrievalProvider`, `ClipSelector`,
  `VideoAssemblyPlanner`, `ClipDownloader`, `VoiceoverGenerator`,
  `SubtitleComposer`, and the reserved `TTSProvider`, `SubtitleBuilder`,
  `Renderer`). `backend/app/infrastructure/generation` holds pure deterministic
  defaults (`DeterministicVideoAssemblyPlanner`, `StubClipDownloader`,
  `StubVoiceoverGenerator`, `StubSubtitleComposer`, ...), and `backend/app/main.py`
  wires those defaults through `app.state`.
- `StoragePort.save_asset(asset, data)` writes bytes for a `VersionedAsset`;
  `LocalFilesystemStorage` derives the path as `{kind}/{asset_id}/v{version}`
  under an injected storage root and confirms every resolved path stays within the
  root. The in-memory test storage keys generically on a
  `memory://{kind}/{asset_id}/v{version}` uri.
- Persistence is kind-agnostic: SQLite stores `assets.kind` as text without an
  enum check constraint, local storage derives paths from `kind.value`, and the
  in-memory fakes key generically on `(run_id, kind)`. No SQLite migration or
  storage refactor is needed for a new asset kind.
- `.gitignore` already ignores `data/assets/*` (keeping `.gitkeep`), so
  `data/assets/render_plan/*` is already covered. It also already ignores
  `data/renders/*` (keeping `data/renders/.gitkeep`), reserved for the future real
  rendered-video bytes a later real-render phase will write into the `RENDER`
  asset. No `.gitignore` change is needed by this phase.
- Architecture boundary tests scan domain, application, API, ports, and the
  generation package for forbidden imports, confine each concrete default
  (including `StubSubtitleComposer`) to `main.py`, and already list
  `SubtitleComposer` in `test_provider_interfaces_live_in_ports` and
  `GenerateSubtitles` in the generation-use-case hint map. New files in those
  layers inherit forbidden-import coverage automatically; this phase adds a
  parallel confinement test for its new default and extends the hint maps.

## Problem Being Solved

The pipeline now produces four durable, independently versioned metadata
artifacts that, together, describe everything needed to render a voiceover B-roll
video: the **video assembly plan** says which clip occupies each timeline
position and for how long; the **downloaded clips** say where each clip's local
media file would live; the **voiceover** says what narration audio plays and for
how long; the **subtitles** say what caption appears, in which language, during
which window. But these four artifacts are *separate*. Nothing in the system
joins them. A future renderer cannot consume them as-is: it would have to read
four assets, re-derive which downloaded clip, which voiceover segment, and which
subtitle segment belong to which assembly position, re-compute the visual and
audio timelines, and decide a target format -- all logic that does not exist and
has no single home. There is no render-intent artifact: no record that says "at
timeline position N, play *this* clip with *this* narration under *this* caption,
during *these* windows, toward *this* output format."

This phase introduces the narrow foundation for that join: a domain model and
asset that represent, per timeline position, a single joined render intent (clip
reference + voiceover reference + subtitle text/timing + computed visual window),
plus a run-level render profile, produced through a replaceable planner port. It
deliberately stops short of creating any video, building any FFmpeg command,
opening any file, or checking any file's existence, so the join model,
persistence, timeline arithmetic, profile shape, and API can be locked in and
tested before any real renderer, encoder, subprocess, media probe, or output-byte
concern is introduced. Because the model carries the per-position references and
windows and the manifest carries the profile, the render plan is the exact input
contract the future `Renderer` / `RenderSpec` path will consume, designed so the
real render phase is additive.

## Answers to Design Questions

| # | Question | Decision |
| --- | --- | --- |
| 1 | Read from latest video assembly plan, downloaded clips, voiceover, and subtitles? | Yes -- read the latest of **all four** upstream artifacts (D51). This is the first multi-artifact join phase. Each is read through its existing latest-reader, which also serves as the dependency guard (a missing input raises `AssetNotFoundError`). |
| 2 | One render plan asset for the whole run? | Yes -- one **set** asset for the whole run (`RENDER_PLAN`) containing many `RenderPlanSegment` records plus a run-level profile in metadata (D50/D52), mirroring `VIDEO_ASSEMBLY_PLAN`, `DOWNLOADED_CLIPS`, `VOICEOVER`, and `SUBTITLE_MANIFEST`. |
| 3 | Domain model name? | `RenderPlanSegment` (D52), a frozen metadata-only domain dataclass. The application read model is `RenderPlan` (D52). |
| 4 | New asset kind? | Yes: `AssetKind.RENDER_PLAN = "render_plan"` (D50). |
| 5 | Reuse `AssetKind.RENDER`, or keep it reserved? | Keep `RENDER` **reserved** for future rendered-video output bytes (D50). `RENDER_PLAN` is the JSON render-intent manifest; `RENDER` stays the future `.mp4` asset produced by `Renderer.render(RenderSpec)`. This mirrors `VOICEOVER` vs `VOICE`, `SUBTITLE_MANIFEST` vs `SUBTITLE`, and `DOWNLOADED_CLIPS` vs `STOCK_CLIP`. The `_PLAN` suffix prevents `RENDER` / `RENDER_PLAN` confusion. |
| 6 | Create a real video file? | **No** (D52/D53). No video file, no placeholder output bytes; the only bytes written are the JSON manifest. |
| 7 | Invoke FFmpeg? | **No** (D53). No FFmpeg, no subprocess, no encoder, no media I/O. The planner is pure. |
| 8 | Render planner port? | Yes -- a **new** metadata-only `RenderPlanner` port (D53), distinct from the reserved `Renderer`. |
| 9 | Deterministic fake planner behavior? | Join the four artifacts by `order_index`; copy `clip_uri`/provider/provider-id from the downloaded clip, `voiceover_uri` from the voiceover `audio_uri`, and subtitle text/language/window from the subtitle; fold the visual timeline from assembly target durations and the voiceover timeline from voiceover durations (D53). No file creation, probing, or FFmpeg. |
| 10 | How do segments join clip, voiceover, and subtitle? | By `order_index`, the shared timeline key all four artifacts already carry (D51/D53). Each `RenderPlanSegment` carries the clip reference, the voiceover reference + audio window, and the subtitle text + caption window for one position, plus a computed visual window. |
| 11 | What if counts/order do not match across artifacts? | A named **application** validation error, `RenderPlanInputMismatchError` -> HTTP 409 (D54). The use-case validates equal counts and identical `order_index` sets across all four artifacts *before* calling the planner; matching is by `order_index`, never by list position. |
| 12 | Validate structure only, or media file existence? | **Structure only** (D52/D54). The references are still metadata-only `memory://` placeholders with no bytes; the planner never opens, probes, or checks the existence of any file. File-existence/probe validation is deferred to the real-render phase. |
| 13 | Render profile fields now? | Yes -- `aspect_ratio`, `resolution_width`, `resolution_height`, `fps`, `container`, `render_intent`, stored as run-level manifest metadata strings with deterministic defaults (D52/D55). Codec fields (`video_codec`/`audio_codec`) are deferred: they are encoder concerns owned by the real renderer (see Open Questions). |
| 14 | Subtitle style fields now? | **No** (deferred). Caption styling (font, size, color, position, burn-in) is a renderer concern; the plan carries only caption text, language, and timing. |
| 15 | Audio mixing fields now? | **No** (deferred). Levels, ducking, fades, and music beds are renderer concerns; the plan carries only the narration reference and its window. |
| 16 | Use-cases? | `CreateRenderPlan` (internal, guarded persistence), `GenerateRenderPlan` (public join), `ListRenderPlans`, `GetLatestRenderPlan` (D54). |
| 17 | API routes? | `POST .../render-plans/generate`, `GET .../render-plans`, `GET .../render-plans/latest` (D54). No manual create route. |
| 18 | Run status gate? | `RunStatus.SCENES_APPROVED`, checked before any upstream read (D51). |
| 19 | Transition the run status? | No. Asset-only; no new `RunStatus`; no transition (D51). The future renderer owns the `rendered` transition. |
| 20 | Tests for boundaries / no-real-render? | See Test Checklist. Reuse the auto-scanning suite; add port-location, port-hint, no-reuse-vs-`Renderer`, use-case-hint, confinement, deterministic-join, timeline-fold, mismatch-409, round-trip, guard-ordering, `memory://`-only/no-output-bytes, no-FFmpeg/subprocess, and no-file-existence assertions. |
| 21 | Explicitly deferred? | See Explicit Non-Goals / Deferred Work. No real render, video file, or output bytes; no FFmpeg/subprocess/encoder; no FFmpeg command preview; no media probe or file-existence check; no subtitle styling; no audio mixing; no `RENDER`/`Renderer`/`RenderSpec` use; no run transition; no UI; no upstream changes. |

## Design Decisions

These decisions continue the project decision log: D1-D7 cover script/scene
planning, D8-D13 stock planning, D14-D19 clip retrieval, D20-D25 selected clip
selection, D26-D31 video assembly planning, D32-D37 clip download, D38-D43
voiceover, and D44-D49 subtitles. This phase adds D50-D55. It is, in structure,
the render-intent analog of the assembly-planning phase: where assembly planning
joined scenes and selected clips into a `VIDEO_ASSEMBLY_PLAN` via
`VideoAssemblyPlanner`, render planning joins four downstream artifacts into a
`RENDER_PLAN` via `RenderPlanner`.

### D50. Add `AssetKind.RENDER_PLAN`; keep `RENDER`, `Renderer`, and `RenderSpec` reserved for future rendered video bytes

- Add `RENDER_PLAN = "render_plan"` to `AssetKind`.
- It represents the set of joined render-intent records derived from the four
  upstream artifacts: one `RenderPlanSegment` per timeline position, each joining
  the visual clip reference, the voiceover reference and audio window, and the
  subtitle text and caption window, plus a run-level render profile, persisted as
  one versioned JSON asset. It is distinct from `VIDEO_ASSEMBLY_PLAN` (visual
  timeline intent), `DOWNLOADED_CLIPS` (visual local references), `VOICEOVER`
  (narration plan), `SUBTITLE_MANIFEST` (caption plan), and `RENDER` (future
  rendered output bytes).
- Do **not** reuse `AssetKind.RENDER`, and do **not** reuse the `Renderer` port or
  the `RenderSpec` input. Throughout the codebase `RENDER` is the future
  *rendered-video-bytes* asset: it is what the reserved
  `Renderer.render(spec: RenderSpec) -> VersionedAsset` is shaped to return -- the
  final encoded video file. The render *plan* is a different artifact -- many
  metadata records plus a profile, no video bytes -- exactly as `SUBTITLE_MANIFEST`
  (the caption plan) is distinct from `SUBTITLE` (the future caption file) and
  `VOICEOVER` (the narration plan) from `VOICE` (the future audio bytes). Keeping
  the render plan (`RENDER_PLAN`) and the eventual rendered video (`RENDER`) as
  distinct kinds lets the plan and the output store evolve and re-run
  independently without colliding versions, and lets a future real-render slice
  consume this plan to build a `RenderSpec` and call `Renderer` -> `RENDER`
  cleanly under the plan this phase locks in. The `_PLAN` suffix is chosen
  specifically so `RENDER` (video bytes) and `RENDER_PLAN` (metadata) can never be
  visually confused in code, storage paths, or tests.
- Persist only JSON metadata through the existing `StoragePort`, indexed through
  `VersionedAssetRepository`. The copied `clip_uri` and `voiceover_uri` are
  references and are never opened, resolved, or probed in this phase. No SQLite
  migration, storage adapter change, or JSON schema registry is added: persistence
  is kind-agnostic, and manifest bytes land under `data/assets/render_plan/...`,
  already covered by the `data/assets/*` ignore.

### D51. Read the latest of all four upstream artifacts; first multi-artifact join phase; asset-only; gated at `scenes_approved`; never transitions the run

- Read from `GetLatestVideoAssemblyPlan`, `GetLatestDownloadedClipSet`,
  `GetLatestVoiceover`, **and** `GetLatestSubtitles` -- all four. This is the first
  phase that joins multiple upstream artifacts rather than transforming one. Each
  contributes a distinct part of the render intent:
  - the **video assembly plan** is the canonical *spine*: it defines the timeline
    positions (`order_index`), the `scene_id` per position, and the visual time
    budget (`target_duration_seconds`) used to fold the visual window;
  - the **downloaded clips** contribute the visual reference (`local_uri` ->
    `clip_uri`, `provider`, `provider_clip_id`);
  - the **voiceover** contributes the narration reference (`audio_uri` ->
    `voiceover_uri`) and the per-position audio `duration_seconds` used to fold the
    voiceover window;
  - the **subtitles** contribute the caption `text`, `language`, and the explicit
    caption window (`start_seconds`/`end_seconds`).
- The assembly plan is treated as the spine because it is the artifact every other
  upstream artifact transitively derives from (downloaded clips and voiceover are
  its siblings; subtitles derive from the voiceover), so its `order_index` set is
  the authoritative timeline. The use-case iterates assembly positions and joins
  the other three by `order_index` (D54).
- Define `_RENDER_PLAN_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})` in the new
  application module. Both `GenerateRenderPlan` and the internal `CreateRenderPlan`
  enforce this status. The generation use-case checks it **first**, before any
  upstream read, so an invalid run returns `AssetCreationRejectedError` (HTTP 409)
  before any reader can produce a 404.
- Re-generating while `scenes_approved` creates the next `RENDER_PLAN` version and
  leaves the run unchanged. Add no status between `scenes_approved` and `rendered`,
  and call no run transition method. A future renderer remains responsible for the
  eventual `rendered` transition.
- If any upstream artifact is missing, its own latest-reader naturally raises
  `AssetNotFoundError(run_id, <kind>)` (mapped to HTTP 404). No special-casing is
  added. The read order is fixed in pipeline order (assembly plan -> downloaded
  clips -> voiceover -> subtitles) so the first missing dependency reported is the
  earliest one in the pipeline, which is the most actionable.

### D52. Add `RenderPlanSegment`; use an application `RenderPlan` read model; profile in manifest metadata; structured join records with no media bytes and no file checks

Add a frozen domain dataclass:

```python
@dataclass(frozen=True)
class RenderPlanSegment:
    order_index: int               # shared timeline key across all four artifacts
    scene_id: str                  # links the record back to its scene
    clip_uri: str                  # copied from DownloadedClip.local_uri (memory://)
    clip_provider: str             # copied from DownloadedClip.provider
    clip_provider_id: str          # copied from DownloadedClip.provider_clip_id
    visual_start_seconds: float    # folded from assembly target durations
    visual_end_seconds: float      # visual_start + target_duration_seconds
    visual_duration_seconds: float # = assembly target_duration_seconds
    voiceover_uri: str             # copied from VoiceoverSegment.audio_uri (memory://)
    voiceover_start_seconds: float # folded from voiceover durations
    voiceover_end_seconds: float   # voiceover_start + voiceover duration_seconds
    voiceover_duration_seconds: float  # = VoiceoverSegment.duration_seconds
    subtitle_text: str             # copied from SubtitleSegment.text
    subtitle_start_seconds: float  # copied from SubtitleSegment.start_seconds
    subtitle_end_seconds: float    # copied from SubtitleSegment.end_seconds
    subtitle_language: str         # copied from SubtitleSegment.language
```

Field semantics:

- `order_index` and `scene_id` come from the matching `VideoAssemblySegment` (the
  spine). `order_index` is the join key; `scene_id` links the joined record back to
  its scene.
- `clip_uri`, `clip_provider`, `clip_provider_id` are copied from the matching
  `DownloadedClip` (`local_uri` -> `clip_uri`). `clip_uri` is the existing
  `memory://downloads/...` reference -- copied, never resolved, opened, or checked
  for existence.
- `voiceover_uri` is copied from the matching `VoiceoverSegment.audio_uri` (the
  `memory://voiceovers/...` reference) -- likewise copied, never resolved.
- `subtitle_text`, `subtitle_start_seconds`, `subtitle_end_seconds`, and
  `subtitle_language` are copied from the matching `SubtitleSegment`. The subtitle
  already carries an explicit window, so it is copied directly rather than folded.
- The **visual timeline** (`visual_start_seconds`, `visual_end_seconds`,
  `visual_duration_seconds`) is the time window the B-roll clip occupies, folded
  from the assembly plan's `target_duration_seconds` in `order_index` order
  (`visual_start` = cumulative previous targets; `visual_end` = `visual_start` +
  this target; first position at `0.0`). This is the same gapless, contiguous fold
  `GenerateSubtitles` already uses.
- The **voiceover timeline** (`voiceover_start_seconds`, `voiceover_end_seconds`,
  `voiceover_duration_seconds`) is the narration audio window, folded from the
  voiceover segments' `duration_seconds` in `order_index` order. The voiceover
  carries no explicit window of its own, so the plan folds one, mirroring the
  visual fold.
- Why **three separate timelines** (visual, voiceover, subtitle) rather than one:
  they are conceptually distinct -- the visual slot is a *target* budget, the
  voiceover window is the *narration* length, and the subtitle window is the
  *caption* display time. In the current deterministic pipeline they coincide
  (the voiceover stub sets `duration_seconds = target_duration_seconds`, and the
  subtitle composer folds the voiceover durations), so all three windows are equal
  today. Keeping them as separate fields means a future real renderer -- where a
  synthesized narration may run shorter/longer than the visual slot, and a real
  caption aligner may split or shift cues -- needs no manifest reshape to express
  the divergence (trim/pad/stretch decisions stay a deferred renderer concern).
- The record contains **no** media bytes, codecs, frame rates, byte ranges,
  filter graphs, or FFmpeg instructions. The copied URIs are descriptive
  references, not resolved paths and not executable commands.

The **render profile is not a per-segment field**. It is run-level and lives in
the manifest's `VersionedAsset.metadata` as strings (`aspect_ratio`,
`resolution_width`, `resolution_height`, `fps`, `container`, `render_intent`),
resolved as deterministic defaults by the use-case (D55), exactly as
`GenerateSubtitles` resolves and stores a run-level `language`. Keeping the
profile run-level (not duplicated onto every segment) avoids redundancy and keeps
`RenderPlanSegment` focused on the per-position join.

Add `RenderPlan` in the application layer as:

```python
class RenderPlan(NamedTuple):
    asset: VersionedAsset
    segments: tuple[RenderPlanSegment, ...]
```

The render profile and provenance are read from `asset.metadata`. Do not add a
domain-level set wrapper -- symmetry with the voiceover, subtitle, assembly-plan,
and downloaded-clip slices plus YAGNI; the application read model already pairs the
`VersionedAsset` with parsed records. (`RenderPlan` mirrors the `Voiceover` /
`Subtitles` read-model naming.)

**One `RenderPlanSegment` per timeline position.** The plan keys one-to-one with
the assembly plan's positions, preserving `order_index`. Under the current flow
(one downloaded clip, one voiceover segment, and one subtitle per assembly
position) this is one render-plan segment per position with every reference
populated. Any future re-grouping is deferred and noted as an Open Question; the
`scene_id` and `order_index` fields are the hooks that let it happen without
reshaping the manifest.

**Metadata-only, no output bytes, no file checks.** This foundation writes no
video file and no placeholder output: the only bytes persisted are the JSON
manifest. The planner stub is pure and the use-case writes exactly one asset (the
manifest) through `StoragePort`. It never opens, resolves, probes, or checks the
existence of the referenced `clip_uri`/`voiceover_uri`. This keeps the phase
symmetric with the prior asset phases; keeps the new generation adapter pure (so
the existing generation-boundary tests pass unchanged); and -- critically -- keeps
the first render-named phase from introducing any non-JSON write, subprocess,
FFmpeg call, or media I/O, so the "no filesystem/render work in domain/application"
rule is satisfied by construction.

### D53. `RenderPlanner` is a whole-plan join port distinct from `Renderer`; the stub joins by `order_index` and folds the timelines purely

Define a runtime-checkable port in `backend/app/ports/providers.py`, separate from
the reserved `Renderer`:

```python
@runtime_checkable
class RenderPlanner(Protocol):
    def plan(
        self,
        assembly_segments: Sequence[VideoAssemblySegment],
        downloaded_clips: Sequence[DownloadedClip],
        voiceover_segments: Sequence[VoiceoverSegment],
        subtitle_segments: Sequence[SubtitleSegment],
    ) -> Sequence[RenderPlanSegment]:
        """Join four timeline-aligned artifacts into render-plan segments."""
        ...
```

- **Whole-plan, not per-segment.** Unlike the downloader, voiceover generator, and
  subtitle composer (all per-item), render planning is intrinsically a *join over
  four collections*: building one segment requires looking up the matching record
  in each artifact by `order_index`, and the visual/voiceover timelines are
  cross-segment folds. The whole-plan shape mirrors `VideoAssemblyPlanner.plan(
  scenes, selected_clips)` -- the existing multi-input join planner -- and keeps
  the matching-and-folding policy (exactly the part a richer planner would vary)
  behind the port, out of the use-case and routes.
- **No `run_id`, no profile parameter.** The planner builds no run-scoped
  reference (it copies existing `memory://` references from upstream), so it needs
  no `run_id`, mirroring the subtitle composer's deliberate omission. The render
  profile is run-level metadata owned by the use-case (D55), not a planner input,
  so it is not passed in either; this keeps the planner focused on the per-position
  join and the timeline folds.
- **Aligned-inputs precondition.** The planner assumes the four collections are
  timeline-aligned: equal length and identical `order_index` sets. The use-case
  guarantees this precondition and raises `RenderPlanInputMismatchError` before
  calling the planner (D54), so the planner never needs to import application
  errors or perform client-facing validation -- it stays a pure mapper. (An
  alternative that folds the mismatch check into the planner is recorded in Open
  Questions.)
- **Distinct from `Renderer`.** `Renderer.render(spec: RenderSpec) -> VersionedAsset`
  consumes a render spec and returns rendered *video bytes*, and stays
  reserved/unused. `RenderPlanner` owns the *plan* policy (which references, which
  timelines, which join); `Renderer` will own the *render* (spec -> real `RENDER`
  bytes via FFmpeg) in a later phase. The two compose cleanly: a future real-render
  flow reads this `RENDER_PLAN`, builds a `RenderSpec`, and calls `Renderer`.
- The port imports only `VideoAssemblySegment`, `DownloadedClip`,
  `VoiceoverSegment`, `SubtitleSegment`, and `RenderPlanSegment` from the domain.
  It has no repository, storage, FastAPI, media/encoder SDK, HTTP, filesystem,
  subprocess, or FFmpeg type in its contract.

Add `StubRenderPlanner` under `backend/app/infrastructure/generation`, named for
symmetry with the other deterministic stubs (it stands in for an absent real
render-planning policy). Its algorithm:

1. Build `order_index`-keyed lookups for the downloaded clips, voiceover segments,
   and subtitle segments.
2. Sort the assembly segments ascending by `order_index` (defensive, mirroring
   `GenerateSubtitles`), and fold two cursors over them: a visual cursor over
   `target_duration_seconds` and a voiceover cursor over the matching voiceover
   segment's `duration_seconds`.
3. For each assembly segment at `order_index = n`, look up the matching downloaded
   clip, voiceover segment, and subtitle segment, and emit one `RenderPlanSegment`:
   - `order_index = n`, `scene_id = assembly_segment.scene_id`;
   - `clip_uri = downloaded_clip.local_uri`, `clip_provider = downloaded_clip.provider`,
     `clip_provider_id = downloaded_clip.provider_clip_id`;
   - `visual_start_seconds = visual_cursor`,
     `visual_duration_seconds = assembly_segment.target_duration_seconds`,
     `visual_end_seconds = visual_start_seconds + visual_duration_seconds`;
   - `voiceover_uri = voiceover_segment.audio_uri`,
     `voiceover_start_seconds = voiceover_cursor`,
     `voiceover_duration_seconds = voiceover_segment.duration_seconds`,
     `voiceover_end_seconds = voiceover_start_seconds + voiceover_duration_seconds`;
   - `subtitle_text = subtitle_segment.text`,
     `subtitle_start_seconds = subtitle_segment.start_seconds`,
     `subtitle_end_seconds = subtitle_segment.end_seconds`,
     `subtitle_language = subtitle_segment.language`.
4. Advance the cursors (`visual_cursor += target_duration_seconds`,
   `voiceover_cursor += voiceover duration_seconds`) and continue.

The adapter is pure and repeatable: the same four aligned inputs produce equal
outputs. It performs no randomness, ranking, scoring, network request, media
probe, file access, file-existence check, subprocess call, FFmpeg call, or encode.
Empty inputs (zero assembly segments) yield an empty plan with no lookups. It does
not set the render profile (that is the use-case's job) and does not validate
alignment (that is the use-case's guard).

### D54. `GenerateRenderPlan` composes the four latest reads; matching by `order_index`; mismatch -> `RenderPlanInputMismatchError` (409); creation kept internal; generate-only public API

`GenerateRenderPlan` receives only `run_id` from the API. It composes:

- `RunRepository` for the D51 guard.
- `GetLatestVideoAssemblyPlan`, `GetLatestDownloadedClipSet`, `GetLatestVoiceover`,
  and `GetLatestSubtitles` for the four upstream artifacts.
- `RenderPlanner` for the pure join policy.
- `CreateRenderPlan` for guarded persistence and versioning.

Execution order is locked:

1. Require the run and check `RunStatus.SCENES_APPROVED` (raise
   `AssetCreationRejectedError` -> 409 before any read).
2. Read the four latest artifacts in pipeline order (assembly plan, downloaded
   clips, voiceover, subtitles). The first missing one raises
   `AssetNotFoundError(<kind>)` -> 404.
3. **Validate alignment.** Compute the `order_index` multiset of each artifact and
   require all four to be equal in length and identical as sets (no missing
   position, no extra record, no duplicate index). On any discrepancy raise
   `RenderPlanInputMismatchError(run_id)` -> HTTP 409. Matching is by `order_index`,
   never by list position.
4. Call `render_planner.plan(assembly_segments, downloaded_clips,
   voiceover_segments, subtitle_segments)` -> ordered `RenderPlanSegment`s.
5. Resolve the render profile defaults (D55) and persist through `CreateRenderPlan`
   with `source = "generated"`, the four artifacts' provenance
   (`*_asset_id` / `*_version`), and the profile metadata.

- `CreateRenderPlan` is the internal guarded persistence use-case. It accepts
  caller-supplied `RenderPlanSegment` entries, computes the next `RENDER_PLAN`
  version, writes JSON through `StoragePort`, sets `source`/provenance/profile
  metadata, and saves the asset index. It owns the canonical D51 status guard,
  defaults `source = "manual"`, and never transitions the run. Constructor
  dependencies are ports/factories only: `RunRepository`,
  `VersionedAssetRepository`, `StoragePort`, and optional `asset_id_factory`.
- **`RenderPlanInputMismatchError`** is a new application-layer error (in
  `backend/app/application/errors.py`), carrying `run_id` and a short reason. A new
  API exception handler maps it to **HTTP 409 Conflict**, mirroring the existing
  `AssetCreationRejectedError` handler. This follows the existing precedent of
  `ApprovedScriptRequiredError` -- a precondition failure (the run is in a valid
  status but an upstream input it needs is missing/inconsistent) that subclasses
  `ValueError` and maps to 409 through its own handler, distinct from the status
  guard. The mismatch is treated as a *reachable client condition* (for example
  regenerating the assembly plan to more segments without regenerating
  voiceover/subtitles), not an internal bug, so a named 409 -- not an unhandled
  `ValueError`/500 -- is the correct response, with a clear remedy (regenerate the
  stale upstream artifacts). Keeping the check in the use-case keeps the planner
  free of application-error imports. (Considered alternatives --
  a `ValueError` internal invariant, or a domain error raised inside the planner --
  are in Open Questions.)
- Expose only:
  - `POST /runs/{run_id}/render-plans/generate`
  - `GET /runs/{run_id}/render-plans`
  - `GET /runs/{run_id}/render-plans/latest`
- Do not expose a manual `POST /runs/{run_id}/render-plans` for caller-supplied
  records. Keeping creation internal avoids accepting arbitrary references,
  timeline windows, or profiles before any render semantics exist. Adding the
  manual route later is a trivial, symmetric one-route change.

`GenerateRenderPlan` is the first generation use-case with **four** latest-readers
plus a planner and a create use-case (seven constructor dependencies). This is the
deliberate consequence of being the first join phase; the hint-map architecture
test is extended to assert exactly this dependency set.

### D55. Storage and path convention; render profile defaults resolved by the use-case; no-overwrite via versioning

- Store each manifest as JSON bytes through `StoragePort`, indexed under
  `(run_id, AssetKind.RENDER_PLAN)`. Use private application helpers
  `_render_plan_segments_to_bytes` / `_render_plan_segments_from_bytes`, mirroring
  the subtitle/voiceover helpers: a JSON list of flat objects; the `*_seconds`
  fields round-trip as `float`, `order_index` as `int`, and the remaining fields as
  `str`.
- Store `source`, provenance, and the render profile in `VersionedAsset.metadata`
  (all strings, because `metadata` is `Mapping[str, str]`):
  - provenance: `video_assembly_plan_asset_id`, `video_assembly_plan_version`,
    `downloaded_clips_asset_id`, `downloaded_clips_version`, `voiceover_asset_id`,
    `voiceover_version`, `subtitles_asset_id`, `subtitles_version`;
  - profile: `aspect_ratio`, `resolution_width`, `resolution_height`, `fps`,
    `container`, `render_intent`.
- **Render profile defaults** are module-level constants the use-case resolves once
  and writes to manifest metadata, exactly as `GenerateSubtitles` resolves a
  run-level `language`:
  - `aspect_ratio = "16:9"`
  - `resolution_width = "1920"`
  - `resolution_height = "1080"`
  - `fps = "30"`
  - `container = "mp4"`
  - `render_intent = "voiceover_b_roll"`
  Keeping the profile in the use-case (not the planner) keeps the planner a pure
  join and keeps the whole-run profile on one authoritative source. No new request
  body or run field is introduced; making the profile a request/run setting later
  is additive (Open Questions).
- Codec fields (`video_codec`, `audio_codec`) are intentionally **not** recorded
  now. `aspect_ratio`/`resolution`/`fps`/`container` describe the *target format*
  (legitimate plan intent), whereas codec choice is an *encoder* concern the real
  `Renderer`/FFmpeg phase owns; recording fake codec constants now would imply an
  encode decision this foundation does not make. They are deferred (Open Questions).
- **Avoiding overwrites.** Each `GenerateRenderPlan` call creates a new, immutable
  `RENDER_PLAN` version; prior versions are never mutated -- the same append-only
  guarantee as every other asset phase. Because this foundation writes no output
  bytes, there is nothing else to overwrite. When a future real-render phase
  materializes a video (into `RENDER` via `Renderer`), it must version-scope the
  output directory so a re-render writes a fresh file rather than clobbering a prior
  version's output; that byte-level no-clobber rule is deferred with output
  materialization and flagged in Open Questions.

## Domain Model Proposal

- Add `AssetKind.RENDER_PLAN = "render_plan"`.
- Add and export frozen `RenderPlanSegment` with exactly the D52 fields, next to
  `SubtitleSegment` and `VoiceoverSegment` in `backend/app/domain/models.py` and
  `backend/app/domain/__init__.py`.
- Do not change `VideoAssemblySegment`, `DownloadedClip`, `VoiceoverSegment`,
  `SubtitleSegment`, `RenderSpec`, `RunStatus`, `AssetKind.RENDER`, the `Renderer`
  port, or run transition rules.
- Do not add output bytes, codecs, filter graphs, FFmpeg command fields, subtitle
  style fields, audio mix fields, absolute paths, or a domain set wrapper.
- Add `RenderPlan` only as an application read model pairing a `VersionedAsset`
  with parsed records, defined in the new `render_plan_assets.py` and exported from
  `backend/app/application/use_cases/__init__.py`.

## Asset / Storage Decision

- Persist the render plan as JSON bytes through the existing `StoragePort` (no
  video files). Index with `VersionedAssetRepository` under
  `(run_id, AssetKind.RENDER_PLAN)`. Metadata includes `source` (`"generated"` for
  `GenerateRenderPlan`, default `"manual"` for a direct `CreateRenderPlan` call),
  the four artifacts' `*_asset_id` / `*_version` provenance, and the render profile
  (`aspect_ratio`, `resolution_width`, `resolution_height`, `fps`, `container`,
  `render_intent`).
- A second generate creates version 2 and leaves earlier manifests and their
  provenance intact.
- The only stored bytes are JSON metadata; `clip_uri` and `voiceover_uri` are
  references and are never opened. Existing generic SQLite, filesystem, and
  in-memory adapters require no code or schema change beyond accepting the new enum
  value naturally. No `.gitignore` change is required for this phase:
  `data/assets/render_plan/*` is already covered by `data/assets/*`, and the future
  rendered output bytes are already covered by the existing `data/renders/*` ignore.

## Render Planner Port Decision

- Add and export `RenderPlanner` from the ports package
  (`backend/app/ports/providers.py`, `backend/app/ports/__init__.py`), separate
  from the reserved `Renderer`.
- Add and export `StubRenderPlanner` from the generation adapter package
  (`backend/app/infrastructure/generation/__init__.py`).
- Add a recording `FakeRenderPlanner` in `tests/fakes/providers.py` for use-case
  and API tests. It records the four input collections and returns configured or
  default `RenderPlanSegment` records; those tests do not depend on the concrete
  adapter.
- Wire only the port into application/API code. The concrete adapter is imported
  only by `main.py` and its own adapter/confinement tests.
- Do not place the planner in `provider_registry.py`; direct composition-root
  wiring matches the current scene/stock/retrieval/selection/assembly/download/
  voiceover/subtitle pattern and avoids an unrelated registry refactor.

## Deterministic Planner Decision

- `StubRenderPlanner` implements the D53 algorithm: join the four artifacts by
  `order_index`; copy `clip_uri`/`clip_provider`/`clip_provider_id` from the
  downloaded clip, `voiceover_uri` from the voiceover `audio_uri`, and
  `subtitle_text`/`subtitle_*_seconds`/`subtitle_language` from the subtitle; fold
  the visual window from assembly `target_duration_seconds` and the voiceover
  window from voiceover `duration_seconds`; preserve `order_index` and `scene_id`.
- It creates **no** video file, **no** placeholder output, and needs no path-safety
  helper (it copies existing references rather than building new ones). It is pure,
  returns records only, and touches no network, filesystem, subprocess, FFmpeg,
  media probe, or encoder. It does not set the render profile (use-case) and does
  not validate alignment (use-case). If a later phase performs real rendering, the
  output bytes must be written by a use-case through the reserved `Renderer` port
  into a `RENDER` `VersionedAsset` -- never by the domain/application layers and
  never to an arbitrary path.

## Use-Case Plan

Create `backend/app/application/use_cases/render_plan_assets.py`, using
`subtitle_assets.py` as the structural template.

1. **`CreateRenderPlan`**
   - `execute(run_id, render_plan_segments, source="manual", asset_metadata=None) -> VersionedAsset`.
   - Requires the run, enforces D51, computes the next `RENDER_PLAN` version, merges
     `{"source": source}` with any provenance/profile metadata, writes JSON through
     `StoragePort`, and saves the asset. Does not transition the run.
   - Constructor deps: `RunRepository`, `VersionedAssetRepository`, `StoragePort`,
     optional `asset_id_factory`.

2. **`GenerateRenderPlan`**
   - `execute(run_id) -> VersionedAsset`.
   - Applies the D51 guard before any read, then follows the D54 order: read the
     four latest artifacts, validate `order_index` alignment (raise
     `RenderPlanInputMismatchError` on mismatch), call the planner to join them,
     resolve the profile defaults, and persist through `CreateRenderPlan` with
     `source = "generated"` plus provenance and profile metadata. Does not parse
     storage itself and does not transition the run.
   - Constructor deps: `RunRepository`, `RenderPlanner`,
     `GetLatestVideoAssemblyPlan`, `GetLatestDownloadedClipSet`,
     `GetLatestVoiceover`, `GetLatestSubtitles`, `CreateRenderPlan`.

3. **`ListRenderPlans`**
   - `execute(run_id) -> Sequence[VersionedAsset]` via
     `asset_repository.list_for_run(run_id, AssetKind.RENDER_PLAN)`.

4. **`GetLatestRenderPlan`**
   - `execute(run_id) -> RenderPlan`.
   - Reads the latest asset, raises `AssetNotFoundError(RENDER_PLAN)` when absent,
     loads its JSON, and returns the parsed read model.

Export all four use-cases and `RenderPlan` from
`backend/app/application/use_cases/__init__.py`.

## API Route Plan

Add response models and routes in the existing `backend/app/api/assets.py` module,
consistent with the existing long route names.

| Method | Path | Returns | Purpose |
| --- | --- | --- | --- |
| `POST` | `/runs/{run_id}/render-plans/generate` | `201 AssetResponse` | Join the four latest upstream artifacts; persist a `RENDER_PLAN` asset (next version, `source=generated`). Applies the D51 rule; may return 409 on input mismatch. |
| `GET` | `/runs/{run_id}/render-plans` | `list[AssetResponse]` | List render-plan asset versions. |
| `GET` | `/runs/{run_id}/render-plans/latest` | `RenderPlanResponse` | Return the latest asset (with profile/provenance metadata) and parsed render-plan segments. |

Add `RenderPlanSegmentModel.from_domain`, `RenderPlanResponse.from_render_plan`,
and a `get_render_planner(request)` resolver reading
`request.app.state.render_planner`. The generate route has no request body in this
foundation (the profile comes from use-case defaults). Register the
`RenderPlanInputMismatchError` -> 409 handler. Existing application error handlers
provide the run/asset 404/409 behavior. There is no manual-create request DTO, raw
asset-byte endpoint, video endpoint, or render endpoint.

## Composition Root Decision

- Add optional `render_planner: RenderPlanner | None = None` to `create_app(...)`,
  default it to `StubRenderPlanner()`, and assign `app.state.render_planner`,
  following the existing `subtitle_composer` / `voiceover_generator` wiring style.
- Keep all repository, storage, latest-reader, create-use-case, and generate
  use-case construction explicit in the route dependency functions, following the
  current asset API pattern.
- Do not alter `provider_registry.py`, settings, environment variables, secrets, or
  lifespan behavior. The default planner is pure and owns no resource, so it never
  affects the database/storage lifespan decision.

## Test Checklist

### Domain and Serialization

- `AssetKind.RENDER_PLAN.value == "render_plan"` and is distinct from `RENDER`,
  `VIDEO_ASSEMBLY_PLAN`, `DOWNLOADED_CLIPS`, `VOICEOVER`, and `SUBTITLE_MANIFEST`.
- `RenderPlanSegment` is frozen (assignment raises) and has exactly the D52 fields.
- JSON round-trip preserves all fields and numeric types (every `*_seconds` field
  as `float`; `order_index` as `int`).
- Latest-read returns the newest parsed manifest; missing latest raises
  `AssetNotFoundError(RENDER_PLAN)`.

### Port and Adapter

- A fake satisfies runtime `isinstance(fake, RenderPlanner)`; the port resolves to
  `backend.app.ports.providers`.
- `get_type_hints(RenderPlanner.plan)` shows the four `Sequence[...]` parameters
  (`VideoAssemblySegment`, `DownloadedClip`, `VoiceoverSegment`, `SubtitleSegment`)
  and `return: Sequence[RenderPlanSegment]`.
- `RenderPlanner` is a different object from `Renderer`; the no-reuse decision is
  visible (separate protocol, separate port).
- `StubRenderPlanner` is deterministic and repeatable: the same four aligned inputs
  produce equal outputs.
- One `RenderPlanSegment` per assembly position, in ascending `order_index`;
  `order_index`/`scene_id` from the assembly segment; `clip_uri`/`clip_provider`/
  `clip_provider_id` copied from the matched downloaded clip; `voiceover_uri` copied
  from the matched voiceover `audio_uri`; `subtitle_text`/`subtitle_start_seconds`/
  `subtitle_end_seconds`/`subtitle_language` copied from the matched subtitle.
- Visual timeline folds correctly (`visual_start_0 == 0.0`; each `visual_start_n ==
  visual_end_{n-1}`; each `visual_end == visual_start + target_duration_seconds`);
  voiceover timeline folds correctly from voiceover `duration_seconds`.
- Matching is by `order_index`, not list position (assert with an input whose lists
  are stored in different orders -- the join still pairs by index).
- No `RenderPlanSegment` field contains an absolute path, drive-style prefix, or
  FFmpeg command; `clip_uri`/`voiceover_uri` remain the copied `memory://` values.

### Use-Cases and Lifecycle

- Create stores `RENDER_PLAN`, increments versions, and persists only JSON.
- `GenerateRenderPlan` tags `source=generated` and includes the four `*_asset_id`/
  `*_version` provenance keys and the six profile keys with the D55 defaults;
  `CreateRenderPlan` defaults `source=manual`.
- The status guard rejects every state except `scenes_approved` with
  `AssetCreationRejectedError(kind=render_plan)`, checked before any upstream read
  and before planner/persistence work (409, not 404), persisting nothing.
- `RunNotFoundError` when the run is missing (planner not called, no reads).
- Each missing upstream artifact yields `AssetNotFoundError(<kind>)` (404),
  reported in pipeline order (assembly plan first), persisting nothing.
- `RenderPlanInputMismatchError` (409) when the four artifacts' `order_index` sets
  or counts differ (for example a voiceover missing one position), checked before
  the planner is called, persisting nothing.
- The planner is called once with the four latest collections; the produced
  segments aggregate every result, in ascending `order_index`.
- An empty pipeline (zero assembly segments, with zero downloaded/voiceover/
  subtitle records) yields an empty `RENDER_PLAN`, calls the planner with empty
  collections, records the profile metadata, and leaves the run exactly
  `scenes_approved`.
- A non-`en` subtitle language propagates: every `subtitle_language` equals the
  upstream value (for example `"te"`), with no provider call.
- `ListRenderPlans` is version-ordered; a second generate creates version 2; the
  run stays exactly `scenes_approved` after create and generate.

### API

- `POST .../render-plans/generate` returns 201 with `kind=render_plan`,
  `version=1`, `source=generated`, the four provenance pairs, and the profile
  metadata.
- `GET` list returns versions in order; `GET` latest returns parsed `segments` with
  contiguous visual timing and the profile/provenance in the asset metadata.
- 404 when the run is missing; 404 when any upstream artifact is missing; 409 when
  status is not `scenes_approved` (before any dependency 404); 409 on input
  mismatch; versioning across two generates.
- Only generate/list/latest routes exist; no manual create, video, or render route
  is registered.

### Architecture Boundaries and No-Real-Render Safety

- Domain auto-scan (`test_domain_has_no_framework_or_outer_layer_imports`) confirms
  no framework or outer-layer imports for the new domain code.
- Add `RenderPlanner` to `test_provider_interfaces_live_in_ports`.
- Extend the asset-use-case hint map with `CreateRenderPlan`
  (run/asset/storage + `asset_id_factory`), `ListRenderPlans` (asset repo), and
  `GetLatestRenderPlan` (asset repo + storage); extend the generation-use-case hint
  map with `GenerateRenderPlan` (`run_repository`, `render_planner`, the four
  latest-readers, and `create_render_plan`) -- the first seven-dependency entry.
- Application auto-scan (`test_application_does_not_import_infrastructure`) and the
  API route scans (`test_assets_route_imports_use_cases_not_infrastructure`,
  `test_api_routes_depend_on_use_cases_not_infrastructure`) cover the new files.
- `test_generation_adapters_import_no_api_application_or_external_modules` already
  forbids api/application/SDK/HTTP/subprocess/FFmpeg modules; the pure
  `StubRenderPlanner` inherits that coverage. Optionally extend the forbidden set
  with video/media libraries (`ffmpeg`, `moviepy`, `imageio`, `imageio_ffmpeg`,
  `av`, `cv2`) to prove the stub performs no real composition or encode.
- Add `test_stub_render_planner_import_confined_to_composition_root` proving only
  `main.py` imports `StubRenderPlanner`.
- Assert persisted bytes decode as JSON and contain no video/output bytes; no
  parsed `RenderPlanSegment` carries an absolute path, drive-style prefix, or FFmpeg
  command string; `clip_uri`/`voiceover_uri` remain `memory://` references.
- Assert the planner and use-case perform no file-existence check or media probe
  (no `os.path.exists`/`Path.exists`/`open`/`stat` on the referenced URIs).
- Search the implementation diff for FFmpeg/subprocess calls, FFmpeg command
  construction, media probing, video/audio encoders, real/placeholder output
  writes, file-existence checks, `RENDER`/`Renderer`/`RenderSpec` materialization,
  subtitle styling, audio mixing, and status transitions; none should be present.

### End-to-End

Extend `tests/test_draft_planning_workflow.py` through:

```text
prompt -> script -> scene table -> stock plan -> clip candidates
       -> selected clips -> video assembly plan -> downloaded clips
       -> voiceover -> subtitles -> render plan
```

After the subtitle steps, assert `POST .../render-plans/generate` returns 201
(`kind=render_plan`, `version=1`, `source=generated`, the four provenance pairs,
profile metadata with the D55 defaults) and `GET .../render-plans/latest` shows one
segment per assembly position, in the same `order_index` order, with `clip_uri`
starting `memory://downloads/`, `voiceover_uri` starting `memory://voiceovers/`,
`subtitle_text` equal to the upstream caption, contiguous visual timing, and the
run still exactly `scenes_approved` (not `rendered`, no transition).

## Implementation Slices

Implement one slice at a time in inward-to-outward order. Run focused tests after
each slice and the full suite after the final slice.

### Slice 1: Domain -- asset kind and record

- **Files:** `backend/app/domain/models.py`, `backend/app/domain/__init__.py`,
  new `tests/test_render_plan_segment.py`.
- **Change:** Add `AssetKind.RENDER_PLAN` and the frozen `RenderPlanSegment`
  dataclass/export (D50, D52). Leave `RENDER` untouched.
- **Tests:** Kind value/distinction (including distinct from `RENDER`), exact
  fields, frozen behavior.
- **Acceptance:** Domain tests and the domain boundary scan pass; no other layer
  changes.

### Slice 2: Port -- `RenderPlanner`

- **Files:** `backend/app/ports/providers.py`, `backend/app/ports/__init__.py`,
  new `tests/test_render_planner_port.py`.
- **Change:** Add/export the D53 runtime-checkable protocol, separate from
  `Renderer`.
- **Tests:** Runtime conformance against a fake, module location, exact type hints
  (four `Sequence[...]` params, `return: Sequence[RenderPlanSegment]`), distinct
  from `Renderer`.
- **Acceptance:** Port tests and architecture tests pass.

### Slice 3: Deterministic adapter and test fake

- **Files:** new `backend/app/infrastructure/generation/stub_render_planner.py`,
  generation package export, `tests/fakes/providers.py` (`FakeRenderPlanner`),
  extended `tests/test_generation_adapters.py`.
- **Change:** Implement the D53 join + timeline folds and the recording fake.
- **Tests:** One record per position, field copies, visual/voiceover folds,
  order_index matching, repeatability, port conformance.
- **Boundary:** No application/API/external/media imports; no file/probe/subprocess.
- **Acceptance:** Focused adapter and generation-boundary tests pass.

### Slice 4: Application -- render-plan use-cases and mismatch error

- **Files:** new `backend/app/application/use_cases/render_plan_assets.py`,
  use-case package export, `backend/app/application/errors.py`
  (`RenderPlanInputMismatchError`), new `tests/test_render_plan_use_cases.py`.
- **Change:** Add the `RenderPlan` read model, JSON helpers,
  create/generate/list/latest use-cases, D51 guard, D54 ordering + alignment
  validation, and provenance/profile metadata.
- **Tests:** Versioning, round-trip, source/provenance/profile metadata,
  latest/list, errors (404 per missing artifact, 409 status, 409 mismatch),
  guard-before-read, planner-call, no transition.
- **Boundary:** Dependencies are ports and sibling use-cases only.
- **Acceptance:** Focused use-case and application-boundary tests pass.

### Slice 5: API routes and composition wiring

- **Files:** `backend/app/api/assets.py`, `backend/app/api/errors.py`,
  `backend/app/main.py`, new `tests/test_render_plan_api.py`.
- **Change:** Add DTOs, generate/list/latest routes, the `get_render_planner`
  resolver, the `RenderPlanInputMismatchError` -> 409 handler, the `render_planner`
  `create_app` parameter, and the default `StubRenderPlanner` wiring.
- **Tests:** 201/404/409 (status and mismatch), latest/list/versioning, route
  absence, injected fake.
- **Boundary:** Routes contain no planner, lifecycle, storage, or version logic;
  the concrete adapter appears only in the composition root.
- **Acceptance:** API and route-boundary tests pass.

### Slice 6: Boundary hardening, E2E, and phase audit

- **Files:** `tests/test_architecture_boundaries.py`,
  `tests/test_draft_planning_workflow.py`; `.gitignore` only if inspection finds a
  real gap (none expected for `data/assets/render_plan/*`).
- **Change:** Add `RenderPlanner` to the port-location test, the three
  persistence/read use-cases to the asset-use-case hint map, `GenerateRenderPlan`
  to the generation-use-case hint map, the `StubRenderPlanner` confinement test, the
  optional extended video/media forbidden-import set, and extend the full workflow.
- **Tests:** Focused architecture/E2E tests, then the full suite.
- **Acceptance:** Full suite and `git diff --check` pass; no rendered video,
  output files, secrets, database files, caches, or virtual-environment files are
  staged.

### Slice Order and Dependencies

```text
1 domain -> 2 port -> 3 stub adapter + fake
                   -> 4 application use-cases + mismatch error
                   -> 5 API + composition root
                   -> 6 boundaries + E2E + audit
```

Slices 3 and 4 can be developed independently after Slice 2 because application
tests use the recording fake. The concrete adapter must exist before Slice 5 wires
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

For the later implementation phase, run focused tests after every slice, then both
commands above before commit. Also inspect staged files to confirm no rendered
video, output files, secrets, SQLite databases, caches, or virtual-environment
files are included.

## Explicit Non-Goals / Deferred Work

- Real rendering, video composition, or any rendered/output video bytes.
- FFmpeg, `ffmpeg`/`ffprobe` subprocess calls, `moviepy`/`imageio`/`av`/`cv2` or any
  encoder/decoder, transcoding, muxing, or filter graphs.
- Generating, previewing, or storing an FFmpeg command string of any kind
  (initial recommendation: no command preview now; not justified for this phase).
- Opening, resolving, probing, or checking the existence of any referenced clip or
  audio file; sample rates, codecs, bitrates, frame rates, durations probed from
  media, or any media analysis.
- Writing any non-JSON bytes, including placeholder output, in this phase.
- Materializing the `RENDER` video asset or registering it in the index; using or
  modifying the reserved `Renderer` port or `RenderSpec`.
- Subtitle styling (font, size, color, position), caption burn-in, or caption
  muxing.
- Audio mixing, levels, ducking, fades, normalization, or music beds.
- Codec selection (`video_codec`/`audio_codec`) or any encoder configuration.
- Transitions, effects, color grading, scaling/cropping, or aspect-ratio
  conversion of media.
- AI ranking, scoring, re-timing, or render-quality estimation.
- Render/preview UI, frontend, progress reporting, or a manual public create route.
- Scene refinement or changes to script, scene, stock planning, candidate
  retrieval, selected-clip, video-assembly-plan, downloaded-clip, voiceover, or
  subtitle behavior.
- A new run status or any run transition (the `rendered` transition stays the
  future renderer's responsibility).
- Provider registry refactoring, a generic pipeline orchestrator, workers, or
  queues.
- Redis, Postgres, S3, cloud/SaaS features, auth, or pagination.
- Database schema changes or a generic JSON schema/version registry.
- Byte-level no-clobber rules and absolute-path resolution (deferred with output
  materialization).

## Open Questions

- **Where mismatch validation lives.** This foundation validates `order_index`
  alignment in the use-case and raises `RenderPlanInputMismatchError` -> 409 (D54).
  The considered alternatives -- folding the check into the planner as a `ValueError`
  internal invariant (rejected: it produces a 500 for a reachable client condition
  and broadens what the use-case must catch) or as a domain error raised inside the
  planner (rejected for the foundation: it couples the pure planner to error policy)
  -- remain straightforward to adopt later if the planner gains other validation.
- **Profile ownership and source.** The render profile is use-case default constants
  in manifest metadata (D55). A later phase must decide whether `aspect_ratio`,
  `resolution`, `fps`, and `container` become request fields, run settings, or a
  richer `RenderProfile` value object (and whether the planner should own them).
  The metadata shape is designed so any of these is additive.
- **Codec fields.** `video_codec`/`audio_codec` are deferred (D55) because codec
  choice is an encoder concern owned by the real renderer. When real rendering lands
  they are added to the profile metadata (or a `RenderProfile`) with no segment
  reshape.
- **Three timelines vs one.** The model carries separate visual, voiceover, and
  subtitle windows (D52), which coincide in the current deterministic pipeline. A
  real renderer must decide trim/pad/stretch when a synthesized narration diverges
  from the visual slot or a real caption aligner shifts cues; that reconciliation is
  deliberately not decided here, and the separate fields are retained so it is
  additive.
- **Per-position vs per-scene granularity.** This foundation emits one
  `RenderPlanSegment` per assembly position (D52). If a future phase re-groups (for
  example merging a scene's positions into a single shot), the `scene_id` field is
  the hook; resolving it is deferred.
- **Per-segment status/reason.** Unlike `DownloadedClip`/`VoiceoverSegment`/
  `SubtitleSegment`, `RenderPlanSegment` carries no `status`/`generation_reason`
  field, because the use-case's alignment guard makes a partially-joined segment
  unrepresentable (every emitted segment has all references). If a future planner
  must emit incomplete segments (for example a missing optional caption), adding
  those fields is additive.
- **Render output materialization and the `rendered` transition.** This foundation
  is metadata-only. A real-render phase will read the `RENDER_PLAN`, build a
  `RenderSpec`, call `Renderer` to produce a `RENDER` video asset under a
  version-scoped output directory, and own the run's `rendered` transition. The
  contract (per-position references plus visual/audio/caption windows plus a target
  profile) is designed so that change is additive.
- **Byte-level no-clobber.** When real output is written, the output directory must
  be version-scoped so re-renders do not overwrite a prior plan version's video.
  Deferred until output materialization exists.
```