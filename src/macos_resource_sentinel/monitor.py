"""Continuous deterministic monitoring loop."""

from __future__ import annotations

import sys
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

from .collector import CollectionError, collect_once
from .incidents import IncidentManager, IncidentTransition
from .notifications import NotificationManager
from .rules import RuleEngine
from .storage import JsonlStore
from .models import SystemSample


class MonitorRunner:
    """Coordinate collection, rules, incident state, and local history."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        state_dir: Path,
        output: TextIO = sys.stdout,
    ) -> None:
        self.config = config
        self.interval_seconds = int(config["sampling"]["interval_seconds"])
        self.output = output
        self.store = JsonlStore(state_dir)
        self.incidents = IncidentManager(self.store)
        self.notifier = NotificationManager(config, state_dir=state_dir)
        self.rules = RuleEngine(config, interval_seconds=self.interval_seconds)
        self.history: deque[SystemSample] = deque(maxlen=self._history_capacity())

    def run(
        self,
        *,
        max_samples: int | None = None,
        ignore_startup_grace: bool = False,
    ) -> int:
        if max_samples is not None and max_samples < 1:
            raise ValueError("max_samples must be at least 1")

        self.store.prepare()
        started_at = datetime.now(UTC)
        startup_grace = int(self.config["sampling"]["startup_grace_seconds"])
        self._append_monitor_event(
            "monitor.started",
            "info",
            "monitor loop started",
            {
                "interval_seconds": self.interval_seconds,
                "startup_grace_seconds": startup_grace,
                "max_samples": max_samples,
            },
        )

        collected = 0
        try:
            while max_samples is None or collected < max_samples:
                cycle_started = time.monotonic()
                try:
                    sample = collect_once(
                        interval_seconds=0.2,
                        disk_paths=self.config["rules"]["disk"]["paths"],
                        top_process_count=5,
                    )
                except CollectionError as exc:
                    self._append_monitor_event("collection.error", "warning", str(exc), {})
                    self._sleep_until_next_cycle(cycle_started)
                    continue

                collected += 1
                self.history.append(sample)
                signals = self.rules.evaluate(self.history)
                grace_active = (
                    not ignore_startup_grace
                    and (datetime.now(UTC) - started_at).total_seconds() < startup_grace
                )
                active_signals = [signal for signal in signals if signal.active]
                transitions: list[IncidentTransition] = []
                if signals and not grace_active:
                    transitions = self.incidents.process(signals)
                elif active_signals and grace_active:
                    self._append_monitor_event(
                        "incident.suppressed",
                        "info",
                        "confirmed signal suppressed by startup grace",
                        {"fingerprints": [signal.fingerprint for signal in active_signals]},
                    )

                if transitions:
                    self.notifier.process(transitions)

                for transition in transitions:
                    print(
                        f"{transition.event_type} {transition.incident_id} "
                        f"[{transition.severity}] {transition.message}",
                        file=self.output,
                        flush=True,
                    )

                if max_samples is None or collected < max_samples:
                    self._sleep_until_next_cycle(cycle_started)
        finally:
            self._append_monitor_event(
                "monitor.stopped",
                "info",
                "monitor loop stopped",
                {"samples_collected": collected},
            )

        return collected

    def _sleep_until_next_cycle(self, cycle_started: float) -> None:
        elapsed = time.monotonic() - cycle_started
        time.sleep(max(0.0, self.interval_seconds - elapsed))

    def _history_capacity(self) -> int:
        rules = self.config["rules"]
        durations = [
            rules["cpu"]["min_duration_seconds"],
            rules["cpu"]["recovery_duration_seconds"],
            rules["process_cpu"]["min_duration_seconds"],
            rules["process_cpu"]["recovery_duration_seconds"],
            rules["load_average"]["min_duration_seconds"],
            rules["memory_pressure"]["min_duration_seconds"],
            rules["memory_pressure"]["recovery_duration_seconds"],
            rules["swap"]["growth_window_seconds"],
        ]
        longest = max(durations)
        return max(8, int(longest / self.interval_seconds) + 8)

    def _append_monitor_event(
        self,
        event_type: str,
        severity: str,
        message: str,
        data: dict[str, Any],
    ) -> None:
        self.store.append_event(
            {
                "schema_version": 1,
                "event_id": f"evt_{uuid4().hex}",
                "timestamp": datetime.now(UTC).isoformat(),
                "event_type": event_type,
                "severity": severity,
                "source": "monitor",
                "message": message,
                "data": data,
            }
        )
