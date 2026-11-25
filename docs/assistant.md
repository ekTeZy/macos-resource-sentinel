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

## Action protocol (Milestone 6)

Actions are not yet executable. Until `mac-sentinel actions` is implemented:

1. The assistant may **explain** and **recommend**.
2. The assistant must **not** run `kill`, `killall`, `sudo`, or arbitrary
   shell against user processes.
3. When the user insists on termination, answer that confirmed `SIGTERM`
   through the executor arrives with Milestone 6.

Once implemented, the flow is:

```bash
mac-sentinel actions request INCIDENT_ID process.terminate --pid PID
mac-sentinel actions confirm ACTION_ID
```

The executor validates the PID against the recorded process identity,
checks protected names/paths, and requires explicit confirmation.
