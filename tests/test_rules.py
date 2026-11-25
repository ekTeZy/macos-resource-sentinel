from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

from macos_resource_sentinel.config import DEFAULT_CONFIG
from macos_resource_sentinel.models import ProcessSample, SystemSample
from macos_resource_sentinel.rules import RuleEngine


def make_sample(
    index: int,
    *,
    cpu: float = 20.0,
    pressure: str = "normal",
    swap_used: int = 0,
    load: float = 0.2,
    disk_free_percent: float = 50.0,
    processes: list[ProcessSample] | None = None,
) -> SystemSample:
    return SystemSample(
        timestamp=(datetime(2026, 11, 25, 12, 0, tzinfo=UTC) + timedelta(seconds=index)).isoformat(),
        platform="Darwin",
        boot_time=1.0,
        cpu_percent=cpu,
        logical_cpus=10,
        load_average=(load, load, load),
        memory={"pressure": pressure, "percent": 80.0},
        swap={"used_bytes": swap_used, "total_bytes": 10_000_000_000},
        disks=[{
            "path": "/",
            "available": True,
            "total_bytes": 100,
            "free_bytes": int(disk_free_percent),
            "free_percent": disk_free_percent,
        }],
        top_processes=processes or [],
    )


def fast_config() -> dict:
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["rules"]["cpu"]["min_duration_seconds"] = 3
    config["rules"]["cpu"]["recovery_duration_seconds"] = 2
    config["rules"]["cpu"]["cooldown_minutes"] = 1
    config["rules"]["memory_pressure"]["min_duration_seconds"] = 3
    config["rules"]["memory_pressure"]["recovery_duration_seconds"] = 2
    config["rules"]["swap"]["minimum_used_mib"] = 1
    config["rules"]["swap"]["growth_mib"] = 2
    config["rules"]["swap"]["growth_window_seconds"] = 10
    return config


def signal_by_rule(signals, rule: str):
    return next(signal for signal in signals if signal.rule == rule)


def test_short_cpu_spike_does_not_become_active() -> None:
    engine = RuleEngine(fast_config(), interval_seconds=1)
    signals = engine.evaluate([make_sample(0, cpu=98.0)])

    assert signal_by_rule(signals, "cpu.aggregate").active is False


def test_sustained_cpu_becomes_active_and_then_recovers() -> None:
    engine = RuleEngine(fast_config(), interval_seconds=1)
    hot = [make_sample(index, cpu=90.0) for index in range(4)]
    hot_signal = signal_by_rule(engine.evaluate(hot), "cpu.aggregate")
    assert hot_signal.active is True

    recovered = hot + [make_sample(index, cpu=30.0) for index in range(4, 7)]
    recovered_signal = signal_by_rule(engine.evaluate(recovered), "cpu.aggregate")
    assert recovered_signal.active is False
    assert recovered_signal.recovered is True


def test_memory_pressure_uses_kernel_level() -> None:
    engine = RuleEngine(fast_config(), interval_seconds=1)
    samples = [make_sample(index, pressure="warning") for index in range(4)]
    signal = signal_by_rule(engine.evaluate(samples), "memory.pressure")

    assert signal.active is True
    assert signal.severity == "warning"


def test_swap_growth_uses_window_delta() -> None:
    engine = RuleEngine(fast_config(), interval_seconds=1)
    samples = [
        make_sample(0, swap_used=1 * 1024 * 1024),
        make_sample(5, swap_used=4 * 1024 * 1024),
    ]
    signal = signal_by_rule(engine.evaluate(samples), "swap.growth")

    assert signal.active is True
    assert signal.observed_value == 3.0


def test_process_cpu_uses_process_identity() -> None:
    config = fast_config()
    config["rules"]["process_cpu"]["min_duration_seconds"] = 3
    config["rules"]["process_cpu"]["recovery_duration_seconds"] = 2
    process = ProcessSample(
        pid=123,
        name="example",
        username="example-user",
        cpu_percent=80.0,
        rss_bytes=1024,
        create_time=100.0,
    )
    samples = [make_sample(index, processes=[process]) for index in range(4)]
    signal = signal_by_rule(RuleEngine(config, interval_seconds=1).evaluate(samples), "process.cpu")

    assert signal.active is True
    assert signal.process is not None
    assert signal.process["pid"] == 123


def test_disk_capacity_is_immediate() -> None:
    signal = signal_by_rule(
        RuleEngine(fast_config(), interval_seconds=1).evaluate([make_sample(0, disk_free_percent=7.0)]),
        "disk.capacity",
    )

    assert signal.active is True
    assert signal.severity == "critical"
