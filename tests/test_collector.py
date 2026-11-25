from __future__ import annotations

from types import SimpleNamespace

from macos_resource_sentinel import collector


def test_memory_pressure_maps_kernel_levels(monkeypatch) -> None:
    monkeypatch.setattr(collector.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        collector.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="2\n"),
    )

    assert collector.read_memory_pressure() == "warning"


def test_memory_pressure_is_unknown_outside_macos(monkeypatch) -> None:
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")

    assert collector.read_memory_pressure() == "unknown"
