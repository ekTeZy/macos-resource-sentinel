"""Structured models returned by the collector."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProcessSample:
    """A privacy-conscious snapshot of one process."""

    pid: int
    name: str
    username: str | None
    cpu_percent: float
    rss_bytes: int
    create_time: float | None
    exe: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SystemSample:
    """A normalized point-in-time system measurement."""

    timestamp: str
    platform: str
    boot_time: float
    cpu_percent: float
    logical_cpus: int
    load_average: tuple[float, float, float] | None
    memory: dict[str, Any]
    swap: dict[str, Any]
    disks: list[dict[str, Any]]
    top_processes: list[ProcessSample]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["load_average"] = list(self.load_average) if self.load_average is not None else None
        payload["top_processes"] = [process.to_dict() for process in self.top_processes]
        return payload
