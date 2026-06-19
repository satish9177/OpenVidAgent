# High-Level Design

OpenVidAgent V1 is a local-first AI video workflow:

`prompt/script -> script approval -> scene table -> stock clips -> voice -> subtitles -> FFmpeg render`

The first architecture goal is separation, not feature depth. The system should make it easy to replace providers, resume work, and inspect intermediate artifacts without turning the entire workflow into one large pipeline function.

## V1 Scope

Included:

- Draft a script from a prompt.
- Pause for script approval before downstream work.
- Convert the approved script into a scene table.
- Resolve stock clips for scenes.
- Generate voice.
- Build subtitles.
- Render with FFmpeg through a renderer port.

Excluded:

- Cinematic dialogue systems.
- Lip-sync.
- AI video generation.
- Redis, Postgres, S3, or hosted SaaS infrastructure.
- Multi-tenant SaaS concerns.

## Layers

| Layer | Path | Responsibility |
| --- | --- | --- |
| Domain | `backend/app/domain` | Pure workflow concepts such as runs, jobs, scenes, versioned assets, and render specs. |
| Application | `backend/app/application` | Use-cases that coordinate the V1 workflow through ports. |
| Ports | `backend/app/ports` | Protocols for providers, storage, queues, and repositories. |
| Infrastructure | `backend/app/infrastructure` | Local adapters and provider plugins that implement ports. |
| API | `backend/app/api` | Thin request/response entrypoints that call use-cases only. |
| Config | `backend/app/config` | Runtime settings and dependency composition. |

Dependencies point inward:

`api -> application -> ports -> domain`

`infrastructure -> ports`

The domain layer does not import FastAPI, databases, HTTP clients, SDKs, or concrete providers.

## Core Concepts

- `Run` represents one requested video workflow.
- `Job` is a durable unit of work that can be persisted, retried, or resumed.
- `VersionedAsset` represents an immutable asset reference with an explicit version.
- `SceneSpec` is a small domain object for the approved script's scene table.
- `RenderSpec` is the only object the renderer needs to produce the final video.

## Provider Model

Providers are plugins behind interfaces:

- `ScriptDraftGenerator`
- `SceneTablePlanner`
- `StockProvider`
- `TTSProvider`
- `SubtitleBuilder`
- `Renderer`

Use-cases depend on these protocols, never on concrete provider classes. Infrastructure modules may implement them using local tools, local models, or external SDKs later, but those choices stay outside orchestration.

## V1 Orchestration Shape

1. API receives a prompt and calls a script-drafting use-case.
2. The run stores the draft script as a versioned asset.
3. The user approves or edits the script.
4. A use-case builds the scene table from the approved script.
5. A use-case resolves stock clips per scene.
6. A use-case generates voice and subtitles.
7. A render use-case builds a `RenderSpec` and calls `Renderer.render`.
8. The rendered video is stored as a versioned asset.

Each step can be represented as a durable job so interrupted local runs can be inspected and resumed.
