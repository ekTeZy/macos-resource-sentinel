"""Read normalized macOS system metrics."""

from __future__ import annotations

import os
import platform
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from .models import ProcessSample, SystemSample


PROCESS_ATTRS = ["pid", "name", "username", "memory_info", "create_time", "exe"]


class CollectionError(RuntimeError):
    """Raised when a system sample cannot be collected."""


def collect_once(
    *,
    interval_seconds: float = 0.2,
    disk_paths: list[str] | None = None,
    top_process_count: int = 5,
) -> SystemSample:
    """Collect one normalized sample.

    A short interval is needed so per-process CPU percentages are based on a
    measured delta rather than the lifetime average exposed by psutil.
    """

    if interval_seconds < 0 or interval_seconds > 5:
        raise CollectionError("collection interval must be between 0 and 5 seconds")
    if top_process_count < 1 or top_process_count > 25:
        raise CollectionError("top process count must be between 1 and 25")

    processes = _prime_process_cpu()
    if interval_seconds:
        time.sleep(interval_seconds)

    cpu_percent = psutil.cpu_percent(interval=None)
    process_samples = _finish_process_samples(processes)

    try:
        load_average = tuple(float(value) for value in os.getloadavg())
    except OSError:
        load_average = None

    virtual_memory = psutil.virtual_memory()
    swap_memory = psutil.swap_memory()
    disks = _collect_disks(disk_paths or ["/"])

    return SystemSample(
        timestamp=datetime.now(UTC).isoformat(),
        platform=f"{platform.system()} {platform.release()}",
        boot_time=float(psutil.boot_time()),
        cpu_percent=float(cpu_percent),
        logical_cpus=psutil.cpu_count(logical=True) or 1,
        load_average=load_average,  # type: ignore[arg-type]
        memory={
            "total_bytes": int(virtual_memory.total),
            "available_bytes": int(virtual_memory.available),
            "used_bytes": int(virtual_memory.used),
            "percent": float(virtual_memory.percent),
            "pressure": "unknown",
        },
        swap={
            "total_bytes": int(swap_memory.total),
            "used_bytes": int(swap_memory.used),
            "free_bytes": int(swap_memory.free),
            "percent": float(swap_memory.percent),
        },
        disks=disks,
        top_processes=process_samples[:top_process_count],
    )


def _prime_process_cpu() -> list[psutil.Process]:
    processes: list[psutil.Process] = []
    for process in psutil.process_iter(attrs=PROCESS_ATTRS):
        try:
            process.cpu_percent(interval=None)
        except (psutil.Error, OSError):
            continue
        processes.append(process)
    return processes


def _finish_process_samples(processes: list[psutil.Process]) -> list[ProcessSample]:
    samples: list[ProcessSample] = []
    for process in processes:
        try:
            cpu_percent = float(process.cpu_percent(interval=None))
            info = process.info
            memory_info = info.get("memory_info")
            samples.append(
                ProcessSample(
                    pid=int(info["pid"]),
                    name=str(info.get("name") or "unknown"),
                    username=_safe_string(info.get("username")),
                    cpu_percent=cpu_percent,
                    rss_bytes=int(memory_info.rss) if memory_info else 0,
                    create_time=_safe_float(info.get("create_time")),
                    exe=_safe_string(info.get("exe")),
                )
            )
        except (psutil.Error, OSError, KeyError, TypeError, ValueError):
            continue
    return sorted(samples, key=lambda item: (item.cpu_percent, item.rss_bytes), reverse=True)


def _collect_disks(paths: list[str]) -> list[dict[str, Any]]:
    disks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_path in paths:
        path = str(Path(raw_path).expanduser())
        if path in seen:
            continue
        seen.add(path)
        try:
            usage = psutil.disk_usage(path)
        except (OSError, psutil.Error) as exc:
            disks.append({"path": path, "available": False, "error": str(exc)})
            continue
        disks.append(
            {
                "path": path,
                "available": True,
                "total_bytes": int(usage.total),
                "used_bytes": int(usage.used),
                "free_bytes": int(usage.free),
                "free_percent": round((usage.free / usage.total) * 100, 2) if usage.total else 0.0,
            }
        )
    return disks


def _safe_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
