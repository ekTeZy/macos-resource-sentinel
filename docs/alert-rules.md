# Alert rules and incident lifecycle

## Design principle

A notification should mean that a problem has persisted long enough to matter. A single high sample is evidence, not an incident.

Every rule needs all of the following:

- trigger condition;
- minimum duration;
- recovery condition;
- severity;
- cooldown policy.

## Sampling model

The default sampling interval is five seconds.

A sample is a point-in-time measurement. A rule match is a state that persists across samples.

Example:

```text
sample 1: CPU 96%  → no alert
sample 2: CPU 91%  → no alert
sample 3: CPU 93%  → no alert
...
sample 36: CPU 88% → three minutes elapsed → create incident
```

The evaluator should tolerate an occasional sample below the trigger if the rolling average remains above the configured threshold.

## Incident lifecycle

```text
normal
  │
  │ trigger observed
  ▼
pending
  │
  │ minimum duration reached
  ▼
firing ─────────────────▶ escalated
  │                            ▲
  │ recovery threshold held    │
  ▼                            │
recovering ────────────────────┘
  │
  │ stable long enough
  ▼
resolved
```

### normal

No rule currently has evidence of a problem.

### pending

A rule has matching samples, but the minimum duration has not elapsed. No notification is sent.

### firing

The rule has been active for the configured duration. One notification may be sent.

### recovering

Values have dropped below the recovery threshold, but not for long enough to close the incident.

### resolved

The incident is closed. One recovery notification may be sent if the original incident produced an alert.

### escalated

The incident stayed active beyond its escalation window. An escalation reminder may be sent at a much lower rate than the sampling loop.

## MVP rules

### Aggregate CPU

| Field | Default |
|---|---:|
| Trigger | 85% |
| Recovery | 65% |
| Minimum duration | 180 seconds |
| Recovery duration | 120 seconds |
| Severity | warning |
| Cooldown | 30 minutes |

A brief compile, indexing operation, video export, or browser spike should not alert unless it continues.

### Single process CPU

| Field | Default |
|---|---:|
| Trigger | 70% of one logical CPU for a laptop-class workload |
| Recovery | 40% |
| Minimum duration | 120 seconds |
| Recovery duration | 120 seconds |
| Severity | warning |
| Cooldown | 30 minutes per process identity |

Process identity is not only the PID. It includes name, executable path when available, user, and start time. This prevents an alert from following an unrelated process after PID reuse.

### Load average

| Field | Default |
|---|---:|
| Trigger | `1.5 × logical_cpu_count` |
| Recovery | `1.0 × logical_cpu_count` |
| Minimum duration | 600 seconds |
| Severity | warning |
| Cooldown | 60 minutes |

Load average is useful as supporting evidence, but it should usually not be the only reason to terminate a process.

### Memory pressure

| Field | Default |
|---|---:|
| Trigger | elevated/warn pressure |
| Recovery | normal pressure |
| Minimum duration | 120 seconds |
| Recovery duration | 180 seconds |
| Severity | warning |
| Cooldown | 30 minutes |

macOS can intentionally keep RAM occupied for cache. Memory pressure and swap behavior are more actionable than a simple percentage of used RAM.

### Swap growth

| Field | Default |
|---|---:|
| Trigger | more than 2 GiB used and growing |
| Growth signal | at least 512 MiB over ten minutes |
| Severity | warning |
| Cooldown | 60 minutes |

The rule should distinguish persistent swap pressure from normal small fluctuations.

### Disk capacity

| Severity | Trigger | Recovery |
|---|---:|---:|
| warning | less than 15% free | more than 20% free |
| critical | less than 8% free | more than 12% free |

Critical disk capacity may bypass ordinary cooldown once per day because it can make the system unstable.

## Notification suppression

Notifications are suppressed when any of the following applies:

- startup grace period is active;
- the same incident fingerprint is in cooldown;
- the hourly notification limit has been reached;
- a maintenance window is active;
- the rule is explicitly snoozed;
- an equivalent alert was already included in a grouped incident.

Suppression must not delete evidence. The event remains visible in the local history.

## Grouping

If CPU, load average, memory pressure, and swap grow together, they should be represented as one grouped incident with multiple findings.

Example:

```text
INC-20261125-0007
findings:
  - aggregate CPU above threshold for three minutes
  - memory pressure elevated
  - swap grew by 780 MiB
primary suspect:
  - process name, CPU, RSS, start time
```

Grouping prevents a single system problem from producing four separate notifications.

## Recovery notification

Recovery notifications are optional and disabled by default for warning incidents.

A recovery message is useful when:

- severity is critical;
- the incident lasted more than ten minutes;
- an action was executed;
- the user explicitly enabled recovery messages.

## Escalation

An active incident can be escalated after fifteen minutes.

Escalation should include:

- original incident ID;
- total active duration;
- whether the same process is still responsible;
- whether memory or swap became worse;
- available safe actions.

Escalation must use its own cooldown and should not reset the original incident history.

## Quiet hours

Quiet hours apply to warning notifications only.

Critical notifications may still be delivered when they indicate a condition that can damage the user's work or make the system unusable, such as critically low disk space.

## Rule evaluation order

1. Build a normalized `SystemSample`.
2. Evaluate independent rule evidence.
3. Feed rule evidence into the incident manager.
4. Group active findings.
5. Apply startup, maintenance, cooldown, and rate-limit checks.
6. Persist the incident transition.
7. Notify only if the transition requires it.

## Initial exclusions

The first version should exclude from process-level action recommendations:

- PID 0 and PID 1;
- kernel tasks;
- processes not owned by the current user;
- the monitoring process itself;
- the configured assistant process;
- login/session/security processes;
- names and paths in the user-defined protected list.

An exclusion from action does not necessarily mean exclusion from reporting.
