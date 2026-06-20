# Clip Download Foundation

Design document for the next phase. This records the intended design and slice
plan before any code is written. No backend, test, or product implementation is
part of this document. The approved direction continues the asset-only tail of
the pipeline: clip retrieval turned `StockQuerySpec` into `ClipCandidate`,
selection turned candidates into `SelectedClip`, and assembly planning turned
selections plus scenes into a `VideoAssemblyPlan`. This phase turns the latest
video assembly plan's segments into a durable, versioned set of *downloaded
clip* records that carry local file references, through a downloader port. It
introduces the download abstraction only. It does not call any real provider,
perform any network request, store real media bytes, probe media, invoke
FFmpeg, or render video.

## Goal

Given the latest video assembly plan for a run, produce a durable, versioned set
of *downloaded clips*: exactly one `DownloadedClip` per `VideoAssemblySegment`,
copying the segment's provider/source metadata and adding a deterministic local
file reference plus a download status. The artifact answers, for each timeline
segment: which provider clip would back this segment, and where would its local
media file live, as metadata (provider, provider clip id, source URL, local
URI, content type, dimensions, duration, order, status)?

This foundation is deliberately narrower than a real downloader. It makes the
"which clips are now local, and where" decision inspectable and repeatable
*without* fetching bytes over the network, storing downloaded media, resolving
real provider URLs, probing media, transcoding, or transitioning the run
lifecycle. For this foundation the downloader is a deterministic fake that
fabricates stable local references only; no real Pexels/Pixabay download exists.

## Target Workflow

The existing asset-only tail is extended by one step. The run reaches
`scenes_approved` exactly as today and remains there while stock planning, clip
retrieval, clip selection, assembly planning, and now clip download create
independently versioned JSON assets.

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
-> download clips                    # NEW: reads the latest video assembly plan,
                                     # calls the ClipDownloader per segment,
                                     # persists a DOWNLOADED_CLIPS asset,
                                     # run stays scenes_approved (asset-only)
```

The target product workflow becomes:

```text
prompt -> script draft -> scene table -> stock plan -> clip candidates
       -> selected clips -> video assembly plan -> downloaded clips
```

## Architecture Rule

Dependencies point inward:

`API/UI -> application use-cases -> domain models/services -> ports/interfaces -> infrastructure adapters`

- The domain remains framework-free and serialization-free.
- Application use-cases orchestrate repositories, storage, latest-asset readers,
  and the downloader port. They do not import infrastructure, open sockets, or
  touch the filesystem directly.
- `ClipDownloader` is a port expressed only in domain types (plus the `run_id`
  identifier string).
- `StubClipDownloader` is a pure infrastructure adapter with no network,
  filesystem, subprocess, FFmpeg, provider SDK, API, or application dependency.
- API routes call application use-cases only. Lifecycle and versioning rules do
  not move into route functions.
- Concrete downloader wiring remains explicit in `backend/app/main.py`.

This is the first phase whose *eventual* real implementation will write
non-JSON local files. That makes the boundary rule especially important: the
domain and application layers must never perform filesystem work. Any byte
materialization (placeholder or real) belongs behind a port/adapter -- the
existing `StoragePort` and its `LocalFilesystemStorage` adapter -- orchestrated
by a use-case through the port. This foundation keeps that risk at zero by
writing only JSON manifest bytes (see Asset / Storage Decision and D34).

## Existing Foundation

This design is based on the current implementation, confirmed by reading the
source, not only the earlier design notes:

- `VersionedAsset` stores `asset_id`, `kind`, `version`, `uri`, and string
  metadata (`metadata` is `Mapping[str, str]`). The generic repository and
  storage ports already support new asset kinds without a database schema
  change.
- `AssetKind` currently includes `SCRIPT`, `SCENE_TABLE`, `STOCK_PLAN`,
  `CLIP_CANDIDATES`, `SELECTED_CLIPS`, `VIDEO_ASSEMBLY_PLAN`, `STOCK_CLIP`,
  `VOICE`, `SUBTITLE`, and `RENDER`. `STOCK_CLIP` exists but is still unused in
  any use-case; every prior design note reserves it for "fetched media bytes /
  the downloaded clip (a later phase)".
- `VideoAssemblySegment` is a frozen domain dataclass with `scene_id`,
  `query_text`, `narration`, `visual_query`, `provider`, `provider_clip_id`,
  `title`, `preview_url`, `source_url`, `target_duration_seconds`,
  `source_duration_seconds`, `width`, `height`, `order_index`, `transition`,
  `continuity_note`, and `selection_reason`. Its `order_index` is zero-based and
  contiguous over the full plan, and the plan already copied selection metadata
  into each segment for durability. This is the per-item input this phase
  downloads from.
- `GetLatestVideoAssemblyPlan` returns the latest parsed
  `VideoAssemblyPlan(asset, segments)` and raises
  `AssetNotFoundError(run_id, VIDEO_ASSEMBLY_PLAN)` when missing. This is the
  read path and the natural dependency guard this phase reuses.
- The video-assembly-plan use-cases (`CreateVideoAssemblyPlan`,
  `GenerateVideoAssemblyPlan`, `ListVideoAssemblyPlans`,
  `GetLatestVideoAssemblyPlan`) plus the `_segments_to_bytes` /
  `_segments_from_bytes` helpers in `video_assembly_plan_assets.py` are the exact
  structural template for this phase's `downloaded_clip_assets.py` module. The
  asset-only guard `_VIDEO_ASSEMBLY_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})`
  and the guard-before-read ordering in `GenerateVideoAssemblyPlan` are copied
  directly.
- `RunStatus` is `created -> script_ready -> script_approved -> scenes_ready ->
  scenes_approved -> rendered` (plus `failed`). `scenes_approved` only
  transitions to `rendered`/`failed`; there is no planning/retrieval/selection/
  assembly/download status, and this phase adds none.
- `backend/app/ports/providers.py` holds runtime-checkable planner/provider/
  selector protocols using domain types (`ClipRetrievalProvider`,
  `ClipSelector`, `VideoAssemblyPlanner`, ...). `backend/app/infrastructure/
  generation` holds pure deterministic defaults (`StubClipRetrievalProvider`,
  `DeterministicClipSelector`, `DeterministicVideoAssemblyPlanner`, ...), and
  `backend/app/main.py` wires those defaults through `app.state`.
- `StoragePort.save_asset(asset, data)` writes bytes for a `VersionedAsset`;
  `LocalFilesystemStorage` derives the path as `{kind}/{asset_id}/v{version}`
  under an injected storage root, validates each component as a safe path
  segment, and confirms every resolved path stays within the root. The in-memory
  test storage keys generically on a `memory://{kind}/{asset_id}/v{version}` uri.
- Persistence is kind-agnostic: SQLite stores `assets.kind` as text without an
  enum check constraint, local storage derives paths from `kind.value`, and the
  in-memory fakes key generically on `(run_id, kind)`. No SQLite migration or
  storage refactor is needed for a new asset kind.
- `.gitignore` already ignores `data/assets/*` (keeping `.gitkeep`), so
  `data/assets/downloaded_clips/*` is already covered. It also already ignores
  `data/clips/*`, reserved for the future real media bytes a later phase will
  download.
- Architecture boundary tests scan domain, application, API, ports, and the
  generation package for forbidden imports, and confine each concrete default
  (`StubStockClipPlanner`, `StubClipRetrievalProvider`, `DeterministicClipSelector`,
  `DeterministicVideoAssemblyPlanner`) to `main.py`. New files in those layers
  inherit forbidden-import coverage automatically; this phase adds a parallel
  confinement test for its new default.

## Problem Being Solved

The video assembly plan says which provider clip should appear at each position
in the final timeline, with target durations and narration context. But every
clip reference in the pipeline so far is still a remote `source_url` plus
provider identifiers -- the system has no notion of a *local* clip and no local
file reference at all. A future renderer cannot open a `source_url`; it needs a
local media file per timeline segment.

This phase introduces the narrow foundation for that transition: a domain model
and asset that represent, per timeline segment, a downloaded clip with a stable
local file reference and a download status, produced through a replaceable
downloader port. It deliberately stops short of fetching or storing any real
media so the abstraction, persistence, and API shape can be locked in and tested
before any network, provider SDK, media probe, or FFmpeg concern is introduced.

## Answers to Design Questions

| # | Question | Decision |
| --- | --- | --- |
| 1 | Read latest video assembly plan or latest selected clips? | The latest **video assembly plan** (D33). It carries timeline order (`order_index`), target/source durations, narration context, and already-copied provider/source metadata per segment. |
| 2 | Downloaded clip domain model name? | `DownloadedClip` (D34), a frozen metadata-only domain dataclass. |
| 3 | New asset kind? | Yes: `AssetKind.DOWNLOADED_CLIPS = "downloaded_clips"` (D32). |
| 4 | Reuse `STOCK_CLIP` for this set asset? | No (D32). `DOWNLOADED_CLIPS` is the JSON manifest of many records; `STOCK_CLIP` stays reserved for a future single-file media-bytes asset. The code's intent for `STOCK_CLIP` is the per-file download, not this set. |
| 5 | One set asset, or one asset per clip? | One **set** asset containing many `DownloadedClip` records (D34), mirroring `SELECTED_CLIPS` and `VIDEO_ASSEMBLY_PLAN`. |
| 6 | Local file reference field? | `local_uri` only: a downloader-defined `memory://downloads/...` reference, never absolute or arbitrary; plus `content_type` (D34/D37). |
| 7 | Copy assembly segment metadata for durability? | Yes (D34). Copy `provider`, `provider_clip_id`, `title`, `source_url`, dimensions, source duration, `scene_id`, `query_text`, and `order_index`, matching the copy-not-reference rule of D22/D28. |
| 8 | Downloader port? | Yes: `ClipDownloader.download(run_id, segment) -> DownloadedClip` (D35), per-segment, expressed in domain types. |
| 9 | Deterministic fake behavior? | Map each `VideoAssemblySegment` to one `DownloadedClip`: copy metadata, keep `order_index`, set `download_status = "available"` and `download_reason = "deterministic_placeholder"`, and derive a stable `memory://` local reference (D35). |
| 10 | Placeholder files or metadata-only? | **Metadata-only** references this foundation; no bytes are written (D34). The alternative (tiny placeholders via `StoragePort`) is documented and is a one-slice change; render validation path explained below. |
| 11 | Storage path convention? | Manifest JSON under `data/assets/downloaded_clips/...` via `StoragePort`. Each record's reference is `downloads/{run_id}/{order_index:04d}/{provider}-{provider_clip_id}.mp4`, exposed as a `memory://`-scheme `local_uri` (D37). |
| 12 | Avoid overwriting files? | Append-only set versioning (`next_version` on `DOWNLOADED_CLIPS`) plus per-segment paths unique by `(run_id, order_index, provider_clip_id)`. Byte-level no-clobber is deferred with byte materialization (D37). |
| 13 | Use-cases? | `CreateDownloadedClipSet`, `DownloadClips`, `ListDownloadedClipSets`, `GetLatestDownloadedClipSet` (D36). |
| 14 | API routes? | `POST .../downloaded-clips/download`, `GET .../downloaded-clips`, `GET .../downloaded-clips/latest` (D36). No manual create route. |
| 15 | Run status gate? | `RunStatus.SCENES_APPROVED`, checked before the assembly-plan read (D33). |
| 16 | Transition the run status? | No. Asset-only; no new `RunStatus`; no transition (D33). |
| 17 | Tests for boundaries / fake-only / no network? | See Test Checklist. Reuse the auto-scanning suite; add port-location, use-case-hint, confinement, deterministic-download, round-trip, guard-ordering, `memory://`-only/no-media-bytes, and no-real-network assertions. |
| 18 | Explicitly deferred? | See Explicit Non-Goals / Deferred Work. No real download, media bytes, probing, FFmpeg, render, `STOCK_CLIP` materialization, run transition, UI, or upstream changes. |

## Design Decisions

These decisions continue the project decision log: D1-D7 cover script/scene
planning, D8-D13 stock planning, D14-D19 clip retrieval, D20-D25 selected clip
selection, and D26-D31 video assembly planning. This phase adds D32-D37.

### D32. Add `AssetKind.DOWNLOADED_CLIPS`; reserve `STOCK_CLIP` for future media bytes

- Add `DOWNLOADED_CLIPS = "downloaded_clips"` to `AssetKind`.
- It represents the set of downloaded-clip records derived from a video assembly
  plan: one `DownloadedClip` per timeline segment, each with a local file
  reference and download status, persisted as one versioned JSON asset. It is
  distinct from `VIDEO_ASSEMBLY_PLAN` (timeline intent), `SELECTED_CLIPS`
  (selection results), `STOCK_CLIP` (future per-file media bytes), and `RENDER`
  (future rendered output).
- Do **not** reuse `STOCK_CLIP`. Across every prior design note `STOCK_CLIP` is
  reserved for "fetched media bytes / the downloaded clip (a later phase)" -- a
  single-file media asset written through `StoragePort.save_asset` as its own
  `VersionedAsset`. That is the per-file artifact a future byte-materialization
  slice will produce; it is not this phase's many-records set/manifest. Keeping
  the manifest (`DOWNLOADED_CLIPS`) and the eventual per-file media bytes
  (`STOCK_CLIP`) as distinct kinds lets the download manifest and the byte store
  evolve and re-run independently without colliding versions.
- Persist only JSON metadata through the existing `StoragePort`, indexed through
  `VersionedAssetRepository`. `source_url` and `local_uri` are references and are
  never fetched or opened in this phase. No SQLite migration, storage adapter
  change, `.gitignore` change, or JSON schema registry is added: persistence is
  kind-agnostic, and manifest bytes land under `data/assets/downloaded_clips/...`,
  already covered by the `data/assets/*` ignore.

### D33. Read the latest video assembly plan; asset-only; gated at `scenes_approved`; never transitions the run

- Read from `GetLatestVideoAssemblyPlan`, **not** `GetLatestSelectedClipSet`. The
  assembly plan is the authoritative timeline: it carries `order_index` (the
  position each clip occupies), `target_duration_seconds` and
  `source_duration_seconds`, narration context, and -- because D28 copied
  selection metadata into each segment -- `provider`, `provider_clip_id`,
  `source_url`, `title`, and dimensions. Selected clips alone lack timeline order
  and target duration. Reading the assembly plan means the download manifest
  preserves timeline order for free and needs only one upstream read.
- Define `_DOWNLOAD_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})` in the new
  application module. Both `DownloadClips` and the internal
  `CreateDownloadedClipSet` enforce this status. The download use-case checks it
  first so an invalid run returns `AssetCreationRejectedError` (HTTP 409) before
  the assembly-plan read can produce a 404.
- Re-downloading while `scenes_approved` creates the next `DOWNLOADED_CLIPS`
  version and leaves the run unchanged. Add no status between `scenes_approved`
  and `rendered`, and call no run transition method. A future renderer remains
  responsible for the eventual `rendered` transition.
- If no video assembly plan exists, `GetLatestVideoAssemblyPlan` naturally raises
  `AssetNotFoundError(run_id, VIDEO_ASSEMBLY_PLAN)` (mapped to HTTP 404). No
  special-casing is added.

### D34. Add `DownloadedClip`; use an application `DownloadedClipSet` read model; metadata-only local references

Add a frozen domain dataclass:

```python
@dataclass(frozen=True)
class DownloadedClip:
    scene_id: str            # links the record back to its scene/query group
    query_text: str          # the stock query that produced the clip
    provider: str            # copied from the assembly segment
    provider_clip_id: str    # copied; stable back-reference to the source clip
    title: str
    source_url: str          # reference only; the URL a real downloader would GET
    local_uri: str           # downloader-defined memory:// reference; never an absolute OS path
    content_type: str        # e.g. "video/mp4"
    duration_seconds: float  # the source clip's own duration (copied)
    width: int
    height: int
    order_index: int         # copied from the segment; preserves timeline order
    download_status: str     # e.g. "available"
    download_reason: str     # why/how, e.g. "deterministic_placeholder"
```

Field semantics:

- `scene_id`, `query_text`, `provider`, `provider_clip_id`, `title`,
  `source_url`, `duration_seconds`, `width`, `height`, and `order_index` are
  copied from the matching `VideoAssemblySegment`. `duration_seconds` is the
  segment's `source_duration_seconds` (the clip's own length); the timeline
  *target* duration deliberately stays in the assembly plan and is not
  duplicated here. Copying keeps each manifest version durable even when the
  assembly plan is regenerated later, matching the copy-not-reference rule of
  D22/D28.
- `local_uri` is the single local reference -- the value a future renderer would
  resolve to obtain the media file. In this foundation it is a downloader-defined
  `memory://downloads/...` placeholder reference (no bytes exist), making it
  unmistakable, like the `memory://` URLs the stub provider and selector already
  produce, that nothing was fetched. It is *not* produced by
  `LocalFilesystemStorage` and is not resolved by any current storage API; it is
  always relative and run-scoped, never an absolute OS path and never a
  user-supplied arbitrary path.
- `content_type` is a deterministic constant in the fake (`"video/mp4"`); it
  describes the intended media type, not a probed value.
- `download_status` and `download_reason` make the record explicit about whether
  a local file is considered present and why. The fake always emits
  `"available"` / `"deterministic_placeholder"`; the fields exist so a future
  real downloader can record `"failed"`, `"skipped"`, etc. without a schema
  change.

The copied fields are descriptive metadata, not media and not executable render
commands. The record contains no media bytes, byte ranges, codecs, frame rates,
or FFmpeg instructions.

Add `DownloadedClipSet` in the application layer as:

```python
class DownloadedClipSet(NamedTuple):
    asset: VersionedAsset
    downloaded_clips: tuple[DownloadedClip, ...]
```

Do not add a domain-level set wrapper -- symmetry with the selected-clip and
assembly-plan slices plus YAGNI; the application read model already pairs the
`VersionedAsset` with parsed records.

**Metadata-only, no placeholder bytes (Q10).** This foundation writes no media
files: the only bytes persisted are the JSON manifest. The downloader fake is
pure and the use-case writes exactly one asset (the manifest) through
`StoragePort`. This keeps the phase perfectly symmetric with retrieval,
selection, and assembly planning, keeps the new generation adapter pure (so the
existing generation-boundary tests pass unchanged), and -- critically -- keeps
the first download-shaped phase from introducing any non-JSON filesystem write,
so the "no filesystem work in domain/application" rule is satisfied by
construction. The considered alternative (write tiny deterministic placeholder
bytes through `StoragePort`, registering one `STOCK_CLIP` `VersionedAsset` per
file) is a clean, one-slice extension recorded in Open Questions; it is not
adopted now because it pins `STOCK_CLIP` semantics, abuses per-`(run, kind)`
versioning as a per-clip index, and adds storage behavior the foundation does
not need.

How later render validation works without placeholder bytes: this foundation
locks the *contract* -- a stable, run-scoped, order-indexed local reference per
timeline segment plus durable provider/source metadata. A future phase swaps
`StubClipDownloader` for a real `ClipDownloader` (or adds a
"materialize placeholders" adapter) that materializes bytes at the deterministic
destination. Because the current `StoragePort` saves and loads versioned assets
only, that phase will need either a new storage method/port for media objects or
one `STOCK_CLIP` `VersionedAsset` per file; it then points each `local_uri` at
the materialized object. Render validation resolves each segment's `local_uri`
against the injected storage root to an absolute path and probes/opens the real
file, joining the assembly segment and the downloaded-clip record by
`order_index` + `provider_clip_id`. Until then, render-readiness tests assert
*structural* readiness (every segment has exactly one downloaded-clip record
with a well-formed local reference and an `"available"` status), not byte
presence.

### D35. `ClipDownloader` is a per-segment port; the deterministic fake maps each segment purely

Define a runtime-checkable port in `backend/app/ports/providers.py`:

```python
@runtime_checkable
class ClipDownloader(Protocol):
    def download(
        self, run_id: str, segment: VideoAssemblySegment
    ) -> DownloadedClip:
        """Resolve one timeline segment to a local downloaded-clip record."""
        ...
```

- **Per-segment, not whole-plan.** A real download is per-clip: one network GET
  per `source_url`. The per-segment boundary mirrors `ClipRetrievalProvider.
  retrieve(query)` (per-query) and lets the use-case aggregate whole-plan-level
  into one manifest (the D17 pattern). The port takes `run_id` so the downloader
  -- which in the real world owns where bytes are written -- can derive a stable,
  run-scoped local reference; `run_id` is a plain identifier string, the same
  shape the repositories already accept, not a layer violation.
- The port imports only `VideoAssemblySegment` and `DownloadedClip` from the
  domain. It has no repository, storage, FastAPI, provider SDK, HTTP,
  filesystem, subprocess, or renderer type in its contract.
- **Why a port at all.** The fake is pure (no I/O), so a port is not required for
  dependency-inversion-over-I/O reasons today. It is still preferred because the
  download *policy* is exactly the part that will gain real I/O (HTTP fetch,
  byte storage, retries, content-type detection); isolating it behind a port
  keeps that churn out of the use-case and routes, gives the proven stub/fake
  test split, and lets a real downloader plug in at `main.py` with zero
  use-case/route change. This reuses an existing, proven pattern
  (`ClipRetrievalProvider`/`ClipSelector`) rather than inventing one.

Add `StubClipDownloader` under `backend/app/infrastructure/generation`, named
for symmetry with `StubClipRetrievalProvider` (it stands in for an absent real
download integration rather than expressing a legitimate v1 *policy* the way
`DeterministicClipSelector` does). Its algorithm for each segment:

1. Copy `scene_id`, `query_text`, `provider`, `provider_clip_id`, `title`,
   `source_url`, `width`, `height`, and `order_index` from the segment, and set
   `duration_seconds = segment.source_duration_seconds`.
2. Set `content_type = "video/mp4"`, `download_status = "available"`,
   `download_reason = "deterministic_placeholder"`.
3. Derive a stable, run-scoped reference
   `local_uri = f"memory://downloads/{run_id}/{order_index:04d}/{provider}-{provider_clip_id}.mp4"`,
   after validating the dynamic components (`run_id`, `provider`,
   `provider_clip_id`) with a tiny safe-segment helper **reimplemented locally**
   in the adapter. That helper rejects empty components, `.`/`..`, slashes,
   backslashes, drive-style `:` prefixes, and null bytes. It must **not** import
   the private `LocalFilesystemStorage._safe_component`.

The adapter is pure and repeatable: same inputs produce equal outputs. It
performs no randomness, ranking, scoring, network request, media probe, file
access, subprocess call, FFmpeg, or rendering. Empty plans never reach it (the
use-case still calls it per segment, so a plan with no segments yields an empty
manifest with no downloader calls).

### D36. `DownloadClips` composes the latest assembly-plan read; creation kept internal; download-only public API

`DownloadClips` receives only `run_id` from the API. It composes:

- `RunRepository` for the D33 guard.
- `GetLatestVideoAssemblyPlan` for the immediate upstream timeline artifact.
- `ClipDownloader` for the pure per-segment mapping policy.
- `CreateDownloadedClipSet` for guarded persistence and versioning.

Execution order is locked:

1. Require the run and check `RunStatus.SCENES_APPROVED`.
2. Read the latest video assembly plan.
3. For each segment, in plan (`order_index`) order, call
   `clip_downloader.download(run_id, segment)` and collect the result.
4. Persist through `CreateDownloadedClipSet` with `source = "downloaded"` and
   provenance metadata (`video_assembly_plan_asset_id`,
   `video_assembly_plan_version`).

This ordering produces the intended errors: a missing run raises
`RunNotFoundError`; an invalid status raises
`AssetCreationRejectedError(DOWNLOADED_CLIPS)` before the read (HTTP 409, not a
dependency 404); a missing assembly plan naturally raises
`AssetNotFoundError(VIDEO_ASSEMBLY_PLAN)` (HTTP 404).

- `CreateDownloadedClipSet` is the internal guarded persistence use-case. It
  accepts caller-supplied `DownloadedClip` entries, computes the next
  `DOWNLOADED_CLIPS` version, writes JSON through `StoragePort`, sets
  `source`/provenance metadata, and saves the asset index. It owns the canonical
  D33 status guard, defaults `source = "manual"`, and never transitions the run.
  Constructor dependencies are ports/factories only: `RunRepository`,
  `VersionedAssetRepository`, `StoragePort`, and optional `asset_id_factory`.
- Expose only:
  - `POST /runs/{run_id}/downloaded-clips/download`
  - `GET /runs/{run_id}/downloaded-clips`
  - `GET /runs/{run_id}/downloaded-clips/latest`
- Do not expose a manual `POST /runs/{run_id}/downloaded-clips` for caller-
  supplied records. Keeping creation internal avoids accepting arbitrary local
  paths or download statuses before any validation or byte semantics exist.
  Adding the manual route later is a trivial, symmetric one-route change.

### D37. Storage and path convention; no-overwrite via versioning and scoped paths

- Store each manifest as JSON bytes through `StoragePort`, indexed under
  `(run_id, AssetKind.DOWNLOADED_CLIPS)`. Use private application helpers
  `_downloaded_clips_to_bytes` / `_downloaded_clips_from_bytes`, mirroring
  `_segments_to_bytes` / `_segments_from_bytes`: a JSON list of flat objects;
  `duration_seconds` round-trips as `float`, `width`/`height`/`order_index` as
  `int`, and the remaining fields as `str`.
- Store `source` and download provenance in `VersionedAsset.metadata`. Provenance
  version values are strings because `metadata` is `Mapping[str, str]`.
- The local reference is deterministic and run-scoped:
  `local_uri = memory://downloads/{run_id}/{order_index:04d}/{provider}-{provider_clip_id}.mp4`.
  The `downloads/` prefix and the run/order/clip scoping guarantee two distinct
  clips never share a reference.
- **Avoiding overwrites (Q12).** Each `DownloadClips` call creates a new,
  immutable `DOWNLOADED_CLIPS` *version*; prior versions are never mutated -- the
  same append-only guarantee as every other asset phase. Because this foundation
  writes no media bytes, there is nothing else to overwrite. When a future phase
  materializes bytes, it must version-scope the media directory (for example,
  include the manifest version in the path) so a re-download writes a fresh
  directory rather than clobbering a prior version's files; that byte-level
  no-clobber rule is deferred with byte materialization and flagged in Open
  Questions.
- The `local_uri` is always the relative, run-scoped `memory://downloads/...`
  value above -- never an absolute OS path and never a user-supplied path. It is
  a downloader-defined placeholder: it is not produced by `LocalFilesystemStorage`
  and is not resolved by any current storage API. A future byte-materialization
  slice that turns it into real bytes will need either a new storage method/port
  for media objects or one `STOCK_CLIP` `VersionedAsset` per materialized clip;
  whichever it chooses must confine every resolved path within the injected
  storage root, as `LocalFilesystemStorage` already does for versioned assets.

## Domain Model Proposal

- Add `AssetKind.DOWNLOADED_CLIPS = "downloaded_clips"`.
- Add and export frozen `DownloadedClip` with exactly the D34 fields, next to
  `SelectedClip` and `VideoAssemblySegment` in `backend/app/domain/models.py`
  and `backend/app/domain/__init__.py`.
- Do not change `VideoAssemblySegment`, `SelectedClip`, `SceneSpec`, `RenderSpec`,
  `RunStatus`, or run transition rules.
- Do not add media bytes, absolute paths, codec/trim/filter fields, or a domain
  set wrapper.
- Add `DownloadedClipSet` only as an application read model pairing a
  `VersionedAsset` with parsed records, defined in the new
  `downloaded_clip_assets.py` and exported from
  `backend/app/application/use_cases/__init__.py`.

## Asset / Storage Decision

- Persist the downloaded-clip set as JSON bytes through the existing
  `StoragePort` (no media files). Index with `VersionedAssetRepository` under
  `(run_id, AssetKind.DOWNLOADED_CLIPS)`. Metadata includes `source`
  (`"downloaded"` for `DownloadClips`, default `"manual"` for a direct
  `CreateDownloadedClipSet` call) plus `video_assembly_plan_asset_id` and
  `video_assembly_plan_version` for generated provenance.
- A second download creates version 2 and leaves earlier manifests and their
  provenance intact.
- The only stored bytes are JSON metadata. `source_url` and `local_uri` are
  references and are never opened. Existing generic SQLite, filesystem, and
  in-memory adapters require no code or schema change beyond accepting the new
  enum value naturally. No `.gitignore` change is required:
  `data/assets/downloaded_clips/*` is already covered.

## Downloader Port Decision

- Add and export `ClipDownloader` from the ports package
  (`backend/app/ports/providers.py`, `backend/app/ports/__init__.py`).
- Add and export `StubClipDownloader` from the generation adapter package
  (`backend/app/infrastructure/generation/__init__.py`).
- Add a recording `FakeClipDownloader` in `tests/fakes/providers.py` for
  use-case and API tests. It records `(run_id, segment)` calls and returns
  configured or default `DownloadedClip` records; those tests do not depend on
  the concrete adapter.
- Wire only the port into application/API code. The concrete adapter is imported
  only by `main.py` and its own adapter/confinement tests.
- Do not place the downloader in `provider_registry.py`; direct composition-root
  wiring matches the current scene/stock/retrieval/selection/assembly pattern and
  avoids an unrelated registry refactor.

## Fake Downloader Decision

- `StubClipDownloader` implements the D35 algorithm: one `DownloadedClip` per
  `VideoAssemblySegment`, metadata copied, `order_index` preserved,
  `download_status = "available"`, `download_reason = "deterministic_placeholder"`,
  `content_type = "video/mp4"`, and a deterministic `memory://` local reference
  derived from `run_id`, `order_index`, `provider`, and `provider_clip_id`.
- It creates **no** placeholder files in this foundation (D34): it is pure,
  returns records only, and touches no network, filesystem, subprocess, or
  FFmpeg. If a later decision adopts placeholder bytes, the bytes must be tiny
  and deterministic and must be written by the use-case through a storage port --
  which today persists versioned assets only, so it will need either a new media
  storage method/port or one `STOCK_CLIP` `VersionedAsset` per file -- never by
  the domain/application layers and never to an arbitrary path.

## Use-Case Plan

Create `backend/app/application/use_cases/downloaded_clip_assets.py`, using
`video_assembly_plan_assets.py` and `selected_clip_assets.py` as the structural
template.

1. **`CreateDownloadedClipSet`**
   - `execute(run_id, downloaded_clips, source="manual", asset_metadata=None) -> VersionedAsset`.
   - Requires the run, enforces D33, computes the next `DOWNLOADED_CLIPS`
     version, merges `{"source": source}` with any provenance metadata, writes
     JSON through `StoragePort`, and saves the asset. Does not transition the run.
   - Constructor deps: `RunRepository`, `VersionedAssetRepository`,
     `StoragePort`, optional `asset_id_factory`.

2. **`DownloadClips`**
   - `execute(run_id) -> VersionedAsset`.
   - Applies the D33 guard before the read, then follows the D36 order: read the
     latest assembly plan, call the downloader once per segment in order,
     aggregate, and persist through `CreateDownloadedClipSet` with
     `source = "downloaded"` and assembly-plan provenance. Does not parse storage
     itself and does not transition the run.
   - Constructor deps: `RunRepository`, `ClipDownloader`,
     `GetLatestVideoAssemblyPlan`, `CreateDownloadedClipSet`.

3. **`ListDownloadedClipSets`**
   - `execute(run_id) -> Sequence[VersionedAsset]` via
     `asset_repository.list_for_run(run_id, AssetKind.DOWNLOADED_CLIPS)`.

4. **`GetLatestDownloadedClipSet`**
   - `execute(run_id) -> DownloadedClipSet`.
   - Reads the latest asset, raises `AssetNotFoundError(DOWNLOADED_CLIPS)` when
     absent, loads its JSON, and returns the parsed read model.

Export all four use-cases and `DownloadedClipSet` from
`backend/app/application/use_cases/__init__.py`.

## API Route Plan

Add response models and routes in the existing `backend/app/api/assets.py`
module, consistent with the existing long route names.

| Method | Path | Returns | Purpose |
| --- | --- | --- | --- |
| `POST` | `/runs/{run_id}/downloaded-clips/download` | `201 AssetResponse` | Download from the latest video assembly plan; persist a `DOWNLOADED_CLIPS` asset (next version, `source=downloaded`). Applies the D33 rule. |
| `GET` | `/runs/{run_id}/downloaded-clips` | `list[AssetResponse]` | List downloaded-clip asset versions. |
| `GET` | `/runs/{run_id}/downloaded-clips/latest` | `DownloadedClipSetResponse` | Return the latest asset and parsed downloaded clips. |

Add `DownloadedClipModel.from_domain`,
`DownloadedClipSetResponse.from_downloaded_clip_set`, and a
`get_clip_downloader(request)` resolver reading
`request.app.state.clip_downloader`. The download route has no request body in
this foundation. Existing application error handlers provide 404/409 behavior.
There is no manual-create request DTO, raw asset-byte endpoint, media endpoint,
or render endpoint.

## Composition Root Decision

- Add optional `clip_downloader: ClipDownloader | None = None` to
  `create_app(...)`, default it to `StubClipDownloader()`, and assign
  `app.state.clip_downloader`, following the existing `clip_selector` /
  `video_assembly_planner` wiring style.
- Keep all repository, storage, latest-reader, create-use-case, and download
  use-case construction explicit in the route dependency functions, following the
  current asset API pattern.
- Do not alter `provider_registry.py`, settings, environment variables, secrets,
  or lifespan behavior. The default downloader is pure and owns no resource, so
  it never affects the database/storage lifespan decision.

## Test Checklist

### Domain and Serialization

- `AssetKind.DOWNLOADED_CLIPS.value == "downloaded_clips"` and is distinct from
  `SELECTED_CLIPS`, `VIDEO_ASSEMBLY_PLAN`, `STOCK_CLIP`, and `RENDER`.
- `DownloadedClip` is frozen (assignment raises) and has exactly the D34 fields.
- JSON round-trip preserves all fields and numeric types (`duration_seconds` as
  `float`; `width`/`height`/`order_index` as `int`).
- Latest-read returns the newest parsed manifest; missing latest raises
  `AssetNotFoundError(DOWNLOADED_CLIPS)`.

### Port and Adapter

- A fake satisfies runtime `isinstance(fake, ClipDownloader)`; the port resolves
  to `backend.app.ports.providers`.
- `get_type_hints(ClipDownloader.download)` shows `run_id: str`,
  `segment: VideoAssemblySegment`, and `return: DownloadedClip`.
- `StubClipDownloader` is deterministic and repeatable: same inputs produce equal
  outputs.
- One `DownloadedClip` per segment; `order_index`, `provider`,
  `provider_clip_id`, `title`, `source_url`, dimensions, and source duration are
  copied correctly.
- `download_status == "available"`, `download_reason == "deterministic_placeholder"`,
  `content_type == "video/mp4"`.
- `local_uri` starts with `memory://downloads/`, is relative (no `..`, no
  backslash, no drive-style prefix), and is derived from `run_id`/`order_index`/
  `provider`/`provider_clip_id`.

### Use-Cases and Lifecycle

- Create stores `DOWNLOADED_CLIPS`, increments versions, and persists only JSON.
- `DownloadClips` tags `source=downloaded` and includes
  `video_assembly_plan_asset_id`/`video_assembly_plan_version`;
  `CreateDownloadedClipSet` defaults `source=manual`.
- The status guard rejects every state except `scenes_approved` with
  `AssetCreationRejectedError(kind=downloaded_clips)`, checked before the
  assembly-plan read and before downloader/persistence work (409, not 404),
  persisting nothing.
- `RunNotFoundError` when the run is missing (downloader not called).
- `DownloadClips` calls the downloader once per segment, in order, with the
  latest plan's segments, and aggregates every result.
- An empty latest plan (zero segments) yields an empty `DOWNLOADED_CLIPS`
  manifest, never calls the downloader, and leaves the run exactly
  `scenes_approved`.
- `DownloadClips` fails naturally with
  `AssetNotFoundError(VIDEO_ASSEMBLY_PLAN)` when no plan exists (seed
  `scenes_approved` but no plan), persisting nothing.
- `ListDownloadedClipSets` is version-ordered; a second download creates
  version 2; the run stays exactly `scenes_approved` after create and download.

### API

- `POST .../downloaded-clips/download` returns 201 with `kind=downloaded_clips`,
  `version=1`, `source=downloaded`, and plan provenance.
- `GET` list returns versions in order; `GET` latest returns parsed
  `downloaded_clips`.
- 404 when the run is missing; 404 when no assembly plan exists; 409 when status
  is not `scenes_approved` (before any dependency 404); versioning across two
  downloads.
- Only download/list/latest routes exist; no manual create or media route is
  registered.

### Architecture Boundaries and Fake-Only / No-Network Safety

- Domain auto-scan (`test_domain_has_no_framework_or_outer_layer_imports`)
  confirms no framework or outer-layer imports.
- Add `ClipDownloader` to `test_provider_interfaces_live_in_ports`.
- Extend the asset-use-case hint map with `CreateDownloadedClipSet`
  (run/asset/storage + `asset_id_factory`), `ListDownloadedClipSets` (asset
  repo), and `GetLatestDownloadedClipSet` (asset repo + storage); extend the
  generation-use-case hint map with `DownloadClips` (`run_repository`,
  `clip_downloader`, `get_latest_video_assembly_plan`,
  `create_downloaded_clip_set`).
- Application auto-scan (`test_application_does_not_import_infrastructure`) and
  the API route scans (`test_assets_route_imports_use_cases_not_infrastructure`,
  `test_api_routes_depend_on_use_cases_not_infrastructure`) cover the new files.
- `test_generation_adapters_import_no_api_application_or_external_modules`
  confirms `StubClipDownloader` imports no api/application/SDK/`httpx`/`requests`/
  `urllib`/`aiohttp`/`socket`/`subprocess`/`ffmpeg`/`moviepy` module.
- Add `test_stub_clip_downloader_import_confined_to_composition_root` proving
  only `main.py` imports `StubClipDownloader`.
- Assert persisted bytes decode as JSON and contain no media bytes; every
  `local_uri` is a `memory://downloads/...` reference (none absolute or
  drive-style).
- Search the implementation diff for HTTP clients, provider SDKs, API-key
  handling, FFmpeg/subprocess calls, media probing, real media writes, render
  calls, and status transitions; none should be present.

### End-to-End

Extend `tests/test_draft_planning_workflow.py` through:

```text
prompt -> script -> scene table -> stock plan -> clip candidates
       -> selected clips -> video assembly plan -> downloaded clips
```

After the assembly-plan steps, assert `POST .../downloaded-clips/download`
returns 201 (`kind=downloaded_clips`, `version=1`, `source=downloaded`, plan
provenance) and `GET .../downloaded-clips/latest` shows one record per assembly
segment, in the same `order_index` order, with copied provider metadata, every
`local_uri` starting `memory://`, `download_status == "available"`, and the run
still exactly `scenes_approved` (not `rendered`, no transition).

## Implementation Slices

Implement one slice at a time in inward-to-outward order. Run focused tests after
each slice and the full suite after the final slice.

### Slice 1: Domain -- asset kind and record

- **Files:** `backend/app/domain/models.py`, `backend/app/domain/__init__.py`,
  new `tests/test_downloaded_clip.py`.
- **Change:** Add `AssetKind.DOWNLOADED_CLIPS` and the frozen `DownloadedClip`
  dataclass/export (D32, D34).
- **Tests:** Kind value/distinction, exact fields, frozen behavior.
- **Acceptance:** Domain tests and the domain boundary scan pass; no other layer
  changes.

### Slice 2: Port -- `ClipDownloader`

- **Files:** `backend/app/ports/providers.py`, `backend/app/ports/__init__.py`,
  new `tests/test_clip_downloader_port.py`.
- **Change:** Add/export the D35 runtime-checkable protocol.
- **Tests:** Runtime conformance against a fake, module location, exact type
  hints (`run_id: str`, `segment: VideoAssemblySegment`, `return: DownloadedClip`).
- **Acceptance:** Port tests and architecture tests pass.

### Slice 3: Deterministic adapter and test fake

- **Files:** new
  `backend/app/infrastructure/generation/stub_clip_downloader.py`, generation
  package export, `tests/fakes/providers.py` + `tests/fakes/__init__.py`
  (`FakeClipDownloader`), extended `tests/test_generation_adapters.py`.
- **Change:** Implement the D35 mapping and the recording fake.
- **Tests:** One record per segment, field copies, status/reason/content-type,
  `memory://` reference, relative path, repeatability, port conformance.
- **Boundary:** No application/API/external/media imports.
- **Acceptance:** Focused adapter and generation-boundary tests pass.

### Slice 4: Application -- downloaded-clip use-cases

- **Files:** new
  `backend/app/application/use_cases/downloaded_clip_assets.py`, use-case package
  export, new `tests/test_downloaded_clip_use_cases.py`.
- **Change:** Add the read model, JSON helpers, create/download/list/latest
  use-cases, D33 guard, D36 ordering, and provenance metadata.
- **Tests:** Versioning, round-trip, source/provenance metadata, latest/list,
  errors, guard-before-read, downloader call-per-segment, no transition.
- **Boundary:** Dependencies are ports and sibling use-cases only.
- **Acceptance:** Focused use-case and application-boundary tests pass.

### Slice 5: API routes and composition wiring

- **Files:** `backend/app/api/assets.py`, `backend/app/main.py`, extended
  `tests/test_asset_api.py` (or a new `tests/test_downloaded_clip_api.py`).
- **Change:** Add DTOs, download/list/latest routes, the `get_clip_downloader`
  resolver, the `clip_downloader` `create_app` parameter, and the default
  `StubClipDownloader` wiring.
- **Tests:** 201/404/409, latest/list/versioning, route absence, injected fake.
- **Boundary:** Routes contain no downloader, lifecycle, storage, or version
  logic; the concrete adapter appears only in the composition root.
- **Acceptance:** API and route-boundary tests pass.

### Slice 6: Boundary hardening, E2E, and phase audit

- **Files:** `tests/test_architecture_boundaries.py`,
  `tests/test_draft_planning_workflow.py`; `.gitignore` only if inspection finds
  a real gap (none expected).
- **Change:** Add `ClipDownloader` to the port-location test, the three
  persistence/read use-cases to the asset-use-case hint map, `DownloadClips` to
  the generation-use-case hint map, the `StubClipDownloader` confinement test,
  and extend the full workflow.
- **Tests:** Focused architecture/E2E tests, then the full suite.
- **Acceptance:** Full suite and `git diff --check` pass; no generated media,
  secrets, database files, caches, or virtual-environment files are staged.

### Slice Order and Dependencies

```text
1 domain -> 2 port -> 3 stub adapter + fake
                   -> 4 application use-cases
                   -> 5 API + composition root
                   -> 6 boundaries + E2E + audit
```

Slices 3 and 4 can be developed independently after Slice 2 because application
tests use the recording fake. The concrete adapter must exist before Slice 5
wires the default.

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

- Real clip download, network fetch, cache, or any media bytes from the internet.
- Pexels, Pixabay, or any provider/API-key integration; HTTP clients
  (`httpx`/`requests`/`urllib`/`aiohttp`/`socket`) or any network I/O.
- Writing media files of any kind in this phase, including placeholder bytes
  (deferred; if adopted later, written tiny/deterministic by the use-case through
  a storage port, which may need a new media-object method).
- Materializing the per-file `STOCK_CLIP` media asset or registering it in the
  index.
- Media probing/inspection, content-type sniffing, codecs, frame rates, byte
  ranges, or any media analysis.
- FFmpeg, subprocess calls, transcoding, rendering, or output files.
- Voiceover/TTS, subtitles, or any audio/subtitle generation.
- AI ranking, scoring, deduplication, clip replacement, or download retry policy.
- Selected-clip / assembly-plan / downloaded-clip editing UI and a manual public
  create route.
- Scene refinement or changes to script, scene, stock planning, candidate
  retrieval, selected-clip, or video-assembly-plan behavior.
- A new run status or any run transition.
- Provider registry refactoring, a generic pipeline orchestrator, workers, or
  queues.
- Redis, Postgres, S3, cloud/SaaS features, auth, or pagination.
- Database schema changes or a generic JSON schema/version registry.
- Byte-level no-clobber rules and absolute-path resolution (deferred with byte
  materialization).

## Open Questions

- **Placeholder bytes.** This foundation is metadata-only (D34). A later phase
  may decide file existence is required for render tests and write tiny
  deterministic placeholder bytes. The current `StoragePort` saves and loads
  versioned assets only, so that phase will need either a new storage method/port
  for media objects or one `STOCK_CLIP` `VersionedAsset` per file, then point each
  `local_uri` at the materialized object. The contract (stable run-scoped,
  order-indexed local references) is designed so that change is additive.
- **Single local reference.** The model carries one `local_uri` only. A second
  storage-root-relative path would today be a constant-prefix transform of it
  with no consumer, so it is omitted (YAGNI). A future byte-materialization/
  render phase may add a second locator if the real resolution model needs one.
- **Downloader call shape.** `download(run_id, segment)` passes `run_id` so the
  downloader owns the local destination. If a richer download request (timeouts,
  preferred format, retry budget) appears, it may move into a small request value
  object; no use-case/route change is needed to do so.
- **Default adapter name.** `StubClipDownloader` (chosen, parallel to
  `StubClipRetrievalProvider` as a stand-in for an absent external integration)
  vs a behavior name like `DeterministicClipDownloader` (parallel to
  `DeterministicClipSelector`). The confinement test name follows whichever is
  chosen; no downstream impact.
- **Byte-level no-clobber.** When real/placeholder bytes are written, the media
  directory must be version-scoped so re-downloads do not overwrite a prior
  manifest version's files. Deferred until byte materialization exists.
