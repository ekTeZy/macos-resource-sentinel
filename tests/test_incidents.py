from __future__ import annotations

import json
from datetime import UTC, datetime

from macos_resource_sentinel.incidents import IncidentManager
from macos_resource_sentinel.rules import RuleSignal
from macos_resource_sentinel.storage import JsonlStore


def cpu_signal(*, active: bool, recovered: bool = False) -> RuleSignal:
    return RuleSignal(
        fingerprint="cpu.aggregate",
        rule="cpu.aggregate",
        active=active,
        recovered=recovered,
        severity="warning",
        observed_value=90.0 if active else 40.0,
        threshold_value=85.0,
        duration_seconds=3,
        message="test CPU signal",
        metadata={"cooldown_minutes": 1},
    )


def test_incident_opens_resolves_and_cooldown_suppresses_reopen(tmp_path) -> None:
    store = JsonlStore(tmp_path)
    manager = IncidentManager(store)
    now = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)

    opened = manager.process([cpu_signal(active=True)], now=now)
    assert len(opened) == 1
    assert opened[0].event_type == "incident.opened"
    incident_id = opened[0].incident_id

    resolved = manager.process([cpu_signal(active=False, recovered=True)], now=now)
    assert len(resolved) == 1
    assert resolved[0].incident_id == incident_id

    suppressed = manager.process([cpu_signal(active=True)], now=now)
    assert suppressed == []

    events = [json.loads(line) for line in store.events_path.read_text().splitlines()]
    assert [event["event_type"] for event in events] == [
        "incident.opened",
        "incident.resolved",
        "notification.suppressed",
    ]


def test_monitor_state_survives_restart(tmp_path) -> None:
    store = JsonlStore(tmp_path)
    first = IncidentManager(store)
    opened = first.process([cpu_signal(active=True)])
    assert len(opened) == 1

    second = IncidentManager(store)
    assert "cpu.aggregate" in second.state["open_incidents"]
