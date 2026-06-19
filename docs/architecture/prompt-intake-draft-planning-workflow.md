# Prompt Intake and Draft Planning Workflow

Design document for the next phase. This records the intended design and slice
plan before any code is written. No backend, test, or product implementation is
part of this document.

All design decisions below are accepted and locked in. D1 (port topology) and
D2 (generation trigger) were finalized after review; the slice plan reflects the
accepted decisions.

## Goal

Make OpenVidAgent accept a user prompt and produce script and scene draft assets
through ports and deterministic fakes/adapters, with no real external providers.
The existing run lifecycle, asset use-cases, and asset routes stay in place; this
phase adds prompt intake fields and two thin generation use-cases that turn a
prompt into a script draft and an approved script into a scene table.

## Target Workflow

The lifecycle maps to explicit HTTP calls (accepted trigger shape, D2):

```
POST /runs {prompt, title, language}        -> create Run            status: created
POST /runs/{id}/script-drafts/generate      -> GenerateScriptDraft   status: script_ready
POST /runs/{id}/approve-script              -> ApproveScript         status: script_approved
POST /runs/{id}/scene-tables/generate       -> GenerateSceneTable    status: scenes_ready
POST /runs/{id}/approve-scenes              -> ApproveScenes         status: scenes_approved
```

Generation is additive. The existing manual endpoints
(`POST /runs/{id}/script-drafts {text}` and `POST /runs/{id}/scene-tables {scenes}`)
remain for manual entry/override.

## Architecture Rule

Dependencies point inward:

`API/UI -> application use-cases -> domain models/services -> ports/interfaces -> infrastructure adapters`

The domain layer does not import FastAPI, databases, HTTP clients, SDKs, or
concrete providers. Generation, versioning, and lifecycle/transition rules live
in application and domain, never in API routes.

## Existing Foundation

This phase builds on code that already exists; the brief partly overlaps it:

- `Run.prompt` is already a required domain field, and `POST /runs {prompt}`
  already works. Only `title` and `language` are missing
  (`domain/models.py`, `api/runs.py`).
- `LLMProvider` already exists with the exact two methods this phase proposes:
  `draft_script(prompt) -> str` and
  `build_scene_table(approved_script) -> Sequence[SceneSpec]`
  (`ports/providers.py`). See D1.
- `FakeLLMProvider` already implements both deterministically
  (`tests/fakes/providers.py`).
- The full status lifecycle already exists with transition rules:
  `created -> script_ready -> script_approved -> scenes_ready -> scenes_approved`
  (`domain/models.py`).
- `CreateScriptDraft(run_id, text)` and `CreateSceneTable(run_id, scenes)`
  already persist a versioned asset and apply the D7 transition rules
  (`script_assets.py`, `scene_assets.py`). Generation use-cases compose these
  rather than replacing them.
- `Run.approved_script` already carries the approved script text, so scene
  generation reads it from the aggregate (no storage round-trip required).
- Architecture boundary tests already scan `application` and `api` imports, so
  new files in those layers inherit forbidden-import coverage automatically.

## Design Decisions

### D1. Generation port topology

`LLMProvider` already bundles both generation methods. Accepted decision: split
it into two single-capability ports and retire `LLMProvider`.

- Define `ScriptDraftGenerator` with `generate(prompt, language) -> str`.
- Define `SceneTablePlanner` with
  `plan(approved_script, language) -> Sequence[SceneSpec]`.
- Both methods include `language` (see D4).
- Retire `LLMProvider`: it has no production implementation yet, so the
  retirement is mechanical and touches roughly six files: `ports/providers.py`,
  `ports/__init__.py`, `config/provider_registry.py`,
  `tests/fakes/providers.py` (+ `tests/fakes/__init__.py`),
  `tests/test_provider_substitution.py`, `tests/test_architecture_boundaries.py`.

Rationale: two single-capability ports give clean Dependency-Inversion and
Interface-Segregation per use-case and align with the existing one-method port
suite (`StockProvider`, `TTSProvider`, `SubtitleBuilder`, `Renderer`). Reusing
the two-method `LLMProvider`, or keeping it alongside the new ports, was
rejected as a weaker Interface-Segregation fit and redundant.

### D2. Generation trigger and API shape

Accepted decision: use separate explicit generation endpoints.

- `POST /runs/{run_id}/script-drafts/generate` and
  `POST /runs/{run_id}/scene-tables/generate` trigger generation (see Target
  Workflow).
- `POST /runs` stays pure intake: it creates a run in `created` status and does
  not auto-generate.
- Generation is never triggered implicitly inside `POST /runs` or inside
  `approve-script`.

Rationale: explicit endpoints mirror the existing one-use-case-per-route pattern
and the human-in-the-loop approval steps, and keep each step independently
testable. Auto-generating inside `POST /runs` or `approve-script` was rejected as
more coupled and less controllable.

### D3. Default deterministic adapters

- Provide concrete, deterministic implementations of the generation ports in
  `backend/app/infrastructure/generation/` (for example `EchoScriptDraftGenerator`
  and `StubSceneTablePlanner`) and wire them as the default in `main.py`, so the
  default app generates with no external calls.
- Keep the lighter `tests/fakes` implementations for use-case unit tests.
- Production defaults are not named "Fake"; concrete names are negotiable.

### D4. Language in port signatures

- Include `language` now: `generate(prompt, language) -> str` and
  `plan(approved_script, language) -> Sequence[SceneSpec]`, so the intake field
  threads through to generation (downstream voice/subtitles need it).
- The deterministic adapters may record `language` in asset metadata so it is
  observable and testable.

### D5. Run intake fields and asset provenance

- Add `title: str | None` (optional) and `language: str` (default `"en"`) to the
  domain `Run`, the `runs` schema, the SQLite run repository, `CreateRun`, and
  the run API request/response models. `prompt` already exists.
- Tag generated assets with `metadata={"source": "generated"}` to distinguish
  them from the existing manual assets (`"source": "manual"`). This is done by
  adding an optional `source` parameter (default `"manual"`) to
  `CreateScriptDraft.execute` / `CreateSceneTable.execute`, which the generation
  use-cases pass as `"generated"`.

### D6. Schema migration stance

- `schema.sql` uses `CREATE TABLE IF NOT EXISTS`, so adding `title`/`language`
  columns does not alter a pre-existing local `data/openvidagent.sqlite`. Tests
  use fresh temporary databases and are unaffected.
- For local development the existing dev database should be deleted to pick up
  the new columns (it is gitignored). No formal migration system is in scope for
  this phase.

## API Route Plan

New routes for this phase (explicit, long route names, consistent with the
existing asset routes):

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/runs/{run_id}/script-drafts/generate` | Generate a script draft from the run prompt via `ScriptDraftGenerator`; applies the D7 script rule; run becomes `script_ready`. |
| `POST` | `/runs/{run_id}/scene-tables/generate` | Generate a scene table from the approved script via `SceneTablePlanner`; applies the D7 scene rule; run becomes `scenes_ready`. |

Reused, unchanged routes: `POST /runs` (now also accepts `title`/`language`),
`POST /runs/{id}/approve-script`, `POST /runs/{id}/approve-scenes`, the existing
manual `POST`/`GET` script-draft and scene-table routes, and `GET /runs/{id}`.

## Planned Slices

Implement one slice at a time, run tests after each, and review at the
checkpoints below. Slice order is strictly sequential: intake fields first
(generation reads `prompt`/`language` off the run), then port contracts, then
adapters, then the script use-case, then the scene use-case (which needs an
approved script), then API plus wiring, then end-to-end hardening.

### Slice 1: Run intake fields (title + language)

- **Goal:** `POST /runs` accepts and persists `prompt` (exists), `title`, and
  `language`; the run still starts `created`.
- **Files likely to change:**
  - `backend/app/domain/models.py` (`Run` gains `title`/`language`;
    `_transition_to` carries them over).
  - `backend/app/infrastructure/db/schema.sql` (add `title`, `language` columns).
  - `backend/app/infrastructure/db/sqlite_run_repository.py`
    (`SELECT`/`INSERT`/`_row_to_run`).
  - `backend/app/application/use_cases/run_lifecycle.py`
    (`CreateRun.execute(prompt, title, language)`).
  - `backend/app/api/runs.py` (`CreateRunRequest`, `create_run`, `RunResponse`).
- **Tests to add:** `Run` holds `title`/`language` and transitions preserve them;
  SQLite run-repository round-trip including the new fields; `CreateRun` sets the
  fields and defaults `language`; `POST /runs` echoes `title`/`language`;
  omitting `language` yields `"en"`.
- **Architecture boundaries at risk:** domain stays framework-free (no new outer
  imports); SQL stays confined to the repository; the API computes nothing.
- **Out of scope:** generation, ports, providers.
- **Acceptance criteria:** `POST /runs {prompt, title, language}` returns all
  three with `status: created`; omitting `language` returns `"en"`; full suite
  green.

### Slice 2: Generation port topology (split; retire LLMProvider) [D1]

- **Goal:** two single-capability generation ports exist and `LLMProvider` is
  removed cleanly.
- **Files likely to change:**
  - `backend/app/ports/providers.py` (define `ScriptDraftGenerator` and
    `SceneTablePlanner` `@runtime_checkable` Protocols with a `language`
    parameter; remove `LLMProvider`).
  - `backend/app/ports/__init__.py` (exports).
  - `backend/app/config/provider_registry.py` (replace `llm` / `require_llm`
    with `script_generator` / `scene_planner` and their requires).
  - `tests/fakes/providers.py` and `tests/fakes/__init__.py` (split
    `FakeLLMProvider` into `FakeScriptDraftGenerator` and
    `FakeSceneTablePlanner`).
  - `tests/test_provider_substitution.py`,
    `tests/test_architecture_boundaries.py`
    (the `test_provider_interfaces_live_in_ports` tuple).
- **Tests to add:** both new ports resolve to `backend.app.ports.providers`; each
  fake satisfies `isinstance` against its port; the substitution test is updated.
- **Architecture boundaries at risk:** ports import only `domain` and `typing`
  (no infrastructure); no dangling `LLMProvider` reference remains anywhere.
- **Out of scope:** use-cases, adapters, real providers.
- **Acceptance criteria:** `LLMProvider` is gone repo-wide; both ports defined;
  registry, fakes, and boundary tests updated; suite green.

### Slice 3: Deterministic default adapters [D3]

- **Goal:** concrete, deterministic implementations of both ports for the default
  app, with no external calls.
- **Files likely to change:**
  - `backend/app/infrastructure/generation/__init__.py`
  - `backend/app/infrastructure/generation/echo_script_draft_generator.py`
    (`EchoScriptDraftGenerator` implements `ScriptDraftGenerator`).
  - `backend/app/infrastructure/generation/stub_scene_table_planner.py`
    (`StubSceneTablePlanner` implements `SceneTablePlanner`).
- **Tests to add:** `tests/test_generation_adapters.py`: determinism (same input
  yields same output); `isinstance` against the ports; a boundary assertion that
  `infrastructure/generation` imports only `domain`/`ports`/stdlib (no `api`,
  no `application`, no provider SDK, no network/FFmpeg).
- **Architecture boundaries at risk:** infrastructure implements ports and must
  not import API or application; no provider SDKs or media tooling.
- **Out of scope:** real LLM, the use-cases, API, wiring.
- **Acceptance criteria:** both adapters deterministically turn prompt into a
  script and a script into scenes (carrying `language`); boundary tests green.

### Slice 4: GenerateScriptDraft use-case

- **Goal:** generate a script draft from `run.prompt`/`run.language` via the port,
  then persist and transition to `script_ready`.
- **Files likely to change:**
  - `backend/app/application/use_cases/script_assets.py` (add
    `GenerateScriptDraft(run_repository, script_generator, create_script_draft)`;
    add an optional `source="manual"` parameter to `CreateScriptDraft.execute`).
  - `backend/app/application/use_cases/__init__.py` (export).
- **Tests to add:** `tests/test_generate_script_draft.py` using fakes: generates
  from `prompt`/`language`, persists a `SCRIPT` asset tagged `source=generated`,
  transitions `created -> script_ready`; `RunNotFoundError` on an unknown run;
  the D7 guard (delegated to `CreateScriptDraft`) is respected.
- **Architecture boundaries at risk:** application depends on `RunRepository` and
  `ScriptDraftGenerator` ports (use-case-to-use-case composition with
  `CreateScriptDraft` is allowed; no infrastructure import); transition logic
  stays in application/domain.
- **Out of scope:** API, scene generation, real LLM.
- **Acceptance criteria:** the use-case yields `script_ready` plus a `SCRIPT`
  asset (`source=generated`) using fakes.

### Slice 5: GenerateSceneTable use-case

- **Goal:** plan a scene table from `run.approved_script`/`run.language` via the
  port, then persist and transition to `scenes_ready`.
- **Files likely to change:**
  - `backend/app/application/use_cases/scene_assets.py` (add
    `GenerateSceneTable(run_repository, scene_planner, create_scene_table)`; add
    an optional `source` parameter to `CreateSceneTable.execute`).
  - `backend/app/application/use_cases/__init__.py` (export).
- **Tests to add:** `tests/test_generate_scene_table.py` using fakes: plans from
  `approved_script`/`language`, persists a `SCENE_TABLE` asset tagged
  `source=generated`, transitions `script_approved -> scenes_ready`; rejects when
  `approved_script` is `None`; `RunNotFoundError` on an unknown run; the D7 guard
  is respected.
- **Architecture boundaries at risk:** application depends on `RunRepository` and
  `SceneTablePlanner` ports (and `CreateSceneTable`); no infrastructure import;
  transitions stay in application/domain.
- **Out of scope:** API, real LLM.
- **Acceptance criteria:** the use-case yields `scenes_ready` plus a
  `SCENE_TABLE` asset (`source=generated`) using fakes.

### Slice 6: Generate endpoints + composition wiring [D2]

- **Goal:** expose generation over HTTP; the default app wires the deterministic
  adapters; tests can inject fakes.
- **Files likely to change:**
  - `backend/app/api/assets.py` (add `POST /runs/{id}/script-drafts/generate` and
    `POST /runs/{id}/scene-tables/generate`; add `app.state` getters for the
    generator and planner).
  - `backend/app/main.py` (extend `create_app(..., script_generator=None,
    scene_planner=None)`; default to `EchoScriptDraftGenerator` /
    `StubSceneTablePlanner`; set them on `app.state`; preserve the
    injected-fakes-skip-disk behavior).
  - `backend/app/api/errors.py` (map any new precondition error, for example
    approved-script-missing, to a 409).
- **Tests to add:** `tests/test_generation_api.py` using `TestClient` with an
  injected fake generator/planner and `InMemoryRunRepository`: both generate
  endpoints return the expected payloads and statuses; a boundary assertion that
  the router imports use-cases not infrastructure; a composition test that
  injected fakes are used and do not trigger extra disk/DB initialization.
- **Architecture boundaries at risk:** routes call use-cases only (no transition,
  versioning, or generation logic, no concrete-adapter imports); `main.py`
  remains the sole wiring point; the injected-fakes-skip-disk invariant holds.
- **Out of scope:** real providers, frontend, raw byte streaming/download.
- **Acceptance criteria:** the default app drives the whole
  `created -> ... -> scenes_approved` flow over HTTP using the stub adapters, and
  the injected-fakes path works without touching disk.

### Slice 7: End-to-end test + boundary hardening + phase audit

- **Goal:** lock the full workflow and the new boundaries into the safety net and
  confirm hygiene before commit.
- **Files likely to change:**
  - `tests/test_draft_planning_workflow.py` (new end-to-end happy-path test).
  - `tests/test_architecture_boundaries.py` (extend for the new ports,
    use-cases, and adapters).
- **Tests to add:** one end-to-end path (`POST /runs` -> generate script ->
  approve -> generate scenes -> approve) asserting statuses, asset versions,
  `source=generated`, and that only stubs/fakes are exercised (no real provider);
  boundary assertions that the new use-cases depend only on port types, the
  generation adapters import no `api`/`application`, and `run_id` is still absent
  from `VersionedAsset`. Optional, per the earlier review follow-up: add
  `pathlib`/`os` and provider-SDK names to the domain forbidden-import set.
- **Architecture boundaries at risk:** this slice is the safety net; guard against
  infrastructure leaking into application/api and against generated artifacts
  being tracked.
- **Out of scope:** everything in the phase-wide out-of-scope list below.
- **Acceptance criteria:** every slice's acceptance criteria hold; the full suite
  is green; phase-auditor criteria (scope, boundaries, git hygiene) satisfied.

## Agent Checkpoints

- **architecture-reviewer after Slice 3:** highest-risk structural change (the
  new ports plus the `LLMProvider` retirement and the first concrete generation
  adapters); verify ports import domain only and infrastructure depends only on
  domain/ports.
- **architecture-reviewer after Slice 5:** both generation use-cases present;
  confirm the application depends only on ports, generation/transition logic is
  not in routes, and the use-cases compose `Create*` cleanly.
- **architecture-reviewer after Slice 6:** routes plus composition root; confirm
  routes call use-cases only, `main.py` is the sole infrastructure wiring point,
  and the injected-fakes-skip-disk invariant holds.
- **test-debugger:** only when tests fail non-obviously (likely spots: Slice 2
  removing `LLMProvider` rippling through substitution/boundary/fakes, and
  Slice 6 `TestClient` dependency wiring).
- **phase-auditor before commit at Slice 7:** verify all acceptance criteria, the
  full suite is green, and database/secrets/generated media/cache files are
  ignored (and `data/assets/.gitkeep` stays trackable).

## Phase-Wide Out of Scope

Not implemented in this phase:

- Real LLM calls, OpenAI, Claude API, Gemini, Pexels, Edge TTS, Sarvam,
  ElevenLabs, FFmpeg.
- Stock search, subtitles, background workers, frontend.
- Full pipeline orchestrator, AI video generation, actor dialogue, lip-sync.
- Per-scene relational rows.
- Revision-after-approval for scripts or scene tables.
- Pagination, auth, raw byte streaming/download.
