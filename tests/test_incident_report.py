"""Tests for read-only incident inspection and assistant bundles."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from macos_resource_sentinel.incident_report import (
    IncidentQuery,
    IncidentReportError,
    build_diagnostic_bundle,
    find_incident,
    latest_incidents,
    query_incidents,
    read_jsonl,
    summarize,
)
from macos_resource_sentinel.storage import JsonlStore


def _snapshot(
    incident_id: str,
    *,
    state: str = "firing",
    rule: str = "memory.pressure",
    severity: str = "warning",
    opened_at: datetime | None = None,
    resolved_at: datetime | None = None,
    message: str = "memory pressure is warning",
) -> dict:
    return {
        "schema_version": 1,
        "incident_id": incident_id,
        "fingerprint": rule,
        "rule": rule,
        "state": state,
        "severity": severity,
        "opened_at": (opened_at or datetime.now(UTC)).isoformat(),
        "updated_at": (opened_at or datetime.now(UTC)).isoformat(),
        "resolved_at": resolved_at.isoformat() if resolved_at else None,
        "message": message,
        "observed_value": 2,
        "threshold_value": 2,
        "duration_seconds": 120,
        "process": None,
        "metadata": {"cooldown_minutes": 30},
    }


@pytest.fixture
def store(tmp_path: Path) -> JsonlStore:
    jsonl_store = JsonlStore(tmp_path / "state")
    jsonl_store.prepare()
    return jsonl_store


def test_read_jsonl_skips_corrupt_lines(store: JsonlStore) -> None:
    store.incidents_path.write_text(
        '{"incident_id":"A"}\nnot json\n\n{"incident_id":"B"}\n', encoding="utf-8"
    )

    records = read_jsonl(store.incidents_path)

    assert [record["incident_id"] for record in records] == ["A", "B"]


def test_read_jsonl_returns_empty_for_missing_file(store: JsonlStore) -> None:
    assert read_jsonl(store.incidents_path) == []


def test_latest_incidents_collapse_snapshots(store: JsonlStore) -> None:
    opened = _snapshot("INC-1")
    store.append_incident(opened)
    resolved = _snapshot(
        "INC-1", state="resolved", resolved_at=datetime.now(UTC), message="memory pressure recovered"
    )
    store.append_incident(resolved)
    store.append_incident(_snapshot("INC-2", rule="swap.growth"))

    records = latest_incidents(store)

    assert len(records) == 2
    inc_1 = next(record for record in records if record.incident_id == "INC-1")
    assert inc_1.state == "resolved"
    assert inc_1.resolved_at is not None
    assert inc_1.snapshots == 2


def test_query_incidents_filter_and_limit(store: JsonlStore) -> None:
    now = datetime.now(UTC)
    for index in range(5):
        store.append_incident(
            _snapshot(f"INC-{index}", rule="memory.pressure", opened_at=now - timedelta(minutes=index))
        )
    store.append_incident(
        _snapshot("INC-SWAP", rule="swap.growth", opened_at=now + timedelta(seconds=1))
    )

    by_rule = query_incidents(store, IncidentQuery(fingerprint="swap.growth"))
    assert [record.incident_id for record in by_rule] == ["INC-SWAP"]

    limited = query_incidents(store, IncidentQuery(limit=2))
    assert len(limited) == 2
    assert limited[0].incident_id == "INC-SWAP"  # newest first


def test_find_incident_raises_for_unknown_id(store: JsonlStore) -> None:
    with pytest.raises(IncidentReportError, match="not found"):
        find_incident(store, "INC-404")


def test_diagnostic_bundle_contains_incident_and_related_events(store: JsonlStore) -> None:
    store.append_incident(_snapshot("INC-9"))
    store.append_event(
        {
            "schema_version": 1,
            "event_id": "evt-1",
            "timestamp": datetime.now(UTC).isoformat(),
            "event_type": "incident.opened",
            "severity": "warning",
            "source": "incident-manager",
            "message": "memory pressure is warning",
            "data": {},
            "incident_id": "INC-9",
        }
    )
    store.append_event(
        {
            "schema_version": 1,
            "event_id": "evt-2",
            "timestamp": datetime.now(UTC).isoformat(),
            "event_type": "monitor.started",
            "severity": "info",
            "source": "monitor",
            "message": "monitor loop started",
            "data": {},
        }
    )

    bundle = build_diagnostic_bundle(store, "INC-9")

    assert bundle["bundle_schema"] == 1
    assert bundle["incident"]["incident_id"] == "INC-9"
    assert [event["event_id"] for event in bundle["related_events"]] == ["evt-1"]
    assert bundle["open_incidents"][0]["incident_id"] == "INC-9"
    json.dumps(bundle)  # bundle must stay JSON-serializable


def test_summary_aggregates_by_rule_and_severity(store: JsonlStore) -> None:
    now = datetime.now(UTC)
    store.append_incident(
        _snapshot("INC-A", rule="memory.pressure", opened_at=now - timedelta(hours=2))
    )
    store.append_incident(
        _snapshot(
            "INC-B",
            rule="swap.growth",
            severity="critical",
            opened_at=now - timedelta(days=2),
        )
    )

    day = summarize(store, period="day", now=now)
    assert day["total_incidents"] == 1
    assert day["by_rule"] == {"memory.pressure": 1}

    week = summarize(store, period="week", now=now)
    assert week["total_incidents"] == 2
    assert week["by_severity"] == {"warning": 1, "critical": 1}


def test_summary_rejects_unknown_period(store: JsonlStore) -> None:
    with pytest.raises(IncidentReportError, match="unknown summary period"):
        summarize(store, period="hour")
