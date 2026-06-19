# OpenVidAgent

OpenVidAgent is an open-source, local-first AI video agent.

## Development Setup

OpenVidAgent declares support for Python 3.11 and newer. Windows local development is currently standardized on Python 3.12 because the test suite is validated there.

Check the available Python interpreters:

```powershell
py -0p
py -3.12 --version
```

If the Python launcher cannot find Python 3.12, install Python 3.12 from python.org and check the common per-user install path:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" --version
```

If `.venv` points at a missing Python install, recreate it instead of repairing it in place:

```powershell
Remove-Item -Recurse -Force .\.venv
py -3.12 -m venv .venv
```

If `py -3.12` is not available but the per-user Python install exists, create the venv with the explicit interpreter path:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
```

Install runtime and test dependencies from the project metadata:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Run the test suite with the venv interpreter:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

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

This avoids a monolithic pipeline by keeping orchestration separate from provider implementations. A use-case can ask a `ScriptDraftGenerator` for a script draft, a `SceneTablePlanner` for a scene table, a `StockProvider` for clips, a `TTSProvider` for voice, a `SubtitleBuilder` for captions, and a `Renderer` for final output without importing concrete SDKs or tools. Providers stay replaceable plugins behind interfaces, jobs remain durable units of work, assets are versioned, and the renderer receives an explicit `RenderSpec` instead of hidden shared state.

See [docs/architecture/high-level-design.md](docs/architecture/high-level-design.md) and [docs/architecture/solid-design-rules.md](docs/architecture/solid-design-rules.md).

### Architecture Tests

The `tests/` suite includes source-level boundary checks so the domain stays framework-free, application use-cases do not import concrete infrastructure, and API routes call application use-cases instead of providers directly. Fake providers in `tests/fakes/` implement the production ports to prove integrations can be substituted before real provider plugins are added.
