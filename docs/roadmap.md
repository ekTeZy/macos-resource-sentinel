# Roadmap

## Milestone 0 — specification

Status: complete.

- Public documentation structure.
- Architecture.
- Alert rules and incident lifecycle.
- Event schema.
- Security model.
- Configuration example.
- Installation plan.

## Milestone 1 — local collector and CLI

Status: in progress.

- Python package with a `src` layout.
- `mac-sentinel collect --once`.
- `mac-sentinel doctor`.
- Configuration loading and validation.
- Structured errors.
- Unit tests for normalization and validation.

## Milestone 2 — deterministic monitoring

- Continuous monitor loop.
- Rule engine.
- Incident lifecycle.
- Cooldowns and startup grace.
- JSONL event history.
- Foreground logging.

## Milestone 3 — notifications

- Stable text templates.
- Native macOS notification channel.
- Telegram Bot API channel.
- Delivery retries with bounded backoff.
- Suppression audit records.

## Milestone 4 — LaunchAgent

- Generic plist template.
- `install-service` command.
- `uninstall-service` command.
- service status and log helpers.
- safe config permissions checks.

## Milestone 5 — assistant bridge

- Incident list/show commands.
- Diagnostic bundle command.
- Compact incident JSON output.
- Local assistant instructions or skill documentation.
- Daily and weekly summary command.

## Milestone 6 — constrained actions

- Action request model.
- Action confirmation.
- protected-process policy;
- `SIGTERM` executor;
- PID/start-time revalidation;
- action audit log.

## Milestone 7 — hardening

- CI tests;
- dependency pinning;
- secret scanning;
- release workflow;
- sample incident fixtures;
- privacy checklist for shared reports.

## Later ideas

These are intentionally outside the MVP:

- per-application baselines;
- browser tab or helper-process attribution;
- network saturation rules;
- battery drain forecasting;
- multiple notification destinations;
- Homebrew distribution;
- signed releases;
- optional `SIGKILL` with separate confirmation;
- service restart actions.

## Definition of done for MVP

The MVP is complete when a fresh macOS user can:

1. install the CLI;
2. run `doctor` successfully;
3. run a foreground monitor;
4. receive no alert for a short CPU spike;
5. receive one grouped alert for a sustained problem;
6. inspect the resulting incident;
7. request and confirm a safe `SIGTERM` action;
8. install and restart the LaunchAgent;
9. find no local secrets or personal runtime data in the public repository.
