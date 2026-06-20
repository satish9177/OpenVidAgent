# Voiceover Foundation

Design document for the next phase. This records the intended design and slice
plan before any code is written. No backend, test, or product implementation is
part of this document. The approved direction continues the asset-only tail of
the pipeline: assembly planning turned selections plus scenes into a
`VideoAssemblyPlan`, and clip download turned the plan's segments into a durable
`DownloadedClipSet` of local clip references. Those steps build the *visual*
side of a voiceover B-roll video. This phase builds the *audio* side: it turns
the latest video assembly plan's per-segment narration into a durable, versioned
*voiceover* artifact -- a set of `VoiceoverSegment` records, each carrying the
narration text, language/voice/provider settings, and a deterministic local
audio reference -- produced through a voiceover generator port. It introduces
the voiceover-plan abstraction only. It does not call any real TTS provider,
perform any network request, store real audio bytes, write placeholder audio
files, invoke FFmpeg, or render video.

## Goal

Given the latest video assembly plan for a run, produce a durable, versioned set
of *voiceover segments*: one `VoiceoverSegment` per `VideoAssemblySegment`,
copying the segment's narration and timeline position and adding voiceover
settings (language, voice, provider), a deterministic local audio reference, a
content type, an estimated duration, and a generation status. The artifact
answers, for each timeline position: what narration would be spoken, in which
language and voice, for roughly how long, and where its audio file would live --
all as metadata.

This foundation is deliberately narrower than a real text-to-speech pipeline. It
makes the "what narration plays where, and in what voice" decision inspectable
and repeatable *without* synthesizing audio, storing audio bytes, calling a TTS
provider, handling API keys, probing audio, mixing/ducking, or transitioning the
run lifecycle. For this foundation the generator is a deterministic stub that
fabricates stable `memory://` audio references and copies narration only; no
real OpenAI / ElevenLabs / Cartesia / Sarvam synthesis exists.

## Target Workflow

The existing asset-only tail is extended by one step. The run reaches
`scenes_approved` exactly as today and remains there while stock planning, clip
retrieval, clip selection, assembly planning, clip download, and now voiceover
create independently versioned JSON assets.

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
-> generate voiceover                # NEW: reads the latest video assembly plan,
                                     # calls the VoiceoverGenerator per segment,
                                     # persists a VOICEOVER asset,
                                     # run stays scenes_approved (asset-only)
```

The target product workflow becomes:

```text
prompt -> script draft -> scene table -> stock plan -> clip candidates
       -> selected clips -> video assembly plan -> downloaded clips -> voiceover
```

Voiceover comes textually after downloaded clips in the workflow, but it does
**not** read from downloaded clips. Downloaded clips and voiceover are
*siblings*, both derived from the same video assembly plan: one produces the
visual local references, the other produces the narration plan. They are
independent and order-insensitive relative to each other; placing voiceover last
reflects the build order of the pipeline, not a data dependency on downloaded
clips. See D39 for why the assembly plan, not the downloaded clip set, is the
correct upstream read.

## Architecture Rule

Dependencies point inward:

`API/UI -> application use-cases -> domain models/services -> ports/interfaces -> infrastructure adapters`

- The domain remains framework-free and serialization-free.
- Application use-cases orchestrate repositories, storage, latest-asset readers,
  and the generator port. They do not import infrastructure, open sockets, call
  a TTS SDK, or touch the filesystem directly.
- `VoiceoverGenerator` is a port expressed only in domain types (plus the
  `run_id` and `language` identifier strings).
- `StubVoiceoverGenerator` is a pure infrastructure adapter with no network,
  filesystem, subprocess, FFmpeg, TTS SDK, audio encoder, API, or application
  dependency.
- API routes call application use-cases only. Lifecycle and versioning rules do
  not move into route functions.
- Concrete generator wiring remains explicit in `backend/app/main.py`.

This phase is audio-adjacent, which makes the boundary rule especially
important. Like clip download, its *eventual* real implementation will write
non-JSON bytes (audio files) and will call an external provider. The domain and
application layers must never perform that work. Any byte materialization
(placeholder or real) and any synthesis call belong behind a port/adapter -- the
new `VoiceoverGenerator` plus the existing `StoragePort` / `LocalFilesystemStorage`
and the reserved `TTSProvider` -- orchestrated by a use-case through ports. This
foundation keeps that risk at zero by writing only JSON manifest bytes and never
calling any provider (see Asset / Storage Decision, D38, and D41).

## Existing Foundation

This design is based on the current implementation, confirmed by reading the
source, not only the earlier design notes:

- `VersionedAsset` stores `asset_id`, `kind`, `version`, `uri`, and string
  metadata (`metadata` is `Mapping[str, str]`). The generic repository and
  storage ports already support new asset kinds without a database schema
  change.
- `AssetKind` currently includes `SCRIPT`, `SCENE_TABLE`, `STOCK_PLAN`,
  `CLIP_CANDIDATES`, `SELECTED_CLIPS`, `VIDEO_ASSEMBLY_PLAN`, `DOWNLOADED_CLIPS`,
  `STOCK_CLIP`, `VOICE`, `SUBTITLE`, and `RENDER`. Crucially, `VOICE = "voice"`
  **already exists** and is still unused in any use-case: `RenderSpec.voice` is
  typed `VersionedAsset`, the reserved `TTSProvider` port returns a
  `VersionedAsset`, and the test `FakeTTSProvider` returns a `VOICE` asset with a
  `memory://voice/...wav` uri. Across the codebase, `VOICE` is reserved for the
  future *audio-bytes* asset that a renderer consumes -- the per-file output of
  real synthesis -- exactly as `STOCK_CLIP` is reserved for future per-file media
  bytes. This phase does not touch `VOICE` or `TTSProvider` (see D38).
- `VideoAssemblySegment` is a frozen domain dataclass whose fields include
  `scene_id`, `narration`, `visual_query`, `target_duration_seconds`,
  `source_duration_seconds`, and a zero-based contiguous `order_index`. Its
  `narration` (copied from the matching `SceneSpec`) and its `order_index` and
  `target_duration_seconds` are exactly the per-item inputs this phase reads. The
  downloaded-clip model deliberately dropped `narration`, which is one reason
  voiceover reads the assembly plan, not the downloaded clip set.
- `GetLatestVideoAssemblyPlan` returns the latest parsed
  `VideoAssemblyPlan(asset, segments)` and raises
  `AssetNotFoundError(run_id, VIDEO_ASSEMBLY_PLAN)` when missing. This is the
  read path and the natural dependency guard this phase reuses.
- The downloaded-clip use-cases (`CreateDownloadedClipSet`, `DownloadClips`,
  `ListDownloadedClipSets`, `GetLatestDownloadedClipSet`) plus the
  `_downloaded_clips_to_bytes` / `_downloaded_clips_from_bytes` helpers in
  `downloaded_clip_assets.py`, and the `StubClipDownloader` adapter with its
  locally-defined `_safe_component` helper, are the exact structural template for
  this phase. The guard `_DOWNLOAD_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})`
  and the guard-before-read ordering in `DownloadClips` are copied directly.
- `Run` carries `language: str = "en"`. The intake API already accepts and echoes
  a run language, so the voiceover language flows from `run.language` with no new
  request field (see D40 / D43).
- `RunStatus` is `created -> script_ready -> script_approved -> scenes_ready ->
  scenes_approved -> rendered` (plus `failed`). `scenes_approved` only
  transitions to `rendered`/`failed`; there is no planning/retrieval/selection/
  assembly/download/voiceover status, and this phase adds none.
- `backend/app/ports/providers.py` holds runtime-checkable provider protocols
  using domain types (`ClipRetrievalProvider`, `ClipSelector`,
  `VideoAssemblyPlanner`, `ClipDownloader`, and the reserved `TTSProvider`,
  `SubtitleBuilder`, `Renderer`). `backend/app/infrastructure/generation` holds
  pure deterministic defaults (`StubClipRetrievalProvider`,
  `DeterministicClipSelector`, `DeterministicVideoAssemblyPlanner`,
  `StubClipDownloader`, ...), and `backend/app/main.py` wires those defaults
  through `app.state`.
- `StoragePort.save_asset(asset, data)` writes bytes for a `VersionedAsset`;
  `LocalFilesystemStorage` derives the path as `{kind}/{asset_id}/v{version}`
  under an injected storage root and confirms every resolved path stays within
  the root. The in-memory test storage keys generically on a
  `memory://{kind}/{asset_id}/v{version}` uri.
- Persistence is kind-agnostic: SQLite stores `assets.kind` as text without an
  enum check constraint, local storage derives paths from `kind.value`, and the
  in-memory fakes key generically on `(run_id, kind)`. No SQLite migration or
  storage refactor is needed for a new asset kind.
- `.gitignore` already ignores `data/assets/*` (keeping `.gitkeep`), so
  `data/assets/voiceover/*` is already covered. It also already ignores
  `data/audio/*`, reserved for the future real audio bytes a later real-TTS phase
  will write into the `VOICE` asset.
- Architecture boundary tests scan domain, application, API, ports, and the
  generation package for forbidden imports, and confine each concrete default
  (`StubStockClipPlanner`, `StubClipRetrievalProvider`, `DeterministicClipSelector`,
  `DeterministicVideoAssemblyPlanner`, `StubClipDownloader`) to `main.py`. New
  files in those layers inherit forbidden-import coverage automatically; this
  phase adds a parallel confinement test for its new default.

## Problem Being Solved

The visual side of the pipeline now reaches a durable downloaded-clip manifest:
the system knows which clip backs each timeline segment and where its local file
would live. But OpenVidAgent V1 is a *voiceover B-roll* product, and the system
still has no notion of voiceover at all. The narration text exists -- it was
authored per scene and copied into each `VideoAssemblySegment.narration` -- but
there is no voiceover plan, no voiceover asset, no record of which language or
voice would speak it, and no audio reference. A future renderer cannot lay a
narration track over the B-roll: it has narration strings scattered across
assembly segments and nothing that says "this is the voiceover."

This phase introduces the narrow foundation for that audio layer: a domain model
and asset that represent, per timeline segment, a voiceover with its narration,
language/voice/provider settings, a stable local audio reference, and a
generation status, produced through a replaceable generator port. It
deliberately stops short of synthesizing or storing any real audio so the
abstraction, persistence, language model, and API shape can be locked in and
tested before any TTS provider, API key, network call, audio encoder, or FFmpeg
concern is introduced. Because the model carries `language` from the start, the
manifest shape already supports Telugu/Hindi and other Indian languages without
a reshape when real synthesis arrives.

## Answers to Design Questions

| # | Question | Decision |
| --- | --- | --- |
| 1 | Read latest video assembly plan, scene table, or script draft? | The latest **video assembly plan** (D39). It carries timeline `order_index`, per-segment `narration`, and `target_duration_seconds`. The scene table lacks timeline order; the script draft lacks scene segmentation and durations; the downloaded clip set dropped narration entirely. |
| 2 | One asset for the whole run, or one per scene? | One **set** asset for the whole run (`VOICEOVER`) containing many `VoiceoverSegment` records (D40), mirroring `SELECTED_CLIPS`, `VIDEO_ASSEMBLY_PLAN`, and `DOWNLOADED_CLIPS`. |
| 3 | Domain model name? | `VoiceoverSegment` (D40), a frozen metadata-only domain dataclass. The application read model is `Voiceover` (D40). |
| 4 | New asset kind? | Yes: `AssetKind.VOICEOVER = "voiceover"` (D38). |
| 5 | Reuse `AssetKind.VOICE`, or keep it reserved? | Keep `VOICE` **reserved** for future audio bytes (D38). `VOICEOVER` is the JSON voiceover-plan manifest; `VOICE` stays the future per-file synthesized-audio asset consumed by `RenderSpec.voice` and produced by `TTSProvider`. This mirrors `DOWNLOADED_CLIPS` vs `STOCK_CLIP`. |
| 6 | Real audio files or metadata only? | **Metadata only** (D40). No audio bytes, no placeholder audio files; the only bytes written are the JSON manifest. |
| 7 | TTS/speech synthesis port (`VoiceoverGenerator`)? | Yes, a **new** `VoiceoverGenerator` port distinct from the reserved `TTSProvider` (D41). `VoiceoverGenerator.generate(run_id, segment, language) -> VoiceoverSegment` returns metadata; `TTSProvider.synthesize(text) -> VersionedAsset` returns audio bytes and stays reserved. |
| 8 | Deterministic fake behavior? | Map each `VideoAssemblySegment` to one `VoiceoverSegment`: copy `scene_id`/`order_index`/`narration`, set `provider="stub"`, `voice_id="stub-narrator"`, `content_type="audio/mpeg"`, `status="available"`, `generation_reason="deterministic_placeholder"`, `duration_seconds=segment.target_duration_seconds`, and a deterministic `memory://` reference (D41). |
| 9 | `memory://` audio references only? | Yes (D41/D43): `memory://voiceovers/{run_id}/{order_index:04d}/{scene_id}.mp3`, with dynamic components validated by a locally reimplemented safe-segment helper. No bytes exist. |
| 10 | What metadata to copy for durability? | From the matching segment: `scene_id`, `order_index`, and `narration` (as `narration_text`); `target_duration_seconds` is used to derive `duration_seconds` (D40/D41). Copy-not-reference, per D22/D28. Visual fields (provider clip ids, URLs, dimensions) are intentionally **not** copied -- they are not narration concerns. |
| 11 | Language/voice/provider fields? | Yes (D40): `language`, `voice_id`, `provider` per segment, so future multilingual/multi-voice output is additive. |
| 12 | Indian languages now, without real TTS? | Yes (D40/D43). `language` is a free-form code (`"en"`, `"te"`, `"hi"`, `"ta"`, ...) sourced from `run.language`. The stub stamps it and fabricates a `memory://` reference regardless of language; **no** provider is called. Real Telugu/Hindi audio is deferred to the real-TTS phase. |
| 13 | Use-cases? | `CreateVoiceover`, `GenerateVoiceover`, `ListVoiceovers`, `GetLatestVoiceover` (D42). |
| 14 | API routes? | `POST .../voiceovers/generate`, `GET .../voiceovers`, `GET .../voiceovers/latest` (D42). No manual create route. |
| 15 | Run status gate? | `RunStatus.SCENES_APPROVED`, checked before the assembly-plan read (D39). |
| 16 | Transition the run status? | No. Asset-only; no new `RunStatus`; no transition (D39). |
| 17 | Tests for boundaries / fake-only / no-real-audio? | See Test Checklist. Reuse the auto-scanning suite; add port-location, port-hint, use-case-hint, confinement, deterministic-generate, round-trip, guard-ordering, `memory://`-only/no-audio-bytes, and no-TTS-SDK assertions (extend the generation-adapter forbidden set with TTS/audio modules). |
| 18 | Explicitly deferred? | See Explicit Non-Goals / Deferred Work. No real/placeholder audio, no TTS provider, no API keys/HTTP, no audio encoders/FFmpeg, no subtitles, no multi-speaker/dialogue/lip-sync, no `VOICE` materialization, no run transition, no UI, no upstream changes. |

## Design Decisions

These decisions continue the project decision log: D1-D7 cover script/scene
planning, D8-D13 stock planning, D14-D19 clip retrieval, D20-D25 selected clip
selection, D26-D31 video assembly planning, and D32-D37 clip download. This phase
adds D38-D43. It is, in structure, the audio analog of the download phase: where
download produced `DOWNLOADED_CLIPS` from the assembly plan via `ClipDownloader`,
voiceover produces `VOICEOVER` from the same plan via `VoiceoverGenerator`.

### D38. Add `AssetKind.VOICEOVER`; keep `VOICE` and `TTSProvider` reserved for future audio bytes

- Add `VOICEOVER = "voiceover"` to `AssetKind`.
- It represents the set of voiceover-plan records derived from a video assembly
  plan: one `VoiceoverSegment` per timeline segment, each with narration text,
  language/voice/provider settings, a local audio reference, and a generation
  status, persisted as one versioned JSON asset. It is distinct from
  `VIDEO_ASSEMBLY_PLAN` (visual timeline intent), `DOWNLOADED_CLIPS` (visual local
  references), `VOICE` (future per-file synthesized audio bytes), `SUBTITLE`
  (future captions), and `RENDER` (future rendered output).
- Do **not** reuse `AssetKind.VOICE`, and do **not** reuse the `TTSProvider`
  port. Throughout the codebase `VOICE` is the future *audio-bytes* asset: it is
  the type of `RenderSpec.voice` (what a renderer plays), it is what the reserved
  `TTSProvider.synthesize(text) -> VersionedAsset` is shaped to return, and it is
  what the test `FakeTTSProvider` already emits (a `VOICE` asset with a
  `.wav` uri). The voiceover *plan* manifest is a different artifact -- many
  metadata records, no bytes -- exactly as `DOWNLOADED_CLIPS` (the JSON manifest)
  is distinct from `STOCK_CLIP` (the future per-file media bytes). Keeping the
  voiceover plan (`VOICEOVER`) and the eventual synthesized audio (`VOICE`) as
  distinct kinds lets the plan and the audio store evolve and re-run
  independently without colliding versions, and lets a future real-TTS slice
  reuse `TTSProvider` -> `VOICE` cleanly under the plan this phase locks in.
- Persist only JSON metadata through the existing `StoragePort`, indexed through
  `VersionedAssetRepository`. The `audio_uri` is a reference and is never opened
  or written to in this phase. No SQLite migration, storage adapter change,
  `.gitignore` change, or JSON schema registry is added: persistence is
  kind-agnostic, and manifest bytes land under `data/assets/voiceover/...`,
  already covered by the `data/assets/*` ignore.

### D39. Read the latest video assembly plan; asset-only; gated at `scenes_approved`; never transitions the run

- Read from `GetLatestVideoAssemblyPlan`, **not** `GetLatestDownloadedClipSet`,
  `GetLatestSceneTable`, or any script-draft read. The assembly plan is the
  authoritative source for voiceover because it carries, per timeline segment,
  the `narration` (already copied from the scene), the `order_index` (the
  position the narration occupies), and the `target_duration_seconds` (the time
  budget the narration must fit). The downloaded clip set is the wrong source:
  it is a sibling visual artifact and its `DownloadedClip` model dropped
  `narration`. The raw scene table is a weaker source: it lacks timeline order
  and a per-position index, and a scene may map to multiple segments. The script
  draft is the weakest: it has no scene segmentation, durations, or order.
  Reading the assembly plan means the voiceover manifest preserves timeline order
  for free and needs only one upstream read.
- Define `_VOICEOVER_ALLOWED = frozenset({RunStatus.SCENES_APPROVED})` in the new
  application module. Both `GenerateVoiceover` and the internal `CreateVoiceover`
  enforce this status. The generation use-case checks it first so an invalid run
  returns `AssetCreationRejectedError` (HTTP 409) before the assembly-plan read
  can produce a 404.
- Re-generating while `scenes_approved` creates the next `VOICEOVER` version and
  leaves the run unchanged. Add no status between `scenes_approved` and
  `rendered`, and call no run transition method. A future renderer remains
  responsible for the eventual `rendered` transition.
- If no video assembly plan exists, `GetLatestVideoAssemblyPlan` naturally raises
  `AssetNotFoundError(run_id, VIDEO_ASSEMBLY_PLAN)` (mapped to HTTP 404). No
  special-casing is added.

### D40. Add `VoiceoverSegment`; use an application `Voiceover` read model; metadata-only audio references

Add a frozen domain dataclass:

```python
@dataclass(frozen=True)
class VoiceoverSegment:
    scene_id: str            # links the record back to its scene
    order_index: int         # copied from the segment; preserves timeline order
    narration_text: str      # copied from the segment's narration
    language: str            # e.g. "en", "te", "hi"; sourced from run.language
    voice_id: str            # e.g. "stub-narrator"
    provider: str            # e.g. "stub"
    audio_uri: str           # generator-defined memory:// reference; never an OS path
    content_type: str        # e.g. "audio/mpeg"
    duration_seconds: float  # estimated narration duration (see D41)
    status: str              # e.g. "available"
    generation_reason: str   # why/how, e.g. "deterministic_placeholder"
```

Field semantics:

- `scene_id`, `order_index`, and `narration_text` are copied from the matching
  `VideoAssemblySegment` (`narration_text` from `segment.narration`). Copying
  keeps each manifest version durable even when the assembly plan is regenerated
  later, matching the copy-not-reference rule of D22/D28. Visual fields
  (`provider_clip_id`, URLs, dimensions) are deliberately **not** copied: they
  are B-roll concerns, not narration concerns, and live in the assembly plan and
  downloaded-clip manifest.
- `language` is the spoken language code, sourced from `run.language` (D43). It
  is a free-form string so any language -- including Telugu (`"te"`), Hindi
  (`"hi"`), Tamil (`"ta"`) -- is representable today without a real provider.
- `voice_id` and `provider` record the voice configuration. The stub uses fixed
  values; the fields exist so a future real generator (or a future request/run
  setting) can vary them without a schema change.
- `audio_uri` is the single local reference -- the value a future renderer would
  resolve to obtain the narration audio. In this foundation it is a
  generator-defined `memory://voiceovers/...` placeholder (no bytes exist),
  making it unmistakable, like the `memory://` references the stub downloader
  already produces, that nothing was synthesized. It is *not* produced by
  `LocalFilesystemStorage` and is not resolved by any current storage API; it is
  always relative and run-scoped, never an absolute OS path.
- `content_type` is a deterministic constant in the stub (`"audio/mpeg"`); it
  describes the intended media type, not a probed value.
- `duration_seconds` is an estimated narration duration; D41 fixes how the stub
  derives it.
- `status` and `generation_reason` make the record explicit about whether the
  voiceover is considered present and why. The stub always emits `"available"` /
  `"deterministic_placeholder"`; the fields exist so a future real generator can
  record `"failed"`, `"skipped"`, etc. without a schema change.

The copied fields are descriptive metadata, not audio and not executable render
commands. The record contains no audio bytes, sample rates, codecs, byte ranges,
or FFmpeg instructions.

Add `Voiceover` in the application layer as:

```python
class Voiceover(NamedTuple):
    asset: VersionedAsset
    segments: tuple[VoiceoverSegment, ...]
```

Do not add a domain-level set wrapper -- symmetry with the selected-clip,
assembly-plan, and downloaded-clip slices plus YAGNI; the application read model
already pairs the `VersionedAsset` with parsed records.

**One `VoiceoverSegment` per `VideoAssemblySegment`.** This foundation keys the
voiceover plan one-to-one with the visual timeline, preserving `order_index`.
Under the current one-selected-clip-per-scene flow this is identical to one
record per scene, so V1 output is unaffected. The alternative -- deduplicating to
one record per scene when a scene spans multiple B-roll segments -- is more
correct at synthesis time (a scene's narration should be spoken once even if its
visuals cut between several clips) but needs cross-segment policy and diverges
from the per-segment `ClipDownloader` parallel. Because the foundation is
metadata-only and synthesizes nothing, the per-segment choice produces no wasted
audio now, and the `scene_id` field is the hook that lets a future real-TTS phase
group by scene without reshaping the manifest. The duplicate-narration concern is
recorded as a first-class Open Question.

**Metadata-only, no placeholder audio.** This foundation writes no audio files:
the only bytes persisted are the JSON manifest. The generator stub is pure and
the use-case writes exactly one asset (the manifest) through `StoragePort`. This
keeps the phase symmetric with retrieval, selection, assembly planning, and
download; keeps the new generation adapter pure (so the existing
generation-boundary tests pass unchanged); and -- critically -- keeps the first
audio-shaped phase from introducing any non-JSON filesystem write or any provider
call, so the "no filesystem/provider work in domain/application" rule is
satisfied by construction.

### D41. `VoiceoverGenerator` is a per-segment port distinct from `TTSProvider`; the stub maps each segment purely

Define a runtime-checkable port in `backend/app/ports/providers.py`, separate
from the reserved `TTSProvider`:

```python
@runtime_checkable
class VoiceoverGenerator(Protocol):
    def generate(
        self, run_id: str, segment: VideoAssemblySegment, language: str
    ) -> VoiceoverSegment:
        """Create one metadata-only voiceover segment from a timeline segment."""
        ...
```

- **Per-segment, not whole-plan.** A real synthesis call is per-narration-chunk:
  one TTS request per segment's narration. The per-segment boundary mirrors
  `ClipDownloader.download(run_id, segment)` and lets the use-case aggregate
  whole-plan-level into one manifest (the D17/D36 pattern). The port takes
  `run_id` so the generator -- which in the real world owns where audio bytes are
  written -- can derive a stable, run-scoped audio reference, and `language` so it
  can stamp the spoken language; both are plain identifier strings, the same
  shape the repositories already accept, not a layer violation.
- **Distinct from `TTSProvider`.** `TTSProvider.synthesize(text) -> VersionedAsset`
  returns an audio-bytes asset and stays reserved/unused. Reusing it would force
  this metadata-only phase to either produce a `VersionedAsset` it has no bytes
  for, or to redefine its contract -- both premature. `VoiceoverGenerator` owns
  the *plan* policy (which narration, which voice/language, where audio would
  live); `TTSProvider` will own the *synthesis* (text -> real `VOICE` bytes) in a
  later phase. The two compose cleanly: a future `GenerateVoiceover`-like flow can
  call `TTSProvider` to materialize each segment's audio at its `audio_uri`.
- The port imports only `VideoAssemblySegment` and `VoiceoverSegment` from the
  domain. It has no repository, storage, FastAPI, TTS SDK, HTTP, filesystem,
  subprocess, or audio-encoder type in its contract.

Add `StubVoiceoverGenerator` under `backend/app/infrastructure/generation`, named
for symmetry with `StubClipDownloader` / `StubClipRetrievalProvider` (it stands
in for an absent real TTS integration). Its algorithm for each segment:

1. Copy `scene_id` and `order_index` from the segment, set
   `narration_text = segment.narration`, and set
   `language = language or "en"` (defensive default; `run.language` already
   defaults to `"en"`).
2. Set `voice_id = "stub-narrator"`, `provider = "stub"`,
   `content_type = "audio/mpeg"`, `status = "available"`,
   `generation_reason = "deterministic_placeholder"`.
3. Set `duration_seconds = segment.target_duration_seconds`.
4. Derive a stable, run-scoped reference
   `audio_uri = f"memory://voiceovers/{run_id}/{order_index:04d}/{scene_id}.mp3"`,
   after validating the dynamic components (`run_id`, `scene_id`) with a tiny
   safe-segment helper **reimplemented locally** in the adapter. That helper
   rejects empty components, `.`/`..`, slashes, backslashes, drive-style `:`
   prefixes, and null bytes. It must **not** import the private
   `LocalFilesystemStorage._safe_component` or `StubClipDownloader._safe_component`.

**Duration estimate: use `target_duration_seconds`, not text length.** The stub
sets `duration_seconds = segment.target_duration_seconds` rather than estimating
from `len(narration)`. Three reasons:

1. In a voiceover B-roll product the narration is the spine and the B-roll is cut
   to it, so the timeline target *is* the narration's time budget. Using it keeps
   the voiceover duration consistent with the assembly plan (no contradictory
   durations float around the run).
2. It is already deterministically computed upstream, so it needs no arbitrary
   words-per-second constant. A text-length estimate would only *fake* realism --
   there is no real TTS here to validate it against -- while adding a magic
   number.
3. It degrades gracefully: the real-TTS phase replaces this estimate with the
   actual synthesized audio length, at which point any divergence between spoken
   length and timeline slot becomes a real (deferred) trim/pad decision rather
   than a property of a fake estimate.

The text-length alternative is recorded in Open Questions. The adapter is pure
and repeatable: same inputs produce equal outputs. It performs no randomness,
ranking, scoring, network request, audio probe, file access, subprocess call,
TTS call, or audio encoding. Empty plans never reach it (the use-case calls it
per segment, so a plan with no segments yields an empty manifest with no
generator calls).

### D42. `GenerateVoiceover` composes the latest assembly-plan read; creation kept internal; generate-only public API

`GenerateVoiceover` receives only `run_id` from the API. It composes:

- `RunRepository` for the D39 guard (and to read `run.language`).
- `GetLatestVideoAssemblyPlan` for the immediate upstream timeline artifact.
- `VoiceoverGenerator` for the pure per-segment mapping policy.
- `CreateVoiceover` for guarded persistence and versioning.

Execution order is locked:

1. Require the run and check `RunStatus.SCENES_APPROVED`.
2. Read the latest video assembly plan.
3. For each segment, in plan (`order_index`) order, call
   `voiceover_generator.generate(run_id, segment, run.language)` and collect the
   result.
4. Persist through `CreateVoiceover` with `source = "generated"` and provenance
   metadata (`video_assembly_plan_asset_id`, `video_assembly_plan_version`,
   `language`).

This ordering produces the intended errors: a missing run raises
`RunNotFoundError`; an invalid status raises
`AssetCreationRejectedError(VOICEOVER)` before the read (HTTP 409, not a
dependency 404); a missing assembly plan naturally raises
`AssetNotFoundError(VIDEO_ASSEMBLY_PLAN)` (HTTP 404).

- `CreateVoiceover` is the internal guarded persistence use-case. It accepts
  caller-supplied `VoiceoverSegment` entries, computes the next `VOICEOVER`
  version, writes JSON through `StoragePort`, sets `source`/provenance metadata,
  and saves the asset index. It owns the canonical D39 status guard, defaults
  `source = "manual"`, and never transitions the run. Constructor dependencies are
  ports/factories only: `RunRepository`, `VersionedAssetRepository`, `StoragePort`,
  and optional `asset_id_factory`.
- Expose only:
  - `POST /runs/{run_id}/voiceovers/generate`
  - `GET /runs/{run_id}/voiceovers`
  - `GET /runs/{run_id}/voiceovers/latest`
- Do not expose a manual `POST /runs/{run_id}/voiceovers` for caller-supplied
  records. Keeping creation internal avoids accepting arbitrary audio references,
  narration overrides, or generation statuses before any validation or synthesis
  semantics exist. Adding the manual route later is a trivial, symmetric one-route
  change.

`GenerateVoiceover` does not read the scene table: the narration it needs is
already on each `VideoAssemblySegment`. Its four constructor dependencies mirror
`DownloadClips` exactly (run repository, generation port, the one latest-read it
needs, and the sibling create use-case).

### D43. Storage and path convention; language threading; no-overwrite via versioning and scoped paths

- Store each manifest as JSON bytes through `StoragePort`, indexed under
  `(run_id, AssetKind.VOICEOVER)`. Use private application helpers
  `_voiceover_segments_to_bytes` / `_voiceover_segments_from_bytes`, mirroring
  `_downloaded_clips_to_bytes` / `_downloaded_clips_from_bytes`: a JSON list of
  flat objects; `duration_seconds` round-trips as `float`, `order_index` as
  `int`, and the remaining fields as `str`.
- Store `source` and provenance in `VersionedAsset.metadata`:
  `video_assembly_plan_asset_id`, `video_assembly_plan_version` (string, because
  `metadata` is `Mapping[str, str]`), and `language` (the run language). The
  per-segment `voice_id`/`provider` are not hoisted to manifest metadata in this
  foundation -- they live on every parsed segment and are queryable from
  `Voiceover.segments`. This keeps `GenerateVoiceover` decoupled from the
  generator's voice identity and avoids an empty-plan edge case (a plan with no
  segments has no voice to record). Hoisting uniform `voice_id`/`provider` to
  manifest metadata later, by reading the first segment, is a trivial additive
  change (Open Questions).
- **Language threading.** The voiceover language is read once from `run.language`
  in `GenerateVoiceover`, passed into every `generate(...)` call, stamped onto
  every `VoiceoverSegment.language`, and recorded once at manifest level. No new
  request body or run field is introduced; the existing intake language flows
  through. The stub's `language or "en"` default is a defensive guard only.
- The audio reference is deterministic and run-scoped:
  `audio_uri = memory://voiceovers/{run_id}/{order_index:04d}/{scene_id}.mp3`.
  The `voiceovers/` prefix and the run/order/scene scoping guarantee two distinct
  timeline positions never share a reference.
- **Avoiding overwrites.** Each `GenerateVoiceover` call creates a new, immutable
  `VOICEOVER` version; prior versions are never mutated -- the same append-only
  guarantee as every other asset phase. Because this foundation writes no audio
  bytes, there is nothing else to overwrite. When a future real-TTS phase
  materializes audio (into `VOICE` via `TTSProvider`), it must version-scope the
  audio directory under `data/audio/...` so a re-generate writes fresh files
  rather than clobbering a prior version's audio; that byte-level no-clobber rule
  is deferred with audio materialization and flagged in Open Questions.

## Domain Model Proposal

- Add `AssetKind.VOICEOVER = "voiceover"`.
- Add and export frozen `VoiceoverSegment` with exactly the D40 fields, next to
  `DownloadedClip` and `VideoAssemblySegment` in `backend/app/domain/models.py`
  and `backend/app/domain/__init__.py`.
- Do not change `VideoAssemblySegment`, `DownloadedClip`, `SelectedClip`,
  `SceneSpec`, `RenderSpec`, `RunStatus`, `AssetKind.VOICE`, the `TTSProvider`
  port, or run transition rules.
- Do not add audio bytes, absolute paths, codec/sample-rate/mix fields, or a
  domain set wrapper.
- Add `Voiceover` only as an application read model pairing a `VersionedAsset`
  with parsed records, defined in the new `voiceover_assets.py` and exported from
  `backend/app/application/use_cases/__init__.py`.

## Asset / Storage Decision

- Persist the voiceover set as JSON bytes through the existing `StoragePort` (no
  audio files). Index with `VersionedAssetRepository` under
  `(run_id, AssetKind.VOICEOVER)`. Metadata includes `source` (`"generated"` for
  `GenerateVoiceover`, default `"manual"` for a direct `CreateVoiceover` call),
  `video_assembly_plan_asset_id`, `video_assembly_plan_version`, and `language`.
- A second generate creates version 2 and leaves earlier manifests and their
  provenance intact.
- The only stored bytes are JSON metadata. `audio_uri` is a reference and is
  never opened. Existing generic SQLite, filesystem, and in-memory adapters
  require no code or schema change beyond accepting the new enum value naturally.
  No `.gitignore` change is required: `data/assets/voiceover/*` is already covered
  by `data/assets/*`, and the future real audio bytes are already covered by the
  existing `data/audio/*` ignore.

## Voiceover Generator Port Decision

- Add and export `VoiceoverGenerator` from the ports package
  (`backend/app/ports/providers.py`, `backend/app/ports/__init__.py`), separate
  from the reserved `TTSProvider`.
- Add and export `StubVoiceoverGenerator` from the generation adapter package
  (`backend/app/infrastructure/generation/__init__.py`).
- Add a recording `FakeVoiceoverGenerator` in `tests/fakes/providers.py` for
  use-case and API tests. It records `(run_id, segment, language)` calls and
  returns configured or default `VoiceoverSegment` records; those tests do not
  depend on the concrete adapter.
- Wire only the port into application/API code. The concrete adapter is imported
  only by `main.py` and its own adapter/confinement tests.
- Do not place the generator in `provider_registry.py`; direct composition-root
  wiring matches the current scene/stock/retrieval/selection/assembly/download
  pattern and avoids an unrelated registry refactor.

## Fake Generator Decision

- `StubVoiceoverGenerator` implements the D41 algorithm: one `VoiceoverSegment`
  per `VideoAssemblySegment`, `scene_id`/`order_index`/narration copied,
  `language` threaded in, `voice_id = "stub-narrator"`, `provider = "stub"`,
  `content_type = "audio/mpeg"`, `status = "available"`,
  `generation_reason = "deterministic_placeholder"`,
  `duration_seconds = segment.target_duration_seconds`, and a deterministic
  `memory://voiceovers/...` reference derived from `run_id`, `order_index`, and
  `scene_id`.
- It creates **no** audio files in this foundation: it is pure, returns records
  only, and touches no network, filesystem, subprocess, TTS SDK, or audio
  encoder. If a later decision adopts placeholder or real audio bytes, the bytes
  must be written by a use-case through a storage port (the existing `StoragePort`
  persists versioned assets only, so it would need a new media-object method or
  one `VOICE` `VersionedAsset` per file, produced via `TTSProvider`) -- never by
  the domain/application layers and never to an arbitrary path.

## Use-Case Plan

Create `backend/app/application/use_cases/voiceover_assets.py`, using
`downloaded_clip_assets.py` as the structural template.

1. **`CreateVoiceover`**
   - `execute(run_id, voiceover_segments, source="manual", asset_metadata=None) -> VersionedAsset`.
   - Requires the run, enforces D39, computes the next `VOICEOVER` version, merges
     `{"source": source}` with any provenance metadata, writes JSON through
     `StoragePort`, and saves the asset. Does not transition the run.
   - Constructor deps: `RunRepository`, `VersionedAssetRepository`, `StoragePort`,
     optional `asset_id_factory`.

2. **`GenerateVoiceover`**
   - `execute(run_id) -> VersionedAsset`.
   - Applies the D39 guard before the read, then follows the D42 order: read the
     latest assembly plan, call the generator once per segment in order with
     `run.language`, aggregate, and persist through `CreateVoiceover` with
     `source = "generated"` and assembly-plan + language provenance. Does not parse
     storage itself and does not transition the run.
   - Constructor deps: `RunRepository`, `VoiceoverGenerator`,
     `GetLatestVideoAssemblyPlan`, `CreateVoiceover`.

3. **`ListVoiceovers`**
   - `execute(run_id) -> Sequence[VersionedAsset]` via
     `asset_repository.list_for_run(run_id, AssetKind.VOICEOVER)`.

4. **`GetLatestVoiceover`**
   - `execute(run_id) -> Voiceover`.
   - Reads the latest asset, raises `AssetNotFoundError(VOICEOVER)` when absent,
     loads its JSON, and returns the parsed read model.

Export all four use-cases and `Voiceover` from
`backend/app/application/use_cases/__init__.py`.

## API Route Plan

Add response models and routes in the existing `backend/app/api/assets.py`
module, consistent with the existing long route names.

| Method | Path | Returns | Purpose |
| --- | --- | --- | --- |
| `POST` | `/runs/{run_id}/voiceovers/generate` | `201 AssetResponse` | Generate from the latest video assembly plan; persist a `VOICEOVER` asset (next version, `source=generated`). Applies the D39 rule. |
| `GET` | `/runs/{run_id}/voiceovers` | `list[AssetResponse]` | List voiceover asset versions. |
| `GET` | `/runs/{run_id}/voiceovers/latest` | `VoiceoverResponse` | Return the latest asset and parsed voiceover segments. |

Add `VoiceoverSegmentModel.from_domain`,
`VoiceoverResponse.from_voiceover`, and a `get_voiceover_generator(request)`
resolver reading `request.app.state.voiceover_generator`. The generate route has
no request body in this foundation (language comes from the run). Existing
application error handlers provide 404/409 behavior. There is no manual-create
request DTO, raw asset-byte endpoint, audio endpoint, or render endpoint.

## Composition Root Decision

- Add optional `voiceover_generator: VoiceoverGenerator | None = None` to
  `create_app(...)`, default it to `StubVoiceoverGenerator()`, and assign
  `app.state.voiceover_generator`, following the existing `clip_downloader` /
  `video_assembly_planner` wiring style.
- Keep all repository, storage, latest-reader, create-use-case, and generate
  use-case construction explicit in the route dependency functions, following the
  current asset API pattern.
- Do not alter `provider_registry.py`, settings, environment variables, secrets,
  or lifespan behavior. The default generator is pure and owns no resource, so it
  never affects the database/storage lifespan decision.

## Test Checklist

### Domain and Serialization

- `AssetKind.VOICEOVER.value == "voiceover"` and is distinct from `VOICE`,
  `DOWNLOADED_CLIPS`, `VIDEO_ASSEMBLY_PLAN`, `SUBTITLE`, and `RENDER`.
- `VoiceoverSegment` is frozen (assignment raises) and has exactly the D40 fields.
- JSON round-trip preserves all fields and numeric types (`duration_seconds` as
  `float`; `order_index` as `int`).
- Latest-read returns the newest parsed manifest; missing latest raises
  `AssetNotFoundError(VOICEOVER)`.

### Port and Adapter

- A fake satisfies runtime `isinstance(fake, VoiceoverGenerator)`; the port
  resolves to `backend.app.ports.providers`.
- `get_type_hints(VoiceoverGenerator.generate)` shows `run_id: str`,
  `segment: VideoAssemblySegment`, `language: str`, and `return: VoiceoverSegment`.
- `VoiceoverGenerator` is a different object from `TTSProvider`; the no-reuse
  decision is visible (separate protocol, separate port).
- `StubVoiceoverGenerator` is deterministic and repeatable: same inputs produce
  equal outputs.
- One `VoiceoverSegment` per segment; `scene_id`, `order_index`, and narration are
  copied correctly; `narration_text == segment.narration`.
- `voice_id == "stub-narrator"`, `provider == "stub"`,
  `content_type == "audio/mpeg"`, `status == "available"`,
  `generation_reason == "deterministic_placeholder"`.
- `duration_seconds == segment.target_duration_seconds`.
- `language` is the passed value; an empty language falls back to `"en"`.
- `audio_uri` starts with `memory://voiceovers/`, is relative (no `..`, no
  backslash, no drive-style prefix), and is derived from `run_id`/`order_index`/
  `scene_id`.

### Use-Cases and Lifecycle

- Create stores `VOICEOVER`, increments versions, and persists only JSON.
- `GenerateVoiceover` tags `source=generated` and includes
  `video_assembly_plan_asset_id`/`video_assembly_plan_version`/`language`;
  `CreateVoiceover` defaults `source=manual`.
- The status guard rejects every state except `scenes_approved` with
  `AssetCreationRejectedError(kind=voiceover)`, checked before the assembly-plan
  read and before generator/persistence work (409, not 404), persisting nothing.
- `RunNotFoundError` when the run is missing (generator not called).
- `GenerateVoiceover` calls the generator once per segment, in order, with the
  latest plan's segments and `run.language`, and aggregates every result.
- An empty latest plan (zero segments) yields an empty `VOICEOVER` manifest,
  never calls the generator, and leaves the run exactly `scenes_approved`.
- `GenerateVoiceover` fails naturally with
  `AssetNotFoundError(VIDEO_ASSEMBLY_PLAN)` when no plan exists (seed
  `scenes_approved` but no plan), persisting nothing.
- A run created with a non-`en` language (for example `"te"`) produces segments
  whose `language == "te"` and manifest metadata `language == "te"`, with **no**
  provider call.
- `ListVoiceovers` is version-ordered; a second generate creates version 2; the
  run stays exactly `scenes_approved` after create and generate.

### API

- `POST .../voiceovers/generate` returns 201 with `kind=voiceover`, `version=1`,
  `source=generated`, plan provenance, and `language`.
- `GET` list returns versions in order; `GET` latest returns parsed `segments`.
- 404 when the run is missing; 404 when no assembly plan exists; 409 when status
  is not `scenes_approved` (before any dependency 404); versioning across two
  generates.
- Only generate/list/latest routes exist; no manual create or audio route is
  registered.

### Architecture Boundaries and Fake-Only / No-Real-Audio Safety

- Domain auto-scan (`test_domain_has_no_framework_or_outer_layer_imports`)
  confirms no framework or outer-layer imports for the new domain code.
- Add `VoiceoverGenerator` to `test_provider_interfaces_live_in_ports`.
- Extend the asset-use-case hint map with `CreateVoiceover`
  (run/asset/storage + `asset_id_factory`), `ListVoiceovers` (asset repo), and
  `GetLatestVoiceover` (asset repo + storage); extend the generation-use-case hint
  map with `GenerateVoiceover` (`run_repository`, `voiceover_generator`,
  `get_latest_video_assembly_plan`, `create_voiceover`).
- Application auto-scan (`test_application_does_not_import_infrastructure`) and
  the API route scans (`test_assets_route_imports_use_cases_not_infrastructure`,
  `test_api_routes_depend_on_use_cases_not_infrastructure`) cover the new files.
- Extend `test_generation_adapters_import_no_api_application_or_external_modules`
  so its forbidden set also includes TTS/audio modules -- `elevenlabs`,
  `cartesia`, `sarvam`, `wave`, `audioop`, `pydub`, `soundfile` -- in addition to
  the existing `openai`/`anthropic`/`google`/`cohere`/`mistralai`/HTTP/subprocess/
  FFmpeg entries. This proves `StubVoiceoverGenerator` calls no real TTS provider
  and writes no audio.
- Add `test_stub_voiceover_generator_import_confined_to_composition_root` proving
  only `main.py` imports `StubVoiceoverGenerator`.
- Assert persisted bytes decode as JSON and contain no audio bytes; every
  `audio_uri` is a `memory://voiceovers/...` reference (none absolute or
  drive-style).
- Search the implementation diff for TTS SDKs, API-key handling, HTTP clients,
  audio encoders, FFmpeg/subprocess calls, audio probing, real/placeholder audio
  writes, subtitle generation, render calls, and status transitions; none should
  be present.

### End-to-End

Extend `tests/test_draft_planning_workflow.py` through:

```text
prompt -> script -> scene table -> stock plan -> clip candidates
       -> selected clips -> video assembly plan -> downloaded clips -> voiceover
```

After the download steps, assert `POST .../voiceovers/generate` returns 201
(`kind=voiceover`, `version=1`, `source=generated`, plan provenance,
`language=en`) and `GET .../voiceovers/latest` shows one segment per assembly
segment, in the same `order_index` order, with `narration_text` equal to the
segment narration, `duration_seconds` equal to the segment
`target_duration_seconds`, `language == "en"`, `voice_id == "stub-narrator"`,
`provider == "stub"`, every `audio_uri` starting `memory://voiceovers/`,
`status == "available"`, and the run still exactly `scenes_approved` (not
`rendered`, no transition).

## Implementation Slices

Implement one slice at a time in inward-to-outward order. Run focused tests after
each slice and the full suite after the final slice.

### Slice 1: Domain -- asset kind and record

- **Files:** `backend/app/domain/models.py`, `backend/app/domain/__init__.py`,
  new `tests/test_voiceover_segment.py`.
- **Change:** Add `AssetKind.VOICEOVER` and the frozen `VoiceoverSegment`
  dataclass/export (D38, D40). Leave `VOICE` untouched.
- **Tests:** Kind value/distinction (including distinct from `VOICE`), exact
  fields, frozen behavior.
- **Acceptance:** Domain tests and the domain boundary scan pass; no other layer
  changes.

### Slice 2: Port -- `VoiceoverGenerator`

- **Files:** `backend/app/ports/providers.py`, `backend/app/ports/__init__.py`,
  new `tests/test_voiceover_generator_port.py`.
- **Change:** Add/export the D41 runtime-checkable protocol, separate from
  `TTSProvider`.
- **Tests:** Runtime conformance against a fake, module location, exact type hints
  (`run_id: str`, `segment: VideoAssemblySegment`, `language: str`,
  `return: VoiceoverSegment`).
- **Acceptance:** Port tests and architecture tests pass.

### Slice 3: Deterministic adapter and test fake

- **Files:** new
  `backend/app/infrastructure/generation/stub_voiceover_generator.py`, generation
  package export, `tests/fakes/providers.py` (`FakeVoiceoverGenerator`), extended
  `tests/test_generation_adapters.py`.
- **Change:** Implement the D41 mapping (with the locally reimplemented
  `_safe_component`) and the recording fake.
- **Tests:** One record per segment, field copies, voice/provider/content-type,
  duration-equals-target, language threading + `"en"` default, `memory://`
  reference, relative path, repeatability, port conformance.
- **Boundary:** No application/API/external/TTS/audio imports.
- **Acceptance:** Focused adapter and (extended) generation-boundary tests pass.

### Slice 4: Application -- voiceover use-cases

- **Files:** new `backend/app/application/use_cases/voiceover_assets.py`,
  use-case package export, new `tests/test_voiceover_use_cases.py`.
- **Change:** Add the `Voiceover` read model, JSON helpers,
  create/generate/list/latest use-cases, D39 guard, D42 ordering, and
  language/plan provenance metadata.
- **Tests:** Versioning, round-trip, source/provenance/language metadata,
  latest/list, errors, guard-before-read, generator call-per-segment with
  `run.language`, no transition.
- **Boundary:** Dependencies are ports and sibling use-cases only.
- **Acceptance:** Focused use-case and application-boundary tests pass.

### Slice 5: API routes and composition wiring

- **Files:** `backend/app/api/assets.py`, `backend/app/main.py`, new
  `tests/test_voiceover_api.py`.
- **Change:** Add DTOs, generate/list/latest routes, the `get_voiceover_generator`
  resolver, the `voiceover_generator` `create_app` parameter, and the default
  `StubVoiceoverGenerator` wiring.
- **Tests:** 201/404/409, latest/list/versioning, route absence, injected fake,
  non-`en` language propagation.
- **Boundary:** Routes contain no generator, lifecycle, storage, or version logic;
  the concrete adapter appears only in the composition root.
- **Acceptance:** API and route-boundary tests pass.

### Slice 6: Boundary hardening, E2E, and phase audit

- **Files:** `tests/test_architecture_boundaries.py`,
  `tests/test_draft_planning_workflow.py`; `.gitignore` only if inspection finds a
  real gap (none expected).
- **Change:** Add `VoiceoverGenerator` to the port-location test, the three
  persistence/read use-cases to the asset-use-case hint map, `GenerateVoiceover`
  to the generation-use-case hint map, the `StubVoiceoverGenerator` confinement
  test, the extended TTS/audio forbidden-import set, and extend the full workflow.
- **Tests:** Focused architecture/E2E tests, then the full suite.
- **Acceptance:** Full suite and `git diff --check` pass; no generated audio,
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
both commands above before commit. Also inspect staged files to confirm no audio,
secrets, SQLite databases, caches, or virtual-environment files are included.

## Explicit Non-Goals / Deferred Work

- Real text-to-speech synthesis or any audio bytes, including from OpenAI TTS,
  ElevenLabs, Cartesia, Sarvam, or any other provider.
- API-key handling, HTTP clients (`httpx`/`requests`/`urllib`/`aiohttp`/`socket`),
  or any network I/O.
- Writing audio files of any kind in this phase, including placeholder audio
  bytes (deferred; if adopted later, written by a use-case through a storage port
  into the `VOICE` asset / `data/audio/...`, which may need a new media-object
  method).
- Materializing the per-file `VOICE` audio asset or registering it in the index;
  using or modifying the reserved `TTSProvider` port.
- Audio probing/inspection, sample rates, codecs, bitrates, byte ranges, or any
  audio analysis or encoding (`wave`/`pydub`/`soundfile`/`audioop`).
- FFmpeg, subprocess calls, mixing, ducking, normalization, alignment, or output
  files.
- Subtitles/captions or any subtitle generation, styling, or timing.
- Multi-speaker dialogue, actor dialogue, lip-sync, or per-speaker voice
  assignment.
- AI ranking, scoring, voice auto-selection, narration rewriting, or generation
  retry policy.
- Voiceover/voice-selection editing UI, frontend, or a manual public create route.
- Scene refinement or changes to script, scene, stock planning, candidate
  retrieval, selected-clip, video-assembly-plan, or downloaded-clip behavior.
- A new run status or any run transition.
- Provider registry refactoring, a generic pipeline orchestrator, workers, or
  queues.
- Redis, Postgres, S3, cloud/SaaS features, auth, or pagination.
- Database schema changes or a generic JSON schema/version registry.
- Byte-level no-clobber rules and absolute-path resolution (deferred with audio
  materialization).

## Open Questions

- **Per-segment vs per-scene granularity.** This foundation emits one
  `VoiceoverSegment` per `VideoAssemblySegment` (D40). When a scene spans multiple
  B-roll segments, that records the same narration on several records, which a
  naive synthesis phase could speak multiple times. The current one-clip-per-scene
  flow never triggers this, so it is harmless today. When real TTS lands, resolve
  it by either (a) synthesizing once per distinct `(scene_id, narration_text)` and
  reusing the audio across that scene's segments, or (b) switching the manifest to
  one record per scene. The `scene_id` field is retained precisely so either path
  is additive and needs no manifest reshape.
- **Duration source.** The stub sets `duration_seconds = target_duration_seconds`
  (D41). The alternative -- estimating from narration length via a
  words/characters-per-second constant -- is rejected for the foundation because
  it fakes realism without a real TTS to validate against. When real synthesis
  exists, the actual audio length replaces the estimate, and any mismatch between
  spoken length and the timeline slot becomes a real trim/pad/stretch decision for
  the renderer -- deliberately not decided here.
- **Voice/provider as run or request settings.** `voice_id` and `provider` are
  stub-fixed (`"stub-narrator"`/`"stub"`). A later phase must decide whether they
  become request fields, run settings, or a richer voice profile (and whether to
  hoist the uniform values into manifest metadata) before supporting per-run voice
  choice. No voice-profile model is added now.
- **Audio bytes and `VOICE` materialization.** This foundation is metadata-only.
  A real-TTS phase will call `TTSProvider` (or a new generator) to synthesize each
  segment's audio, store it as a `VOICE` `VersionedAsset` under `data/audio/...`,
  and point each `audio_uri` at the materialized object. The contract (stable
  run-scoped, order-indexed audio references plus durable narration/language/voice
  metadata) is designed so that change is additive.
- **Byte-level no-clobber.** When real/placeholder audio is written, the audio
  directory must be version-scoped so re-generates do not overwrite a prior
  manifest version's audio. Deferred until audio materialization exists.
