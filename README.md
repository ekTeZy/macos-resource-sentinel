# macOS Resource Sentinel

`macos-resource-sentinel` is a local monitoring agent for macOS. It watches sustained CPU, memory, swap, load, and disk problems, suppresses short-lived spikes, records structured incidents, and provides a safe handoff for diagnostics and user-approved actions.

The project is designed around a clear boundary:

- deterministic local monitoring decides **whether something is an incident**;
- stable notification templates explain **what happened**;
- an AI assistant such as a locally deployed OpenClaw-compatible agent can explain **why it may have happened** and request a constrained follow-up action;
- a small local executor performs only explicitly allowed and confirmed operations.

## Goals

- Avoid notifications for two- or three-second resource spikes.
- Keep the monitoring path deterministic and inexpensive.
- Preserve machine-readable incident history for later analysis.
- Keep credentials and personal configuration out of the repository.
- Make every process action explicit, auditable, and reversible where possible.

## Non-goals

- Continuous AI polling of system metrics.
- Autonomous termination of arbitrary processes.
- Remote control of a Mac by an untrusted cloud service.
- A replacement for full observability platforms.

## Current status

This repository currently contains the architecture and product specification. The first implementation milestone is tracked in [`docs/roadmap.md`](docs/roadmap.md).

## Documentation

- [Architecture](docs/architecture.md)
- [Alert rules and incident lifecycle](docs/alert-rules.md)
- [Event schema](docs/event-schema.md)
- [Security model](docs/security-model.md)
- [Configuration](docs/configuration.md)
- [Installation plan](docs/installation.md)
- [Roadmap](docs/roadmap.md)

## License

MIT. See [LICENSE](LICENSE).
