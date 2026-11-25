# Event schema

All persisted records are JSON objects, one object per line. Every record includes `schema_version` so old history can still be interpreted after a format change.

Current version: `1`.

## Common fields

| Field | Type | Required | Description |
|---|---|---:|---|
| `schema_version` | integer | yes | Record format version. |
| `event_id` | string | yes | Unique event identifier. |
| `incident_id` | string | when applicable | Stable incident identifier. |
| `timestamp` | string | yes | RFC 3339 timestamp with timezone. |
| `event_type` | string | yes | Dotted event type. |
| `severity` | string | yes | `info`, `warning`, or `critical`. |
| `source` | string | yes | Producing component. |
| `message` | string | no | Short human-readable summary. |
| `data` | object | no | Event-specific structured payload. |

## Incident identifier

Format:

```text
INC-YYYYMMDD-NNNN
```

The sequence is local to the machine and date. It is not intended to be globally unique.

## Event types

### `sample.collected`

Optional detailed sample record. Full samples may be sampled or compacted to avoid unbounded history.

```json
{
  "schema_version": 1,
  "event_id": "evt_01JEXAMPLE",
  "timestamp": "2026-11-25T12:00:00+03:00",
  "event_type": "sample.collected",
  "severity": "info",
  "source": "collector",
  "data": {
    "cpu_percent": 41.2,
    "load_average": [2.1, 1.8, 1.4],
    "logical_cpus": 10,
    "memory": {
      "pressure": "normal",
      "swap_used_bytes": 1073741824
    },
    "top_processes": [
      {
        "pid": 1234,
        "name": "example-process",
        "username": "example-user",
        "cpu_percent": 18.4,
        "rss_bytes": 268435456,
        "create_time": 1764000000.0
      }
    ]
  }
}
```

Real examples in public documentation must use placeholder names and IDs.

### `rule.pending`

A rule has evidence but has not reached its duration requirement.

```json
{
  "schema_version": 1,
  "event_id": "evt_01JEXAMPLE",
  "incident_id": "INC-20261125-0001",
  "timestamp": "2026-11-25T12:00:00+03:00",
  "event_type": "rule.pending",
  "severity": "info",
  "source": "rule-engine",
  "data": {
    "rule": "cpu.aggregate",
    "observed_value": 88.4,
    "trigger_value": 85.0,
    "elapsed_seconds": 30,
    "required_seconds": 180
  }
}
```

### `incident.opened`

```json
{
  "schema_version": 1,
  "event_id": "evt_01JEXAMPLE",
  "incident_id": "INC-20261125-0001",
  "timestamp": "2026-11-25T12:03:00+03:00",
  "event_type": "incident.opened",
  "severity": "warning",
  "source": "incident-manager",
  "message": "Sustained aggregate CPU usage",
  "data": {
    "fingerprint": "cpu.aggregate:example-window",
    "state": "firing",
    "findings": [
      {
        "rule": "cpu.aggregate",
        "observed_value": 91.2,
        "trigger_value": 85.0,
        "duration_seconds": 180
      }
    ],
    "top_processes": [],
    "allowed_actions": ["inspect"]
  }
}
```

### `incident.updated`

Records material changes while an incident remains active.

### `incident.escalated`

Records that an active incident crossed its escalation window.

### `incident.recovering`

Records that values crossed the recovery threshold but have not remained stable long enough.

### `incident.resolved`

```json
{
  "schema_version": 1,
  "event_id": "evt_01JEXAMPLE",
  "incident_id": "INC-20261125-0001",
  "timestamp": "2026-11-25T12:08:00+03:00",
  "event_type": "incident.resolved",
  "severity": "info",
  "source": "incident-manager",
  "message": "CPU usage recovered",
  "data": {
    "duration_seconds": 300,
    "recovery_value": 58.7,
    "recovery_threshold": 65.0
  }
}
```

### `notification.suppressed`

```json
{
  "schema_version": 1,
  "event_id": "evt_01JEXAMPLE",
  "incident_id": "INC-20261125-0001",
  "timestamp": "2026-11-25T12:03:00+03:00",
  "event_type": "notification.suppressed",
  "severity": "info",
  "source": "notifier",
  "data": {
    "reason": "cooldown",
    "retry_after_seconds": 1500,
    "channel": "telegram"
  }
}
```

### `notification.sent`

Contains delivery metadata, not the full credentials or private endpoint response.

```json
{
  "schema_version": 1,
  "event_id": "evt_01JEXAMPLE",
  "incident_id": "INC-20261125-0001",
  "timestamp": "2026-11-25T12:03:03+03:00",
  "event_type": "notification.sent",
  "severity": "info",
  "source": "notifier",
  "data": {
    "channel": "telegram",
    "delivery_id": "placeholder"
  }
}
```

## Action request record

An action request is not authorization to execute. It is a request that can later be approved.

```json
{
  "schema_version": 1,
  "event_id": "evt_01JEXAMPLE",
  "incident_id": "INC-20261125-0001",
  "timestamp": "2026-11-25T12:04:00+03:00",
  "event_type": "action.requested",
  "severity": "warning",
  "source": "action-executor",
  "data": {
    "action_id": "act_01JEXAMPLE",
    "action_type": "process.terminate",
    "target": {
      "pid": 1234,
      "name": "example-process",
      "username": "example-user",
      "create_time": 1764000000.0
    },
    "method": "SIGTERM",
    "expires_at": "2026-11-25T12:06:00+03:00",
    "status": "awaiting_confirmation"
  }
}
```

## Action result record

```json
{
  "schema_version": 1,
  "event_id": "evt_01JEXAMPLE",
  "incident_id": "INC-20261125-0001",
  "timestamp": "2026-11-25T12:05:00+03:00",
  "event_type": "action.completed",
  "severity": "info",
  "source": "action-executor",
  "data": {
    "action_id": "act_01JEXAMPLE",
    "action_type": "process.terminate",
    "status": "success",
    "method": "SIGTERM",
    "exit_observed": false,
    "verification": "signal_accepted"
  }
}
```

Failure statuses include:

- `expired`;
- `target_changed`;
- `not_allowed`;
- `permission_denied`;
- `process_not_found`;
- `execution_failed`.

## Data retention

Suggested defaults:

- raw samples: 24 hours;
- rule transitions: 30 days;
- incidents: 180 days;
- action records: 365 days;
- daemon logs: 14 days or a fixed size limit.

Retention cleanup must never delete the record of a completed action before its configured audit retention expires.

## Privacy rules

Runtime history may contain personal process names, paths, usernames, and command-line fragments. It remains local by default.

Before sharing an incident publicly:

1. remove username and hostname;
2. replace chat and delivery IDs;
3. replace process paths that reveal a home directory;
4. remove command-line arguments;
5. review application and process names for private context.
