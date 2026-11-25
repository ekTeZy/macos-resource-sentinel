"""Deterministic rolling-window rules for confirmed resource signals."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from .models import ProcessSample, SystemSample


PRESSURE_LEVELS = {
    "unknown": -1,
    "normal": 0,
    "warning": 1,
    "critical": 2,
}


@dataclass(frozen=True, slots=True)
class RuleSignal:
    """A confirmed rule state for one fingerprint."""

    fingerprint: str
    rule: str
    active: bool
    recovered: bool
    severity: str
    observed_value: float
    threshold_value: float
    duration_seconds: int
    message: str
    process: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class RuleEngine:
    """Evaluate sustained conditions from a rolling sample history."""

    def __init__(self, config: dict[str, Any], *, interval_seconds: int) -> None:
        self.config = config
        self.interval_seconds = max(1, int(interval_seconds))

    def evaluate(self, history: Iterable[SystemSample]) -> list[RuleSignal]:
        samples = list(history)
        if not samples:
            return []

        signals: list[RuleSignal] = []
        rules = self.config["rules"]
        if rules["cpu"]["enabled"]:
            signals.extend(self._evaluate_aggregate_cpu(samples, rules["cpu"]))
        if rules["process_cpu"]["enabled"]:
            signals.extend(self._evaluate_process_cpu(samples, rules["process_cpu"]))
        if rules["load_average"]["enabled"]:
            signals.extend(self._evaluate_load_average(samples, rules["load_average"]))
        if rules["memory_pressure"]["enabled"]:
            signals.extend(self._evaluate_memory_pressure(samples, rules["memory_pressure"]))
        if rules["swap"]["enabled"]:
            signals.extend(self._evaluate_swap(samples, rules["swap"]))
        if rules["disk"]["enabled"]:
            signals.extend(self._evaluate_disk(samples[-1], rules["disk"]))
        return signals

    def _evaluate_aggregate_cpu(self, samples: list[SystemSample], rule: dict[str, Any]) -> list[RuleSignal]:
        active_window = self._window(samples, rule["min_duration_seconds"])
        recovery_window = self._window(samples, rule["recovery_duration_seconds"])
        active = False
        recovered = False
        observed = self._mean([sample.cpu_percent for sample in active_window])

        if self._has_coverage(active_window, rule["min_duration_seconds"]):
            active = observed >= float(rule["trigger_percent"])
        if self._has_coverage(recovery_window, rule["recovery_duration_seconds"]):
            recovered = self._mean([sample.cpu_percent for sample in recovery_window]) < float(rule["recover_percent"])

        return [
            RuleSignal(
                fingerprint="cpu.aggregate",
                rule="cpu.aggregate",
                active=active,
                recovered=recovered,
                severity="warning",
                observed_value=round(observed, 2),
                threshold_value=float(rule["trigger_percent"]),
                duration_seconds=int(rule["min_duration_seconds"]),
                message=f"aggregate CPU averaged {observed:.1f}% over {rule['min_duration_seconds']} seconds",
                metadata={"cooldown_minutes": rule["cooldown_minutes"]},
            )
        ]

    def _evaluate_process_cpu(self, samples: list[SystemSample], rule: dict[str, Any]) -> list[RuleSignal]:
        ignored_names = set(rule.get("ignored_names", []))
        grouped: dict[str, list[tuple[SystemSample, ProcessSample]]] = {}
        latest_by_key: dict[str, ProcessSample] = {}

        for sample in samples:
            for process in sample.top_processes:
                if process.name in ignored_names or process.create_time is None:
                    continue
                key = f"{process.pid}:{process.create_time:.3f}"
                grouped.setdefault(key, []).append((sample, process))
                latest_by_key[key] = process

        signals: list[RuleSignal] = []
        for key, entries in grouped.items():
            process = latest_by_key[key]
            active_entries = self._window_entries(entries, rule["min_duration_seconds"])
            recovery_entries = self._window_entries(entries, rule["recovery_duration_seconds"])
            active_values = [item.cpu_percent for _, item in active_entries]
            recovery_values = [item.cpu_percent for _, item in recovery_entries]
            observed = self._mean(active_values)

            active = (
                self._has_entry_coverage(active_entries, rule["min_duration_seconds"])
                and observed >= float(rule["trigger_percent"])
            )
            recovered = (
                self._has_entry_coverage(recovery_entries, rule["recovery_duration_seconds"])
                and self._mean(recovery_values) < float(rule["recover_percent"])
            )
            if not recovery_entries:
                latest_seen = max(_timestamp(sample) for sample, _ in entries)
                recovered = (_timestamp(samples[-1]) - latest_seen).total_seconds() >= rule["recovery_duration_seconds"]

            fingerprint = f"process.cpu:{process.name}:{key}"
            signals.append(
                RuleSignal(
                    fingerprint=fingerprint,
                    rule="process.cpu",
                    active=active,
                    recovered=recovered,
                    severity="warning",
                    observed_value=round(observed, 2),
                    threshold_value=float(rule["trigger_percent"]),
                    duration_seconds=int(rule["min_duration_seconds"]),
                    message=f"process {process.name} averaged {observed:.1f}% CPU",
                    process=process.to_dict(),
                    metadata={"cooldown_minutes": rule["cooldown_minutes"]},
                )
            )
        return signals

    def _evaluate_load_average(self, samples: list[SystemSample], rule: dict[str, Any]) -> list[RuleSignal]:
        window = self._window(samples, rule["min_duration_seconds"])
        values = [
            sample.load_average[0] / max(1, sample.logical_cpus)
            for sample in window
            if sample.load_average is not None
        ]
        observed = self._mean(values)
        active = self._has_coverage(window, rule["min_duration_seconds"]) and observed >= float(rule["trigger_multiplier"])
        recovered = bool(values) and observed < float(rule["recovery_multiplier"])
        return [
            RuleSignal(
                fingerprint="load.average",
                rule="load.average",
                active=active,
                recovered=recovered,
                severity="warning",
                observed_value=round(observed, 2),
                threshold_value=float(rule["trigger_multiplier"]),
                duration_seconds=int(rule["min_duration_seconds"]),
                message=f"normalized load average is {observed:.2f}",
                metadata={"cooldown_minutes": rule["cooldown_minutes"]},
            )
        ]

    def _evaluate_memory_pressure(self, samples: list[SystemSample], rule: dict[str, Any]) -> list[RuleSignal]:
        active_window = self._window(samples, rule["min_duration_seconds"])
        recovery_window = self._window(samples, rule["recovery_duration_seconds"])
        levels = [PRESSURE_LEVELS.get(str(sample.memory.get("pressure")), -1) for sample in active_window]
        known_levels = [level for level in levels if level >= 0]
        latest = str(samples[-1].memory.get("pressure", "unknown"))
        latest_level = PRESSURE_LEVELS.get(latest, -1)

        active = (
            self._has_coverage(active_window, rule["min_duration_seconds"])
            and bool(known_levels)
            and self._mean(known_levels) >= 0.8
            and latest_level > 0
        )
        recovered = self._has_coverage(recovery_window, rule["recovery_duration_seconds"]) and all(
            PRESSURE_LEVELS.get(str(sample.memory.get("pressure")), 0) == 0 for sample in recovery_window
        )
        severity = "critical" if latest == "critical" else "warning"
        observed = float(max(known_levels or [latest_level]))
        return [
            RuleSignal(
                fingerprint="memory.pressure",
                rule="memory.pressure",
                active=active,
                recovered=recovered,
                severity=severity,
                observed_value=observed,
                threshold_value=1.0,
                duration_seconds=int(rule["min_duration_seconds"]),
                message=f"memory pressure is {latest}",
                metadata={"cooldown_minutes": rule["cooldown_minutes"], "pressure": latest},
            )
        ]

    def _evaluate_swap(self, samples: list[SystemSample], rule: dict[str, Any]) -> list[RuleSignal]:
        window = self._window(samples, rule["growth_window_seconds"])
        if not window:
            return []
        first = window[0].swap["used_bytes"]
        latest = window[-1].swap["used_bytes"]
        minimum = int(rule["minimum_used_mib"]) * 1024 * 1024
        growth = int(rule["growth_mib"]) * 1024 * 1024
        delta = latest - first
        active = latest >= minimum and delta >= growth
        recovered = latest < minimum or delta < growth // 2
        observed_mib = delta / 1024 / 1024
        threshold_mib = growth / 1024 / 1024
        return [
            RuleSignal(
                fingerprint="swap.growth",
                rule="swap.growth",
                active=active,
                recovered=recovered,
                severity="warning",
                observed_value=round(observed_mib, 1),
                threshold_value=round(threshold_mib, 1),
                duration_seconds=int(rule["growth_window_seconds"]),
                message=f"swap grew by {observed_mib:.0f} MiB over {rule['growth_window_seconds']} seconds",
                metadata={"cooldown_minutes": rule["cooldown_minutes"], "used_bytes": latest},
            )
        ]

    def _evaluate_disk(self, sample: SystemSample, rule: dict[str, Any]) -> list[RuleSignal]:
        signals: list[RuleSignal] = []
        for disk in sample.disks:
            if not disk.get("available"):
                continue
            path = str(disk["path"])
            free_percent = float(disk["free_percent"])
            critical = free_percent < float(rule["critical_free_percent"])
            warning = free_percent < float(rule["warning_free_percent"])
            if critical:
                severity = "critical"
                threshold = float(rule["critical_free_percent"])
                recovery = float(rule["critical_recovery_percent"])
            else:
                severity = "warning"
                threshold = float(rule["warning_free_percent"])
                recovery = float(rule["warning_recovery_percent"])
            signals.append(
                RuleSignal(
                    fingerprint=f"disk.capacity:{path}",
                    rule="disk.capacity",
                    active=warning or critical,
                    recovered=free_percent >= recovery,
                    severity=severity,
                    observed_value=free_percent,
                    threshold_value=threshold,
                    duration_seconds=0,
                    message=f"disk {path} has {free_percent:.1f}% free",
                    metadata={"path": path, "cooldown_minutes": 60 * 24 if critical else 60},
                )
            )
        return signals

    def _window(self, samples: list[SystemSample], duration_seconds: int) -> list[SystemSample]:
        latest = _timestamp(samples[-1])
        return [sample for sample in samples if (latest - _timestamp(sample)).total_seconds() <= duration_seconds]

    def _window_entries(
        self,
        entries: list[tuple[SystemSample, ProcessSample]],
        duration_seconds: int,
    ) -> list[tuple[SystemSample, ProcessSample]]:
        latest = _timestamp(entries[-1][0])
        return [entry for entry in entries if (latest - _timestamp(entry[0])).total_seconds() <= duration_seconds]

    def _has_coverage(self, samples: list[SystemSample], duration_seconds: int) -> bool:
        if duration_seconds <= 0:
            return True
        required = self._required_samples(duration_seconds)
        if len(samples) < required:
            return False
        elapsed = (_timestamp(samples[-1]) - _timestamp(samples[0])).total_seconds()
        return elapsed >= max(0, duration_seconds - self.interval_seconds)

    def _has_entry_coverage(self, entries: list[tuple[SystemSample, ProcessSample]], duration_seconds: int) -> bool:
        if duration_seconds <= 0:
            return True
        if len(entries) < self._required_samples(duration_seconds):
            return False
        elapsed = (_timestamp(entries[-1][0]) - _timestamp(entries[0][0])).total_seconds()
        return elapsed >= max(0, duration_seconds - self.interval_seconds)

    def _required_samples(self, duration_seconds: int) -> int:
        return max(1, math.ceil((duration_seconds / self.interval_seconds) * 0.75))

    @staticmethod
    def _mean(values: Iterable[float]) -> float:
        items = list(values)
        return sum(items) / len(items) if items else 0.0


def _timestamp(sample: SystemSample) -> datetime:
    return datetime.fromisoformat(sample.timestamp.replace("Z", "+00:00"))
