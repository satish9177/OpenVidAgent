# OpenVidAgent Phase Control Skill

Use this skill when implementing or reviewing OpenVidAgent development phases.

OpenVidAgent is an open-source, local-first AI video orchestration agent.

It is not trying to beat Runway, Veo, or other foundation video models. It is a workflow/orchestration agent:

prompt/script → script approval → scene table → stock clips → voice → subtitles → FFmpeg render → scene-level refinement.

## Architecture Rule

All implementation must preserve this direction:

API/UI → application use-cases → domain models/services → ports/interfaces → infrastructure adapters.

## Hard Boundaries

Domain:

* Must be framework-free.
* Must not import FastAPI.
* Must not import SQLite.
* Must not import filesystem adapters.
* Must not import infrastructure.
* Must not import API.
* Must not know provider implementations.

Application:

* May orchestrate use-cases.
* Must depend on ports/interfaces.
* Must not import concrete SQLite repositories.
* Must not import concrete filesystem storage.
* Must not import FastAPI.
* Must not call provider SDKs directly.

Ports:

* Define interfaces/protocols.
* Must not import infrastructure.

Infrastructure:

* Implements ports.
* May know SQLite, local filesystem, provider SDKs, FFmpeg, and other concrete tools.

API:

* May know FastAPI.
* Must call application use-cases only.
* Must not contain lifecycle transition rules.
* Must not mutate domain models directly.
* Must not import concrete repositories, except composition wiring in main.py if explicitly required.

main.py / composition root:

* May wire concrete infrastructure adapters.
* May initialize database/storage dependencies.
* Should keep wiring explicit and small.

## Current V1 Scope

Allowed V1 direction:

* Voiceover B-roll only
* Local-first
* BYO-key
* FastAPI backend
* SQLite
* Local filesystem storage
* Provider plugin architecture
* Script approval
* Scene table approval
* Scene-level refinement later

Not in V1 foundation unless explicitly requested:

* Actor dialogue
* Lip-sync
* AI video generation
* Redis
* Postgres
* S3
* SaaS deployment
* Frontend
* Background worker system
* Generic full pipeline orchestrator

## Phase Loop Rules

Before coding a bigger phase:

1. Create a phase checklist.
2. Break the phase into small slices.
3. For each slice, state:

   * files likely to change
   * tests to add
   * architecture boundaries at risk
   * explicit out-of-scope items
4. Implement only one slice at a time.
5. Run tests after each slice where possible.
6. Report:

   * files changed
   * tests run
   * test result
   * completed checklist items
   * remaining checklist items
   * out-of-scope items avoided
   * architecture boundaries checked

Never implement a full large phase in one uncontrolled pass.

## Review Rules

After every one or two implementation slices:

* Use the architecture reviewer.
* Check imports and boundaries.
* Confirm application still depends on ports.
* Confirm API routes call use-cases only.
* Confirm no provider/media/frontend/full-pipeline logic was added accidentally.

Before commit:

* Run the phase auditor.
* Confirm all acceptance criteria.
* Confirm tests pass.
* Confirm generated media, secrets, DB files, and cache files are ignored.

## Testing Expectations

Prefer focused tests first:

* domain transition tests
* use-case tests with fakes
* repository tests with temporary SQLite
* API tests with TestClient and injected fake/test repository
* architecture boundary tests

Do not weaken tests to make implementation pass.
Do not delete boundary tests.
Do not skip tests unless explicitly justified.

## Output Format For Implementation Slices

At the end of each slice, report:

Files changed:
Tests added:
Validation run:
Validation result:
Architecture checks:
Out-of-scope avoided:
Remaining checklist:

## Output Format For Reviews

Return:

1. Boundary violations
2. SOLID/Clean Architecture concerns
3. Out-of-scope additions
4. Missing tests
5. Safe to continue: yes/no
