"""Read-only inspection of recorded incidents, events, and summaries.

This module is the assistant bridge: it gives deterministic, machine-readable
access to local history without mutating any monitor state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .storage import JsonlStore


class IncidentReportError(RuntimeError):
    """Raised when local history cannot be read or interpreted."""


@dataclass(frozen=True, slots=True)
class IncidentQuery:
    state: str | None = None
    fingerprint: str | None = None
    limit: int = 20


@dataclass(frozen=True, slots=True)
class IncidentRecord:
    """The latest known snapshot of a single incident."""

    incident_id: str
    fingerprint: str
    rule: str
    state: str
    severity: str
    message: str
    opened_at: datetime
    resolved_at: datetime | None
    duration_seconds: int
    process: dict[str, Any] | None
    metadata: dict[str, Any] = field(default_factory=dict)
    snapshots: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "fingerprint": self.fingerprint,
            "rule": self.rule,
            "state": self.state,
            "severity": self.severity,
            "message": self.message,
            "opened_at": _iso(self.opened_at),
            "resolved_at": _iso(self.resolved_at) if self.resolved_at else None,
            "duration_seconds": self.duration_seconds,
            "process": self.process,
            "metadata": self.metadata,
        }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file, skipping blank and corrupt lines."""
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
    except OSError as exc:
        raise IncidentReportError(f"cannot read {path}: {exc}") from exc
    return records


def latest_incidents(store: JsonlStore) -> list[IncidentRecord]:
    """Collapse incident snapshots to the latest state per incident ID."""
    snapshots: dict[str, list[dict[str, Any]]] = {}
    for record in read_jsonl(store.incidents_path):
        incident_id = record.get("incident_id")
        if not incident_id:
            continue
        snapshots.setdefault(str(incident_id), []).append(record)

    records: list[IncidentRecord] = []
    for incident_id, versions in snapshots.items():
        latest = versions[-1]
        opened = _parse_timestamp(latest.get("opened_at"))
        if opened is None:
            continue
        records.append(
            IncidentRecord(
                incident_id=incident_id,
                fingerprint=str(latest.get("fingerprint", "")),
                rule=str(latest.get("rule", "")),
                state=str(latest.get("state", "unknown")),
                severity=str(latest.get("severity", "info")),
                message=str(latest.get("message", "")),
                opened_at=opened,
                resolved_at=_parse_timestamp(latest.get("resolved_at")),
                duration_seconds=int(latest.get("duration_seconds") or 0),
                process=latest.get("process") if isinstance(latest.get("process"), dict) else None,
                metadata=latest.get("metadata") if isinstance(latest.get("metadata"), dict) else {},
                snapshots=len(versions),
            )
        )
    records.sort(key=lambda record: record.opened_at, reverse=True)
    return records


def query_incidents(store: JsonlStore, query: IncidentQuery) -> list[IncidentRecord]:
    records = latest_incidents(store)
    if query.state:
        records = [record for record in records if record.state == query.state]
    if query.fingerprint:
        records = [record for record in records if record.fingerprint == query.fingerprint]
    if query.limit > 0:
        records = records[: query.limit]
    return records


def find_incident(store: JsonlStore, incident_id: str) -> IncidentRecord:
    for record in latest_incidents(store):
        if record.incident_id == incident_id:
            return record
    raise IncidentReportError(f"incident not found: {incident_id}")


def incident_events(store: JsonlStore, incident_id: str) -> list[dict[str, Any]]:
    """All audit events that reference a given incident."""
    events = [
        event
        for event in read_jsonl(store.events_path)
        if event.get("incident_id") == incident_id
    ]
    events.sort(key=lambda event: str(event.get("timestamp", "")))
    return events


def build_diagnostic_bundle(store: JsonlStore, incident_id: str) -> dict[str, Any]:
    """Assemble everything an assistant needs to explain one incident."""
    record = find_incident(store, incident_id)
    events = incident_events(store, incident_id)
    return {
        "bundle_schema": 1,
        "generated_at": _iso(datetime.now(UTC)),
        "incident": record.to_dict(),
        "related_events": events,
        "open_incidents": [item.to_dict() for item in query_incidents(store, IncidentQuery(state="firing", limit=10))],
        "recent_incidents": [
            item.to_dict()
            for item in query_incidents(store, IncidentQuery(limit=10))
            if item.incident_id != incident_id
        ],
    }


def summarize(store: JsonlStore, *, period: str, now: datetime | None = None) -> dict[str, Any]:
    """Aggregate incident history for a daily or weekly report."""
    now = now or datetime.now(UTC)
    window = {"day": timedelta(days=1), "week": timedelta(days=7)}.get(period)
    if window is None:
        raise IncidentReportError(f"unknown summary period: {period}")

    cutoff = now - window
    records = [record for record in latest_incidents(store) if record.opened_at >= cutoff]

    by_rule: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    firing = 0
    for record in records:
        by_rule[record.rule] = by_rule.get(record.rule, 0) + 1
        by_severity[record.severity] = by_severity.get(record.severity, 0) + 1
        if record.state == "firing":
            firing += 1

    return {
        "summary_schema": 1,
        "period": period,
        "window_start": _iso(cutoff),
        "generated_at": _iso(now),
        "total_incidents": len(records),
        "open_incidents": firing,
        "by_rule": dict(sorted(by_rule.items(), key=lambda item: item[1], reverse=True)),
        "by_severity": dict(sorted(by_severity.items(), key=lambda item: item[1], reverse=True)),
        "incidents": [record.to_dict() for record in records],
    }


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


__all__ = [
    "IncidentQuery",
    "IncidentRecord",
    "IncidentReportError",
    "build_diagnostic_bundle",
    "find_incident",
    "incident_events",
    "latest_incidents",
    "query_incidents",
    "read_jsonl",
    "summarize",
]
