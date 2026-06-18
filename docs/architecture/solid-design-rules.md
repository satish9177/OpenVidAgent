# SOLID Design Rules

These rules keep OpenVidAgent small, local-first, and easy to extend.

## Single Responsibility

- API routes translate transport concerns and call use-cases only.
- Use-cases coordinate one workflow step or closely related group of steps.
- Domain objects model workflow state only.
- Infrastructure adapters handle provider SDKs, local tools, filesystems, and process execution.

## Open/Closed

- Add providers by implementing ports in `backend/app/infrastructure`.
- Do not change use-cases to support a new provider.
- Add new workflow capabilities as new use-cases and ports when they represent new behavior.

## Liskov Substitution

- Any implementation of `LLMProvider`, `StockProvider`, `TTSProvider`, `SubtitleBuilder`, or `Renderer` must be replaceable without changing use-case code.
- Provider methods should return domain objects, not provider-specific response types.

## Interface Segregation

- Keep ports small and task-focused.
- Do not create one large pipeline interface.
- Split provider capabilities when a consumer does not need all methods.

## Dependency Inversion

- Use-cases depend on ports and domain objects.
- Infrastructure implements ports.
- Concrete provider imports are not allowed inside orchestrators or use-cases.
- Domain imports must not include FastAPI, databases, HTTP clients, SDKs, or provider modules.

## Project Rules

- API routes call use-cases only.
- Use-cases depend on ports/interfaces.
- Infrastructure implements ports.
- Domain has no FastAPI, DB, HTTP, or provider imports.
- Providers are plugins behind interfaces.
- Renderer uses a `RenderSpec` object.
- Jobs are durable units of work.
- Assets are versioned.
- No concrete provider imports inside orchestrator/use-case code.

## Review Checklist

- Does the change preserve the dependency direction?
- Are provider details isolated in infrastructure?
- Are intermediate outputs represented as versioned assets?
- Can a failed or interrupted workflow step be retried as a job?
- Is the renderer called with a `RenderSpec` instead of implicit shared state?
- Is the new code smaller than the problem it solves?
