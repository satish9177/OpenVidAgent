# OpenVidAgent

OpenVidAgent is an open-source, local-first AI video agent.

## Architecture

The V1 architecture is a small Clean Architecture skeleton for the flow:

`prompt/script -> script approval -> scene table -> stock clips -> voice -> subtitles -> FFmpeg render`

The code is split into stable layers:

- `backend/app/domain` contains pure video workflow concepts such as jobs, versioned assets, scenes, and `RenderSpec`.
- `backend/app/application` is reserved for use-cases that orchestrate the V1 workflow.
- `backend/app/ports` defines provider and persistence protocols.
- `backend/app/infrastructure` is where local adapters and provider plugins implement ports.
- `backend/app/api` is for thin HTTP routes that call use-cases only.
- `backend/app/config` is for composition and runtime settings.

This avoids a monolithic pipeline by keeping orchestration separate from provider implementations. A use-case can ask an `LLMProvider` for a script, a `StockProvider` for clips, a `TTSProvider` for voice, a `SubtitleBuilder` for captions, and a `Renderer` for final output without importing concrete SDKs or tools. Providers stay replaceable plugins behind interfaces, jobs remain durable units of work, assets are versioned, and the renderer receives an explicit `RenderSpec` instead of hidden shared state.

See [docs/architecture/high-level-design.md](docs/architecture/high-level-design.md) and [docs/architecture/solid-design-rules.md](docs/architecture/solid-design-rules.md).

### Architecture Tests

The `tests/` suite includes source-level boundary checks so the domain stays framework-free, application use-cases do not import concrete infrastructure, and API routes call application use-cases instead of providers directly. Fake providers in `tests/fakes/` implement the production ports to prove integrations can be substituted before real provider plugins are added.
