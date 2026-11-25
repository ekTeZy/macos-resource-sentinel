"""Incident lifecycle management."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from .rules import RuleSignal
from .storage import JsonlStore


@dataclass(frozen=True, slots=True)
class IncidentTransition:
    event_type: str
    incident_id: str
    fingerprint: str
    severity: str
    message: str
    rule: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class IncidentManager:
    """Turn confirmed rule signals into persistent incident transitions."""

    def __init__(self, store: JsonlStore) -> None:
        self.store = store
        self.store.prepare()
        self.state = self.store.load_state()

    def process(self, signals: list[RuleSignal], *, now: datetime | None = None) -> list[IncidentTransition]:
        now = now or datetime.now(UTC)
        transitions: list[IncidentTransition] = []
        signals_by_fingerprint = {signal.fingerprint: signal for signal in signals}

        for signal in signals:
            if signal.active:
                transition = self._handle_active(signal, now)
                if transition is not None:
                    transitions.append(transition)

        open_incidents = dict(self.state["open_incidents"])
        for fingerprint, incident in open_incidents.items():
            signal = signals_by_fingerprint.get(fingerprint)
            if signal is not None and signal.active:
                incident["updated_at"] = _iso(now)
                incident["observed_value"] = signal.observed_value
                incident["severity"] = signal.severity
                incident["message"] = signal.message
                self.state["open_incidents"][fingerprint] = incident
                continue
            if signal is not None and signal.recovered:
                transitions.append(self._resolve(fingerprint, incident, signal, now))

        self.store.save_state(self.state)
        return transitions

    def _handle_active(self, signal: RuleSignal, now: datetime) -> IncidentTransition | None:
        open_incidents = self.state["open_incidents"]
        if signal.fingerprint in open_incidents:
            return None

        cooldown_until = self.state["cooldowns"].get(signal.fingerprint)
        if cooldown_until and datetime.fromisoformat(cooldown_until) > now:
            suppressed = self.state["suppressed"]
            if suppressed.get(signal.fingerprint) != cooldown_until:
                suppressed[signal.fingerprint] = cooldown_until
                self._append_event(
                    event_type="notification.suppressed",
                    severity="info",
                    source="incident-manager",
                    now=now,
                    incident_id=None,
                    message="incident notification suppressed by cooldown",
                    data={
                        "fingerprint": signal.fingerprint,
                        "reason": "cooldown",
                        "cooldown_until": cooldown_until,
                    },
                )
            return None

        self.state["incident_sequence"] += 1
        incident_id = f"INC-{now:%Y%m%d}-{self.state['incident_sequence']:04d}"
        incident = {
            "schema_version": 1,
            "incident_id": incident_id,
            "fingerprint": signal.fingerprint,
            "rule": signal.rule,
            "state": "firing",
            "severity": signal.severity,
            "opened_at": _iso(now),
            "updated_at": _iso(now),
            "resolved_at": None,
            "message": signal.message,
            "observed_value": signal.observed_value,
            "threshold_value": signal.threshold_value,
            "duration_seconds": signal.duration_seconds,
            "process": signal.process,
            "metadata": signal.metadata,
        }
        open_incidents[signal.fingerprint] = incident
        self.state["suppressed"].pop(signal.fingerprint, None)

        self.store.append_incident(incident)
        self._append_event(
            event_type="incident.opened",
            severity=signal.severity,
            source="incident-manager",
            now=now,
            incident_id=incident_id,
            message=signal.message,
            data=incident,
        )
        return IncidentTransition(
            event_type="incident.opened",
            incident_id=incident_id,
            fingerprint=signal.fingerprint,
            severity=signal.severity,
            message=signal.message,
            rule=signal.rule,
            data=incident,
        )

    def _resolve(
        self,
        fingerprint: str,
        incident: dict[str, Any],
        signal: RuleSignal,
        now: datetime,
    ) -> IncidentTransition:
        self.state["open_incidents"].pop(fingerprint, None)
        cooldown_minutes = int(incident.get("metadata", {}).get("cooldown_minutes", 30))
        cooldown_until = _iso(now + timedelta(minutes=cooldown_minutes))
        self.state["cooldowns"][fingerprint] = cooldown_until

        incident = dict(incident)
        incident["state"] = "resolved"
        incident["resolved_at"] = _iso(now)
        incident["observed_value"] = signal.observed_value
        incident["message"] = signal.message

        self.store.append_incident(incident)
        self._append_event(
            event_type="incident.resolved",
            severity="info",
            source="incident-manager",
            now=now,
            incident_id=str(incident["incident_id"]),
            message=f"incident resolved: {signal.rule}",
            data=incident,
        )
        return IncidentTransition(
            event_type="incident.resolved",
            incident_id=str(incident["incident_id"]),
            fingerprint=fingerprint,
            severity=str(incident.get("severity", "info")),
            message=f"incident resolved: {signal.rule}",
            rule=signal.rule,
            data=incident,
        )

    def _append_event(
        self,
        *,
        event_type: str,
        severity: str,
        source: str,
        now: datetime,
        incident_id: str | None,
        message: str,
        data: dict[str, Any],
    ) -> None:
        record = {
            "schema_version": 1,
            "event_id": f"evt_{uuid4().hex}",
            "timestamp": _iso(now),
            "event_type": event_type,
            "severity": severity,
            "source": source,
            "message": message,
            "data": data,
        }
        if incident_id is not None:
            record["incident_id"] = incident_id
        self.store.append_event(record)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()
