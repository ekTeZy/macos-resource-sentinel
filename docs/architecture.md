# Architecture

## Overview

macOS Resource Sentinel is a local agent that turns noisy operating-system metrics into a small number of confirmed, actionable incidents.

The system is intentionally split into deterministic and assistive layers:

- the deterministic layer samples metrics, evaluates thresholds, manages cooldowns, stores evidence, and sends stable notifications;
- the assistive layer works only with structured incidents and can provide diagnostics, recommendations, and user-approved actions;
- the execution layer is deliberately smaller than either of them and accepts only constrained commands.

This separation keeps routine monitoring cheap, predictable, and auditable.

## High-level flow

```text
┌─────────────────────────────────────────────────────────────────┐
│                         mac-sentinel                            │
│                                                                 │
│  ┌──────────┐   ┌─────────────┐   ┌──────────────────┐          │
│  │ Collector│──▶│ Rule Engine │──▶│ Incident Manager │          │
│  └──────────┘   └─────────────┘   └────────┬─────────┘          │
│       │                    │               │                    │
│       ▼                    ▼               ▼                    │
│  ┌──────────────────────────────────────────────────────┐       │
│  │                Local event/incident store            │       │
│  └───────────────────────────┬──────────────────────────┘       │
│                              │                                  │
│                              ▼                                  │
│                        ┌───────────┐                            │
│                        │ Notifier  │                            │
│                        └───────────┘                            │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
                   Stable incident notification
                               │
                               ▼
                    ┌────────────────────┐
                    │ Assistive agent    │
                    │ diagnostics and    │
                    │ recommendations    │
                    └─────────┬──────────┘
                              │ constrained request
                              ▼
                    ┌────────────────────┐
                    │ Action Executor    │
                    │ allowlist + audit  │
                    └────────────────────┘
```

## Components

### Collector

The collector is the only component that reads operating-system metrics directly.

Planned inputs:

- aggregate CPU utilization;
- per-process CPU and RSS;
- load average and CPU count;
- memory pressure where available;
- virtual memory and swap;
- mounted filesystem capacity;
- power source and battery state where useful;
- boot time and sample timestamp.

The collector does not decide whether a value is abnormal. It returns a versioned `SystemSample` object.

Implementation preference:

- Python 3.12 or newer;
- `psutil` for portable process and system data;
- narrowly scoped macOS commands only where `psutil` cannot expose a required signal.

### Rule Engine

The rule engine compares one or more samples against configuration.

It is responsible for:

- minimum violation duration;
- trigger and recovery thresholds;
- per-rule severity;
- ignored processes and paths;
- rules that require several samples rather than one spike.

It does not format user-facing messages and does not invoke external services.

### Incident Manager

The incident manager owns state transitions:

```text
normal → pending → firing → recovering → resolved
```

It also handles:

- grouping related rule matches;
- incident identity;
- cooldown windows;
- recovery detection;
- escalation after a long-running incident;
- suppression after process restart or system reboot.

The incident manager is the only component allowed to create a new incident record.

### Storage

The first version uses append-only JSON Lines files. This is easy to inspect, version, and debug without requiring a database daemon.

Planned local state directory:

```text
~/.local/state/macos-resource-sentinel/
├── events.jsonl
├── incidents.jsonl
├── actions.jsonl
├── monitor.log
└── spool/
```

These files are local runtime state and must not be committed.

### Notifier

The notifier renders a stable template from an incident record.

Initial channels:

- Telegram Bot API;
- native macOS notification as a fallback or local-only mode.

The notifier is deterministic. An assistant may add context later, but the base alert remains predictable and testable.

### Assistant bridge

The assistant bridge exposes incidents through the CLI instead of giving an assistant broad filesystem or shell access.

Planned commands:

```bash
mac-sentinel incidents list
mac-sentinel incidents show INCIDENT_ID
mac-sentinel incidents diagnose INCIDENT_ID
mac-sentinel actions request INCIDENT_ID terminate-process
```

The assistant may help interpret output and draft a recommended next step, but it cannot bypass the action executor.

### Action Executor

The executor performs a small set of local operations.

MVP operations:

- collect additional diagnostics for a known incident;
- send `SIGTERM` to a validated process after confirmation;
- check whether the referenced process exited.

The executor validates the incident, process identity, process start time, ownership, action allowlist, and confirmation expiry before doing anything.

## Process model

The daemon runs as the signed-in macOS user through a LaunchAgent.

It must not require `sudo` for the MVP. A process owned by another user or by the system can be reported and diagnosed, but not terminated by the default policy.

## Configuration model

Configuration is layered:

1. built-in defaults;
2. public example configuration;
3. user configuration at `~/.config/macos-resource-sentinel/config.toml`;
4. temporary command-line overrides for diagnostics.

Secrets are not stored in repository files. A secret may be provided through an environment variable or a local secret reference.

## Failure behavior

The daemon follows a fail-quiet policy for telemetry collection and a fail-visible policy for actions:

- a temporary metric collection error is logged and retried;
- a notification delivery error does not erase the incident;
- an invalid or expired action confirmation always fails closed;
- executor errors are returned in structured form and audited.

## Boundary with an assistant

An assistant is useful for contextual work, not for deterministic safety decisions.

Allowed assistant responsibilities:

- explain an incident;
- correlate process names with recent history;
- suggest threshold tuning;
- request an allowed action;
- summarize incidents over a day or week.

Disallowed assistant responsibilities:

- continuous metric polling;
- inventing thresholds without changing configuration;
- arbitrary shell execution;
- autonomous process termination;
- direct access to secrets.

## Public repository boundary

The public repository may contain:

- specifications;
- schemas;
- sample configuration without credentials;
- source code and tests;
- generic examples.

The public repository must not contain:

- bot tokens;
- Telegram chat IDs;
- hostnames tied to a real person;
- real process history;
- personal paths outside conventional examples;
- local LaunchAgent files with user-specific labels or paths.
