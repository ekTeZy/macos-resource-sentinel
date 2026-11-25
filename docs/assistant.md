# Assistant integration

This document defines how an external assistant (for example Kimi Claw)
reads macOS Resource Sentinel data and talks to the user about incidents.

The assistant is an **explain-and-coordinate** layer. The monitor stays the
single source of truth about what happened; the assistant never polls system
metrics itself and never bypasses the action executor.

## Read path

All commands are read-only and safe to run at any time:

```bash
mac-sentinel incidents list                 # newest first, human-readable table
mac-sentinel incidents list --state firing  # only open incidents
mac-sentinel incidents show INCIDENT_ID     # one incident, detail view
mac-sentinel incidents bundle INCIDENT_ID   # assistant-ready JSON
mac-sentinel summary --period day           # daily aggregation
mac-sentinel summary --period week --json   # weekly aggregation as JSON
```

Raw history lives in the state directory:

```text
~/.local/state/macos-resource-sentinel/
├── events.jsonl          # append-only audit log
├── incidents.jsonl       # append-only incident snapshots
└── notification-state.json
```

Prefer the CLI over reading the files directly; the CLI collapses incident
snapshots to the latest state and validates the schema.

## Diagnostic bundle contract

`mac-sentinel incidents bundle INCIDENT_ID` prints a single JSON object:

| Field | Meaning |
|---|---|
| `bundle_schema` | Bundle format version. Currently `1`. |
| `incident` | Latest snapshot: id, rule, state, severity, message, opened/resolved timestamps, responsible process, rule metadata. |
| `related_events` | Audit events referencing this incident, ordered by time. |
| `open_incidents` | Currently firing incidents (up to 10). |
| `recent_incidents` | Up to 10 recent incidents other than this one. |

When a user asks "почему это произошло" / "why did I get this alert", the
assistant should run the bundle command for the referenced incident ID and
answer from those facts: rule, thresholds, duration, observed value, process.

## Interpreting common rules

- `memory.pressure` — macOS kernel pressure level (`warning`/`critical`).
  High RAM percentage alone is not an alert trigger; pressure is.
- `swap.growth` — swap grew by the configured amount within the window.
  A statically high swap value is not an alert by itself.
- `cpu.aggregate` / `process_cpu` — sustained averages over the configured
  duration; short spikes never reach these rules.

## Response style for chat channels

- One short conclusion first, then at most three supporting facts.
- Always name the incident ID and the rule.
- If the user asks to act on a process, see the action protocol below —
  do not improvise shell commands.

## Action protocol

The assistant may **explain**, **recommend**, and **coordinate** approved
actions. It must never run `kill`, `killall`, `sudo`, or arbitrary shell
against user processes itself — all terminations go through the executor.

Flow when the user asks to stop a process:

```bash
# 1. Identify the process from the incident bundle
mac-sentinel incidents bundle INCIDENT_ID

# 2. Stage the request; relay the printed confirmation line to the user
mac-sentinel actions request INCIDENT_ID process.terminate --pid PID

# 3. Only after the user explicitly approves, confirm within the TTL
mac-sentinel actions confirm ACT-XXXXXXXX-XXXXXX
```

Rules for the assistant:

1. Always show the user the target line (`pid`, process name) before
   confirming anything.
2. Never confirm an action the user did not explicitly approve in the
   current conversation.
3. If confirmation fails with `identity changed`, explain that the PID was
   reused and a fresh request is required.
4. Protected refusals (`process name ... is protected`) are final — do not
   retry with different arguments.
