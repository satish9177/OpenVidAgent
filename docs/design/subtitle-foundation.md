# Subtitle Foundation

Design document for the next phase. This records the intended design and slice
plan before any code is written. No backend, test, or product implementation is
part of this document. The approved direction continues the asset-only tail of
the pipeline: assembly planning turned selections plus scenes into a
`VideoAssemblyPlan`, clip download turned the plan's segments into a durable
`DownloadedClipSet` of local clip references, and voiceover turned the plan's
per-segment narration into a durable `Voiceover` -- a set of `VoiceoverSegment`
records carrying narration text, language/voice/provider settings, a deterministic
audio reference, and an estimated duration. Those steps build the visual and
audio sides of a voiceover B-roll video. This phase builds the *caption* side: it
turns the latest voiceover's per-segment narration and timing into a durable,
versioned *subtitle* artifact -- a set of `SubtitleSegment` records, each carrying
the caption text, language, and a computed timeline window -- produced through a
subtitle composer port. It introduces the subtitle-plan abstraction only. It does
not write any real `.srt` or `.vtt` file, write placeholder subtitle bytes, call
any external provider, invoke FFmpeg, or render or burn captions.

## Goal

Given the latest voiceover for a run, produce a durable, versioned set of
*subtitle segments*: one `SubtitleSegment` per `VoiceoverSegment`, copying the
segment's caption text and language and adding a computed timeline window
(`start_seconds`, `end_seconds`, `duration_seconds`), a structural format marker,
and a generation status. The artifact answers, for each timeline position: what
caption text would appear on screen, in which language, and during which time
window -- all as metadata.

This foundation is deliberately narrower than a real subtitle pipeline. It makes
the "what caption shows when, and in what language" decision inspectable and
repeatable *without* writing caption files, serializing to SRT/VTT, aligning text
to audio, calling any speech-to-text or forced-alignment provider, styling cues,
burning captions into video, or transitioning the run lifecycle. For this
foundation the composer is a deterministic stub that copies the voiceover's
narration text and derives timing arithmetically from the voiceover's per-segment
durations; no real subtitle file and no real alignment exist.

## Target Workflow

The existing asset-only tail is extended by one step. The run reaches
`scenes_approved` exactly as today and remains there while stock planning, clip
retrieval, clip selection, assembly planning, clip download, voiceover, and now
subtitles create independently versioned JSON assets.

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
-> generate subtitles                # NEW: reads the latest voiceover,
                                     # calls the SubtitleComposer per segment,
                                     # persists a SUBTITLE_MANIFEST asset,
                                     # run stays scenes_approved (asset-only)
```

The target product workflow becomes:

```text
prompt -> script draft -> scene table -> stock plan -> clip candidates
       -> selected clips -> video assembly plan -> downloaded clips
       -> voiceover -> subtitles
```

Unlike voiceover and downloaded clips -- which are *siblings* both derived from
the video assembly plan -- subtitles read from the **voiceover**, not the
assembly plan, and so are *downstream* of it (see D45). Captions transcribe the
spoken narration, and the voiceover is the artifact that already settled which
narration is spoken, in which language, and for how long. Reading the voiceover
gives subtitles the exact text, language, and per-segment duration they need, in
timeline order, from a single upstream read.

## Architecture Rule

Dependencies point inward:

`API/UI -> application use-cases -> domain models/services -> ports/interfaces -> infrastructure adapters`

- The domain remains framework-free and serialization-free.
- Application use-cases orchestrate repositories, storage, latest-asset readers,
  and the composer port. They do not import infrastructure, open sockets, call a
  subtitle/alignment SDK, or touch the filesystem directly.
- `SubtitleComposer` is a port expressed only in domain types (plus the
  `start_seconds` timeline offset float).
- `StubSubtitleComposer` is a pure infrastructure adapter with no network,
  filesystem, subprocess, FFmpeg, alignment SDK, API, or application dependency.
- API routes call application use-cases only. Lifecycle and versioning rules do
  not move into route functions.
- Concrete composer wiring remains explicit in `backend/app/main.py`.

This phase is subtitle-file-adjacent, which makes the boundary rule especially
important. Like clip download (media files) and voiceover (audio files), its
*eventual* real implementation will write non-JSON bytes (`.srt` / `.vtt` files)
through a real provider/formatter. The domain and application layers must never
perform that work. Any byte materialization (placeholder or real) and any
alignment call belong behind a port/adapter -- the new `SubtitleComposer` plus the
existing `StoragePort` / `LocalFilesystemStorage` and the reserved
`SubtitleBuilder` -- orchestrated by a use-case through ports. This foundation
keeps that risk at zero by writing only JSON manifest bytes, fabricating no file
reference at all, and never calling any provider (see Asset / Storage Decision,
D44, and D46).

## Existing Foundation

This design is based on the current implementation, confirmed by reading the
source, not only the earlier design notes:

- `VersionedAsset` stores `asset_id`, `kind`, `version`, `uri`, and string
  metadata (`metadata` is `Mapping[str, str]`). The generic repository and
  storage ports already support new asset kinds without a database schema change.
- `AssetKind` currently includes `SCRIPT`, `SCENE_TABLE`, `STOCK_PLAN`,
  `CLIP_CANDIDATES`, `SELECTED_CLIPS`, `VIDEO_ASSEMBLY_PLAN`, `DOWNLOADED_CLIPS`,
  `STOCK_CLIP`, `VOICEOVER`, `VOICE`, `SUBTITLE`, and `RENDER`. Crucially,
  `SUBTITLE = "subtitle"` **already exists** and is still unused in any use-case:
  `RenderSpec.subtitles` is typed `VersionedAsset | None`, the reserved
  `SubtitleBuilder.build(script, voice) -> VersionedAsset` is shaped to return a
  subtitle asset, and the test `FakeSubtitleBuilder` returns a `SUBTITLE` asset
  with a `memory://subtitles/subtitle-1.srt` uri. Across the codebase, `SUBTITLE`
  is reserved for the future *caption-file-bytes* asset that a renderer consumes
  -- the `.srt` / `.vtt` output of real subtitle building -- exactly as `VOICE` is
  reserved for future synthesized-audio bytes and `STOCK_CLIP` for future per-file
  media bytes. This phase does not touch `SUBTITLE` or `SubtitleBuilder` (see D44).
- `VoiceoverSegment` is a frozen domain dataclass whose fields are `scene_id`,
  `order_index`, `narration_text`, `language`, `voice_id`, `provider`,
  `audio_uri`, `content_type`, `duration_seconds`, `status`, and
  `generation_reason`. Its `narration_text`, `language`, `order_index`, and
  `duration_seconds` are exactly the per-item inputs this phase reads; its audio
  fields (`voice_id`, `provider`, `audio_uri`, `content_type`) are deliberately
  not read, as they are narration-delivery concerns, not caption concerns.
- `GetLatestVoiceover` returns the latest parsed `Voiceover(asset, segments)` and
  raises `AssetNotFoundError(run_id, VOICEOVER)` when missing. This is the read
  path and the natural dependency guard this phase reuses. The voiceover manifest
  stores `language` in `VersionedAsset.metadata`, so the run-level caption
  language is available even for an empty (zero-segment) voiceover.
- The voiceover use-cases (`CreateVoiceover`, `GenerateVoiceover`,
  `ListVoiceovers`, `GetLatestVoiceover`) plus the `_voiceover_segments_to_bytes`
  / `_voiceover_segments_from_bytes` helpers in `voiceover_assets.py`, and the
  `StubVoiceoverGenerator` adapter, are the exact structural template for this
  phase. The guard `_VOICEOVER_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})`
  and the guard-before-read ordering in `GenerateVoiceover` are copied directly.
- `Run` carries `language: str = "en"`, which `GenerateVoiceover` already threads
  into every `VoiceoverSegment.language`. Subtitles inherit that language from the
  voiceover segments with no new request field and no re-read of `run.language`
  (see D46 / D49).
- `RunStatus` is `created -> script_ready -> script_approved -> scenes_ready ->
  scenes_approved -> rendered` (plus `failed`). `scenes_approved` only transitions
  to `rendered`/`failed`; there is no planning/retrieval/selection/assembly/
  download/voiceover/subtitle status, and this phase adds none.
- `backend/app/ports/providers.py` holds runtime-checkable provider protocols
  using domain types (`ClipRetrievalProvider`, `ClipSelector`,
  `VideoAssemblyPlanner`, `ClipDownloader`, `VoiceoverGenerator`, and the reserved
  `TTSProvider`, `SubtitleBuilder`, `Renderer`).
  `backend/app/infrastructure/generation` holds pure deterministic defaults
  (`StubClipRetrievalProvider`, `DeterministicClipSelector`,
  `DeterministicVideoAssemblyPlanner`, `StubClipDownloader`,
  `StubVoiceoverGenerator`, ...), and `backend/app/main.py` wires those defaults
  through `app.state`.
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
  `data/assets/subtitle_manifest/*` is already covered. It also already ignores
  `data/subtitles/*`, reserved for the future real caption-file bytes (`.srt` /
  `.vtt`) a later `SubtitleBuilder` phase will write into the `SUBTITLE` asset.
- Architecture boundary tests scan domain, application, API, ports, and the
  generation package for forbidden imports, confine each concrete default
  (including `StubVoiceoverGenerator`) to `main.py`, and already list
  `VoiceoverGenerator` in `test_provider_interfaces_live_in_ports`. New files in
  those layers inherit forbidden-import coverage automatically; this phase adds a
  parallel confinement test for its new default.

## Problem Being Solved

The pipeline now reaches a durable voiceover manifest: the system knows, per
timeline segment, what narration would be spoken, in which language, for roughly
how long, and where its audio file would live. But OpenVidAgent V1 is a
*voiceover B-roll with subtitles* product, and the system still has no notion of a
subtitle or caption at all. The narration text exists -- authored per scene,
copied through the assembly plan, and copied again into each
`VoiceoverSegment.narration_text` -- but there is no subtitle plan, no subtitle
asset, no timeline window saying when each caption appears or disappears, and no
caption artifact a future renderer could lay over the B-roll. A future renderer
cannot show captions: it has narration strings on voiceover segments and a single
per-segment `duration_seconds`, but nothing that says "this is the on-screen
caption, shown from t0 to t1."

This phase introduces the narrow foundation for that caption layer: a domain model
and asset that represent, per timeline segment, a subtitle with its caption text,
language, computed timeline window, and a generation status, produced through a
replaceable composer port. It deliberately stops short of writing or formatting
any caption file so the abstraction, persistence, timing model, and API shape can
be locked in and tested before any SRT/VTT serializer, alignment provider, cue
styling, or FFmpeg/burn-in concern is introduced. Because the model carries
`language` -- resolved from the voiceover, which already carries `run.language` --
the manifest shape already supports Telugu/Hindi and other Indian languages
without a reshape when real subtitle files arrive.

## Answers to Design Questions

| # | Question | Decision |
| --- | --- | --- |
| 1 | Read latest voiceover, latest video assembly plan, or latest scene table? | The latest **voiceover** (D45). It already carries ordered narration text, the spoken `language`, per-segment `duration_seconds`, `order_index`, and `scene_id` -- exactly the caption text, language, and timing inputs. The assembly plan lacks language and an estimated narration duration; the scene table lacks timeline order and per-position duration. |
| 2 | One asset for the whole run, or one per scene? | One **set** asset for the whole run (`SUBTITLE_MANIFEST`) containing many `SubtitleSegment` records (D46), mirroring `VOICEOVER`, `DOWNLOADED_CLIPS`, and `VIDEO_ASSEMBLY_PLAN`. |
| 3 | Domain model name? | `SubtitleSegment` (D46), a frozen metadata-only domain dataclass. The application read model is `Subtitles` (D46). |
| 4 | New asset kind? | Yes: `AssetKind.SUBTITLE_MANIFEST = "subtitle_manifest"` (D44). |
| 5 | Reuse `AssetKind.SUBTITLE`, or keep it reserved? | Keep `SUBTITLE` **reserved** for future caption-file bytes (D44). `SUBTITLE_MANIFEST` is the JSON subtitle-plan manifest; `SUBTITLE` stays the future per-file `.srt` / `.vtt` asset consumed by `RenderSpec.subtitles` and produced by `SubtitleBuilder`. This mirrors `VOICEOVER` vs `VOICE` and `DOWNLOADED_CLIPS` vs `STOCK_CLIP`. The explicit `_MANIFEST` suffix prevents `SUBTITLE` / `SUBTITLE_MANIFEST` confusion. |
| 6 | Real `.srt` / `.vtt` files or metadata only? | **Metadata only** (D46). No caption files, no placeholder subtitle bytes; the only bytes written are the JSON manifest. |
| 7 | Subtitle builder port? | Yes, a **new** metadata-only `SubtitleComposer` port (D47), distinct from the reserved `SubtitleBuilder`. |
| 8 | Reuse the reserved `SubtitleBuilder`, or define a new metadata-only port? | Define a **new** `SubtitleComposer` (D47). `SubtitleBuilder.build(script, voice) -> VersionedAsset` is reserved to return caption-file bytes from the full script and the voice audio; reusing it would force this metadata-only phase to produce a `VersionedAsset` it has no bytes for, or to redefine its contract -- both premature. |
| 9 | Deterministic fake behavior? | Map each `VoiceoverSegment` to one `SubtitleSegment`: copy `scene_id`/`order_index`, set `text = voiceover_segment.narration_text`, `language` = the supplied `language` argument (the use-case-resolved manifest language), `duration_seconds = voiceover_segment.duration_seconds`, `start_seconds` = the supplied cumulative offset, `end_seconds = start + duration`, `format = "manifest"`, `status = "available"`, `generation_reason = "deterministic_placeholder"` (D47). |
| 10 | `memory://subtitles/...` references only, or no file reference at all? | **No file reference at all** (D46). The model has no `subtitle_uri`; the structured text+timing records *are* the caption content. A per-segment `memory://subtitles/...` reference would mismodel a whole-run `.srt` / `.vtt` file and collide with the namespace the reserved `SubtitleBuilder` already uses. |
| 11 | What metadata to copy for durability? | From each voiceover segment: `scene_id`, `order_index`, `narration_text` (as `text`), and `duration_seconds`. `language` is the manifest language the use-case resolves once and passes in (D47/D48/D49), not a per-segment copy. `start_seconds`/`end_seconds` are derived from the cumulative durations (D46/D47). Copy-not-reference, per D22/D28. Audio fields (`voice_id`, `provider`, `audio_uri`, `content_type`) are intentionally **not** copied -- they are delivery concerns, not caption concerns. |
| 12 | Use voiceover segment `duration_seconds` for timing? | Yes (D47). `duration_seconds` is copied per segment; `start_seconds`/`end_seconds` are accumulated from it (first segment at `0.0`, each `end = start + duration`, next `start = previous end`). |
| 13 | Language fields for Telugu/Hindi/Indian-language captions now? | Yes (D46/D49). `language` is the manifest language the use-case resolves from the voiceover (asset metadata -> first segment language -> `"en"`) and passes into every `compose(...)`; in the normal path this equals `voiceover_segment.language`, which already carries `run.language` (`"en"`, `"te"`, `"hi"`, `"ta"`, ...). No new request field; no provider call. |
| 14 | Use-cases? | `CreateSubtitles`, `GenerateSubtitles`, `ListSubtitles`, `GetLatestSubtitles` (D48). |
| 15 | API routes? | `POST .../subtitles/generate`, `GET .../subtitles`, `GET .../subtitles/latest` (D48). No manual create route. |
| 16 | Run status gate? | `RunStatus.SCENES_APPROVED`, checked before the voiceover read (D45). |
| 17 | Transition the run status? | No. Asset-only; no new `RunStatus`; no transition (D45). |
| 18 | Tests for boundaries / fake-only / no-file behavior? | See Test Checklist. Reuse the auto-scanning suite; add port-location, port-hint, use-case-hint, confinement, deterministic-compose, cumulative-timing, round-trip, guard-ordering, no-`subtitle_uri`/no-caption-bytes, and no-alignment-SDK assertions. |
| 19 | Explicitly deferred? | See Explicit Non-Goals / Deferred Work. No real/placeholder `.srt`/`.vtt`, no `SubtitleBuilder`/`SUBTITLE` materialization, no alignment/STT provider, no cue styling, no FFmpeg/burn-in, no run transition, no UI, no upstream changes. |

## Design Decisions

These decisions continue the project decision log: D1-D7 cover script/scene
planning, D8-D13 stock planning, D14-D19 clip retrieval, D20-D25 selected clip
selection, D26-D31 video assembly planning, D32-D37 clip download, and D38-D43
voiceover. This phase adds D44-D49. It is, in structure, the caption analog of the
voiceover phase: where voiceover produced `VOICEOVER` from the assembly plan via
`VoiceoverGenerator`, subtitles produce `SUBTITLE_MANIFEST` from the voiceover via
`SubtitleComposer`.

### D44. Add `AssetKind.SUBTITLE_MANIFEST`; keep `SUBTITLE` and `SubtitleBuilder` reserved for future caption-file bytes

- Add `SUBTITLE_MANIFEST = "subtitle_manifest"` to `AssetKind`.
- It represents the set of subtitle-plan records derived from a voiceover: one
  `SubtitleSegment` per voiceover segment, each with caption text, language, a
  computed timeline window, and a generation status, persisted as one versioned
  JSON asset. It is distinct from `VOICEOVER` (narration plan), `DOWNLOADED_CLIPS`
  (visual local references), `SUBTITLE` (future caption-file bytes), and `RENDER`
  (future rendered output).
- Do **not** reuse `AssetKind.SUBTITLE`, and do **not** reuse the `SubtitleBuilder`
  port. Throughout the codebase `SUBTITLE` is the future *caption-file-bytes*
  asset: it is the type of `RenderSpec.subtitles` (what a renderer overlays or
  burns), it is what the reserved `SubtitleBuilder.build(script, voice) ->
  VersionedAsset` is shaped to return, and it is what the test
  `FakeSubtitleBuilder` already emits (a `SUBTITLE` asset with a `.srt` uri). The
  subtitle *plan* manifest is a different artifact -- many metadata records, no
  caption file -- exactly as `VOICEOVER` (the JSON narration plan) is distinct from
  `VOICE` (the future synthesized-audio bytes). Keeping the subtitle plan
  (`SUBTITLE_MANIFEST`) and the eventual caption file (`SUBTITLE`) as distinct
  kinds lets the plan and the file store evolve and re-run independently without
  colliding versions, and lets a future real-subtitle slice reuse `SubtitleBuilder`
  -> `SUBTITLE` cleanly under the plan this phase locks in. The `_MANIFEST` suffix
  is chosen specifically so `SUBTITLE` (file bytes) and `SUBTITLE_MANIFEST`
  (metadata) can never be visually confused in code, storage paths, or tests.
- Persist only JSON metadata through the existing `StoragePort`, indexed through
  `VersionedAssetRepository`. No SQLite migration, storage adapter change,
  `.gitignore` change, or JSON schema registry is added: persistence is
  kind-agnostic, and manifest bytes land under `data/assets/subtitle_manifest/...`,
  already covered by the `data/assets/*` ignore. The future caption files are
  already covered by the existing `data/subtitles/*` ignore.

### D45. Read the latest voiceover; asset-only; gated at `scenes_approved`; never transitions the run

- Read from `GetLatestVoiceover`, **not** `GetLatestVideoAssemblyPlan`,
  `GetLatestDownloadedClipSet`, or any scene-table read. The voiceover is the
  authoritative source for subtitles because it carries, per timeline segment, the
  `narration_text` (the exact words that will be spoken, and therefore captioned),
  the `language` (which the caption must match), the `order_index` (the position
  the caption occupies), and the `duration_seconds` (the time the narration -- and
  thus the caption -- occupies). The video assembly plan is a weaker source: it has
  no spoken language and only a *target* slot duration, not the narration's
  estimated speaking duration that the voiceover settled. The scene table is the
  weakest: it lacks timeline order and a per-position index, and a scene may map to
  multiple segments. Reading the voiceover means the subtitle manifest preserves
  timeline order and language for free and needs only one upstream read.
- This makes subtitles **downstream** of voiceover, not a sibling. Voiceover and
  downloaded clips are siblings of the assembly plan; subtitles depend on the
  voiceover's text, language, and timing, so they read it directly.
- Define `_SUBTITLE_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})` in the new
  application module. Both `GenerateSubtitles` and the internal `CreateSubtitles`
  enforce this status. The generation use-case checks it first so an invalid run
  returns `AssetCreationRejectedError` (HTTP 409) before the voiceover read can
  produce a 404.
- Re-generating while `scenes_approved` creates the next `SUBTITLE_MANIFEST`
  version and leaves the run unchanged. Add no status between `scenes_approved` and
  `rendered`, and call no run transition method. A future renderer remains
  responsible for the eventual `rendered` transition.
- If no voiceover exists, `GetLatestVoiceover` naturally raises
  `AssetNotFoundError(run_id, VOICEOVER)` (mapped to HTTP 404). No special-casing
  is added.

### D46. Add `SubtitleSegment`; use an application `Subtitles` read model; structured records with no file reference

Add a frozen domain dataclass:

```python
@dataclass(frozen=True)
class SubtitleSegment:
    scene_id: str            # links the record back to its scene
    order_index: int         # copied from the voiceover segment; preserves order
    text: str                # the caption text (copied narration)
    language: str            # e.g. "en", "te", "hi"; resolved manifest language
    start_seconds: float     # cumulative timeline start (see D47)
    end_seconds: float       # start + duration_seconds
    duration_seconds: float  # copied from the voiceover segment
    format: str              # structural marker, e.g. "manifest"
    status: str              # e.g. "available"
    generation_reason: str   # why/how, e.g. "deterministic_placeholder"
```

Field semantics:

- `scene_id`, `order_index`, and `duration_seconds` are copied from the matching
  `VoiceoverSegment`; `text` is copied from `voiceover_segment.narration_text`.
  Copying keeps each manifest version durable even when the voiceover is regenerated
  later, matching the copy-not-reference rule of D22/D28. Audio fields (`voice_id`,
  `provider`, `audio_uri`, `content_type`) are deliberately **not** copied: they
  describe how the narration is delivered as sound, not what the caption says.
- `language` is the resolved subtitle manifest language that the use-case passes
  into `compose(...)` (see D47/D48/D49): a single value resolved once via
  `voiceover.asset.metadata.get("language", voiceover.segments[0].language if voiceover.segments else "en")`.
  It usually equals the source `VoiceoverSegment.language` -- in the normal
  `GenerateVoiceover` path every segment already carries `run.language` -- but the
  use-case fallback policy is authoritative, so the field is uniform across the
  manifest even when an upstream voiceover asset omits a `language` key or its
  segments disagree. It is a free-form string so any language -- including Telugu
  (`"te"`), Hindi (`"hi"`), Tamil (`"ta"`) -- is representable today without a real
  provider.
- `start_seconds` and `end_seconds` are the caption's on-screen window, derived by
  the use-case accumulating per-segment durations (D47); `duration_seconds` is the
  copied per-segment duration and always equals `end_seconds - start_seconds`.
  These are plain seconds-as-float; SRT/VTT timestamp formatting
  (`HH:MM:SS,mmm`) is a serializer concern deferred to the caption-file phase.
- `format` is a deterministic constant in the stub (`"manifest"`); it records that
  this record is the structured subtitle representation, not a serialized cue.
  **`"manifest"` is a placeholder / category marker for this metadata-only
  foundation, not a real subtitle file format** -- do not read it as a file type. A
  future subtitle-file materialization phase may set real file formats such as
  `"srt"` or `"vtt"`; the field exists so that change needs no schema change.
- `status` and `generation_reason` make the record explicit about whether the
  caption is considered present and why. The stub always emits `"available"` /
  `"deterministic_placeholder"`; the fields exist so a future real composer can
  record `"failed"`, `"skipped"`, etc. without a schema change.

**No `subtitle_uri` / file reference (Q10).** Unlike voiceover and downloaded
clips, the subtitle model carries **no** local reference. The justification is a
genuine asymmetry, not an omission:

1. Audio and media bytes are genuinely separate, non-representable artifacts, so
   `audio_uri` / `local_uri` were forward pointers to where those bytes would
   live. A subtitle's text plus timing window *is* the caption content -- the
   structured records already are the subtitle. A future `.srt` / `.vtt` is merely
   a serialization of the same data, not a separate artifact the manifest must
   point at.
2. A real caption file is a single whole-run document with sequential cue indices,
   produced by `SubtitleBuilder` -> the `SUBTITLE` asset. A per-segment
   `subtitle_uri` (for example `memory://subtitles/{run_id}/{order}/{scene}.json`)
   would invent a per-segment-file shape that does not match how `.srt` / `.vtt`
   actually work, and would create a reference with no consumer (YAGNI).
3. The `memory://subtitles/...` namespace is already claimed by the reserved
   caption-file path: the existing `FakeSubtitleBuilder` emits
   `memory://subtitles/subtitle-1.srt`. Adding a per-segment `memory://subtitles/`
   reference now would overload that namespace and conflate the metadata manifest
   with the future caption file.

Because there is no per-segment file reference, this adapter needs **no**
path-safety / safe-segment helper at all -- a simplification over the voiceover and
download stubs, which each reimplemented `_safe_component` to validate dynamic URI
components. The `scene_id` and whole-run `SUBTITLE` asset are the hooks a future
caption-file phase uses to materialize a real document.

Add `Subtitles` in the application layer as:

```python
class Subtitles(NamedTuple):
    asset: VersionedAsset
    segments: tuple[SubtitleSegment, ...]
```

Do not add a domain-level set wrapper -- symmetry with the voiceover, selected-clip,
assembly-plan, and downloaded-clip slices plus YAGNI; the application read model
already pairs the `VersionedAsset` with parsed records. (`Subtitles` mirrors the
`Voiceover` read-model name; the alternative `SubtitleSet` is noted in Open
Questions.)

**One `SubtitleSegment` per `VoiceoverSegment`.** This foundation keys the subtitle
plan one-to-one with the voiceover, preserving `order_index` and inheriting whatever
granularity the voiceover already chose. Under the current one-voiceover-segment-
per-assembly-segment flow this is one caption per timeline segment, so V1 output is
unaffected. Any future re-grouping (for example splitting long narration into
multiple shorter cues for readability, or merging by scene) is deferred and noted as
an Open Question; the `scene_id` field is the hook that lets it happen without
reshaping the manifest.

**Metadata-only, no caption files.** This foundation writes no `.srt` / `.vtt` and
no placeholder subtitle bytes: the only bytes persisted are the JSON manifest. The
composer stub is pure and the use-case writes exactly one asset (the manifest)
through `StoragePort`. This keeps the phase symmetric with voiceover and download;
keeps the new generation adapter pure (so the existing generation-boundary tests
pass unchanged); and -- critically -- keeps the first caption-shaped phase from
introducing any non-JSON filesystem write or any provider call, so the "no
filesystem/provider work in domain/application" rule is satisfied by construction.

### D47. `SubtitleComposer` is a per-segment port distinct from `SubtitleBuilder`; the stub maps each segment purely; the use-case owns cumulative timing

Define a runtime-checkable port in `backend/app/ports/providers.py`, separate from
the reserved `SubtitleBuilder`:

```python
@runtime_checkable
class SubtitleComposer(Protocol):
    def compose(
        self,
        voiceover_segment: VoiceoverSegment,
        start_seconds: float,
        language: str,
    ) -> SubtitleSegment:
        """Create one metadata-only timed subtitle segment."""
        ...
```

- **Per-segment, with a supplied timeline offset.** A subtitle's window depends on
  all prior segments' durations, which is a cross-segment concern. Rather than
  hand the whole list to the port (the rejected alternative in Open Questions), the
  port stays per-segment -- mirroring `VoiceoverGenerator.generate(...)` and
  `ClipDownloader.download(...)` -- and the use-case threads a running
  `start_seconds` cursor in. The composer then sets
  `end_seconds = start_seconds + voiceover_segment.duration_seconds` and returns a
  complete record. The cumulative fold (a trivial accumulation of per-segment
  durations) is exactly the orchestration role the use-case already owns for
  retrieval/selection/download/voiceover. `start_seconds` is a plain float, the
  same shape as the `run_id` / `language` identifier strings the other ports
  already accept, not a layer violation.
- **A resolved `language` parameter, but no `run_id`.** Unlike the downloader and
  voiceover generator, the composer builds no run-scoped file reference (D46 removes
  `subtitle_uri`), so it needs no `run_id`. It does take an explicit `language: str`.
  `GenerateSubtitles` resolves a single manifest language once with the defensive
  fallback
  `voiceover.asset.metadata.get("language", voiceover.segments[0].language if voiceover.segments else "en")`
  and threads that one resolved value into every `compose(...)` call; the composer
  uses the passed `language` directly when constructing `SubtitleSegment.language`.
  Keeping language *resolution* in the use-case (where the voiceover read and its
  metadata already live) and language *use* in the composer keeps the composer pure
  and keeps the whole manifest on one authoritative language. In the normal
  `GenerateVoiceover` path this resolved value equals the voiceover/run language that
  every `VoiceoverSegment.language` already carries, so a per-segment copy and this
  passed value coincide. For a manually/internally created voiceover (whose asset
  metadata may omit `language`, or whose segments could disagree) the use-case
  fallback is authoritative and yields deterministic manifest-level language
  behavior. Omitting `run_id` is a deliberate divergence justified by D46; a future
  caption-file port (`SubtitleBuilder`) is where run scoping returns.
- **Distinct from `SubtitleBuilder`.** `SubtitleBuilder.build(script, voice) ->
  VersionedAsset` returns a caption-file-bytes asset built from the full script and
  the voice audio, and stays reserved/unused. `SubtitleComposer` owns the *plan*
  policy (which caption text, which language, which timeline window);
  `SubtitleBuilder` will own the *file build* (script + voice -> real `SUBTITLE`
  `.srt`/`.vtt` bytes) in a later phase. The two compose cleanly: a future
  caption-file flow can serialize this manifest's segments, or align them to the
  `VOICE` audio, and emit one `SUBTITLE` asset.
- The port imports only `VoiceoverSegment` and `SubtitleSegment` from the domain.
  It has no repository, storage, FastAPI, alignment/STT SDK, HTTP, filesystem,
  subprocess, or FFmpeg type in its contract.

Add `StubSubtitleComposer` under `backend/app/infrastructure/generation`, named for
symmetry with `StubVoiceoverGenerator` / `StubClipDownloader` (it stands in for an
absent real subtitle integration). Its algorithm for each segment:

1. Copy `scene_id` and `order_index` from the voiceover segment, set
   `text = voiceover_segment.narration_text`, and set `language` from the supplied
   `language` argument (the manifest language the use-case resolved).
2. Set `duration_seconds = voiceover_segment.duration_seconds`.
3. Set `start_seconds = start_seconds` (the supplied cumulative offset) and
   `end_seconds = start_seconds + voiceover_segment.duration_seconds`.
4. Set `format = "manifest"`, `status = "available"`,
   `generation_reason = "deterministic_placeholder"`.

The use-case supplies the cumulative offset by folding over the voiceover segments
in `order_index` order. For a `GenerateVoiceover`-produced voiceover the stored
`voiceover.segments` order *already is* `order_index` order (the voiceover writes
segments in video-assembly-plan order). To stay robust for a manually/internally
created voiceover whose segments could be stored out of order, the use-case sorts
defensively by `order_index` before the fold rather than relying on stored order:

```text
cursor = 0.0
for voiceover_segment in sorted(voiceover.segments, key=lambda s: s.order_index):
    subtitle = subtitle_composer.compose(voiceover_segment, cursor, language)
    cursor += voiceover_segment.duration_seconds
    collect(subtitle)
```

So the first caption starts at `0.0`, each caption ends at `start + duration`, and
the next caption starts at the previous caption's end -- a gapless, contiguous,
deterministic timeline driven entirely by the voiceover's per-segment durations,
in ascending `order_index`. The implementation advances the cursor with
`start_seconds += voiceover_segment.duration_seconds`; because the stub sets
`end_seconds = start_seconds + voiceover_segment.duration_seconds`, this is
equivalent to advancing with `subtitle.end_seconds` for the stub. The defensive sort
is cheap and guarantees the timeline is never mis-ordered by an upstream voiceover
that stored segments out of order.

The adapter is pure and repeatable: same inputs (the same segment and the same
`start_seconds`) produce equal outputs. It performs no randomness, ranking,
scoring, network request, alignment, file access, subprocess call, or
serialization. Empty voiceovers never reach it (the use-case calls it per segment,
so a voiceover with no segments yields an empty manifest with no composer calls and
leaves the cursor at `0.0`).

### D48. `GenerateSubtitles` composes the latest voiceover read; creation kept internal; generate-only public API

`GenerateSubtitles` receives only `run_id` from the API. It composes:

- `RunRepository` for the D45 guard.
- `GetLatestVoiceover` for the immediate upstream narration/timing artifact.
- `SubtitleComposer` for the pure per-segment mapping policy.
- `CreateSubtitles` for guarded persistence and versioning.

Execution order is locked:

1. Require the run and check `RunStatus.SCENES_APPROVED`.
2. Read the latest voiceover.
3. Fold over its segments sorted ascending by `order_index` (a defensive sort, so
   an out-of-order upstream voiceover cannot mis-time captions), threading the
   cumulative `start_seconds` cursor, calling
   `subtitle_composer.compose(segment, cursor)` and collecting each result.
4. Persist through `CreateSubtitles` with `source = "generated"` and provenance
   metadata (`voiceover_asset_id`, `voiceover_version`, and a resolved `language`).
   The manifest `language` must not assume `metadata["language"]` exists, because
   only the `GenerateVoiceover` path stamps it -- an internally/manually created
   voiceover may carry only `metadata["source"]`. Resolve it defensively:

   ```python
   language = voiceover.asset.metadata.get(
       "language",
       voiceover.segments[0].language if voiceover.segments else "en",
   )
   ```

   so the manifest records the voiceover's language when present, otherwise the
   first segment's language, otherwise `"en"` (the zero-segment case).

This ordering produces the intended errors: a missing run raises
`RunNotFoundError`; an invalid status raises
`AssetCreationRejectedError(SUBTITLE_MANIFEST)` before the read (HTTP 409, not a
dependency 404); a missing voiceover naturally raises
`AssetNotFoundError(VOICEOVER)` (HTTP 404).

- `CreateSubtitles` is the internal guarded persistence use-case. It accepts
  caller-supplied `SubtitleSegment` entries, computes the next `SUBTITLE_MANIFEST`
  version, writes JSON through `StoragePort`, sets `source`/provenance metadata, and
  saves the asset index. It owns the canonical D45 status guard, defaults
  `source = "manual"`, and never transitions the run. Constructor dependencies are
  ports/factories only: `RunRepository`, `VersionedAssetRepository`, `StoragePort`,
  and optional `asset_id_factory`.
- Expose only:
  - `POST /runs/{run_id}/subtitles/generate`
  - `GET /runs/{run_id}/subtitles`
  - `GET /runs/{run_id}/subtitles/latest`
- Do not expose a manual `POST /runs/{run_id}/subtitles` for caller-supplied
  records. Keeping creation internal avoids accepting arbitrary caption text, timing
  windows, or generation statuses before any validation or serialization semantics
  exist. Adding the manual route later is a trivial, symmetric one-route change.

`GenerateSubtitles` does not read the assembly plan or the scene table: the caption
text, language, and timing it needs are already on each `VoiceoverSegment`. Its four
constructor dependencies mirror `GenerateVoiceover` / `DownloadClips` exactly (run
repository, generation port, the one latest-read it needs, and the sibling create
use-case).

### D49. Storage and path convention; manifest language resolved by the use-case; no-overwrite via versioning

- Store each manifest as JSON bytes through `StoragePort`, indexed under
  `(run_id, AssetKind.SUBTITLE_MANIFEST)`. Use private application helpers
  `_subtitle_segments_to_bytes` / `_subtitle_segments_from_bytes`, mirroring
  `_voiceover_segments_to_bytes` / `_voiceover_segments_from_bytes`: a JSON list of
  flat objects; `start_seconds`, `end_seconds`, and `duration_seconds` round-trip
  as `float`, `order_index` as `int`, and the remaining fields as `str`.
- Store `source` and provenance in `VersionedAsset.metadata`: `voiceover_asset_id`,
  `voiceover_version` (string, because `metadata` is `Mapping[str, str]`), and
  `language`. The same resolved `language` is recorded once in manifest metadata and
  passed into every `compose(...)` call, so it also lives on every parsed segment and
  is queryable from `Subtitles.segments`. It is resolved with the defensive fallback
  `voiceover.asset.metadata.get("language", voiceover.segments[0].language if voiceover.segments else "en")`
  so it is present even when the upstream voiceover asset omits a `language` key (a
  manually/internally created voiceover) or has zero segments.
- **Language threading.** The caption language is *not* re-read from `run.language`
  in this phase. `GenerateSubtitles` resolves one manifest language from the latest
  voiceover via the defensive fallback above (voiceover asset metadata -> first
  segment language -> `"en"`), records it in manifest metadata, and threads that one
  resolved value into every `compose(...)` call, which the composer writes onto each
  `SubtitleSegment.language`. Language *resolution* stays in the use-case and
  language *use* stays in the composer, so the whole manifest carries one
  authoritative language. In the normal `GenerateVoiceover` path this equals the
  `run.language` that `GenerateVoiceover` already stamped onto every
  `VoiceoverSegment.language`, so it matches a per-segment copy; for manual/internal
  voiceovers the fallback gives deterministic manifest-level behavior. No new request
  body or run field is introduced; this is strictly cleaner than the voiceover phase,
  which had to thread `run.language` itself.
- **Avoiding overwrites.** Each `GenerateSubtitles` call creates a new, immutable
  `SUBTITLE_MANIFEST` version; prior versions are never mutated -- the same
  append-only guarantee as every other asset phase. Because this foundation writes
  no caption bytes, there is nothing else to overwrite. When a future caption-file
  phase materializes `.srt` / `.vtt` (into `SUBTITLE` via `SubtitleBuilder`), it
  must version-scope the subtitle directory under `data/subtitles/...` so a
  re-generate writes fresh files rather than clobbering a prior version's captions;
  that byte-level no-clobber rule is deferred with file materialization and flagged
  in Open Questions.

## Domain Model Proposal

- Add `AssetKind.SUBTITLE_MANIFEST = "subtitle_manifest"`.
- Add and export frozen `SubtitleSegment` with exactly the D46 fields, next to
  `VoiceoverSegment` and `DownloadedClip` in `backend/app/domain/models.py` and
  `backend/app/domain/__init__.py`.
- Do not change `VoiceoverSegment`, `DownloadedClip`, `VideoAssemblySegment`,
  `SelectedClip`, `SceneSpec`, `RenderSpec`, `RunStatus`, `AssetKind.SUBTITLE`, the
  `SubtitleBuilder` port, or run transition rules.
- Do not add caption bytes, file URIs, absolute paths, cue-styling fields, or a
  domain set wrapper.
- Add `Subtitles` only as an application read model pairing a `VersionedAsset` with
  parsed records, defined in the new `subtitle_assets.py` and exported from
  `backend/app/application/use_cases/__init__.py`.

## Asset / Storage Decision

- Persist the subtitle set as JSON bytes through the existing `StoragePort` (no
  caption files). Index with `VersionedAssetRepository` under
  `(run_id, AssetKind.SUBTITLE_MANIFEST)`. Metadata includes `source`
  (`"generated"` for `GenerateSubtitles`, default `"manual"` for a direct
  `CreateSubtitles` call), `voiceover_asset_id`, `voiceover_version`, and
  `language`.
- A second generate creates version 2 and leaves earlier manifests and their
  provenance intact.
- The only stored bytes are JSON metadata; no record carries a file reference.
  Existing generic SQLite, filesystem, and in-memory adapters require no code or
  schema change beyond accepting the new enum value naturally. No `.gitignore`
  change is required: `data/assets/subtitle_manifest/*` is already covered by
  `data/assets/*`, and the future caption files are already covered by the existing
  `data/subtitles/*` ignore.

## Subtitle Composer Port Decision

- Add and export `SubtitleComposer` from the ports package
  (`backend/app/ports/providers.py`, `backend/app/ports/__init__.py`), separate from
  the reserved `SubtitleBuilder`.
- Add and export `StubSubtitleComposer` from the generation adapter package
  (`backend/app/infrastructure/generation/__init__.py`).
- Add a recording `FakeSubtitleComposer` in `tests/fakes/providers.py` for use-case
  and API tests. It records `(voiceover_segment, start_seconds, language)` calls and
  returns configured or default `SubtitleSegment` records; those tests do not depend
  on the concrete adapter.
- Wire only the port into application/API code. The concrete adapter is imported
  only by `main.py` and its own adapter/confinement tests.
- Do not place the composer in `provider_registry.py`; direct composition-root
  wiring matches the current scene/stock/retrieval/selection/assembly/download/
  voiceover pattern and avoids an unrelated registry refactor.

## Fake Composer Decision

- `StubSubtitleComposer` implements the D47 algorithm: one `SubtitleSegment` per
  `VoiceoverSegment`, `scene_id`/`order_index` copied, `language` set from the
  supplied `language` argument (the use-case-resolved manifest language),
  `text = voiceover_segment.narration_text`,
  `duration_seconds = voiceover_segment.duration_seconds`, `start_seconds` taken
  from the supplied offset, `end_seconds = start + duration`, `format = "manifest"`
  (a placeholder/category marker, not a real subtitle file format -- see D46),
  `status = "available"`, `generation_reason = "deterministic_placeholder"`.
- It creates **no** caption files and needs no path-safety helper in this foundation
  (D46): it is pure, returns records only, and touches no network, filesystem,
  subprocess, alignment SDK, or serializer. If a later decision adopts real or
  placeholder `.srt` / `.vtt` bytes, the bytes must be written by a use-case through
  a storage port (producing a `SUBTITLE` `VersionedAsset` via `SubtitleBuilder`) --
  never by the domain/application layers and never to an arbitrary path.

## Use-Case Plan

Create `backend/app/application/use_cases/subtitle_assets.py`, using
`voiceover_assets.py` as the structural template.

1. **`CreateSubtitles`**
   - `execute(run_id, subtitle_segments, source="manual", asset_metadata=None) -> VersionedAsset`.
   - Requires the run, enforces D45, computes the next `SUBTITLE_MANIFEST` version,
     merges `{"source": source}` with any provenance metadata, writes JSON through
     `StoragePort`, and saves the asset. Does not transition the run.
   - Constructor deps: `RunRepository`, `VersionedAssetRepository`, `StoragePort`,
     optional `asset_id_factory`.

2. **`GenerateSubtitles`**
   - `execute(run_id) -> VersionedAsset`.
   - Applies the D45 guard before the read, then follows the D48 order: read the
     latest voiceover, fold over its segments with a cumulative `start_seconds`
     cursor calling the composer per segment, aggregate, and persist through
     `CreateSubtitles` with `source = "generated"` and voiceover + language
     provenance. Does not parse storage itself and does not transition the run.
   - Constructor deps: `RunRepository`, `SubtitleComposer`, `GetLatestVoiceover`,
     `CreateSubtitles`.

3. **`ListSubtitles`**
   - `execute(run_id) -> Sequence[VersionedAsset]` via
     `asset_repository.list_for_run(run_id, AssetKind.SUBTITLE_MANIFEST)`.

4. **`GetLatestSubtitles`**
   - `execute(run_id) -> Subtitles`.
   - Reads the latest asset, raises `AssetNotFoundError(SUBTITLE_MANIFEST)` when
     absent, loads its JSON, and returns the parsed read model.

Export all four use-cases and `Subtitles` from
`backend/app/application/use_cases/__init__.py`.

## API Route Plan

Add response models and routes in the existing `backend/app/api/assets.py` module,
consistent with the existing long route names.

| Method | Path | Returns | Purpose |
| --- | --- | --- | --- |
| `POST` | `/runs/{run_id}/subtitles/generate` | `201 AssetResponse` | Generate from the latest voiceover; persist a `SUBTITLE_MANIFEST` asset (next version, `source=generated`). Applies the D45 rule. |
| `GET` | `/runs/{run_id}/subtitles` | `list[AssetResponse]` | List subtitle asset versions. |
| `GET` | `/runs/{run_id}/subtitles/latest` | `SubtitlesResponse` | Return the latest asset and parsed subtitle segments. |

Add `SubtitleSegmentModel.from_domain`, `SubtitlesResponse.from_subtitles`, and a
`get_subtitle_composer(request)` resolver reading
`request.app.state.subtitle_composer`. The generate route has no request body in
this foundation (language comes from the voiceover). Existing application error
handlers provide 404/409 behavior. There is no manual-create request DTO, raw
asset-byte endpoint, caption-file endpoint, or render endpoint.

## Composition Root Decision

- Add optional `subtitle_composer: SubtitleComposer | None = None` to
  `create_app(...)`, default it to `StubSubtitleComposer()`, and assign
  `app.state.subtitle_composer`, following the existing `voiceover_generator` /
  `clip_downloader` wiring style.
- Keep all repository, storage, latest-reader, create-use-case, and generate
  use-case construction explicit in the route dependency functions, following the
  current asset API pattern.
- Do not alter `provider_registry.py`, settings, environment variables, secrets, or
  lifespan behavior. The default composer is pure and owns no resource, so it never
  affects the database/storage lifespan decision.

## Test Checklist

### Domain and Serialization

- `AssetKind.SUBTITLE_MANIFEST.value == "subtitle_manifest"` and is distinct from
  `SUBTITLE`, `VOICEOVER`, `VOICE`, `DOWNLOADED_CLIPS`, and `RENDER`.
- `SubtitleSegment` is frozen (assignment raises) and has exactly the D46 fields.
- JSON round-trip preserves all fields and numeric types (`start_seconds`,
  `end_seconds`, `duration_seconds` as `float`; `order_index` as `int`).
- Latest-read returns the newest parsed manifest; missing latest raises
  `AssetNotFoundError(SUBTITLE_MANIFEST)`.

### Port and Adapter

- A fake satisfies runtime `isinstance(fake, SubtitleComposer)`; the port resolves
  to `backend.app.ports.providers`.
- `get_type_hints(SubtitleComposer.compose)` shows
  `voiceover_segment: VoiceoverSegment`, `start_seconds: float`, `language: str`,
  and `return: SubtitleSegment`.
- `SubtitleComposer` is a different object from `SubtitleBuilder`; the no-reuse
  decision is visible (separate protocol, separate port).
- `StubSubtitleComposer` is deterministic and repeatable: same segment + same
  `start_seconds` + same `language` produce equal outputs.
- One `SubtitleSegment` per call; `scene_id` and `order_index` are copied;
  `language == language` (the passed argument is used verbatim, even when it differs
  from `voiceover_segment.language`); `text == voiceover_segment.narration_text`;
  `duration_seconds == voiceover_segment.duration_seconds`.
- `start_seconds` equals the supplied offset; `end_seconds == start_seconds +
  duration_seconds`.
- `format == "manifest"`, `status == "available"`,
  `generation_reason == "deterministic_placeholder"`.
- The `SubtitleSegment` has no `subtitle_uri` / file-reference field; no field
  contains a `memory://` or absolute path value.

### Use-Cases and Lifecycle

- Create stores `SUBTITLE_MANIFEST`, increments versions, and persists only JSON.
- `GenerateSubtitles` tags `source=generated` and includes
  `voiceover_asset_id`/`voiceover_version`/`language`; `CreateSubtitles` defaults
  `source=manual`.
- The status guard rejects every state except `scenes_approved` with
  `AssetCreationRejectedError(kind=subtitle_manifest)`, checked before the voiceover
  read and before composer/persistence work (409, not 404), persisting nothing.
- `RunNotFoundError` when the run is missing (composer not called).
- `GenerateSubtitles` calls the composer once per segment, in order, with the latest
  voiceover's segments, threading a cumulative cursor and the single resolved
  `language` into every `compose(voiceover_segment, start_seconds, language)` call;
  the produced segments are contiguous (`start_0 == 0.0`; each `start_n == end_{n-1}`;
  each `end == start + duration`) and aggregate every result.
- A voiceover whose segments are stored out of `order_index` order yields subtitle
  segments ordered ascending by `order_index`, with timing accumulated in that order
  (the defensive sort in `GenerateSubtitles`), not in stored order.
- Manifest `language` resolution, asserted both in manifest metadata and in the
  `language` argument passed to every `compose(...)` call: (a) voiceover asset
  metadata has `language` -> use the metadata language; (b) voiceover asset metadata
  lacks `language` but has segments -> use the first segment's `language`; (c)
  voiceover asset metadata lacks `language` and has zero segments -> default to
  `"en"`.
- An empty latest voiceover (zero segments) yields an empty `SUBTITLE_MANIFEST`
  manifest, never calls the composer, records a manifest-level `language` via the
  defensive fallback (the voiceover's `language` metadata when present, else `"en"`),
  and leaves the run exactly `scenes_approved`.
- `GenerateSubtitles` fails naturally with `AssetNotFoundError(VOICEOVER)` when no
  voiceover exists (seed `scenes_approved` but no voiceover), persisting nothing.
- A voiceover produced for a non-`en` language (for example `"te"`) produces
  subtitle segments whose `language == "te"` and manifest metadata `language ==
  "te"`, with **no** provider call.
- `ListSubtitles` is version-ordered; a second generate creates version 2; the run
  stays exactly `scenes_approved` after create and generate.

### API

- `POST .../subtitles/generate` returns 201 with `kind=subtitle_manifest`,
  `version=1`, `source=generated`, voiceover provenance, and `language`.
- `GET` list returns versions in order; `GET` latest returns parsed `segments` with
  contiguous timing.
- 404 when the run is missing; 404 when no voiceover exists; 409 when status is not
  `scenes_approved` (before any dependency 404); versioning across two generates.
- Only generate/list/latest routes exist; no manual create or caption-file route is
  registered.

### Architecture Boundaries and Fake-Only / No-File Safety

- Domain auto-scan (`test_domain_has_no_framework_or_outer_layer_imports`) confirms
  no framework or outer-layer imports for the new domain code.
- Add `SubtitleComposer` to `test_provider_interfaces_live_in_ports`.
- Extend the asset-use-case hint map with `CreateSubtitles`
  (run/asset/storage + `asset_id_factory`), `ListSubtitles` (asset repo), and
  `GetLatestSubtitles` (asset repo + storage); extend the generation-use-case hint
  map with `GenerateSubtitles` (`run_repository`, `subtitle_composer`,
  `get_latest_voiceover`, `create_subtitles`).
- Application auto-scan (`test_application_does_not_import_infrastructure`) and the
  API route scans (`test_assets_route_imports_use_cases_not_infrastructure`,
  `test_api_routes_depend_on_use_cases_not_infrastructure`) cover the new files.
- `test_generation_adapters_import_no_api_application_or_external_modules` already
  forbids api/application/SDK/HTTP/subprocess/FFmpeg/audio modules; the pure
  `StubSubtitleComposer` inherits that coverage. Optionally extend the forbidden set
  with subtitle/alignment modules (`pysrt`, `webvtt`, `srt`, `aeneas`, `whisper`,
  `vosk`) to prove the stub performs no real serialization or alignment.
- Add `test_stub_subtitle_composer_import_confined_to_composition_root` proving only
  `main.py` imports `StubSubtitleComposer`.
- Assert persisted bytes decode as JSON and contain no caption-file bytes; no parsed
  `SubtitleSegment` carries a file reference, `memory://` value, or absolute path.
- Search the implementation diff for SRT/VTT serializers, alignment/STT SDKs, cue
  styling, FFmpeg/subprocess calls, real/placeholder caption writes, burn-in/render
  calls, `SUBTITLE`/`SubtitleBuilder` materialization, and status transitions; none
  should be present.

### End-to-End

Extend `tests/test_draft_planning_workflow.py` through:

```text
prompt -> script -> scene table -> stock plan -> clip candidates
       -> selected clips -> video assembly plan -> downloaded clips
       -> voiceover -> subtitles
```

After the voiceover step, assert `POST .../subtitles/generate` returns 201
(`kind=subtitle_manifest`, `version=1`, `source=generated`, voiceover provenance,
`language=en`) and `GET .../subtitles/latest` shows one segment per voiceover
segment, in the same `order_index` order, with `text` equal to the voiceover
`narration_text`, `language == "en"`, `duration_seconds` equal to the voiceover
segment `duration_seconds`, contiguous timing (`start_0 == 0.0`, each
`start_n == end_{n-1}`, each `end == start + duration`), `format == "manifest"`,
`status == "available"`, no file reference on any segment, and the run still exactly
`scenes_approved` (not `rendered`, no transition).

## Implementation Slices

Implement one slice at a time in inward-to-outward order. Run focused tests after
each slice and the full suite after the final slice.

### Slice 1: Domain -- asset kind and record

- **Files:** `backend/app/domain/models.py`, `backend/app/domain/__init__.py`, new
  `tests/test_subtitle_segment.py`.
- **Change:** Add `AssetKind.SUBTITLE_MANIFEST` and the frozen `SubtitleSegment`
  dataclass/export (D44, D46). Leave `SUBTITLE` untouched.
- **Tests:** Kind value/distinction (including distinct from `SUBTITLE`), exact
  fields, frozen behavior, no file-reference field.
- **Acceptance:** Domain tests and the domain boundary scan pass; no other layer
  changes.

### Slice 2: Port -- `SubtitleComposer`

- **Files:** `backend/app/ports/providers.py`, `backend/app/ports/__init__.py`, new
  `tests/test_subtitle_composer_port.py`.
- **Change:** Add/export the D47 runtime-checkable protocol, separate from
  `SubtitleBuilder`.
- **Tests:** Runtime conformance against a fake, module location, exact type hints
  (`voiceover_segment: VoiceoverSegment`, `start_seconds: float`, `language: str`,
  `return: SubtitleSegment`), and distinctness from `SubtitleBuilder`.
- **Acceptance:** Port tests and architecture tests pass.

### Slice 3: Deterministic adapter and test fake

- **Files:** new
  `backend/app/infrastructure/generation/stub_subtitle_composer.py`, generation
  package export, `tests/fakes/providers.py` (`FakeSubtitleComposer`), and
  (optionally) extended `tests/test_generation_adapters.py`.
- **Change:** Implement the D47 mapping and the recording fake. No safe-segment
  helper is needed (no URI).
- **Tests:** One record per call, field copies, text/duration copy,
  start/end arithmetic, format/status/reason constants, the passed `language` is
  used on `SubtitleSegment.language`, repeatability, port conformance.
- **Boundary:** No application/API/external/subtitle-SDK imports.
- **Acceptance:** Focused adapter and generation-boundary tests pass.

### Slice 4: Application -- subtitle use-cases

- **Files:** new `backend/app/application/use_cases/subtitle_assets.py`, use-case
  package export, new `tests/test_subtitle_use_cases.py`.
- **Change:** Add the `Subtitles` read model, JSON helpers,
  create/generate/list/latest use-cases, D45 guard, D48 ordering with the defensive
  `order_index` sort and cumulative cursor, and voiceover/language provenance
  metadata with the defensive `language` fallback (asset metadata -> first segment
  -> `"en"`).
- **Tests:** Versioning, round-trip, source/provenance metadata, latest/list,
  errors, guard-before-read, composer call-per-segment with cumulative timing,
  out-of-order segments sorted by `order_index`, the three `language`-fallback cases
  (asset metadata present / absent-with-segments / absent-and-empty), empty-voiceover,
  no transition.
- **Boundary:** Dependencies are ports and sibling use-cases only.
- **Acceptance:** Focused use-case and application-boundary tests pass.

### Slice 5: API routes and composition wiring

- **Files:** `backend/app/api/assets.py`, `backend/app/main.py`, new
  `tests/test_subtitle_api.py`.
- **Change:** Add DTOs, generate/list/latest routes, the `get_subtitle_composer`
  resolver, the `subtitle_composer` `create_app` parameter, and the default
  `StubSubtitleComposer` wiring.
- **Tests:** 201/404/409, latest/list/versioning, route absence, injected fake,
  non-`en` language propagation, contiguous timing in the response.
- **Boundary:** Routes contain no composer, lifecycle, storage, or version logic;
  the concrete adapter appears only in the composition root.
- **Acceptance:** API and route-boundary tests pass.

### Slice 6: Boundary hardening, E2E, and phase audit

- **Files:** `tests/test_architecture_boundaries.py`,
  `tests/test_draft_planning_workflow.py`; `.gitignore` only if inspection finds a
  real gap (none expected).
- **Change:** Add `SubtitleComposer` to the port-location test, the three
  persistence/read use-cases to the asset-use-case hint map, `GenerateSubtitles` to
  the generation-use-case hint map, the `StubSubtitleComposer` confinement test, the
  optional subtitle/alignment forbidden-import additions, and extend the full
  workflow.
- **Tests:** Focused architecture/E2E tests, then the full suite.
- **Acceptance:** Full suite and `git diff --check` pass; no generated captions,
  secrets, database files, caches, or virtual-environment files are staged.

### Slice Order and Dependencies

```text
1 domain -> 2 port -> 3 stub adapter + fake
                   -> 4 application use-cases
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
commands above before commit. Also inspect staged files to confirm no captions,
secrets, SQLite databases, caches, or virtual-environment files are included.

## Explicit Non-Goals / Deferred Work

- Real `.srt` / `.vtt` caption files or any caption-file bytes, including
  placeholder subtitle files (deferred; if adopted later, written by a use-case
  through a storage port into the `SUBTITLE` asset / `data/subtitles/...` via
  `SubtitleBuilder`).
- Materializing the per-file `SUBTITLE` caption asset or registering it in the
  index; using or modifying the reserved `SubtitleBuilder` port.
- Subtitle serialization/formatting (SRT/VTT timestamp formatting, cue indices,
  `WEBVTT` headers) or any serializer library (`srt`, `pysrt`, `webvtt`).
- Forced alignment, speech-to-text, word-level timing, or any alignment/STT
  provider (`aeneas`, `whisper`, `vosk`); HTTP clients or any network I/O.
- API-key handling, provider SDKs, or any external integration.
- Cue styling, positioning, line wrapping, reading-speed limits, or re-segmentation
  of narration into multiple cues.
- FFmpeg, subprocess calls, caption burn-in, overlay rendering, or output files.
- Any handling policy for failed/skipped voiceover segments (non-`available`
  voiceover `status`); this foundation copies text/timing regardless of status
  because the stub always emits `"available"` (see Open Questions).
- Multi-speaker labels, actor dialogue, lip-sync, or per-speaker caption tracks.
- Real audio synthesis, TTS providers, or any audio bytes.
- AI ranking, scoring, translation, or caption rewriting.
- Subtitle-editing UI, frontend, or a manual public create route.
- Scene refinement or changes to script, scene, stock planning, candidate
  retrieval, selected-clip, video-assembly-plan, downloaded-clip, or voiceover
  behavior.
- A new run status or any run transition.
- Provider registry refactoring, a generic pipeline orchestrator, workers, or
  queues.
- Redis, Postgres, S3, cloud/SaaS features, auth, or pagination.
- Database schema changes or a generic JSON schema/version registry.
- Byte-level no-clobber rules and absolute-path resolution (deferred with caption-
  file materialization).

## Open Questions

- **Composer call shape: per-segment with offset vs whole-list.** This foundation
  uses a per-segment `compose(voiceover_segment, start_seconds, language)` with the
  use-case owning the cumulative fold and language resolution (D47), keeping symmetry
  with `VoiceoverGenerator` /
  `ClipDownloader`. The rejected alternative -- `compose(voiceover_segments) ->
  Sequence[SubtitleSegment]` letting the composer own timing -- is cleaner for the
  timing concern but breaks the per-item port parallel and concentrates more policy
  in the adapter. If a future real composer needs cross-segment context (merging,
  reading-speed re-segmentation), revisit the whole-list shape; the use-case/route
  contract is unchanged either way.
- **Caption granularity.** This foundation emits one `SubtitleSegment` per
  `VoiceoverSegment` (D46), inheriting the voiceover's granularity. Real captioning
  often splits long narration into multiple short, time-boxed cues for readability,
  or merges by scene. That re-segmentation is deferred; the `scene_id` and
  `order_index` fields are retained so either path is additive and needs no manifest
  reshape.
- **Non-`available` voiceover segment status.** Future real voiceover generation may
  produce segments with `status = "failed"` or `"skipped"`. This foundation copies
  text and timing regardless of the voiceover segment's `status`, because the stub
  always emits `"available"`, so the distinction never arises today. A future phase
  must decide whether subtitle generation should skip such segments, emit a blank
  caption, mark the subtitle `status` unavailable (the `SubtitleSegment.status` field
  is the hook), or still emit a caption -- and how that interacts with the cumulative
  timeline (whether a skipped segment still consumes its `duration_seconds`). No
  handling policy is chosen now.
- **Timing model: gapless cumulative vs aligned.** The stub assumes captions are
  gapless and back-to-back, driven entirely by voiceover durations (D47). Real
  captions may need gaps, lead-in/lead-out padding, or alignment to actual
  synthesized audio. When real audio and alignment exist, `start_seconds`/
  `end_seconds` become aligned values rather than a pure accumulation; the field
  shape is unchanged.
- **Read model name.** `Subtitles` (chosen, mirroring `Voiceover`) vs `SubtitleSet`
  (mirroring `DownloadedClipSet` / `SelectedClipSet`). No downstream impact; the API
  response/type names follow whichever is chosen.
- **Caption files and `SUBTITLE` materialization.** This foundation is metadata-only.
  A caption-file phase will call `SubtitleBuilder` (or a new builder) to serialize/
  align these segments into a `.srt` / `.vtt`, store it as a `SUBTITLE`
  `VersionedAsset` under `data/subtitles/...`, and wire it into `RenderSpec.subtitles`.
  The contract (durable per-segment text, language, and contiguous timing) is
  designed so that change is additive.
- **Byte-level no-clobber.** When real/placeholder caption files are written, the
  subtitle directory must be version-scoped so re-generates do not overwrite a prior
  manifest version's captions. Deferred until file materialization exists.
```