# OpenVidAgent Agent Instructions

OpenVidAgent is an open-source, local-first AI video orchestration agent.

It is not a foundation video model. It is an orchestration workflow:

prompt/script → script approval → scene table → stock clips → voice → subtitles → FFmpeg render → scene-level refinement.

## Architecture Rule

Preserve this architecture:

API/UI → application use-cases → domain models/services → ports/interfaces → infrastructure adapters.

## Layer Rules

### Domain

Allowed:

* dataclasses
* enums
* value objects
* pure domain services
* domain errors
* lifecycle rules

Forbidden:

* FastAPI
* SQLite
* filesystem adapter imports
* provider SDK imports
* infrastructure imports
* API imports
* application imports

### Application

Allowed:

* use-cases
* orchestration of domain behavior
* use of ports/interfaces
* application errors

Forbidden:

* concrete SQLite repositories
* concrete filesystem storage
* provider SDK calls
* FastAPI imports
* direct media generation
* direct subprocess/FFmpeg calls

### Ports

Allowed:

* Protocol/interface definitions

Forbidden:

* infrastructure imports
* concrete adapter knowledge

### Infrastructure

Allowed:

* SQLite repositories
* local filesystem storage
* provider adapters
* FFmpeg adapter later
* implementations of ports

### API

Allowed:

* FastAPI routes
* request/response DTOs
* HTTP error mapping
* calling application use-cases

Forbidden:

* lifecycle transition rules
* direct domain mutation
* concrete SQLite repository imports in route modules
* provider/media orchestration

### Composition Root

backend/app/main.py may wire concrete infrastructure.

Keep this wiring explicit and small.

## Current Product Scope

V1 includes:

* Voiceover B-roll only
* Local-first operation
* BYO-key
* FastAPI backend
* SQLite
* Local filesystem storage
* Provider plugin architecture
* Script approval
* Scene table approval
* FFmpeg render later

V1 excludes unless explicitly requested:

* actor dialogue
* lip-sync
* AI video generation
* Redis
* Postgres
* S3
* SaaS features
* frontend
* background worker system
* full generic pipeline orchestrator

## Development Rules

Before implementing a large task:

1. Restate the requested phase.
2. Create a checklist.
3. Split the phase into small slices.
4. Implement one slice at a time.
5. Run focused tests after each slice.
6. Do not expand scope.

For every slice, report:

* files changed
* tests added
* tests run
* validation result
* architecture boundaries checked
* remaining checklist items

## Testing Rules

Prefer:

* domain unit tests
* use-case tests with fake repositories/adapters
* repository tests with temporary SQLite
* storage tests with temporary directories
* API tests with injected fake/test dependencies
* architecture boundary tests

Do not remove or weaken boundary tests.

## Common Commands

Install:

pip install -e ".[dev]"

Run tests:

python -m pytest

If python is not on PATH on Windows, try:

.\.venv\Scripts\python.exe -m pytest

If the venv launcher is broken, report the exact failure and the available working Python command.

## Git / Commit Rules

Do not commit automatically unless explicitly asked.

Before suggesting a commit:

* run tests or report why they could not run
* run git diff --check if available
* confirm no generated media, secrets, SQLite files, cache files, or venv files are staged
* summarize changed files

## Out-of-Scope Guard

Do not add these unless explicitly requested:

* Pexels
* Edge TTS
* Sarvam
* ElevenLabs
* FFmpeg execution
* subtitles
* frontend
* background workers
* full pipeline orchestrator
* cloud storage
* Redis/Postgres
* AI video generation
* actor dialogue
* lip-sync

## Review Checklist

Before finishing any implementation, check:

* Domain remains framework-free.
* Application does not import infrastructure.
* API routes call use-cases only.
* Infrastructure implements ports.
* main.py is the only place wiring concrete adapters when possible.
* Tests cover valid and invalid paths.
* Scope did not expand.
