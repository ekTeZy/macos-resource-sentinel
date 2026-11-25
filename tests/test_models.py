from __future__ import annotations

from macos_resource_sentinel.models import ProcessSample, SystemSample


def test_system_sample_serializes_processes() -> None:
    process = ProcessSample(
        pid=123,
        name="example",
        username="example-user",
        cpu_percent=12.5,
        rss_bytes=1024,
        create_time=100.0,
    )
    sample = SystemSample(
        timestamp="2026-11-25T12:00:00+00:00",
        platform="Darwin",
        boot_time=1.0,
        cpu_percent=10.0,
        logical_cpus=10,
        load_average=(1.0, 1.0, 1.0),
        memory={"pressure": "unknown"},
        swap={"used_bytes": 0},
        disks=[],
        top_processes=[process],
    )

    payload = sample.to_dict()

    assert payload["top_processes"][0]["pid"] == 123
    assert payload["load_average"] == [1.0, 1.0, 1.0]
